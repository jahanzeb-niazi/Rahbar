"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import time

import httpx

from .config import IndexerSettings

BATCH = 32
ATTEMPTS = 3
# nomic-embed-text is trained with task prefixes; the API uses "search_query: " for questions.
DOCUMENT_PREFIX = {"nomic-embed-text": "search_document: "}


def embed(texts: list[str], settings: IndexerSettings,
          client: httpx.Client | None = None) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    POST {ollama_url}/api/embed with {"model": ..., "input": [texts]} returns
    {"embeddings": [[...], ...]}. Batched, BATCH texts per request.
    """
    prefix = DOCUMENT_PREFIX.get(settings.embed_model.split(":")[0], "")
    vectors: list[list[float]] = []
    owned = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
    try:
        for start in range(0, len(texts), BATCH):
            batch = [prefix + t for t in texts[start:start + BATCH]]
            vectors.extend(_embed_batch(client, settings, batch))
    finally:
        if owned:
            client.close()
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedded {len(vectors)} vectors for {len(texts)} texts")
    dims = {len(v) for v in vectors}
    if len(dims) > 1:
        raise RuntimeError(f"embedding model returned mixed dimensions: {sorted(dims)}")
    return vectors


def _embed_batch(client: httpx.Client, settings: IndexerSettings,
                 batch: list[str]) -> list[list[float]]:
    url = f"{settings.ollama_url.rstrip('/')}/api/embed"
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = client.post(url, json={"model": settings.embed_model, "input": batch})
            r.raise_for_status()
            return [list(map(float, v)) for v in r.json()["embeddings"]]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            last = exc
            if attempt < ATTEMPTS:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"embedding failed after {ATTEMPTS} attempts: {last!r}")
