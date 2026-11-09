#!/usr/bin/env bash
# Builds the three images from the pinned-tag Dockerfiles. The base image must already be in the local Docker cache
# or be pullable ONCE at build time (build time only; the cluster never pulls: imagePullPolicy: Never).
source "$(dirname "$0")/_common.sh"; need docker
cd "$K8S_DIR"
docker build -f Dockerfiles/app.Dockerfile       -t rfg-app:m2a       src
docker build -f Dockerfiles/store.Dockerfile     -t rfg-store:m2a     src
docker build -f Dockerfiles/collector.Dockerfile -t rfg-collector:m2a src
docker images --digests | grep -E 'rfg-(app|store|collector)' | tee "$K8S_DIR/raw-results/images.txt"
