#!/bin/sh
# Bring up profile K locally: kind cluster, CloudNativePG operator (pinned), the
# images (side-loaded, nothing pulled inside kind), the local-kind overlay.
#   deploy/eks-cnpg/local/up.sh
# Then deploy/eks-cnpg/local/verify.sh. Tear down: kind delete cluster --name vg-cnpg
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$HERE/.."; REPO="$ROOT/../.."
CNPG_CHART_VERSION="${CNPG_CHART_VERSION:-0.29.1}"      # operator 1.30.1
EXT_IMAGE="${EXT_IMAGE:-vg-planner-ext:0.2.0-18.4-trixie}"
IMAGES="ghcr.io/cloudnative-pg/postgresql:18.4-minimal-trixie
ghcr.io/cloudnative-pg/pgvector:0.8.7-18-trixie
ghcr.io/cloudnative-pg/postgis-extension:3.6.4-202610221437-18-trixie"

kind get clusters 2>/dev/null | grep -qx vg-cnpg || kind create cluster --config "$HERE/kind-config.yaml"
kubectl config use-context kind-vg-cnpg >/dev/null

# The plugin image, built (and its regression suite passed) from this checkout.
docker image inspect "$EXT_IMAGE" >/dev/null 2>&1 || docker build \
  -f "$ROOT/images/vg-planner/Dockerfile" -t "$EXT_IMAGE" "$REPO"
for img in $IMAGES; do docker image inspect "$img" >/dev/null 2>&1 || docker pull -q "$img"; done
kind load docker-image --name vg-cnpg "$EXT_IMAGE" $IMAGES

helm repo add cnpg https://cloudnative-pg.github.io/charts >/dev/null 2>&1 || true
helm repo update cnpg >/dev/null
helm upgrade --install cnpg cnpg/cloudnative-pg --version "$CNPG_CHART_VERSION" \
  --namespace cnpg-system --create-namespace --wait

PYTHON="${PYTHON:-python3}" "$ROOT/render_all.sh" --check
kubectl apply -k "$ROOT/manifests/overlays/local-kind"
echo "waiting for the cluster to be ready ..."
kubectl -n vitalgraph-db wait cluster/vitalgraph-pg --for=condition=Ready --timeout=15m
kubectl -n vitalgraph-db get pods -o wide
