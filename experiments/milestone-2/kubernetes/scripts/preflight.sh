#!/usr/bin/env bash
# Verifies prerequisites and records the environment. Read-only: installs nothing, changes nothing.
source "$(dirname "$0")/_common.sh"
OUT="$K8S_DIR/raw-results/environment.txt"; mkdir -p "$K8S_DIR/raw-results"
{
  echo "date_utc: $(date -u +%FT%TZ)"; echo "uname: $(uname -a)"
  echo "cpus: $(nproc)"; echo "mem_gib: $(awk '/MemTotal/{printf "%.1f",$2/1048576}' /proc/meminfo)"
  echo "docker: $(docker version --format '{{.Client.Version}} / server {{.Server.Version}}' 2>&1 | head -1)"
  echo "kind: $(kind version 2>&1 | head -1)"; echo "kubectl: $(kubectl version --client 2>&1 | head -1)"
} | tee "$OUT"
need docker; need kind; need kubectl
docker info >/dev/null 2>&1 || { echo "Docker daemon is not reachable (start Docker Desktop / dockerd)." >&2; exit 3; }
CPUS=$(nproc); [ "$CPUS" -ge 4 ] || echo "WARNING: <4 CPUs. 3 Kind nodes + load generators will compete for CPU; results will be noisier (record this in the report)."
echo "preflight OK -> $OUT"
