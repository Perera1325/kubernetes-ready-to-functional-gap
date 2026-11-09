#!/usr/bin/env bash
# STEP 1 diagnostics. Read-only; installs/changes nothing. Output: raw-results/diagnostics.txt (paste/send this file back).
source "$(dirname "$0")/_common.sh"
OUT="$K8S_DIR/raw-results/diagnostics.txt"; mkdir -p "$K8S_DIR/raw-results"
{
echo "== date: $(date -u +%FT%TZ)"; echo "== kernel: $(uname -r)"; grep -qi microsoft /proc/version && echo "== WSL2: yes" || echo "== WSL2: no"
echo "== cpus: $(nproc)"; free -m | sed -n 1,2p; echo "== disk (cwd):"; df -h . | tail -1
[ -f "$HOME/.wslconfig" ] && echo "(note: .wslconfig lives on the Windows side: %UserProfile%\\.wslconfig)"
echo "== docker client/server:"; docker version 2>&1 | head -30
echo "== docker info (resources):"; docker info 2>&1 | grep -E 'Server Version|CPUs|Total Memory|Operating System|Cgroup|Storage Driver|Docker Root Dir|ERROR|failed' 
echo "== kind:"; kind version 2>&1 | head -2; echo "== kubectl:"; kubectl version --client 2>&1 | head -3
echo "== node image in repo config:"; grep 'image:' "$K8S_DIR/configs/kind-cluster.yaml" | sort -u
echo "== existing kind clusters:"; kind get clusters 2>&1
echo "== reachability (HTTP code; 000 = blocked):"
for u in https://registry-1.docker.io/v2/ https://registry.k8s.io/v2/ https://ghcr.io/v2/; do printf "%s -> " $u; curl -s -o /dev/null -m 10 -w "%{http_code}\n" $u; done
} 2>&1 | tee "$OUT"
echo; echo "Suitability rule of thumb: Docker server reachable, >=4 CPUs and >=8 GiB RAM given to Docker/WSL2, >=15 GB free disk."
