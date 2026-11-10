"""Semantic cache in Redis (section 3.3, ADR 0003).

An entry is the question's vector plus the response it produced, stored in one Redis hash
per index generation: `rahbar:cache:<generation>`. A lookup is a hit when the cosine
similarity to a stored question is at or above CACHE_THRESHOLD from the ConfigMap.

Invalidation on re-index: the generation is the name of the collection the index pointer
names, and it changes on every indexer run. Entries for any other generation are never read
and are deleted the first time this API sees the new generation, so answers from the old
index are never served. The indexer needs no Redis access for this (NetworkPolicy: redis
from api only).

What is cached is decided by the caller (services/answer.py): never follow-ups,
abstentions, out-of-scope answers, fallbacks or anything that failed validation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any, Protocol

log = logging.getLogger("rahbar.cache")

PREFIX = "rahbar:cache:"


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Cache(Protocol):
    def lookup(self, vector: list[float], generation: str) -> dict[str, Any] | None: ...
    def store(self, question: str, vector: list[float], generation: str,
              response: dict[str, Any]) -> None: ...
    def ping(self) -> str: ...


class NullCache:
    """No Redis configured (unit tests, `make dev`): every lookup misses."""

    enabled = False

    def lookup(self, vector: list[float], generation: str) -> dict[str, Any] | None:
        return None

    def store(self, question: str, vector: list[float], generation: str,
              response: dict[str, Any]) -> None:
        return None

    def ping(self) -> str:
        return "ok"


class SemanticCache:
    enabled = True

    def __init__(self, client: Any, threshold: float) -> None:
        self.redis = client
        self.threshold = threshold
        self._generation: str | None = None

    def _invalidate_stale(self, generation: str) -> None:
        """Delete entries written against any other index generation (a re-index)."""
        if generation == self._generation:
            return
        current = PREFIX + generation
        stale = [k for k in self.redis.scan_iter(match=PREFIX + "*")
                 if (k.decode() if isinstance(k, bytes) else k) != current]
        if stale:
            self.redis.delete(*stale)
            log.info("cache invalidated after re-index",
                     extra={"generation": generation, "deleted_keys": len(stale)})
        self._generation = generation

    def lookup(self, vector: list[float], generation: str) -> dict[str, Any] | None:
        self._invalidate_stale(generation)
        best, best_score = None, -1.0
        for raw in self.redis.hvals(PREFIX + generation):
            entry = json.loads(raw)
            score = cosine(vector, entry["vector"])
            if score > best_score:
                best, best_score = entry, score
        if best is not None and best_score >= self.threshold:
            log.info("cache hit", extra={"similarity": round(best_score, 4),
                                         "cached_question": best["question"]})
            response: dict[str, Any] = best["response"]
            return response
        return None

    def store(self, question: str, vector: list[float], generation: str,
              response: dict[str, Any]) -> None:
        self._invalidate_stale(generation)
        field = hashlib.sha256(" ".join(question.lower().split()).encode()).hexdigest()
        entry = {"question": question, "vector": vector, "response": response}
        self.redis.hset(PREFIX + generation, field, json.dumps(entry))

    def ping(self) -> str:
        try:
            self.redis.ping()
            return "ok"
        except Exception as exc:
            return f"unreachable: {type(exc).__name__}"


def get_cache(redis_host: str, redis_port: int, threshold: float) -> Cache:
    if not redis_host:
        return NullCache()
    import redis

    client = redis.Redis(host=redis_host, port=redis_port, socket_timeout=2.0,
                         socket_connect_timeout=2.0)
    return SemanticCache(client, threshold)
