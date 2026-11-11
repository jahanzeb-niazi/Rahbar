# ADR 0004: LLM provider (ollama-host) and data governance

## Status
Accepted · 8 November 2026

## Context
Section 3.5 asks for the provider behind an interface selected by `LLM_PROVIDER`, with at
least one mode supported fully. The modes are ollama-host (Ollama on the laptop),
ollama-incluster (a bonus) and hosted (a free-tier API with a key). The choice also
decides where user questions and document text travel, which is a data-governance
question as much as an engineering one.

## Decision
- **ollama-host is the one fully supported mode.** Generation uses `llama3.2:3b`.
  Embeddings use `nomic-embed-text` through the same Ollama host (we embed through the
  generation host, as section 3.5 allows; the README says so). The base ConfigMap names
  `http://host.minikube.internal:11434`, but on our Docker Desktop minikube that name did
  not resolve. The dev overlay therefore patches `OLLAMA_URL` to
  `http://192.168.65.254:11434`, Docker Desktop's host address, which forwards to the
  laptop's localhost. Ollama can keep its default `127.0.0.1` binding and is never exposed
  on the LAN. The dev overlay's NetworkPolicy allows egress from api and indexer to that
  one address on port 11434 only (`k8s/overlays/dev/networkpolicy-ollama.yaml`).
- The interface is `api/app/providers/llm/base.py` (`generate(question, passages) ->
  Answer`). The prompt is built in `services/prompt.py`, and validation, retry and fallback
  live in `services/generation.py`, so swapping providers is one file in `providers/llm/`.
- `LLM_PROVIDER=hosted` is **not supported**: `HostedProvider` fails at startup with a
  clear message rather than failing on the first question. `stub` is used by every unit
  test and by the CI e2e job (real embeddings, stub generation).
- Enforcement: the `Answer` JSON schema is sent as Ollama's `format`, so decoding is
  constrained to it. The reply is still validated with Pydantic, retried once, then
  replaced with a safe canned answer. Temperature is `0.1` (ConfigMap, with its
  justification).

## Data governance and PII
- **Where data goes.** Questions, retrieved passages and answers never leave the
  laptop/cluster boundary: Chroma, Redis and Ollama all run locally. With a hosted provider,
  every question and five retrieved chunks would be sent to a third party under its
  retention terms. That is the main reason we did not choose it.
- **What the corpus contains.** Only public FAST-NUCES documents (corpus/MANIFEST.md).
  Nothing from SLATE, Flex, NU Mail or behind a login. Some documents name officials
  (for example the Rector's foreword); these are public office-holders in public documents.
- **What we store about users.** The cache stores question text and its vector so that a
  later similar question can be served. Users should not paste personal data into
  questions. The cache is per index generation and is flushed on every re-index, so
  nothing persists beyond a week. Logs record the request id, retrieved chunk ids, scores
  and flags, not the answer text. The question text is not logged either; only the cache
  hit line records the matched question.
- **Secrets.** ollama-host needs no key. The Secret manifest in Git is a placeholder
  (`k8s/base/secret.placeholder.yaml`, `REPLACE_ME`, not listed in kustomization), and
  `*secret*.yaml` and `.env` are gitignored.
- **Untrusted text.** Retrieved text and model output are data. They are delimited in the
  prompt, schema-constrained, validated, never passed to `eval`, and never used to build a
  query or a shell command.

## Options considered
- **hosted (Groq, Google AI Studio, OpenRouter):** faster generation and no laptop GPU
  needed, but it sends user questions and document text to a third party, needs a key in
  a Secret, and depends on free-tier rate limits during the CI eval and the demo.
- **ollama-incluster:** keeps everything inside the cluster, but needs at least 8 GB for
  minikube and a slow-starting pod for the model weights. It is a bonus mode, so not
  pursued.

## Consequences
- Easier: no secrets to manage or rotate, no rate limits, and data stays local.
- Harder: generation speed depends on the laptop's CPU (several seconds per answer), and
  the cluster depends on a process outside it. That dependency is reached through one
  NetworkPolicy rule, and `/readyz` deliberately does not check Ollama: a slow LLM must not
  take every API pod out of the Service. Generation failures become the fallback answer
  and `rahbar_fallbacks_total`.
