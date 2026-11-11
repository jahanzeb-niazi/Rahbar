# AI usage

We used one AI tool: **Claude Code** (Anthropic, model Claude Opus 5.5), in the Claude
desktop app, working inside this repository. We made every architectural decision
ourselves. Claude proposed options with trade-offs, we chose, and it implemented. The
decisions we made are listed below; we can explain each one and the code behind it.

| Tool | What it wrote or shaped | What we changed afterwards, and why |
| --- | --- | --- |
| Claude Code | **Indexer stages** (`indexer/pipeline/extract.py`, `clean.py`, `chunk.py`, `embed.py`, `store.py`) and their tests | We ran each stage against the real PDFs and fixed what broke: two-column pages were read straight across, the handbook carried the facing page's text at negative x coordinates, the prospectus's 3-column page was detected as one giant table, running footers sat mid-page, and table-of-contents lines were taken as headings. Each fix is in the code with the reason in a comment. One fix Claude proposed for the prospectus columns (detect the gutters despite margin marks and hanging clause numbers) fixed those 5 pages but split single-column handbook pages and an annual-report table, so we reverted it and documented the prospectus as not recovered (PIPELINE.md) |
| Claude Code | **API query pipeline**: `ChromaRetriever`, Ollama provider, prompt, validation with retry and fallback, citation check, Redis semantic cache, `/readyz`, embedding-pin guard, metrics, and their tests | We chose ollama-host only, Redis for the cache, a follow-up heuristic instead of a contract change, and a clear "unsupported" error for hosted mode. We tightened the "asks about an older version" rule after seeing that words like "earlier" would pull in repealed rules |
| Claude Code | **Evaluation**: `recall_at_k`, `citation_validity`, `summarise`, `gate` in `eval/run_eval.py` | We decided the section-matching rule (same source, golden heading contained in the retrieved section) |
| Claude Code | **`eval/golden.yaml`** | Questions written from the documents before any tuning. The version-sensitive answers were found by reading the 2023 scanned rules page by page and comparing them with the 2026 handbook |
| Claude Code | **Dockerfiles, Kubernetes manifests, overlays, `ci.yml`, `cd.yml`, `scripts/e2e-up.sh`** | We chose the blue/green re-index, fetching the corpus at Job start with checksum verification, kind for CI, and real embeddings with a stub LLM in CI |
| Claude Code | **Docs and ADRs** (first drafts) | Numbers in PIPELINE.md, FAILURE-ANALYSIS.md and ENGINEERING-NOTES.md come from our own runs (`kubectl top`, eval results, logs). We checked each claim against the raw results; two drafts were wrong and corrected: a per-question rank claim in ADR 0002, and the first draft of engineering note 7, which described the wrong incident |
| Claude Code | **Measurement scripts** (chunking runs, cache-threshold pairs, `kubectl top` sampling, failure-analysis Jobs) | We wrote the cache-threshold question pairs to include near-misses that need a different answer (2023 vs 2026 rules, B- vs B+). The tuned values (chunks 200/25, cache 0.95, floor 0.65) are the ones the data supported |

## Decisions we made (Claude asked, we answered)
1. LLM provider: ollama-host (llama3.2:3b + nomic-embed-text); hosted not supported.
2. Semantic cache: Redis, not a second Chroma collection (ADR 0003).
3. Corpus delivery: download at Job start and verify SHA-256 against the committed manifest.
4. Live index during re-index: blue/green collection plus pointer flip (ADR 0001).
5. Corpus: 9 FAST-NUCES documents, with hostel rules deliberately absent.
6. Chunk unit: approximate tokens (words x 1.3).
7. Follow-ups: text heuristic plus one structured log line per turn, no contract change.
8. CI: kind cluster, real embeddings, stub LLM.
9. Memory: minikube at 4 GB so Ollama can run on the same 16 GB laptop.
