#!/usr/bin/env bash
source "$(dirname "$0")/_common.sh"; need kubectl
cd "$K8S_DIR"; CTX="--context kind-${CLUSTER_NAME}"
kubectl $CTX apply -f manifests/00-namespace.yaml
kubectl $CTX apply -f manifests/10-store.yaml -f manifests/20-app.yaml -f manifests/30-rbac.yaml -f manifests/40-results-pvc.yaml
kubectl $CTX -n rfg create configmap rfg-config --from-file=k8s-baseline.json=configs/k8s-baseline.json --dry-run=client -o yaml | kubectl $CTX apply -f -
echo "waiting for the dependency (first start generates the WAL; this can take a minute)..."
$KCTL rollout status statefulset/rfg-store --timeout=300s
$KCTL get pods,svc,pvc -o wide | tee "$K8S_DIR/raw-results/deploy-state.txt"
