"""Ollama provider: ollama-host or ollama-incluster (section 3.5).

Enforce, then validate: the Answer JSON schema goes to Ollama as `format`, so decoding is
constrained to it, and the reply is still parsed with Answer.model_validate_json. A reply
that fails to parse raises; services/generation.py retries once and then falls back.
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...routes.metrics import TOKENS_IN, TOKENS_OUT
from ...schemas import Answer, Passage
from ...services.prompt import build_messages

NUM_PREDICT = 512   # cap the reply: a short answer + reasoning; bounds generation time on CPU
NUM_CTX = 4096   # 5 chunks of ~400 tokens + instructions + the JSON answer is ~2,800 tokens;
                 # 8192 needs a 0.9 GB KV cache, which a 16 GB laptop running minikube lacks


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # ollama_url, llm_model, temperature, llm_timeout
        self.http = httpx.Client(timeout=httpx.Timeout(settings.llm_timeout, connect=5.0))

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        r = self.http.post(
            f"{self.settings.ollama_url.rstrip('/')}/api/chat",
            json={
                "model": self.settings.llm_model,
                "messages": build_messages(question, passages),
                "format": Answer.model_json_schema(),
                "stream": False,
                "options": {"temperature": self.settings.temperature, "num_ctx": NUM_CTX,
                            "num_predict": NUM_PREDICT},
            },
        )
        r.raise_for_status()
        body = r.json()
        TOKENS_IN.observe(body.get("prompt_eval_count", 0))
        TOKENS_OUT.observe(body.get("eval_count", 0))
        return Answer.model_validate_json(body["message"]["content"])
