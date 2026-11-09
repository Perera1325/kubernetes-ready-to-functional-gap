# Milestone 2-A — Real-Kubernetes validation of the Ready-to-Functional Gap (RFG)

> **STATUS: 60-run pilot executed** (`pilot-20261109`: 4 scenarios x 3 arms x 5 repetitions on kind v0.25.0, Kubernetes 1.31.2).
> 59 runs passed independent validation, 1 was flagged INVALID and is kept. Results: `data/pilot-20261109/` and `reports/milestone-2a-results.md`.
> The text below is the original design document written *before* the first run; where it says "not run" or gives time estimates, the pilot has since superseded it
> (the full pilot took under 30 minutes). Simulation (Milestone 1) results are never mixed with real measurements.

## What this package is
A complete, ready-to-run deployment of the Milestone-1 workload on a Kind cluster (1 control-plane + 2 workers):

| Piece | What | Where |
|---|---|---|
| Dependency | StatefulSet `rfg-store` (+PVC with the WAL), ClusterIP Service `rfg-store`, headless `rfg-store-hl`; TCP readiness (realistic shallow check; answers `-LOADING` during replay as in M1) | `manifests/10-store.yaml` |
| App | Deployments `rfg-app-shallow` (arm A/C) and `rfg-app-deep` (arm B), 2 replicas (one arm up at a time), ClusterIP Service `rfg-app`; **real kubelet readiness probes** on port 8081, period 1 s | `manifests/20-app.yaml` |
| Collector | one in-cluster Python process = fault injector + Pod/EndpointSlice watcher + all transaction streams, **one monotonic clock** | `src/collector.py`, `src/kube.py` |
| Streams | G per-replica direct (20 Hz, pod IP); U via the Service (tx 20 Hz + static 10 Hz); D dependency PING (10 Hz); arm C observer (5 Hz, N=5, detection only) | `src/collector.py`, `src/client.py`, `src/observer.py` |
| Analysis | Milestone-1 functions reused **unchanged** (`src/analyze_m1.py`, byte-identical copy, test-enforced) + Kubernetes extras | `analysis/` |

Application logic is untouched: `rfg_common.py` (validation) is byte-identical to M1; `tx()`, warm-up/`init_loop` and WAL replay were diffed against M1.
Only addressing was added: `--bind-address`, `--dep-host`, `--dep-port`, `--http-port` (`--port` kept as alias), `--health-port` (serves only `/healthz/*`).

## Install prerequisites (nothing was installed by the author; do this yourself, it needs admin rights)
Needs: Docker (running daemon), `kind`, `kubectl`; ≥4 CPUs and ≥8 GiB RAM recommended (3 Kind nodes + load generators; with 2 vCPUs results will be noisy).
- **Windows 10/11:** enable WSL2, install Docker Desktop with the WSL2 backend, open an Ubuntu WSL shell, then install `kind` and `kubectl` inside WSL. Run all scripts from WSL.
- **Linux:** install Docker Engine (`systemctl enable --now docker`), add your user to the `docker` group (re-login), install `kind` and `kubectl` binaries into `/usr/local/bin`.
- **Official guides** (not fetched from the authoring sandbox — check versions yourself): <https://docs.docker.com/engine/install/>, <https://kind.sigs.k8s.io/docs/user/quick-start/>, <https://kubernetes.io/docs/tasks/tools/>.
- **Offline / separate machine:** on a networked machine run `scripts/build-images.sh` then `scripts/save-images.sh` (produces `rfg-images.tar` incl. the Kind node image); copy the package + tar; `docker load -i rfg-images.tar`. No public pulls happen at runtime (`imagePullPolicy: Never`, images loaded with `kind load`).
- Base images are pinned by **tag** (`python:3.13.1-slim-bookworm`, `kindest/node:v1.31.2`). Digests could not be resolved offline: run `scripts/pin-digests.sh` once to obtain them. Check that your `kind` release supports the node image tag.

