#!/usr/bin/env bash
# ONE manual run. Every run gets a unique timestamped name, so earlier raw data is never overwritten.
source "$(dirname "$0")/_common.sh"
NAME="${RUN_NAME:-manual-$(date +%Y%m%d-%H%M%S)}"
"$K8S_DIR/scripts/run-collector.sh" "$NAME" "--scenarios ${SCENARIO:-replace-during-dep} --arms ${ARM:-A} --reps 1 --rep-start 0"
"$K8S_DIR/scripts/analyze.sh" "$NAME"
for d in "$K8S_DIR/raw-results/$NAME"/*/; do [ -f "$d/events.csv" ] && python3 -I "$K8S_DIR/analysis/validate_run.py" "$d"; done
echo "run name: $NAME"
