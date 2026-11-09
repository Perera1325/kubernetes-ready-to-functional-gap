#!/usr/bin/env bash
# Run once on a machine WITH registry access: resolves the base-image digest and prints the pinned reference to put in
# the Dockerfiles' ARG PYTHON_IMAGE (or pass --build-arg). Does not modify files.
source "$(dirname "$0")/_common.sh"; need docker
for img in python:3.13.1-slim-bookworm "$(grep -m1 'image:' "$K8S_DIR/configs/kind-cluster.yaml" | awk '{print $2}')"; do
  echo "$img -> $(docker buildx imagetools inspect "$img" --format '{{.Manifest.Digest}}' 2>/dev/null || echo 'could not resolve (offline?)')"
done
