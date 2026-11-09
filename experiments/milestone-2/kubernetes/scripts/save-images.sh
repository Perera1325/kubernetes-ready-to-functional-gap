#!/usr/bin/env bash
# Offline transfer: save the built images (and the Kind node image) into one tar for a machine without registry access.
source "$(dirname "$0")/_common.sh"; need docker
NODE_IMG=$(grep -m1 'image:' "$K8S_DIR/configs/kind-cluster.yaml" | awk '{print $2}')
docker save -o "$K8S_DIR/rfg-images.tar" "${IMAGES[@]}" "$NODE_IMG"; ls -lh "$K8S_DIR/rfg-images.tar"
echo "On the target machine:  docker load -i rfg-images.tar   then   scripts/create-cluster.sh"
