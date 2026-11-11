# ADR 0001: The indexer is a Job; the API only reads

## Status
Accepted · 8 November 2026

## Context
RAHBAR has two workloads with opposite shapes. Indexing (extract, OCR, clean, chunk,
embed, store) is heavy, slow, and needed once and again only when the documents change.
Querying is light, fast, and runs on every question. The API runs as three replicas
behind one Service, and the vector store is one Chroma pod with one ReadWriteOnce volume.

The obvious design is to index when an API pod starts, so a fresh deployment "just works".
With three replicas that design breaks in four ways:

1. **Three writers, one volume.** Three pods would write the same collection at once,
   each part-way through a different document. Chroma would accept all of it, and the
   result is an index that no single run produced: duplicated chunks, half-written
   documents, or a collection deleted by pod B while pod A is still adding to it.
2. **Every restart re-indexes.** A rolling update, an OOMKill, a node drain or a
   readiness blip would each pay the full OCR and embedding cost again (minutes per pod,
   because 32 pages of our corpus are OCR'd).
3. **Readiness becomes a lie.** Either the pod says ready before the index exists and
   serves empty retrievals, or it stays unready for minutes. In the second case the startup
   probe kills it part-way through and a rolling update swaps three working pods for three
   that are still chunking PDFs.
4. **No re-index without a redeploy.** Changing the corpus would mean restarting the API,
   which is the configuration-needs-a-rebuild failure from Lecture 05.

## Decision
- A Kubernetes **Job** (`k8s/base/indexer-job.yaml`) builds the index and exits. A weekly
  **CronJob** (`k8s/base/reindex-cronjob.yaml`) runs the same image and command, with
  `concurrencyPolicy: Forbid` so two indexers never write at once. An on-demand re-index is
  one command with no redeploy:
  `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`.
- `indexer/pipeline/store.py` is the only code that writes to Chroma. The API process has
  no write path (`api/app/retrieval/chroma.py` only calls `get_collection`, `query`,
  `count` and `heartbeat`), and the NetworkPolicy lets only api and indexer reach Chroma.
- The API's readiness probe (`/readyz`, `api/app/routes/health.py`) reports ready only
  when Chroma is reachable, the collection exists **and is non-empty**, its embedding model
  matches `EMBED_MODEL`, and Redis is reachable. Until the Job has run, the pods are
  withheld from the Service instead of serving empty answers.

### What happens to the live index during a re-index: blue/green
The Job never modifies the collection the API is reading. Each run writes a **new**
collection `rahbar-g<UTC timestamp>`. Only after every chunk is stored and the count
checked does it flip a pointer: the collection `rahbar-active`, whose metadata is
`{"target": "rahbar-g..."}`, is updated in one metadata write. The API resolves the
pointer on every question, so it moves to the new index without a restart and without a
moment where the collection is empty or half-built. The generation just replaced is kept
so queries already in flight can finish; older ones are deleted. A failed run, for
example a checksum mismatch, an OCR crash or an OOMKill, never reaches the flip, so the
old index keeps serving and the Job's failure is visible in `kubectl get jobs`.

The generation name also invalidates the semantic cache (ADR 0003): cache entries are keyed
by generation, so the first question after a flip cannot be served a stale answer.

## Options considered
- **Index in API startup**: rejected for the four reasons above.
- **An init container on the API Deployment**: still runs once per pod (three writers, a
  re-index on every restart). It only moves the problem.
- **Delete and rebuild the collection in place**: simpler, but for the length of the run
  the API sees an empty or partial collection. Readiness would flap to 503 on all three
  pods at once, which is downtime caused by a routine re-index.
- **A long-running indexer Deployment that watches for changes**: an idle pod holding
  1 GiB of memory to do work that happens weekly.

## Consequences
- Easier: re-indexing is safe at any time, the API restarts in seconds, and the indexer's
  large memory limit (it OCRs and embeds) is paid only while the Job runs.
- Harder: a fresh cluster needs the Job to finish before the API becomes ready (README
  apply order), and Chroma briefly holds two generations of the index (about twice
  the storage; the 2 GiB PVC has room).
- Watch: `kubectl get jobs -n rahbar` after the weekly run, and the API's
  `cache invalidated after re-index` log line, which confirms the flip was seen.
