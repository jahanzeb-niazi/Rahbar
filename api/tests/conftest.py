"""Shared fakes: no Chroma, no Redis, no Ollama, no network (section 6)."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.schemas import Answer, Citation, Passage


def passage(cid: str, score: float, source: str = "handbook-2026.pdf",
            section: str = "1. Attendance", text: str = "Attendance is 80 percent.") -> Passage:
    return Passage(chunk_id=cid, text=text, source=source, section=section, page=4, score=score)


class FakeRetriever:
    name = "fake"

    def __init__(self, passages: list[Passage], vector: list[float] | None = None,
                 generation: str = "rahbar-g1") -> None:
        self.passages = passages
        self.vector = vector if vector is not None else [1.0, 0.0, 0.0]
        self.gen = generation
        self.checks = {"chroma": "ok", "collection": "ok", "embed_model": "ok"}
        self.retrieve_calls = 0

    def embed(self, question: str) -> list[float] | None:
        return self.vector

    def generation(self) -> str:
        return self.gen

    def retrieve(self, question: str, k: int, vector: list[float] | None = None) -> list[Passage]:
        self.retrieve_calls += 1
        return self.passages[:k]

    def check(self) -> dict[str, str]:
        return dict(self.checks)


class ScriptedProvider:
    """Returns (or raises) the scripted items in order; records every call."""

    name = "scripted"

    def __init__(self, *script: Answer | Exception) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, list[Passage]]] = []

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        self.calls.append((question, passages))
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def grounded(source: str = "handbook-2026.pdf", section: str = "1. Attendance") -> Answer:
    return Answer(reasoning="r", answer=f"Attendance must be 80% [{source} / {section}].",
                  citations=[Citation(source=source, section=section, page=4)],
                  answered_from_context=True, confidence="high")


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}
        self.up = True

    def hset(self, key: str, field: str, value: str) -> None:
        self.data.setdefault(key, {})[field] = value

    def hvals(self, key: str) -> list[str]:
        return list(self.data.get(key, {}).values())

    def scan_iter(self, match: str) -> Iterator[str]:
        return iter([k for k in list(self.data) if fnmatch.fnmatch(k, match)])

    def delete(self, *keys: str) -> None:
        for k in keys:
            self.data.pop(k, None)

    def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("down")
        return True


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    from app.main import app

    with TestClient(app) as c:
        yield c
