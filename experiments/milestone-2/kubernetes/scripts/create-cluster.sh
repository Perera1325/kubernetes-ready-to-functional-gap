#!/usr/bin/env bash
# Creates the Kind cluster (1 control-plane + 2 workers), loads the images into every node, deploys, waits for the store.
# Requires: docker daemon, kind, kubectl, images already built/loaded. Creates one Kind cluster named "rfg" (containers only).
source "$(dirname "$0")/_common.sh"; need docker; need kind; need kubectl
cd "$K8S_DIR"
kind get clusters | grep -qx "$CLUSTER_NAME" || kind create cluster --config configs/kind-cluster.yaml --wait 120s
for i in "${IMAGES[@]}"; do kind load docker-image "$i" --name "$CLUSTER_NAME"; done
"$K8S_DIR/scripts/deploy.sh"
