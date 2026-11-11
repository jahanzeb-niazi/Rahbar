"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

router = APIRouter()
log = logging.getLogger("rahbar.health")

_last_failure: dict[str, str] = {}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """200 only if Chroma is reachable, the collection exists and is non-empty, its
    embedding model matches EMBED_MODEL (section 4.4), and Redis is reachable.
    Otherwise 503, naming each dependency that failed."""
    state = request.app.state
    try:
        checks = dict(state.retriever.check())
    except Exception as exc:
        checks = {"retriever": f"error: {type(exc).__name__}"}
    checks["redis"] = state.cache.ping() if getattr(state.cache, "enabled", False) else "disabled"
    failed = {k: v for k, v in checks.items() if v not in ("ok", "disabled")}
    if failed:
        response.status_code = 503
        if failed != _last_failure:      # log each new failure once, not every 10 seconds
            log.error("not ready", extra={"failed": failed})
        _last_failure.clear()
        _last_failure.update(failed)
        return {"status": "not ready", "failed": sorted(failed), "checks": checks}
    if _last_failure:
        log.info("ready again", extra={"checks": checks})
        _last_failure.clear()
    return {"status": "ready", "checks": checks}
