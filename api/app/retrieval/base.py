"""The retriever interface. The rest of the API only ever sees this."""

from __future__ import annotations

from typing import Protocol

from ..schemas import Passage


class Retriever(Protocol):
    name: str

    def embed(self, question: str) -> list[float] | None:
        """The question's vector from the pinned model, or None when there is no model
        (the stub). The semantic cache compares these vectors."""
        ...

    def generation(self) -> str:
        """An id that changes whenever the index is rebuilt. Cache entries are keyed by
        it, so a re-index invalidates every cached answer."""
        ...

    def retrieve(self, question: str, k: int, vector: list[float] | None = None) -> list[Passage]:
        """Return up to k passages, best first."""
        ...

    def check(self) -> dict[str, str]:
        """Readiness checks: name -> "ok" or a reason it failed."""
        ...
