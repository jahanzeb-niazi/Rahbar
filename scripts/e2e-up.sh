#!/usr/bin/env bash
# Bring RAHBAR up on an ephemeral kind cluster for CI (e2e-eval) and CD (deploy).
#
#   scripts/e2e-up.sh <overlay-dir>      e.g. k8s/overlays/dev  or  k8s/overlays/prod
#
# Expects: a kind cluster created with .github/kind-config.yaml (port 80 mapped to the host),
# the overlay's images either loaded into kind (dev) or pullable (prod).
#
# What it does, in order:
#   1. ingress-nginx for kind, waited until ready
#   2. Ollama as a container on the "kind" Docker network with ONLY the embedding model:
#      CI uses real embeddings and the stub LLM (no model weights on a CPU runner)
#   3. kubectl apply -k <overlay>, then point the ConfigMap at the CI settings:
#      LLM_PROVIDER=stub, the Ollama container, and the fixture corpus baked into the image
#   4. the indexer Job (from the CronJob template), waited until complete
#   5. kubectl rollout status for every Deployment and the StatefulSet
set -euo pipefail

OVERLAY="${1:?usage: scripts/e2e-up.sh <overlay-dir>}"
NS=rahbar
EMBED_MODEL=nomic-embed-text
OLLAMA_IMAGE=ollama/ollama:0.6.8

echo "::group::ingress-nginx"
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.2/deploy/static/provider/kind/deploy.yaml
kubectl wait -n ingress-nginx --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s
echo "::endgroup::"

echo "::group::ollama (embeddings only)"
docker run -d --name ollama --network kind "$OLLAMA_IMAGE"
for _ in $(seq 1 30); do docker exec ollama ollama list >/dev/null 2>&1 && break; sleep 2; done
docker exec ollama ollama pull "$EMBED_MODEL"
OLLAMA_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ollama)
echo "ollama at $OLLAMA_IP"
echo "::endgroup::"

echo "::group::apply $OVERLAY"
kubectl apply -k "$OVERLAY"
# The Job starts as soon as it is applied, before the CI settings below; replace it.
kubectl delete job indexer -n "$NS" --ignore-not-found --wait=true
kubectl patch configmap rahbar-config -n "$NS" --type merge -p "{\"data\": {
  \"LLM_PROVIDER\": \"stub\",
  \"OLLAMA_URL\": \"http://${OLLAMA_IP}:11434\",
  \"FETCH_CORPUS\": \"false\",
  \"CORPUS_DIR\": \"/app/fixtures\"}}"
# The overlay's allow-ollama-egress names the laptop's address; here Ollama is a container.
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ollama-egress
  namespace: $NS
spec:
  podSelector:
    matchExpressions:
      - {key: app, operator: In, values: ["api", "indexer"]}
  policyTypes: ["Egress"]
  egress:
    - to:
        - ipBlock:
            cidr: ${OLLAMA_IP}/32
      ports:
        - {protocol: TCP, port: 11434}
EOF
echo "::endgroup::"

echo "::group::wait for chroma"
kubectl rollout status statefulset/chroma -n "$NS" --timeout=300s
echo "::endgroup::"

echo "::group::indexer Job (fixture corpus)"
kubectl create job --from=cronjob/reindex e2e-index -n "$NS"
if ! kubectl wait --for=condition=complete job/e2e-index -n "$NS" --timeout=600s; then
  kubectl logs -n "$NS" job/e2e-index --tail=100 || true
  exit 1
fi
kubectl logs -n "$NS" job/e2e-index --tail=20
echo "::endgroup::"

echo "::group::rollout"
# the api pods started before the ConfigMap patch; restart them onto the CI settings
kubectl rollout restart deployment/api -n "$NS"
kubectl rollout status deployment/redis -n "$NS" --timeout=300s
kubectl rollout status deployment/ui -n "$NS" --timeout=300s
if ! kubectl rollout status deployment/api -n "$NS" --timeout=300s; then
  kubectl get pods -n "$NS" -o wide
  kubectl logs -n "$NS" deployment/api --tail=50 || true
  exit 1
fi
kubectl get pods,svc,ingress -n "$NS"
echo "::endgroup::"
