"""Stage 5: Store. The only code in the whole system that writes to Chroma.

Blue/green (ADR 0001): each run writes a brand-new collection `<base>-g<timestamp>` while
the API keeps serving the current one, then flips the pointer collection `<base>-active`
(its metadata holds {"target": <name>}) in a single metadata update. The API resolves the
pointer on every question, so it moves to the new index without a restart, and a failed run
leaves the old index serving. Older generations are deleted, keeping the one just replaced
so in-flight queries against it can finish.
"""

from __future__ import annotations

import time
from typing import Any

from .config import IndexerSettings
from .models import Chunk

ADD_BATCH = 500


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def pointer_name(base: str) -> str:
    return f"{base}-active"


def generation_prefix(base: str) -> str:
    return f"{base}-g"


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings,
          client: Any = None) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count."""
    if not chunks or len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    ids = [c.id for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate chunk ids")
    client = client or get_client(settings)
    base = settings.collection
    name = f"{generation_prefix(base)}{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
    collection = client.create_collection(
        name=name,
        metadata={
            "hnsw:space": "cosine",
            "embed_model": settings.embed_model,
            "dimension": len(vectors[0]),
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    for start in range(0, len(chunks), ADD_BATCH):
        part = chunks[start:start + ADD_BATCH]
        collection.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            embeddings=vectors[start:start + ADD_BATCH],
            metadatas=[c.metadata() for c in part],
        )
    count = int(collection.count())
    if count != len(chunks):
        client.delete_collection(name)
        raise RuntimeError(f"wrote {count} of {len(chunks)} chunks; new index discarded")

    previous = _flip_pointer(client, base, name)
    _delete_old_generations(client, base, keep={name, previous})
    return count


def _flip_pointer(client: Any, base: str, target: str) -> str:
    """Point `<base>-active` at the new generation; return the generation it replaced."""
    pointer = client.get_or_create_collection(pointer_name(base), metadata={"target": target})
    previous = str((pointer.metadata or {}).get("target", ""))
    pointer.modify(metadata={"target": target})
    return previous


def _delete_old_generations(client: Any, base: str, keep: set[str]) -> None:
    prefix = generation_prefix(base)
    for col in client.list_collections():
        col_name = col if isinstance(col, str) else col.name
        if col_name.startswith(prefix) and col_name not in keep:
            client.delete_collection(col_name)
