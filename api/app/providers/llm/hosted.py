"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter): not supported here.

This deployment supports ollama-host only (ADR 0004). The provider interface is unchanged,
so adding hosted mode later means writing generate() in this one file. Until then, selecting
it fails at startup with a clear message instead of failing on the first question.
"""

from __future__ import annotations

from ...config import Settings
from ...schemas import Answer, Passage


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        raise ValueError("LLM_PROVIDER=hosted is not supported in this deployment; "
                         "use ollama-host (see docs/adr/0004-llm-provider-and-data-governance.md)")

    def generate(self, question: str, passages: list[Passage]) -> Answer:  # pragma: no cover
        raise ValueError("LLM_PROVIDER=hosted is not supported in this deployment")
