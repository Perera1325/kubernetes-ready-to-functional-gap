#!/usr/bin/env bash
# shared helpers; sourced by the other scripts. Nothing here installs software or changes system settings.
set -euo pipefail
K8S_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-rfg}"
IMAGES=(rfg-app:m2a rfg-store:m2a rfg-collector:m2a)
KCTL="kubectl --context kind-${CLUSTER_NAME} -n rfg"
need() { command -v "$1" >/dev/null 2>&1 || { echo "MISSING: $1  (see README.md > 'Install prerequisites')" >&2; exit 2; }; }
