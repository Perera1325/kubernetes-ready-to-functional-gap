#!/usr/bin/env bash
# 5-rep pilot: 4 scenarios x 3 arms x 5 reps = 60 runs at probe period 1 s. NO 10 s sweep. Interleaved per repetition.
# DO NOT RUN without explicit approval. Unique timestamped name; never overwrites.
source "$(dirname "$0")/_common.sh"
NAME="${RUN_NAME:-pilot-$(date +%Y%m%d-%H%M%S)}"
"$K8S_DIR/scripts/run-collector.sh" "$NAME" "--reps ${REPS:-5} --rep-start 1"
"$K8S_DIR/scripts/analyze.sh" "$NAME"
echo "run name: $NAME"
