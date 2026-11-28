"""Turns a question into an AskResponse: the query pipeline of section 3.2.

1. Receive and validate (AskRequest: 3 to 500 characters, else 422).
2. Cache check, skipped for follow-up questions (services/cache.py, services/followup.py).
3. Embed the question with the pinned model (the vector is shared with step 2).
4. Retrieve top_k from Chroma, superseded documents filtered out (retrieval/chroma.py).
5. Augment: instructions, numbered evidence, question (services/prompt.py).
6. Generate a schema-constrained answer at TEMPERATURE (providers/llm/).
7. Validate: parse, check citations, retry once, then fall back (services/generation.py).
8. Store the turn (one JSON log line) and a cache entry when it is safe to cache.

Nothing below the relevance floor counts as evidence; with no evidence the model is not
called and the service abstains honestly.
"""

from __future__ import annotations

import logging
from typing import Any
import time

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.chroma import ChromaRetriever, wants_older_version
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import Answer, AskResponse, RetrievedRef
from .cache import Cache, NullCache
from .followup import is_followup
from .generation import generate_validated
from .prompt import build_messages
from .trace import INJECTIONS, INSTRUCTION, emit

log = logging.getLogger("rahbar.answer")

ABSTAIN_TEXT = ("The documents I have do not cover this question, so I cannot answer it. "
                "Please check with the relevant university office.")


def _abstain(reasoning: str) -> Answer:
    return Answer(reasoning=reasoning, answer=ABSTAIN_TEXT, citations=[],
                  answered_from_context=False, confidence="low")


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings,
    cache: Cache | None = None, *, bypass_cache: bool = False,
) -> AskResponse:
    cache = cache or NullCache()
    followup = is_followup(question)

    started = time.perf_counter()
    vector = retriever.embed(question)
    stages = {"embedding": time.perf_counter() - started}
    generation = retriever.generation()
    trace: dict[str, Any] = {
        "trace_id": request_id_var.get(), "query": question, "rewritten_query": None,
        "embedding_model": settings.embed_model, "embedding_version": settings.embed_model,
        "collection": generation, "retrieved": [], "context": [], "prompt": [],
        "filters": {"relevance_floor": settings.relevance_floor,
                    "superseded": None if wants_older_version(question) else False},
        "reranked_order": [], "guardrails": [], "cache": "skipped", "latency_seconds": stages,
        "model": settings.llm_model, "parameters": {"temperature": settings.temperature,
                                                   "seed": 42, "num_ctx": 4096, "num_predict": 512},
    }

    def finish(response: AskResponse) -> None:
        stages["total"] = time.perf_counter() - started
        trace["response"] = response.model_dump()
        trace["citations"] = [citation.model_dump() for citation in response.citations]
        emit(trace)

    cache_started = time.perf_counter()

    # 2. cache check
    if followup or vector is None or bypass_cache:
        metrics.record_cache("skipped")
    else:
        hit = cache.lookup(vector, generation)
        if hit is not None and "_trace" in hit:
            metrics.record_cache("hit")
            response = AskResponse(**{**hit, "request_id": request_id_var.get(), "cached": True})
            for key in ("retrieved", "context", "prompt", "reranked_order", "filters"):
                trace[key] = hit.get("_trace", {}).get(key, trace[key])
            trace["cache_origin"] = hit.get("_trace", {}).get("trace_id")
            trace["cache"] = "hit"
            stages["cache"] = time.perf_counter() - cache_started
            finish(response)
            _log_turn(settings, response, followup=followup, fallback=False)
            return response
        metrics.record_cache("miss")
        trace["cache"] = "miss"
    stages["cache"] = time.perf_counter() - cache_started

    # 3-4. retrieve
    retrieval_started = time.perf_counter()
    if isinstance(retriever, ChromaRetriever):
        passages = retriever.retrieve(question, k=settings.top_k, vector=vector,
                                      generation=generation)
    else:
        passages = retriever.retrieve(question, k=settings.top_k, vector=vector)
    stages["retrieval"] = time.perf_counter() - retrieval_started
    trace["retrieved"] = [p.model_dump(exclude={"text"}) for p in passages]
    metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - started)
    guard_started = time.perf_counter()
    evidence = []
    for passage in passages:
        if passage.score < settings.relevance_floor:
            continue
        lines = passage.text.splitlines()
        discard = [line for line in lines if INSTRUCTION.search(line)]
        if discard:
            INJECTIONS.inc()
            trace["guardrails"].append({"action": "removed instruction-like lines",
                                        "chunk_id": passage.chunk_id, "lines": len(discard)})
            passage = passage.model_copy(update={"text": "\n".join(
                line for line in lines if not INSTRUCTION.search(line))})
        if passage.text.strip():
            evidence.append(passage)
    trace["reranked_order"] = [p.chunk_id for p in evidence]
    trace["context"] = [p.model_dump() for p in evidence]
    stages["guardrails"] = time.perf_counter() - guard_started

    # 5-7. generate and validate, or abstain
    fallback = False
    if not evidence:
        answer = _abstain(f"no passage reached the relevance floor {settings.relevance_floor}")
        metrics.ABSTENTIONS.labels(reason="below_floor").inc()
    else:
        trace["prompt"] = build_messages(question, evidence) if provider.name == "ollama" else []
        gen_started = time.perf_counter()
        answer, fallback = generate_validated(provider, question, evidence)
        stages["generation_and_validation"] = time.perf_counter() - gen_started
        metrics.GENERATION_LATENCY.observe(stages["generation_and_validation"])
        if fallback:
            metrics.FALLBACKS.inc()
        elif not answer.answered_from_context:
            metrics.ABSTENTIONS.labels(reason="model").inc()

    response = AskResponse(
        request_id=request_id_var.get(),
        answer=answer.answer,                 # answer.reasoning is never sent to the user
        citations=answer.citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[
            RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page,
                         score=p.score)
            for p in passages
        ],
        provider=provider.name,
        cached=False,
    )

    # 8. store the turn, and cache it only when that is safe
    safe_to_cache = (trace["cache"] == "miss" and not followup and not fallback and vector is not None
                     and answer.answered_from_context and bool(answer.citations))
    if safe_to_cache and vector is not None:
        cache.store(question, vector, generation,
                    {**response.model_dump(exclude={"request_id", "cached"}),
                     "_trace": {key: trace[key] for key in (
                         "trace_id", "retrieved", "context", "prompt", "reranked_order", "filters")}})
    finish(response)
    _log_turn(settings, response, followup=followup, fallback=fallback)
    return response


def _log_turn(settings: Settings, response: AskResponse, *, followup: bool,
              fallback: bool) -> None:
    log.info(
        "answered",
        extra={
            "top_k": settings.top_k,
            "chunk_ids": [p.chunk_id for p in response.retrieved],
            "scores": [round(p.score, 4) for p in response.retrieved],
            "abstained": not response.answered_from_context,
            "answered_from_context": response.answered_from_context,
            "citations": len(response.citations),
            "cached": response.cached,
            "followup": followup,
            "fallback": fallback,
            "provider": response.provider,
        },
    )
