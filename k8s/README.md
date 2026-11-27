# Assignment 03 on Kubernetes

Run from the repository root on a single-node minikube cluster with PowerShell 7. The shared ReadWriteOnce volume assumes the node can co-mount it across pods. Allow enough memory for the API replicas, Chroma and Jobs. Ollama runs on the host and must listen on an address the cluster can reach. Use the existing dev overlay's address or adjust both its Ollama endpoint and egress CIDR.

```powershell
ollama pull nomic-embed-text
ollama pull llama3.2:3b
minikube start --cni=calico
minikube addons enable metrics-server
docker build -t rahbar-api:dev api
docker build -t rahbar-ui:dev ui
docker build -t rahbar-indexer:dev -f indexer/Dockerfile .
'rahbar-api:dev','rahbar-ui:dev','rahbar-indexer:dev' | ForEach-Object { minikube image load $_ }
kubectl apply -k k8s/assignment3
```

Use a fresh namespace or cluster. Deployment selectors are immutable once created. The A03 overlay suspends the A02 ingestion schedules and one-shot Job.

## A. Verify and update

```powershell
./scripts/ragops.ps1 ingest -Name batch-a -Batch a
kubectl -n rahbar wait --for=condition=complete job/batch-a --timeout=600s
kubectl -n rahbar logs job/batch-a
./scripts/ragops.ps1 ingest -Name batch-a-repeat
kubectl -n rahbar wait --for=condition=complete job/batch-a-repeat --timeout=600s
kubectl -n rahbar logs job/batch-a-repeat
```

Run the baseline and release experiment before updating the input. For Batch B and drift, use Part E below. After that experiment, run these two independent checks.

```powershell
./scripts/ragops.ps1 ingest -Name delete-fees -Batch deleted
kubectl -n rahbar wait --for=condition=complete job/delete-fees --timeout=600s
kubectl -n rahbar logs job/delete-fees
./scripts/ragops.ps1 ingest -Name restore-rules -Batch b -Restore '{"academic-rules":"2026"}'
kubectl -n rahbar wait --for=condition=complete job/restore-rules --timeout=600s
kubectl -n rahbar logs job/restore-rules
```

A manifest lists the authoritative snapshot. To index unseen documents, stage files on the PVC under `/lake/input`, add metadata entries to `_index.json`, then run the same ingest command without `-Batch`. Use a maintenance window while changing inputs. An optional end marker detects a truncated final page when a known terminator exists. The supplied batches are fictional Assignment 02 fixture extensions. Raw input is retained so a CronJob can re-verify it. Quarantine, retained archive copies and per-run reports are under `/lake`. Verification checks are recorded individually even when the disposition is quarantine. Near duplicate detection compares embeddings of the first 1,800 normalized characters with a provisional cosine cutoff of 0.96. A newly accepted generation reuses previously embedded vectors and publishes with the existing blue/green pointer. The report counts actual rows in the current serving collection. Restore overrides the version for that ingestion run. Persist the override in the scheduled Job spec if it should survive scheduled ingestion.

## B. Baseline suite

```powershell
kubectl -n rahbar rollout status deployment/api --timeout=300s
kubectl apply -f k8s/eval-job.yaml
kubectl -n rahbar wait --for=condition=complete job/ragops-eval --timeout=1800s
kubectl -n rahbar logs job/ragops-eval
```

The suite runs twice with seed 42, uses evaluation requests that bypass the semantic cache, and retains trace IDs. CPU scheduling, Ollama load, approximate search and warm caches in dependencies can still affect repeatability. The required human-authored questions and human review must be supplied by the group. The included questions are synthetic. The faithfulness proxy requires an expected phrase and a citation to a relevant passage. It can miss unsupported claims and reject valid paraphrases. The gate parameters are provisional. A faithful answer rate of 0.60 is an initial compatibility floor for this proxy. The latency limit budgets one minute for the local demo. Citation validation requires full consistency with retrieved passages.

## C. Candidate and gate

