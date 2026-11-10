"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy    # week 1: three fake chunks, no model needed
    python -m pipeline.run            # the real pipeline: extract, clean, chunk, embed, store

Exit code 0 means the index was written; anything else fails the Job, and
Kubernetes retries it up to the Job's backoffLimit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import IndexerSettings, get_settings
from .models import Chunk


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "msg": msg, **fields}), flush=True)


def _front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """List (path, doc_version, superseded) for every document to index.

    corpus/fetch.py writes _index.json next to the files it downloads; use it when
    present. Otherwise read Markdown front matter (the CI fixtures work this way).
    """
    root = Path(corpus_dir)
    index = root / "_index.json"
    if index.exists():
        entries = json.loads(index.read_text(encoding="utf-8"))
        return [(root / e["file"], str(e.get("doc_version", "unknown")),
                 bool(e.get("superseded", False))) for e in entries]
    found = []
    for path in sorted(root.glob("*")):
        if path.suffix.lower() not in {".pdf", ".md", ".html", ".txt"}:
            continue
        if path.name.lower().startswith("readme"):
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", "unknown"),
                      meta.get("superseded", "false").lower() == "true"))
    return found


def fetch_corpus(settings: IndexerSettings) -> None:
    """Download the corpus into CORPUS_DIR with corpus/fetch.py --frozen, which fails unless
    every file matches the SHA-256 in the committed corpus/MANIFEST.md (docs/PIPELINE.md)."""
    here = Path(__file__).resolve().parent
    script = next((p for p in (here.parent / "corpus" / "fetch.py",
                               here.parents[1] / "corpus" / "fetch.py") if p.exists()), None)
    if script is None:
        raise SystemExit("FETCH_CORPUS=true but corpus/fetch.py is not in the image")
    log("fetching corpus", into=settings.corpus_dir)
    result = subprocess.run([sys.executable, str(script), "--frozen", "--raw",
                             settings.corpus_dir], check=False)
    if result.returncode != 0:
        raise SystemExit(f"corpus fetch or checksum verification failed ({result.returncode})")


def run_pipeline(settings: IndexerSettings) -> int:
    from .chunk import chunk, estimate_tokens
    from .clean import clean
    from .embed import embed
    from .extract import extract
    from .store import store

    documents = discover(settings.corpus_dir)
    if not documents:
        raise SystemExit(f"no documents found in {settings.corpus_dir}")
    all_chunks: list[Chunk] = []
    original_tokens = 0
    for path, doc_version, superseded in documents:
        raw = extract(str(path), doc_version, superseded)
        doc = clean(raw)
        original_tokens += sum(estimate_tokens(p.text) for p in doc.pages)
        pieces = chunk(doc, settings.chunk_size, settings.chunk_overlap)
        log("chunked", source=path.name, pages=len(doc.pages),
            ocr_pages=sum(1 for p in raw.pages if p.ocr),
            empty_pages=sum(1 for p in doc.pages if not p.text.strip()),
            doc_version=doc_version, superseded=superseded, chunks=len(pieces))
        all_chunks.extend(pieces)
    stored_tokens = sum(estimate_tokens(c.text) for c in all_chunks)
    log("chunking summary", chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
        chunks=len(all_chunks), original_tokens=original_tokens, stored_tokens=stored_tokens,
        storage_amplification=round(stored_tokens / max(original_tokens, 1), 3))
    vectors = embed([c.text for c in all_chunks], settings)
    log("embedded", chunks=len(vectors), dimension=len(vectors[0]) if vectors else 0,
        embed_model=settings.embed_model)
    return store(all_chunks, vectors, settings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    parser.add_argument("--dummy", action="store_true", help="write three fake chunks")
    args = parser.parse_args()
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if settings.fetch_corpus and not args.dummy:
            fetch_corpus(settings)
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
        else:
            count = run_pipeline(settings)
    except NotImplementedError as exc:
        log("indexer stage not implemented yet", error=str(exc))
        return 2
    log("indexer finished", chunks=count, seconds=round(time.perf_counter() - started, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
