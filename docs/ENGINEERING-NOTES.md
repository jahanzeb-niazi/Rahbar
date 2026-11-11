# Engineering notes

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

**The failure.** Three writers race on one index, and every restart re-indexes.

- The Deployment has `replicas: 3` (`k8s/base/api.yaml:10`), so a rollout or a scale-up
  starts three indexers at once.
- All of them write into the one Chroma collection behind the single `ReadWriteOnce`
  volume (`k8s/base/chroma-statefulset.yaml:79-83`). Each one adds its own 877 chunks, so
  the index ends up with duplicates or a mix of half-written generations.
- A full index here takes **624 s** (`manual-reindex-1`, mostly OCR of 41 pages). That is
  far beyond our startup probe's budget of 30 × 2 s = 60 s (`k8s/base/api.yaml:66-69`).
  The kubelet would kill every pod halfway through indexing, and they would CrashLoop
  forever.
- Even with a longer budget, a new pod would serve nothing for ten minutes. Each pod would
  also need about 300Mi more memory and a full CPU for OCR.

**The object that prevents it** is a separate one-shot **Job**, `kind: Job` at
`k8s/base/indexer-job.yaml:7`, with `backoffLimit: 3` and `activeDeadlineSeconds: 3600`
(lines 14-15). It is the only writer. The weekly CronJob that re-indexes sets
`concurrencyPolicy: Forbid` (`k8s/base/reindex-cronjob.yaml:13`), so two indexers can never
run at once.

The API pods only read. They resolve the `rahbar-active` pointer on each request
(`api/app/retrieval/chroma.py`). The indexer writes a new generation and flips the pointer
only after the count checks out (`indexer/pipeline/store.py`), so a re-index needs no API
restart. Evidence: `docs/evidence/reindex-cache-invalidation.txt` shows the same three api
pods before and after `manual-reindex-1`.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?

Our probes, in `k8s/base/api.yaml:70-77`:

| Probe | Endpoint | What it checks | Timing |
| --- | --- | --- | --- |
| Liveness | `/healthz` | Touches no dependency | Every 20 s, 3 failures |
| Readiness | `/readyz` | Chroma, the collection, the embedding pin and Redis (`api/app/routes/health.py`) | Every 10 s, 3 failures |

**Swapped**, liveness would call `/readyz`. When Chroma is slow for 90 seconds:

- Every replica's liveness probe fails at the same moment, because they share the one
  Chroma.
- After 3 × 20 s = 60 s the kubelet **kills all three containers**.
- Each restarted container waits up to 60 s in its startup probe and is then judged by the
  same failing liveness check. The pods fall into CrashLoopBackOff with growing back-off
  delays.
- So a 90-second slowdown becomes several minutes of total outage after Chroma has already
  recovered. Every in-flight request is lost when its pod is killed, including generations
  that take 30 to 120 s.

Readiness on `/healthz` would never fail, so the Service would keep sending traffic to pods
that return 503 for every question.

**As configured:**

- The three pods go NotReady after 30 s and leave the Service's endpoints.
- The Ingress returns 503 for those 90 seconds; no pod restarts.
- The pods come back on the next successful readiness check, within 10 s of Chroma
  recovering.

We saw readiness do this for real in the pin demonstration (`docs/evidence/embedding-pin-guard.txt`):
the kubelet logged `Readiness probe failed: HTTP probe failed with statuscode: 503` six
times, the pod stayed at 0/1, and it was never restarted.

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?

The HPA (`k8s/base/hpa.yaml:16-22`) measures the api container's CPU usage divided by
`requests.cpu`, which is 100m (`k8s/base/api.yaml`). That is the pod's own Python work:

- parsing JSON;
- calling the embedding endpoint;
- the cache lookup.

It does **not** include the generation itself, which runs in Ollama on the host. The pod
just waits on a socket.

Measured during the 19-question golden run, which kept the model busy the whole time
(`docs/evidence/kubectl-top-during-generation.txt`, 75 samples): the HPA reading stayed
between **1% and 12%** against its 70% target. Per-pod CPU was typically 12-13m while
questions took 31-118 s each. The HPA never scaled, and it was right not to: more API pods
would only queue more requests in front of the same single model.

