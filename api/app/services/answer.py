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
import time

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import Answer, AskResponse, RetrievedRef
from .cache import Cache, NullCache
from .followup import is_followup
from .generation import generate_validated

log = logging.getLogger("rahbar.answer")

ABSTAIN_TEXT = ("The documents I have do not cover this question, so I cannot answer it. "
                "Please check with the relevant university office.")


def _abstain(reasoning: str) -> Answer:
    return Answer(reasoning=reasoning, answer=ABSTAIN_TEXT, citations=[],
                  answered_from_context=False, confidence="low")


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings,
    cache: Cache | None = None,
) -> AskResponse:
    cache = cache or NullCache()
    followup = is_followup(question)

    started = time.perf_counter()
    vector = retriever.embed(question)
    generation = retriever.generation()

    # 2. cache check
    if followup or vector is None:
        metrics.record_cache("skipped")
    else:
        hit = cache.lookup(vector, generation)
        if hit is not None:
            metrics.record_cache("hit")
            response = AskResponse(**{**hit, "request_id": request_id_var.get(), "cached": True})
            _log_turn(settings, response, followup=followup, fallback=False)
            return response
        metrics.record_cache("miss")

    # 3-4. retrieve
    passages = retriever.retrieve(question, k=settings.top_k, vector=vector)
    metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - started)
    evidence = [p for p in passages if p.score >= settings.relevance_floor]

    # 5-7. generate and validate, or abstain
    fallback = False
    if not evidence:
        answer = _abstain(f"no passage reached the relevance floor {settings.relevance_floor}")
        metrics.ABSTENTIONS.labels(reason="below_floor").inc()
    else:
        gen_started = time.perf_counter()
        answer, fallback = generate_validated(provider, question, evidence)
        metrics.GENERATION_LATENCY.observe(time.perf_counter() - gen_started)
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
    safe_to_cache = (not followup and not fallback and vector is not None
                     and answer.answered_from_context and bool(answer.citations))
    if safe_to_cache and vector is not None:
        cache.store(question, vector, generation,
                    response.model_dump(exclude={"request_id", "cached"}))
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
