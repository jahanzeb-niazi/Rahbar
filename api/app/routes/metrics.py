"""Prometheus metrics at /metrics (section 4.8).

Request count and latency per route, retrieval and generation latency, cache hits and the
hit ratio, abstentions, fallbacks, and tokens in and out per generation request.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
RETRIEVAL_LATENCY = Histogram(
    "rahbar_retrieval_seconds", "Question embedding plus vector search latency",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
GENERATION_LATENCY = Histogram(
    "rahbar_generation_seconds", "LLM generation latency, retries included",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
CACHE_LOOKUPS = Counter("rahbar_cache_lookups_total", "Semantic cache lookups", ["result"])
CACHE_HIT_RATIO = Gauge("rahbar_cache_hit_ratio", "Cache hits / (hits + misses) since start")
ABSTENTIONS = Counter("rahbar_abstentions_total", "Answers with answered_from_context=false",
                      ["reason"])
FALLBACKS = Counter("rahbar_fallbacks_total", "Canned fallback answers after a failed retry")
TOKENS_IN = Histogram("rahbar_tokens_in", "Prompt tokens per generation request",
                      buckets=(100, 250, 500, 1000, 2000, 4000, 8000))
TOKENS_OUT = Histogram("rahbar_tokens_out", "Completion tokens per generation request",
                       buckets=(25, 50, 100, 200, 400, 800, 1600))

_hits = 0
_misses = 0


def record_cache(result: str) -> None:
    """result is hit, miss or skipped; skipped lookups do not move the ratio."""
    global _hits, _misses
    CACHE_LOOKUPS.labels(result=result).inc()
    if result == "hit":
        _hits += 1
    elif result == "miss":
        _misses += 1
    if _hits + _misses:
        CACHE_HIT_RATIO.set(_hits / (_hits + _misses))


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
