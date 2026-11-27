"""Verify a corpus snapshot, reuse vectors, then publish the verified generation."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .chunk import chunk
from .clean import clean
from .config import IndexerSettings
from .embed import embed
from .extract import extract
from .models import Chunk
from .store import get_client, pointer_name, store


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b) or 1)


def version_order(version: str) -> tuple[tuple[bool, int | str], ...]:
    return tuple((part.isdigit(), int(part) if part.isdigit() else part.lower())
                 for part in re.findall(r"[0-9]+|[^0-9]+", version))


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run(settings: IndexerSettings, lake: Path, restores: dict[str, str]) -> int:
    root = Path(settings.corpus_dir)
    manifest = json.loads((root / "_index.json").read_text(encoding="utf-8"))
    if not manifest:
        raise ValueError("the corpus manifest is empty")
    state_path = lake / f"{settings.collection}-state.json"
    pin = [settings.embed_model, settings.chunk_size, settings.chunk_overlap]
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    old = state.get("documents", {}) if state.get("pin") == pin else {}
    accepted: dict[str, dict] = {}
    seen: dict[str, str] = {}
    rows: dict[str, dict] = {}
    chunks: list[Chunk] = []
    vectors: list[list[float]] = []
    counts: Counter[str] = Counter()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    for item in manifest:
        name = item["file"]
        if Path(name).name != name or name in rows:
            raise ValueError(f"invalid or repeated manifest file {name!r}")
        path = root / name
        doc_id = item.get("doc_id", name)
        version = str(item.get("doc_version", ""))
        checks: dict[str, dict[str, str | bool]] = {}
        rows[name] = {"doc_id": doc_id, "version": version, "checks": checks}

        def check(kind: str, ok: bool, reason: str) -> None:
            checks[kind] = {"pass": ok, "reason": reason}

        fingerprint = ""
        body_hash = ""
        raw = None
        try:
            data = path.read_bytes()
            fingerprint = hashlib.sha256(data).hexdigest()
            raw = extract(str(path), version, False)
            body = " ".join(" ".join(p.text for p in raw.pages).split())
            body_hash = hashlib.sha256(body.encode()).hexdigest()
            quality = (len(body) >= 24 and sum(c.isalpha() for c in body) >= len(body) * 0.35
                       and "\ufffd" not in body and "\x00" not in body)
            check("quality", quality, "readable text" if quality else "empty or garbled text")
        except Exception as exc:
            check("quality", False, f"extraction failed ({type(exc).__name__})")

        missing = [key for key in ("source", "title", "doc_id", "doc_version", "page_count")
                   if not item.get(key)]
        complete = (not missing and raw is not None and item["page_count"] == len(raw.pages)
                    and all(p.text.strip() for p in raw.pages)
                    and (not item.get("end_marker") or
                         raw.pages[-1].text.rstrip().endswith(item["end_marker"])))
        check("completeness", complete, "metadata, pages and end marker match" if complete
              else f"missing {', '.join(missing)}" if missing else "page count, content or end marker mismatch")
        check("recency", True, "no newer accepted version found")
        if body_hash in seen:
            check("uniqueness", False, f"exact extracted-text hash matches {seen[body_hash]}")
        elif not checks["quality"]["pass"] or not complete or raw is None:
            check("uniqueness", False, "ineligible for duplicate comparison")
        else:
            signature = hashlib.sha256(json.dumps([fingerprint, item], sort_keys=True).encode()).hexdigest()
            saved = old.get(name, {})
            reused = saved.get("signature") == signature
            centroid = saved["centroid"] if reused else embed([body[:1800]], settings)[0]
            counts["verification_embeddings"] += int(not reused)
            nearest = max(((cosine(centroid, record["centroid"]), other)
                           for other, record in accepted.items() if record["doc_id"] != doc_id),
                          default=(0.0, ""))
            unique = nearest[0] < 0.96
            check("uniqueness", unique, f"nearest {nearest[1] or 'none'} ({nearest[0]:.4f})")
            if unique:
                seen[body_hash] = name
                accepted[name] = (saved if reused else {
                    "signature": signature, "doc_id": doc_id, "version": version,
                    "centroid": centroid, "chunks": [], "vectors": [],
                })

    active = {}
    for record in accepted.values():
        doc_id, version = record["doc_id"], record["version"]
        active[doc_id] = max(active.get(doc_id, ""), version, key=version_order)
    for doc_id, version in restores.items():
        if not any(record["doc_id"] == doc_id and record["version"] == version
                   for record in accepted.values()):
            raise ValueError(f"cannot restore absent version {doc_id} {version}")
    active.update(restores)
    for name, row in rows.items():
        source = root / name
        record = accepted.get(name)
        if record is None:
            row["disposition"] = "quarantine"
            destination = lake / "quarantine" / run_id / name
        elif active[record["doc_id"]] != record["version"]:
            row["disposition"] = "archive"
            row["checks"]["recency"] = {"pass": False, "reason": f"active version {active[record['doc_id']]}"}
            key = hashlib.sha256(f"{record['doc_id']}\0{record['version']}".encode()).hexdigest()
            destination = lake / "archive" / key / name
        else:
            row["disposition"] = "index"
            destination = lake / "verified" / name
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        if record is None:
            continue
        archived = row["disposition"] == "archive"
        if not record["chunks"] and not archived:
            document = clean(extract(str(source), record["version"], False))
            pieces = chunk(document, settings.chunk_size, settings.chunk_overlap)
            record["chunks"] = [asdict(piece) for piece in pieces]
            record["vectors"] = embed([piece.text for piece in pieces], settings)
            counts["chunks_embedded"] += len(pieces)
        if not archived:
            chunks.extend(Chunk(**{**piece, "doc_id": record["doc_id"]}) for piece in record["chunks"])
            vectors.extend(record["vectors"])

    client = get_client(settings)
    snapshot = {"pin": pin, "documents": accepted, "active": active}
    try:
        target = client.get_collection(pointer_name(settings.collection)).metadata["target"]
        collection = client.get_collection(target)
    except Exception:
        collection = None
    if collection is None or any(state.get(key) != value for key, value in snapshot.items()):
        store(chunks, vectors, settings, client)
        target = client.get_collection(pointer_name(settings.collection)).metadata["target"]
        collection = client.get_collection(target)
    save(state_path, snapshot)
    actual = Counter(meta.get("doc_id", meta["source"]) for meta in collection.get(include=["metadatas"])["metadatas"])
    all_ids = {row["doc_id"] for row in rows.values()} | {record["doc_id"] for record in old.values()}
    report = {"run": run_id, "collection": target, "documents": rows,
              "chunks_embedded": counts["chunks_embedded"],
              "verification_embeddings": counts["verification_embeddings"],
              "chunk_counts_by_document": {doc_id: actual[doc_id] for doc_id in sorted(all_ids)}}
    save(lake / "results" / f"verification-{run_id}-{settings.collection}.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return int(collection.count())
