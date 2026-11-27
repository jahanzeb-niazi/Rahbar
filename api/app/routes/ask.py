"""POST /api/ask. The Ingress sends /api/* here unchanged, so the prefix stays."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request, Response

from ..logjson import request_id_var
from ..retrieval.chroma import PinMismatchError
from ..schemas import AskRequest, AskResponse
from ..services.answer import answer_question
from ..services.trace import emit

log = logging.getLogger("rahbar.ask")

router = APIRouter(prefix="/api")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request, response: Response) -> AskResponse:
    state = request.app.state
    started = time.perf_counter()

    def failed_turn(reason: str) -> None:
        emit({
            "trace_id": request_id_var.get(), "query": body.question, "rewritten_query": None,
            "embedding_model": state.settings.embed_model, "embedding_version": state.settings.embed_model,
            "collection": state.settings.collection, "retrieved": [], "context": [], "prompt": [],
            "filters": {}, "reranked_order": [], "guardrails": [], "cache": "unknown",
            "latency_seconds": {"total": time.perf_counter() - started}, "model": state.settings.llm_model,
            "parameters": {"temperature": state.settings.temperature}, "citations": [],
            "response": {"answered_from_context": False, "error": reason}, "status": 503,
        })

    try:
        result = answer_question(body.question, state.retriever, state.provider,
                                 state.settings, state.cache,
                                 bypass_cache=request.headers.get("X-RAGOps-Eval") == "1")
    except PinMismatchError as exc:
        failed_turn("pin mismatch")
        log.error("refusing to answer: embedding pin mismatch", extra={"conflict": str(exc)})
        raise HTTPException(status_code=503, detail="the index and the API disagree on the "
                            "embedding model; the service is not ready") from exc
    except Exception as exc:  # a dependency (Chroma, Ollama, Redis) failed mid-request
        failed_turn(type(exc).__name__)
        log.exception("dependency failure", extra={"error": type(exc).__name__})
        raise HTTPException(status_code=503, detail="a dependency is unavailable; "
                            "please try again shortly") from exc
    response.headers["X-Cache"] = "hit" if result.cached else "miss"
    return result
