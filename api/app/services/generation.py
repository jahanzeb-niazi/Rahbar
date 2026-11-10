"""Generate, validate, retry once, then fall back (section 3.2 steps 6-7, section 3.4).

Validation has two layers:
1. Structure: the provider parses the reply with Answer.model_validate_json; a reply that is
   not valid JSON for the schema raises ValidationError.
2. Grounding: every citation must match a passage retrieved for this request (same source
   and section). Citations that match nothing are fabricated and are dropped. An answer that
   claims to be from the context but has no valid citation left is rejected.

A rejected or failed attempt is retried once; a second failure returns FALLBACK, so a user
never sees a 500 because the model wrote prose instead of JSON.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from ..providers.llm.base import LLMProvider
from ..schemas import Answer, Citation, Passage

log = logging.getLogger("rahbar.generation")

FALLBACK_TEXT = ("Sorry, I could not produce a reliable, cited answer from the documents for "
                 "this question. Please try rephrasing it.")


def fallback_answer() -> Answer:
    return Answer(reasoning="fallback after a failed retry", answer=FALLBACK_TEXT,
                  citations=[], answered_from_context=False, confidence="low")


class GroundingError(ValueError):
    """The answer claims to come from the context but cites nothing that was retrieved."""


def _key(source: str, section: str) -> tuple[str, str]:
    return (" ".join(source.split()).lower(), " ".join(section.split()).lower())


def _find(c: Citation, passages: list[Passage]) -> Passage | None:
    """The retrieved passage a citation names: same source, and the cited section equals
    the passage's section or is contained in it (models often cite only the last part of
    "5. Academic Assessment > Academic Warning/Probation"). Exact matches win."""
    source, section = _key(c.source, c.section)
    same_source = [p for p in passages if _key(p.source, p.section)[0] == source]
    for p in same_source:
        if _key(p.source, p.section)[1] == section:
            return p
    if len(section) >= 3:
        for p in same_source:
            if section in _key(p.source, p.section)[1]:
                return p
    return None


def valid_citations(citations: list[Citation], passages: list[Passage]) -> list[Citation]:
    """Keep only citations that name a retrieved passage, rewritten to that passage's exact
    source, section and page, so every returned citation matches `retrieved` exactly."""
    kept: list[Citation] = []
    for c in citations:
        p = _find(c, passages)
        if p is not None and all(_key(k.source, k.section) != _key(p.source, p.section)
                                 for k in kept):
            kept.append(Citation(source=p.source, section=p.section, page=p.page))
    return kept


def check_grounding(answer: Answer, passages: list[Passage]) -> Answer:
    if not answer.answered_from_context:
        return answer.model_copy(update={"citations": []})
    cited = valid_citations(answer.citations, passages)
    if not cited:
        raise GroundingError(f"{len(answer.citations)} citations, none match a retrieved passage")
    if len(cited) < len(answer.citations):
        log.warning("dropped fabricated citations",
                    extra={"dropped": len(answer.citations) - len(cited)})
    return answer.model_copy(update={"citations": cited})


def generate_validated(provider: LLMProvider, question: str,
                       passages: list[Passage]) -> tuple[Answer, bool]:
    """Return (answer, used_fallback). Two attempts at most."""
    for attempt in (1, 2):
        try:
            return check_grounding(provider.generate(question, passages), passages), False
        except (ValidationError, GroundingError, ValueError, KeyError, httpx.HTTPError) as exc:
            log.warning("generation rejected", extra={"attempt": attempt,
                                                      "error": type(exc).__name__,
                                                      "detail": str(exc)[:300]})
    return fallback_answer(), True
