"""Unit tests for the five pipeline stages. No Chroma, no Ollama, no network."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from pipeline.chunk import chunk, estimate_tokens, heading_of
from pipeline.clean import clean, repeating_lines
from pipeline.config import get_settings
from pipeline.embed import embed
from pipeline.extract import extract, html_to_text, table_to_markdown
from pipeline.models import Chunk, Document, Page
from pipeline.store import pointer_name, store

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"


# ------------------------------------------------------------------ extract

def test_markdown_extract_drops_front_matter_and_keeps_headings() -> None:
    doc = extract(str(FIXTURES / "academic-rules-2026.md"), "2026", False)
    assert doc.source == "academic-rules-2026.md"
    assert not doc.pages[0].text.startswith("---")
    assert "## 1. Attendance" in doc.pages[0].text


def test_table_rows_keep_their_columns() -> None:
    md = table_to_markdown([["Programme", "Fee"], ["BS", "10,000"], [None, None], ["MS", "12,500"]])
    assert md.splitlines() == ["| Programme | Fee |", "| --- | --- |",
                               "| BS | 10,000 |", "| MS | 12,500 |"]


def test_html_keeps_headings_and_tables_and_drops_scripts() -> None:
    html = """<html><head><script>var x=1;</script></head><body><nav>Home</nav>
    <h2>Tuition Fee</h2><p>Per credit hour.</p>
    <table><tr><th>Programme</th><th>PKR</th></tr><tr><td>BS</td><td>11,500</td></tr></table>
    </body></html>"""
    text = html_to_text(html)
    assert "## Tuition Fee" in text
    assert "| BS | 11,500 |" in text
    assert "var x" not in text and "Home" not in text


# ------------------------------------------------------------------ clean

def _doc(pages: list[str]) -> Document:
    return Document(source="d.pdf", doc_version="1", superseded=False,
                    pages=[Page(source="d.pdf", page=i + 1, text=t) for i, t in enumerate(pages)])


def test_clean_strips_running_headers_footers_and_page_numbers() -> None:
    topics = ["attendance", "grading", "admission", "registration", "assessment"]
    pages = [f"NATIONAL UNIVERSITY\n1.{i} Rules about {t} apply.\nHandbook 2026 page {i}\n{i}"
             for i, t in enumerate(topics, start=1)]
    cleaned = clean(_doc(pages))
    for p in cleaned.pages:
        assert "NATIONAL UNIVERSITY" not in p.text
        assert "Handbook 2026" not in p.text
        assert p.text.startswith("1.")          # the clause number is deliberately kept


def test_clean_rejoins_hyphenated_words_and_fixes_apostrophes() -> None:
    cleaned = clean(_doc(["Bachelor�s regis-\ntration is open."]))
    assert cleaned.pages[0].text == "Bachelor's registration is open."


def test_short_documents_have_no_repeating_lines() -> None:
    assert repeating_lines(_doc(["a\nb", "a\nb"]).pages) == set()


# ------------------------------------------------------------------ chunk

def test_heading_detection() -> None:
    assert heading_of("## 2. Academic warning") == "2. Academic warning"
    assert heading_of("4. Registration") == "4. Registration"
    assert heading_of("Attendance Requirements") == "Attendance Requirements"
    assert heading_of("1.21 Students are required to maintain 100% attendance") is None
    assert heading_of("1. Medium of Instruction 1") is None     # a table-of-contents line
    assert heading_of("the semester.") is None
    assert heading_of("| BS | 10,000 |") is None


def test_chunks_follow_sections_and_carry_metadata() -> None:
    doc = clean(extract(str(FIXTURES / "academic-rules-2023.md"), "2023", True))
    chunks = chunk(doc, size=400, overlap=50)
    sections = {c.section for c in chunks}
    assert {"1. Attendance", "2. Academic warning", "3. Repeating a course"} <= sections
    for c in chunks:
        assert c.text.startswith(c.section)
        assert c.doc_version == "2023" and c.superseded is True
        assert set(c.metadata()) == {"source", "section", "page", "doc_version", "superseded"}
    attendance = next(c for c in chunks if c.section == "1. Attendance")
    assert "75 percent" in attendance.text and "1.75" not in attendance.text


def test_chunks_respect_size_and_overlap() -> None:
    sentences = " ".join(f"Sentence number {i} explains one rule in detail." for i in range(200))
    doc = _doc([f"## 1. Long Definitions\n{sentences}"])
    chunks = chunk(doc, size=100, overlap=20)
    assert len(chunks) > 5
    for c in chunks:
        body = c.text.split("\n", 1)[1]
        assert estimate_tokens(body) <= 100
    last_sentence = chunks[0].text.splitlines()[-1]
    assert chunks[1].text.splitlines()[1] == last_sentence    # overlap carried forward


def test_chunk_ids_are_stable_and_unique() -> None:
    doc = clean(extract(str(FIXTURES / "fees-2026.md"), "2026", False))
    a, b = chunk(doc, 400, 50), chunk(doc, 400, 50)
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)


def test_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValueError):
        chunk(_doc(["text"]), size=50, overlap=50)


# ------------------------------------------------------------------ embed

def test_embed_batches_uses_the_pinned_model_and_prefix() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]})

    settings = replace(get_settings(), embed_model="nomic-embed-text", ollama_url="http://o")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    vectors = embed([f"t{i}" for i in range(40)], settings, client=client)
    assert len(vectors) == 40 and len(seen) == 2                 # 32 + 8
    assert all(b["model"] == "nomic-embed-text" for b in seen)
    assert seen[0]["input"][0] == "search_document: t0"


# ------------------------------------------------------------------ store

class FakeCollection:
    def __init__(self, name: str, metadata: dict | None) -> None:
        self.name, self.metadata, self.rows = name, dict(metadata or {}), {}

    def add(self, ids, documents, embeddings, metadatas) -> None:
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows[i] = (d, e, m)

    def count(self) -> int:
        return len(self.rows)

    def modify(self, metadata: dict) -> None:
        self.metadata = dict(metadata)


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def create_collection(self, name: str, metadata: dict) -> FakeCollection:
        if name in self.collections:
            raise ValueError("exists")
        self.collections[name] = FakeCollection(name, metadata)
        return self.collections[name]

    def get_or_create_collection(self, name: str, metadata: dict) -> FakeCollection:
        return self.collections.get(name) or self.create_collection(name, metadata)

    def delete_collection(self, name: str) -> None:
        del self.collections[name]

    def list_collections(self) -> list[FakeCollection]:
        return list(self.collections.values())


def _chunks(n: int) -> list[Chunk]:
    return [Chunk(id=f"c{i}", text=f"text {i}", source="a.pdf", section="1 A", page=1,
                  doc_version="2026", superseded=False) for i in range(n)]


def test_store_records_the_pin_and_flips_the_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    settings = get_settings()
    times = iter(["20260101000000", "20260102000000", "20260103000000"])
    monkeypatch.setattr("pipeline.store.time.strftime",
                        lambda fmt, *_: next(times) if fmt == "%Y%m%d%H%M%S" else "t")

    assert store(_chunks(3), [[1.0, 0.0]] * 3, settings, client=client) == 3
    pointer = client.collections[pointer_name(settings.collection)]
    first = pointer.metadata["target"]
    built = client.collections[first]
    assert built.metadata["embed_model"] == settings.embed_model
    assert built.metadata["dimension"] == 2
    assert built.metadata["hnsw:space"] == "cosine"

    store(_chunks(2), [[1.0, 0.0]] * 2, settings, client=client)
    second = pointer.metadata["target"]
    assert second != first and first in client.collections        # previous kept for in-flight
    store(_chunks(2), [[1.0, 0.0]] * 2, settings, client=client)
    assert first not in client.collections                         # older generations removed


def test_store_rejects_mismatched_vectors() -> None:
    with pytest.raises(ValueError):
        store(_chunks(2), [[1.0]], get_settings(), client=FakeClient())
