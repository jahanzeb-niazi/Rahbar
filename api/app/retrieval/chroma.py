"""The real retriever (sections 3.2 and 4.4). It only reads Chroma; the indexer Job writes.

The index is blue/green (ADR 0001): the indexer writes `<collection>-g<timestamp>` and flips
the pointer collection `<collection>-active` to it. This retriever resolves the pointer on
every question, so a re-index takes effect without a restart. With no pointer (the week-1
dummy index) it reads `<collection>` directly.
"""

from __future__ import annotations

import logging
import re
import socket
from typing import Any

import httpx

from ..config import Settings
from ..schemas import Passage
from ..services.pin import pin_mismatch

log = logging.getLogger("rahbar.retrieval")

# nomic-embed-text is trained with task prefixes; the indexer uses "search_document: ".
QUERY_PREFIX = {"nomic-embed-text": "search_query: "}

# The user is asking about an older version: search superseded documents too (section 3.2).
_OLDER = re.compile(
    r"\b(old|older|previous|earlier|former|outdated)\s+"
    r"(version|edition|rules|policy|handbook|regulations)\b"
    r"|\b(superseded|repealed)\b|\b20(0\d|1\d|2[0-5])\b",
    re.I,
)


class PinMismatchError(RuntimeError):
    """The index was built with a different embedding model than this API uses."""


def wants_older_version(question: str) -> bool:
    return bool(_OLDER.search(question))


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None
        self.http = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))

    @property
    def client(self) -> Any:
        """Created on first use, not at startup: chromadb.HttpClient contacts the server in
        its constructor, and process startup (and so liveness) must never wait on Chroma.
        Until Chroma answers, /readyz reports it as the failed dependency."""
        if self._client is None:
            # Fail in 2 s, not after the OS TCP timeout (minutes on Linux) when the Service
            # has no ready endpoint yet and packets are dropped.
            socket.create_connection((self.settings.chroma_host, self.settings.chroma_port),
                                     timeout=2.0).close()
            import chromadb  # the thin client, from chromadb-client in requirements.txt
            from chromadb.config import Settings as ChromaSettings

            self._client = chromadb.HttpClient(
                host=self.settings.chroma_host, port=self.settings.chroma_port,
                settings=ChromaSettings(anonymized_telemetry=False))
        return self._client

    @client.setter
    def client(self, value: Any) -> None:
        self._client = value

    # ------------------------------------------------------------ index resolution

    def active_name(self) -> str:
        """The collection the pointer names, or the base collection without a pointer."""
        base = self.settings.collection
        try:
            pointer = self.client.get_collection(f"{base}-active")
            target = (pointer.metadata or {}).get("target")
            if target:
                return str(target)
        except Exception:  # no pointer yet: the dummy index, or nothing indexed
            pass
        return base

    def _collection(self) -> Any:
        return self.client.get_collection(self.active_name())

    def generation(self) -> str:
        return self.active_name()

    # ------------------------------------------------------------ query pipeline

    def embed(self, question: str) -> list[float]:
        prefix = QUERY_PREFIX.get(self.settings.embed_model.split(":")[0], "")
        r = self.http.post(f"{self.settings.ollama_url.rstrip('/')}/api/embed",
                           json={"model": self.settings.embed_model, "input": [prefix + question]})
        r.raise_for_status()
        return [float(x) for x in r.json()["embeddings"][0]]

    def retrieve(self, question: str, k: int, vector: list[float] | None = None) -> list[Passage]:
        collection = self._collection()
        problem = pin_mismatch(collection.metadata or {}, self.settings.embed_model)
        if problem:
            raise PinMismatchError(problem)
        vector = vector if vector is not None else self.embed(question)
        dimension = (collection.metadata or {}).get("dimension")
        if dimension is not None and int(dimension) != len(vector):
            raise PinMismatchError(
                f"embedding dimension mismatch: index {collection.name} has {dimension}-d "
                f"vectors but {self.settings.embed_model} returned {len(vector)}-d")
        where = None if wants_older_version(question) else {"superseded": False}
        result = collection.query(query_embeddings=[vector], n_results=k, where=where,
                                  include=["documents", "metadatas", "distances"])
        passages = []
        for cid, text, meta, dist in zip(result["ids"][0], result["documents"][0],
                                         result["metadatas"][0], result["distances"][0]):
            meta = meta or {}
            page = meta.get("page")
            passages.append(Passage(
                chunk_id=cid, text=text or "", source=str(meta.get("source", "")),
                section=str(meta.get("section", "")),
                page=int(page) if isinstance(page, (int, float)) else None,
                score=round(1.0 - float(dist), 4),     # cosine distance -> similarity
            ))
        return passages

    # ------------------------------------------------------------ readiness

    def check(self) -> dict[str, str]:
        checks: dict[str, str] = {}
        try:
            self.client.heartbeat()
            checks["chroma"] = "ok"
        except Exception as exc:
            checks["chroma"] = f"unreachable: {type(exc).__name__}"
            return checks
        try:
            collection = self._collection()
        except Exception:
            checks["collection"] = f"collection {self.active_name()!r} does not exist"
            return checks
        count = int(collection.count())
        checks["collection"] = "ok" if count > 0 else f"collection {collection.name!r} is empty"
        problem = pin_mismatch(collection.metadata or {}, self.settings.embed_model)
        checks["embed_model"] = problem or "ok"
        return checks
