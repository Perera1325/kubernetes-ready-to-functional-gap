# Milestone 2-A — Real-Kubernetes validation of RFG: results report

**Status: NOT RUN — blocked by the environment. No real-Kubernetes experiment was executed. This report contains zero real-cluster measurements.**
Date: 2026-11-09. Scope: M2-A only (no queue consumers, readiness gate, controller, 10 s sweep, M2-B/C/D).

## 1. Outcome in one paragraph
A Kind cluster could not be created in the authoring sandbox, so I built, unit-tested (mock API only) and packaged the full deployment and did not claim a run. The hypothesis therefore has **neither survived nor failed** real-Kubernetes validation: the only evidence on the Ready-to-Functional Gap remains the Milestone-1 *local simulation*. The package is ready to run on any machine with Docker + kind + kubectl.

## 2. Exact blocker (evidence: `experiments/milestone-2/kubernetes/raw-results/blocker-evidence/environment-check.txt`)
| Need | Found in sandbox |
|---|---|
| Docker daemon | CLI 29.9.2 present; **no daemon, no `/var/run/docker.sock`** ("failed to connect to the docker API") |
| `kind`, `kubectl`, `helm`, `k3s`, `minikube`, `podman` | not installed |
| Download kind/kubectl/images | `registry-1.docker.io`, `registry.k8s.io`, `ghcr.io`, `quay.io`, `dl.k8s.io`, `kind.sigs.k8s.io`, `proxy.golang.org`: all blocked (HTTP 000); only `pypi.org` reachable |
| Host | 2 vCPU, 7.8 GiB RAM, Linux 6.18; running as root |

Per your rule ("do not install privileged software or modify system settings without explicit permission") I did **not** try to start a daemon, build a rootless runtime, or work around the network. Nothing was installed or reconfigured.

## 3. What was built (all under `experiments/milestone-2/kubernetes/`; M1 untouched, its 21 tests still pass)
- `src/application/` — M1 app/store copies with only addressing flags added (`--bind-address`, `--dep-host`, `--dep-port`, `--http-port`/`--port`, `--health-port`, `--make-wal-if-missing`). `rfg_common.py` byte-identical to M1; `tx()`, warm-up and WAL replay diffed identical.
- `Dockerfiles/` (app, store, collector; base pinned by tag; digest pinning script because digests were unresolvable offline), `configs/kind-cluster.yaml` (1+2 nodes), `manifests/` (namespace, store StatefulSet+PVC+Services, app Deployments for arm A/B with real kubelet probes + ClusterIP Service, RBAC, results PVC, collector pod template), `scripts/` (preflight, build, save/load offline, create-cluster, deploy, run-collector, run-manual, run-pilot, analyze, teardown, pin-digests).
- `src/collector.py`, `src/kube.py` — in-cluster collector on one monotonic clock: fault injection via the API; Pod + EndpointSlice watches; streams G/U/static/D; arm C observer; M1-compatible raw files plus `k8s_events.csv`.
- `analysis/` — reuses M1 analysis unchanged (`src/analyze_m1.py`, byte-identical) and adds T_endpoint_available, RFG_endpoint, watch-latency estimate, dependency-functional time and the replacement-overlap check.

## 4. Tests (`tests/test_output.txt`): 22 pass — mock/static only
Parity with the M1 app/store tests; new flags; byte-identity checks; fake chunked watch incl. dropped-connection resume; fault-request shape (`gracePeriodSeconds=0`, merge-patch scale); pod→logical mapping; analysis on a constructed run; manifest/Dockerfile/probe-config consistency. **These show the code paths behave as designed against a fake; they say nothing about real kubelet, probe, EndpointSlice or DNS behaviour.**

## 5. Research questions
**RQ1–RQ5: none can be answered; every real-cluster quantity is *not measured*.** (The exact RQ wording from your M2-A message is not in the context I retained after compaction; paste it and I will map each RQ to its field in `summary.json`.) Not measured: real RFG per scenario/arm, endpoint-level RFG, watch-receipt latency, whether `replace-during-dep` truly overlaps dependency recovery in a real cluster, probe overhead on a real kubelet, observer behaviour in a real cluster.

## 6. Comparison with Milestone 1
Nothing to compare yet. Milestone-1 (simulation) findings, for reference only: conditional gap present when readiness ignores a recovering dependency (replace-during-dep RFG 0.84–1.44 s, 5/5), absent for plain replacement with a healthy dependency (negative in 15/15), deep probe shortens Ready-but-invalid time but not user-visible errors, observer made no false-functional declaration in 30 observations (`reports/milestone-1-results.md`). Real-vs-simulation differences I *expect to need checking* (hypotheses, not findings): container start latency, kube-proxy/EndpointSlice propagation, CoreDNS caching of the store address, force-delete semantics, contention on a small host.

## 7. Does the hypothesis survive real-Kubernetes validation?
**Undetermined.** Decision rules H-A…H-E are fixed in `research/experimental_methodology.md` §7 *before* any real data exists, including the outcome that would count against the hypothesis (no gap in 5/5 runs, or the replacement never overlapping dependency recovery). The conditional framing you asked for (no universal-readiness-defect claim) is built into H-A/H-B.

## 8. Risks you should know before running
The package has never touched a cluster: expect first-run fixes (selectors/RBAC/StorageClass/WAL first-start time). On <4 CPUs, 3 Kind nodes plus 20+ Hz streams will add noise; record host specs. Watch times are receipt times, not state-change times. If `replace-during-dep` shows the dependency recovering before the replacement starts, that is a valid result ("not triggerable under these timings"), not a failure of the harness.

## 9. To proceed (needs your action)
Run on a Linux/WSL2 machine with Docker: follow `experiments/milestone-2/kubernetes/README.md` (preflight → build → create-cluster → `run-manual.sh` → review → `run-pilot.sh`). Send me `raw-results/` and I will analyse it. Alternatively give explicit permission to try installing a container runtime here (it would still lack registry access, so I do not expect it to work).

## References
No new external sources were consulted in M2-A. Verified sources used earlier in the programme are listed in `evidence/sources.csv`; Milestone-1 results in `reports/milestone-1-results.md`.
