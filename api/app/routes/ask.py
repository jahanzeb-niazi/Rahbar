"""POST /api/ask. The Ingress sends /api/* here unchanged, so the prefix stays."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from ..retrieval.chroma import PinMismatchError
from ..schemas import AskRequest, AskResponse
from ..services.answer import answer_question

log = logging.getLogger("rahbar.ask")

router = APIRouter(prefix="/api")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request, response: Response) -> AskResponse:
    state = request.app.state
    try:
        result = answer_question(body.question, state.retriever, state.provider,
                                 state.settings, state.cache)
    except PinMismatchError as exc:
        log.error("refusing to answer: embedding pin mismatch", extra={"conflict": str(exc)})
        raise HTTPException(status_code=503, detail="the index and the API disagree on the "
                            "embedding model; the service is not ready") from exc
    except Exception as exc:  # a dependency (Chroma, Ollama, Redis) failed mid-request
        log.exception("dependency failure", extra={"error": type(exc).__name__})
        raise HTTPException(status_code=503, detail="a dependency is unavailable; "
                            "please try again shortly") from exc
    response.headers["X-Cache"] = "hit" if result.cached else "miss"
    return result