**The signal that should scale it** is load on generation:

- the number of in-flight `/api/ask` requests per pod (or the generation queue length);
- generation latency, which we already export as the
  `rahbar_generation_seconds` histogram in `api/app/routes/metrics.py:25`;
- tokens per second, from `rahbar_tokens_out` (line 36).

**What we would have to build:**

1. An in-flight gauge in the api.
2. Prometheus scraping `/metrics`.
3. `prometheus-adapter` (or KEDA) to expose the gauge as a custom metric.
4. An HPA on `type: Pods` with that metric.

On this laptop the bottleneck is one CPU-bound Ollama, so the real scaling unit would be
the model server, with GPU nodes, not the API.

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong

The Job sets requests 500m / 512Mi and limits 1 CPU / **1Gi** (`k8s/base/indexer-job.yaml:49-52`;
the CronJob uses the same values at `k8s/base/reindex-cronjob.yaml:53-56`).

| Run | Peak memory (`kubectl top`) | Against the 1Gi limit | Evidence |
| --- | ---: | --- | --- |
| First full run | **925Mi**, then killed | — | `docs/evidence/kubectl-top-indexer-oomkilled.txt` |
| After the fix | **306Mi** | 3.3×, about 718Mi of headroom | `docs/evidence/kubectl-top-indexer-run.txt` |

In the first run, memory climbed 55 → 373 → 596 → 839Mi; the container was killed and
restarted, then 265 → 852Mi, then 243 → 925Mi. Kubernetes reported the container as
**OOMKilled with exit code 137** (128 + SIGKILL), and the Job gave up after `backoffLimit`.

The cause was not the embeddings, which the assignment's troubleshooting table suggests
first. pdfplumber caches every parsed page. The Aug 2023 rules draw every glyph as vector
outlines, so that one PDF held about 950 MB locally. Calling `raw_page.close()` after each
page (`indexer/pipeline/extract.py:78`) brought the local peak for that file to 93 MB.

We kept the 1Gi limit rather than lowering it to fit 306Mi. A page with more vector
outlines, or an OCR spike at 300 dpi, can double the peak, and a re-index that dies at
minute nine is expensive. The 512Mi request is above the peak, so the scheduler reserves
what the Job really uses.

## 5. recall@5 by question type: where is it worst, and why?

From `eval/results.json` (200/25 chunks, real model):

| Type | recall@5 |
| --- | ---: |
| ordinary | 1.00 |
| version | 1.00 |
| injection | 1.00 |
| **exact** | **0.75** |

The only question missed in every chunking configuration is **e01**: "What does clause
1.21 require?". Its top hit is a prospectus chunk at 0.6965, and the handbook's clause 1.21
is not in the top 5 at all.

**Why embeddings struggle.** A dense embedding encodes what a passage is *about*, not its
exact tokens:

- "clause 1.21", "clause 1.12" and "clause 2.21" are near neighbours in vector space;
- the number itself carries almost no weight against the surrounding words about
  registration.

So the chunk that literally contains "1.21" scores no higher than any chunk about the same
topic. e04 (the Rs. 500 rechecking fee) is the same problem in a milder form: rank 3,
behind two chunks about other fees.

**The fix from the RAG lecture is hybrid search.** Run a keyword (BM25) retriever next to
the vector one and merge the two rankings with reciprocal rank fusion, optionally followed
by a cross-encoder re-ranker. BM25 scores the exact token "1.21" highly, which is exactly
what the dense retriever misses. We did not build it, because it is outside the assignment.
The gate's per-type recall would show whether it worked.

## 6. EMBED_MODEL changed on the API only: what does your system do?

**What it does.** The collection metadata records the model it was built with
(`indexer/pipeline/store.py:53-55`). A restarted api pod with a different `EMBED_MODEL`
then behaves like this:

- `/readyz` returns **503**, and the log names both models: "embedding model mismatch: the
  index was built with 'nomic-embed-text' (dimension 768) but this API has
  EMBED_MODEL='all-minilm'" (`api/app/services/pin.py:13-23`).