```powershell
./scripts/ragops.ps1 ingest -Name index-candidate -Collection rahbar-candidate
kubectl -n rahbar wait --for=condition=complete job/index-candidate --timeout=600s
kubectl -n rahbar set env deployment/api-candidate TOP_K=1
kubectl -n rahbar rollout status deployment/api-candidate --timeout=300s
./scripts/ragops.ps1 eval -Name bad -Endpoint http://api-candidate:8000 -Reference baseline
kubectl -n rahbar logs -f job/bad
kubectl -n rahbar set env deployment/api-candidate TOP_K=6
kubectl -n rahbar rollout status deployment/api-candidate --timeout=300s
./scripts/ragops.ps1 eval -Name candidate -Endpoint http://api-candidate:8000 -Reference baseline
kubectl -n rahbar logs -f job/candidate
./scripts/ragops.ps1 release -Name candidate
```

The only query-pipeline experiment is top-k (5 baseline, 6 candidate, 1 negative control). The candidate uses an isolated Chroma collection with the same corpus snapshot and model. Check gate outcomes before promotion. To exercise ConfigMap control against the same candidate, change the latency upper bound to a value below its measured p95 using `kubectl -n rahbar edit configmap ragops-gate`. Run a fresh evaluation Job with `-Name strict`. Restore the original ConfigMap with `kubectl apply -k k8s/assignment3` **before promotion** and re-evaluate the candidate. Applying the overlay also plants its declared Deployment state.

## D. Traces and metrics

```powershell
kubectl -n rahbar port-forward svc/api 8000:8000
```

In a second terminal, use Batch B for the injection test.

```powershell
$turn = Invoke-RestMethod http://localhost:8000/api/ask -Method Post -ContentType application/json -Body '{"question":"When and where is orientation check-in?"}'
kubectl -n rahbar logs -l traffic=live --tail=120 | Select-String $turn.request_id
Invoke-WebRequest http://localhost:8000/metrics
python traces/inspect_trace.py $turn.request_id
python traces/inspect_trace.py --from-time 2026-01-01T00:00:00Z
```

Copy the cluster trace files first, using the evidence commands in F. Cached hits keep the original prompt and its originating trace ID. A response that abstained before generation has no model prompt.

## E. Coverage and data drift

```powershell
./scripts/ragops.ps1 coverage -Name coverage-before
./scripts/ragops.ps1 coverage -Name coverage-expanded -Golden golden-expanded.jsonl
kubectl -n rahbar logs job/coverage-before
kubectl -n rahbar logs job/coverage-expanded
./scripts/ragops.ps1 ingest -Name batch-b -Batch b
kubectl -n rahbar wait --for=condition=complete job/batch-b --timeout=600s
kubectl -n rahbar logs job/batch-b
./scripts/ragops.ps1 eval -Name drift-same-gold
./scripts/ragops.ps1 eval -Name drift-updated-gold -Golden golden-batch-b.jsonl
```

Use the baseline live Deployment for the drift comparison. Undo a previous promotion first if needed. The same-gold run exposes stale labels. The updated-gold run uses the newer policy as ground truth. The initial 0.82 cosine criterion is a provisional bar for semantic similarity, and 85% is the paper's example coverage target. The expanded set labels six workload gaps as cases where the correct answer is abstention.

## F. Inspect, capture evidence, and undo

```powershell
kubectl -n rahbar get all,pvc,configmap,cronjob,job
kubectl -n rahbar top pods --containers
kubectl -n rahbar rollout history deployment/api
kubectl -n rahbar rollout status deployment/api
kubectl -n rahbar rollout undo deployment/api
kubectl -n rahbar rollout status deployment/api
$pod = kubectl -n rahbar get pod -l traffic=live -o 'jsonpath={.items[0].metadata.name}'
kubectl -n rahbar cp "${pod}:/lake/results/." eval/results
kubectl -n rahbar cp "${pod}:/lake/traces/." traces
```

After undo, ask a fresh question with header `X-RAGOps-Eval: 1` and find its trace in the live pod logs. Capture collection and embedding model version. To demonstrate an operationally bad release, deploy a nonexistent collection manually in a demo-only exercise, confirm the rollout cannot become ready, then undo. Keep the bad candidate evaluation separate and do not promote its failed revision. Record live resource use while Jobs are active and capture the required terminal screenshots from your own cluster. Commit generated JSON and JSONL under `eval/results/` and `traces/` after reviewing the recorded queries and contexts.
