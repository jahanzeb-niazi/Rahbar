"""Guard against re-embedding unchanged chunks or retaining deleted rows."""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from pipeline import verified
from pipeline.config import get_settings


def test_incremental_verification(tmp_path: Path, monkeypatch):
    corpus = tmp_path / "input"
    corpus.mkdir()
    lake = tmp_path / "lake"
    manifest = corpus / "_index.json"
    rows = {}
    target = None

    class Collection:
        def get(self, include):
            assert include == ["metadatas"]
            return {"metadatas": list(rows.values())}

        def count(self):
            return len(rows)

    class Client:
        def get_collection(self, name):
            if name.endswith("-active"):
                if target is None:
                    raise KeyError(name)
                return SimpleNamespace(metadata={"target": target})
            return Collection()

    def store(chunks, vectors, settings, client):
        nonlocal target
        assert len(chunks) == len(vectors)
        target = str(int(target or "0") + 1)
        rows.clear()
        rows.update((chunk.id, chunk.metadata()) for chunk in chunks)

    def embed(texts, _settings):
        return [[1.0, 0.0] if "attendance" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(verified, "embed", embed)
    monkeypatch.setattr(verified, "store", store)
    monkeypatch.setattr(verified, "get_client", lambda settings: Client())
    settings = replace(get_settings(), corpus_dir=str(corpus))
    entries = []
    for name, text in (("rules", "The attendance quota applies before the examination."),
                       ("fees", "Tuition is paid at the bank when the invoice arrives.")):
        path = corpus / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        entries.append({"file": path.name, "doc_id": name, "source": path.name,
                        "title": name, "doc_version": "2026", "page_count": 1})

    def run(items):
        manifest.write_text(json.dumps(items), encoding="utf-8")
        verified.run(settings, lake, {})
        latest = sorted((lake / "results").glob("verification-*.json"))[-1]
        return json.loads(latest.read_text(encoding="utf-8"))

    assert run(entries)["chunks_embedded"] == 2
    assert run(entries)["chunks_embedded"] == 0
    assert target == "1"
    (corpus / "rules.md").write_text("The attendance quota now applies to evening courses.", encoding="utf-8")
    assert run(entries)["chunks_embedded"] == 1
    report = run(entries[:1])
    assert report["chunks_embedded"] == 0
    assert report["chunk_counts_by_document"] == {"fees": 0, "rules": 1}