- The pod never becomes Ready, so it never receives traffic.
- Because `maxUnavailable: 0` (`k8s/base/api.yaml:16`), the rollout stalls and the three
  old pods keep answering.
- If a request reached the pod anyway, `retrieve()` would raise `PinMismatchError`
  (`api/app/retrieval/chroma.py:105-107`), and `/api/ask` would return a clear 503 saying
  the index and the API disagree (`api/app/routes/ask.py:24-26`).

We ran it: `docs/evidence/embedding-pin-guard.txt`.

**Without the guardrail** it depends on the new model's dimension:

- **Different dimension** (all-minilm is 384, nomic is 768): Chroma rejects the query, and
  every question becomes a 500 with a stack trace. That is loud, but it is an outage. Our
  extra dimension check (`api/app/retrieval/chroma.py:109-112`) turns that into the same
  clear 503.
- **Same dimension** (for example another 768-dimension model): this is the dangerous case.
  Retrieval returns the "nearest" chunks in an unrelated vector space, which is effectively
  random passages with plausible-looking scores. The model then either abstains on
  everything or answers from irrelevant text and cites it, with no error anywhere.
  recall@5 would collapse. In production, only the abstention rate and user complaints
  would show it.

## 7. The failure that cost us more than an hour

**Symptom.** From the first real questions (13:05 UTC on 8 November) until 14:29, answers
through the Ingress came back as the canned fallback ("could not produce a grounded
answer"). At first every one did; later, many did.

Nothing looked broken:

- every pod was 1/1 READY;
- `/readyz` was green;
- retrieval was clearly fine, with the right sections first at scores of 0.80-0.87.

**What we wrongly believed first.** The fallback is what `generate_validated()`
(`api/app/services/generation.py`) returns after the model fails validation twice. So we
read it as a model-quality problem: a 3B model writing bad JSON or making up citations.
We looked at the prompt and the schema.

**What told us the truth** was two things, one per hidden cause.

1. **The api's warning log.**
   `kubectl logs -n rahbar -l app=api --tail=200 | grep "generation rejected"` showed the
   reason for both attempts:

   ```
   {"level": "WARNING", "logger": "rahbar.generation", "msg": "generation rejected", "attempt": 2,
    "error": "HTTPStatusError", "detail": "Server error '500 Internal Server Error' for url 'http://192.168.65.254:11434/api/chat'"}
   ```

   It was not a validation error: Ollama itself was failing. Calling it directly, outside
   the cluster, gave the real message:

   ```
   curl http://127.0.0.1:11434/api/chat -d '{"model":"llama3.2:3b", ..., "options":{"num_ctx":8192}}'
   ... failed to allocate buffer for kv cache
   ```

   The laptop had about 3 GB free with minikube holding 6 GB. The 8,192-token context needs
   a 0.9 GB KV cache on top of 2 GB of weights. The fallback had done its job, which is to
   never show a 500, and that is exactly what hid the error.

   **Fix:** `NUM_CTX = 4096` (`api/app/providers/llm/ollama.py`) and minikube recreated at
   4 GB.
2. **The same log line, with a different error.** With generation working, the first golden
   run still had fallbacks, and the warning now said `"error": "GroundingError"`. The
   model's citations were *real but shortened*: it cited section
   `Academic Warning/Probation`, while the retrieved passage's section was `5. Academic Assessment > Academic Warning/Probation`. Our exact-match
   grounding check (`check_grounding`) rejected correct, grounded answers as uncited.

   **Fix:** a citation now matches a retrieved passage when its section is contained in the
   passage's section. The citation is then rewritten to the passage's exact source, section
   and page, so the user only ever sees real ones. A test covers it:
   `test_shortened_section_citation_is_accepted_and_rewritten_exactly` in
   `api/tests/test_pipeline.py:360`.

**Lesson:** a safe fallback must still say *why* it fired. The `generation rejected` warning
(`api/app/services/generation.py:90`) names the error class. The turn log records
`fallback`, and `rahbar_fallbacks_total` counts it (`api/app/routes/metrics.py:33`). A
fallback rate near 100% with green readiness means "look at the provider", not "look at
the model".
