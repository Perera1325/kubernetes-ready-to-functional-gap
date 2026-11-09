#!/usr/bin/env bash
# usage: run-collector.sh NAME "collector run args"      e.g.  run-collector.sh manual "--scenarios pod-replace --arms A --reps 1 --rep-start 0"
# Starts the in-cluster collector pod, waits for it to finish, copies EVERYTHING it produced (raw per-run data + log) to raw-results/NAME.
source "$(dirname "$0")/_common.sh"; need kubectl
NAME="$1"; ARGS="${2:-}"; cd "$K8S_DIR"; DEST="raw-results/$NAME"
# NEVER overwrite raw data: refuse if this name was already used on the host
if [ -e "$DEST" ]; then echo "REFUSING: $DEST already exists (raw data is never overwritten). Choose another NAME." >&2; exit 4; fi
mkdir -p "$DEST"
$KCTL delete pod rfg-collector --ignore-not-found --wait=true >/dev/null
sed -e "s|__NAME__|$NAME|g" -e "s|__ARGS__|$ARGS|g" manifests/50-collector-pod.yaml.tmpl | kubectl --context kind-${CLUSTER_NAME} apply -f -
$KCTL wait --for=condition=Ready pod/rfg-collector --timeout=120s
echo "collector running: $NAME  (tail: kubectl --context kind-${CLUSTER_NAME} -n rfg exec rfg-collector -- tail -f /results/$NAME.log)"
until $KCTL exec rfg-collector -- test -f "/results/$NAME.EXIT" 2>/dev/null; do sleep 10; done
$KCTL exec rfg-collector -- tar -C /results -cf - "$NAME" "$NAME.log" "$NAME.EXIT" | tar -C raw-results -xf -
{ date -u +%FT%TZ; kubectl --context kind-${CLUSTER_NAME} version; $KCTL get nodes -o wide 2>&1; kubectl --context kind-${CLUSTER_NAME} get nodes -o wide; $KCTL get pods -o wide; $KCTL get events --sort-by=.lastTimestamp; } > "$DEST/cluster-info.txt" 2>&1
echo "exit code of collector: $(cat raw-results/$NAME.EXIT)"; echo "raw results in $DEST"
