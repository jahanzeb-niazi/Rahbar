# ADR 0003: Redis for the semantic cache

## Status
Accepted · 8 November 2026

## Context
Section 3.3 asks for a semantic cache: if a new question is close enough in meaning to one
already answered, serve the stored answer instead of retrieving and generating again.
Generation on a CPU laptop takes seconds per question, so a hit saves most of the request
time. The cache must sit in front of three API replicas, so it must be shared (a
per-process dictionary would give each replica its own cold cache). It must survive a pod
restart and be invalidated whenever the index is rebuilt. Allowed stores: Redis or a
second Chroma collection.

## Decision
**Redis** (`k8s/base/redis.yaml`: a Deployment with a PVC and append-only persistence),
used through `api/app/services/cache.py`:

- One Redis hash per index generation, `rahbar:cache:<generation>`. Each field holds the
  question, its embedding (already computed for retrieval, so the cache costs no extra
  model call) and the full response.
- A lookup reads the hash and computes cosine similarity in the API. A hit is similarity
  at or above `CACHE_THRESHOLD` from the ConfigMap; the value was chosen with data
  (docs/PIPELINE.md, "Semantic cache").
- **Invalidation on re-index:** the generation is the name of the collection that the index
  pointer names (ADR 0001). When the API sees a new generation, it deletes every other
  generation's hash before reading. The indexer never talks to Redis, and the NetworkPolicy
  allows redis traffic from api only.
- **Never cached:** follow-up questions, abstentions (including below-floor and
  out-of-scope answers), fallbacks, and anything that failed validation. A response is
  cached only when it is answered from context and has at least one valid citation
  (`services/answer.py`, `safe_to_cache`).
- A hit is marked `cached: true` in the response and by an `X-Cache: hit` header; the UI
  shows a cache chip. This is the one addition to the `AskResponse` contract, an optional
  field with a default, so older clients are unaffected.

## Options considered
- **A second Chroma collection.** Nearest-neighbour search would be native, but it couples
  the cache to the vector store: cache writes would come from the API, which ADR 0001
  keeps read-only against Chroma, and the NetworkPolicy would have to allow it. Cache
  churn would also share Chroma's single pod and PVC with the index, and invalidation
  would mean deleting collections next to the live index.
- **Redis with a vector index (RediSearch).** Faster lookups at scale, but it needs the
  Redis Stack image and module configuration. Our cache holds tens to hundreds of
  entries, where a linear scan of 768-dimension vectors takes well under a millisecond
  per entry.
- **In-process LRU per replica.** Not shared across replicas, lost on restart, and with no
  way to invalidate all three replicas together.

## Consequences
- Easier: a separate failure domain. If Redis is down, `/readyz` reports `redis` as the
  failed dependency. Cache data has its own small PVC, and flushing it never touches the
  index.
- Harder: the linear scan grows with the number of entries. With thousands of distinct
  questions per generation we would move to RediSearch or cap entries per generation.
- Watch: `rahbar_cache_hit_ratio` and `rahbar_cache_lookups_total{result}` on `/metrics`,
  and the `cache hit` log line, which records the similarity and the matched question so a
  false hit can be traced.
