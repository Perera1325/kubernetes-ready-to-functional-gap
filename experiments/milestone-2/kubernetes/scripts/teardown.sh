#!/usr/bin/env bash
source "$(dirname "$0")/_common.sh"; need kind
kind delete cluster --name "$CLUSTER_NAME"