## Reproduce
```bash
cd experiments/milestone-2/kubernetes
scripts/preflight.sh            # read-only checks, records environment.txt
scripts/build-images.sh         # builds rfg-app/store/collector :m2a
scripts/create-cluster.sh       # kind cluster + load images + deploy + wait for the store (first start generates the WAL)
scripts/run-manual.sh           # ONE manual run (default: replace-during-dep, arm A) + analysis. Look at it by hand first.
scripts/run-pilot.sh            # 4 scenarios x 3 arms x 5 reps = 60 runs, probe period 1 s (no 10 s sweep). Estimate ~1-2 h (not measured).
scripts/analyze.sh pilot        # re-runnable offline analysis -> raw-results/pilot/aggregate.{csv,md}
scripts/teardown.sh             # kind delete cluster
```
Env knobs: `SCENARIO=`, `ARM=` (manual run), `REPS=` (pilot), `CLUSTER_NAME=`.
Raw output per run (`raw-results/<name>/<scenario>__<arm>__<rep>/`): `events.csv`, `probe_transitions.csv` (Pod Ready as received on the watch), `user.csv`, `oracle.csv` (G), `dependency.csv` (D), `observer_raw.csv`, `observer_events.csv`, `k8s_events.csv` (every Pod/EndpointSlice/endpoint watch row with monotonic **and** wall receipt time), `stats.json`, `config.json`, `summary.json` (written by analysis). Aborted runs keep their data plus `ABORTED.txt`; nothing is discarded.

## Measurement design (what is and is not precise)
- `T_fault` = collector clock just before the fault API call is sent; API-returned time is also stored (`kill_api`, `dep_kill` rows).
- Pod/EndpointSlice times are **watch-receipt times** on the collector clock (they lag the true state change by an unknown, unmeasured amount). Pod condition `lastTransitionTime` and `startedAt` have 1 s resolution and use the node clock; they are stored raw and used **only** to estimate watch-receipt latency (±1 s), never for sub-second claims.
- `T_pod_ready` = Pod Ready condition received on the watch; `T_container_ready` = container `ready` in `containerStatuses` (equal in observe mode, no readiness gate); `T_endpoint_available` = EndpointSlice endpoint ready for that pod; `T_func` = start of the first sustained window (≥20 consecutive valid tx spanning ≥1 s) on stream G.
- Logical names: the two initial pods are `r0.1`/`r1.1` (sorted pod name), the replacement is `r0.2`. The scenario faults hit `r0.1` (app pod) and/or `rfg-store-0`.

## Deviations from Milestone 1 (all forced by real Kubernetes; none touch validation/WAL/CRC/warm-up/backoff)
1. Probe `timeoutSeconds` = 1 (integer ≥1) vs 0.8 s in the simulation. Probe period/threshold identical (1 s / 3 / 1).
2. Pod kill = API `DELETE … gracePeriodSeconds=0` (not SIGKILL). The container may keep serving briefly until kubelet stops it; that is recorded, not corrected.
3. `dep-restart`/`replace-during-dep`: downtime is whatever delete→recreate→start→WAL-replay takes in the cluster (M1 used a fixed 1 s); whether the replacement app pod actually starts **while the dependency is still recovering** is *measured* (`replacement_started_before_dep_functional`), not assumed.
4. No `no_endpoints` response class: a ClusterIP with no ready endpoints shows up as connection refused/timeouts → `conn_error`.
5. The kubelet probe log is not observable from the API, so `probe_log.csv` is empty and probe-request counts come from the app's own `/admin/stats`. No CPU-seconds metric in M2-A.
6. Collector, load generators, store and apps share the Kind nodes (and the host). This is a threat to validity; record host CPU/RAM in the report.

## Known untested risks (nothing here has touched a real cluster)
Written without ever running on Kubernetes, so expect to find and report bugs on first run: label/selector assumptions in the watchers, RBAC completeness, StorageClass availability for the PVCs, first-start WAL generation time vs. readiness, CoreDNS/kube-proxy propagation delays (real effects, desired in the data but unquantified), CPU contention on small hosts, and manual-run behaviour of `replace-during-dep` (the dependency may recover before the replacement app is up, in which case the conditional gap is simply not triggered; that is a valid result).

## Tests (mock/static only — `tests/test_output.txt`, 22 tests)
Parity of the M2 app/store copy with the M1 tests; new flags; byte-identity of validation logic and of the reused M1 analysis; watch list/stream/reconnect on a fake chunked API; fault-request shape (`gracePeriodSeconds=0`, merge-patch scale); pod→logical mapping and unexpected-event notes; raw-file writing and analysis on a constructed run; static manifest/Dockerfile/probe-config consistency. **None of these prove the manifests or collector work on a real cluster.**
