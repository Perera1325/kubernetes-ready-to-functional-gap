#!/usr/bin/env bash
# Offline analysis of raw-results/NAME (host side, python3 stdlib only). Re-runnable; never modifies raw CSVs.
source "$(dirname "$0")/_common.sh"; cd "$K8S_DIR"; R="raw-results/$1"
for d in "$R"/*/; do [ -f "$d/events.csv" ] && python3 -I analysis/analyze_k8s.py "$d" > /dev/null; done
python3 -I analysis/aggregate_k8s.py "$R"; echo "see $R/aggregate.md"
