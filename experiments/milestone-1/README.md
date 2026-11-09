# Milestone 1 — Reproduce the Ready-to-Functional Gap (LOCAL SIMULATION, not Kubernetes)

**Kubernetes was not available** in the workspace (no Docker daemon, no kubectl/kind, registry and release downloads blocked). Every number here comes from real OS processes on one 2-vCPU VM with *emulated* kubelet probe semantics and an emulated Service. Nothing here is a Kubernetes measurement.

## Environment inspected
Linux VM, 2 vCPU, 7.8 GiB RAM, 252 GB disk (30 GB free), Python 3.13, Go 1.24, Docker CLI present but no daemon, no kubectl/kind/k3s/minikube, outbound access limited to package registries and GitHub git.

## Architecture (updated)
```
transaction-client  U (20/s tx + 10/s static) --> Router (Service emulator; routes only to Ready replicas)
                    G (20/s per replica, direct, ignores readiness = ground truth)
Router --> app replicas r0, r1 (HTTP) --TCP--> store (KV with WAL replay, answers -LOADING until replayed)
Prober (kubelet semantics: period, failureThreshold, successThreshold, random first-probe offset)
   arm A: GET /healthz/shallow (process alive)   arm B: GET /healthz/deep (dependency PING + cache warm)
   arm C: shallow probe + standalone Observer (5/s direct tx, N=5 consecutive) - detection only
fault-injector: degrade/recover app, SIGKILL app, SIGKILL+restart dependency
collector: analyze.py (T_fault, T_container_ready, T_pod_ready, T_func, RFG), aggregate.py
```
Real dependency/initialisation (not sleep timers): replay of ~900k WAL lines with CRC check (~1.1 s of CPU), cache warm-up by SCANning 100k keys, client reconnect with exponential backoff (0.5 s base, 8 s cap — an explicit parameter that strongly shapes results).

## Layout
`application/` app, store, shared validation · `fault-injector/` · `transaction-client/` · `collector/` analysis+observer · `harness/` prober, router, runner · `configs/` · `tests/` · `results/run1/` raw data (63 files per cell dir: events, user, oracle, probe logs, observer, stats, config, summary).

## Reproduce
```bash
cd experiments/milestone-1
python3 -I -W ignore -m unittest discover -s tests -v          # 21 tests, ~20 s (do not run during a batch)
python3 harness/runner.py --reps 5 --out results/run1            # 60 runs, ~15 min, uses ports 27001-27100
python3 collector/aggregate.py results/run1                      # writes aggregate.csv / aggregate.md
# optional realistic probe period (10 s), longer runs:
python3 harness/runner.py --config configs/k8s-default-probe.json --reps 3 --out results/run2   # NOT run yet
```
Single run: `python3 harness/runner.py --scenarios dep-restart --arms A --reps 1 --out /tmp/x`. Raw data are kept; analysis can be re-run offline with `collector/analyze.py <run-dir>`.

## Real-Kubernetes path (not done here)
On a machine with Docker: install kind (`go install sigs.k8s.io/kind@latest` or the release binary) and kubectl, `kind create cluster --config` with 1 control-plane + 2 workers, containerise `application/`, deploy app as a Deployment (probe path per arm) and the store as a StatefulSet, and record Pod `Ready` transition times via the API (second granularity) plus the same G/U clients through a Service. App needs `--dep-host`/bind-address options first (currently hard-coded to 127.0.0.1). That is Milestone 2 work.

## Problems encountered
- Observer latency metric was first compared against the *start* of the truth window (biased by ~0.8 s). Fixed (compare against window completion), all 60 runs re-analysed from raw data, test added.
- 3 pre-fault invalid samples in 60 runs: in-flight requests at the injection instant (3.00 s after steady state), not baseline flakiness. They do not affect metrics (analysis starts at T_fault).
- Per-run copy of the dependency log (28 MB x 60) removed after the batch; regenerated deterministically by the runner.
- Unclosed-file ResourceWarnings in harness code (cosmetic).

## Limitations
Not Kubernetes (no kubelet, EndpointSlice delay, container start latency, CNI). Python threads on 2 vCPUs share the machine with the system under test. n=5 per cell, descriptive only. Gap magnitude depends on my backoff, replay size and probe period (1 s, not the Kubernetes default 10 s). `app-degrade` is a deliberately constructed fault, so the gap there is true by construction. "Invalid" treats the app's graceful fallback as a failure; an application that tolerates fallbacks would score differently. Queue consumers and gate mode are not implemented (gate fields exist in the analyzer and are unit-tested only on synthetic data). Arm C's user-visible results equal A's by design.
