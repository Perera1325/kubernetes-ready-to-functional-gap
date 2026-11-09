# Experimental methodology (v2, Milestone 1) — supersedes the timestamp definitions in final_research_proposal.md

Status: Milestone 1 only. Environment limitation: no Kubernetes available (no Docker daemon, no registry access). All Milestone 1 runs are a **LOCAL SIMULATION** with real OS processes; see experiments/milestone-1/README.md.

## 1. Timestamps (corrected; no circular dependency)
| Symbol | Meaning |
|---|---|
| T_fault | fault injected |
| T_container_ready | native container readiness probe passes (first Ready transition after launch/fault) |
| T_pod_ready | overall Pod Ready. **Observe mode:** equals T_container_ready (single container, no custom gate). **Gate mode:** custom readiness-gate condition is False until functional verification passes; verification starts after T_container_ready; T_pod_ready = max(T_container_ready, T_gate_true). Waiting for T_pod_ready to start verification is explicitly avoided. |
| T_func | start of the first *sustained* functional window |

- RFG_observe = T_func - T_pod_ready; RFG_cr = T_func - T_container_ready (comparable across modes).
- Sustained criterion (Milestone 1 values): >= 20 consecutive valid synthetic transactions spanning >= 1.0 s (20 Hz); any invalid response resets the window (failure threshold = 1).
- "Valid" is not HTTP 200. A response is valid only if it is from the primary path, carries the correct read-your-write value and the correct cached price (rfg_common.validate_tx). A degraded fallback returns HTTP 200 and is counted `invalid_business`.
- Degradation onset: the first invalid ground-truth sample at/after T_fault. T_func is searched only after onset. If no invalid sample occurs, the fault "did not manifest" and there is no gap.
- Queue consumers (processing completion, duplicates via idempotency keys) are NOT in Milestone 1; planned for Milestone 2.

## 2. Streams
- G (ground truth): direct, per-replica 20 Hz synthetic transactions ignoring readiness.
- U (user-visible): 20 Hz transactions + 10 Hz static pings through the Service emulator, which routes only to replicas the emulated readiness probe currently marks Ready.
- Observer (arm C only): 5 Hz direct transactions per replica after container-ready; "functional" after 5 consecutive valid responses; "functional_lost" on the first invalid response.

## 3. Arms
A: shallow probe (process alive) — standard Kubernetes behaviour for a typical HTTP probe. B: expert deep probe (dependency PING + cache warm). C: shallow probe + standalone observer (detection logic only; no actuation, so C's user-visible results equal A's by construction; only detection quality and overhead are compared).

## 4. Scenarios
1. app-degrade: app drops dependency connection and stops reconnecting for 3 s, then recovers (re-initialises: reconnect + cache warm).
2. pod-replace: SIGKILL replica r0.1, launch replacement r0.2 (healthy dependency).
3. dep-restart: SIGKILL the dependency, restart after 1 s; it replays a ~900k-line WAL (about 1.1 s of real CRC/parse work) and answers -LOADING meanwhile; apps reconnect with exponential backoff (0.5 s base, 8 s cap).
4. replace-during-dep: correlated failure — dependency and one replica killed together, both restarted; the replacement starts while the dependency is still loading.

## 5. Measures (per run)
rfg_observe_max_s, ready_nonfunctional_s (probe says Ready while G invalid), false_notready_s (G valid while probe NotReady — includes plain probe lag), tx/static error durations and per-class counts, zero_endpoint_s (no Ready replica), stale_ready_s (killed replica still Ready; probe-lag, not RFG), probe_requests, dep_ops_probe, app CPU seconds, observer detection latency/false-functional.

## 6. Design, statistics, limits
- 5 repetitions per scenario x arm (Milestone 1 pilot), arms interleaved within each repetition to spread drift. Descriptive statistics only (median [min-max]). No significance tests, no sample-size justification yet: n=5 cannot support inference. Variance from the pilot will size Milestone 2.
- Probe period 1 s (Kubernetes default is 10 s) to keep runs short; a k8s-default configuration exists (configs/k8s-default-probe.json) but was only run if stated in the results report.
- Threats: not Kubernetes (no kubelet, EndpointSlice propagation delay, container start latency, CNI); Python threads and GIL on 2 vCPUs; harness and system under test share the machine; the dependency, cache warm-up size, and backoff parameters are my choices and strongly shape the gap; fault models are controlled, not field-derived.

## 7. Milestone 2-A — real-Kubernetes design (added; status: PREPARED, NOT RUN)
No cluster could be created in the authoring environment (no Docker daemon; kind/kubectl absent; registries blocked), so nothing in this section has been measured on Kubernetes. See `experiments/milestone-2/kubernetes/README.md` and `reports/milestone-2a-results.md`.
- **System:** Kind 1 control-plane + 2 workers; dependency StatefulSet+PVC; 2-replica app Deployment (one arm up at a time) behind a ClusterIP Service; real kubelet readiness probes (period 1 s, timeout 1 s, failure threshold 3); no liveness/startup probes (as M1).
- **Single clock:** the collector runs in-cluster, injects faults through the API and generates all streams, so every timestamp is on one CLOCK_MONOTONIC.
- **Timestamps:** T_fault = just before the fault API call; T_container_ready / T_pod_ready / T_endpoint_available = *watch-receipt* times (Pod, EndpointSlice); T_func unchanged (sustained window on stream G). Receipt lags the true change by an unmeasured amount. Pod-condition `lastTransitionTime` (1 s resolution, node clock) is used only to estimate watch-receipt latency (±1 s), never for sub-second claims.
- **New derived fields:** RFG_endpoint = T_func − T_endpoint_available; RFG_k8s_podready = T_func − T_pod_ready(watch); dependency functional time from a 10 Hz PING stream (D); `replacement_started_before_dep_functional` (does the replacement app answer before the dependency does?).
- **Unchanged from M1:** business-validity rule, WAL replay/CRC, cache warm-up, backoff, scenario definitions, arms A/B/C, sustained criterion, analysis functions (byte-identical copy).
- **Forced differences:** probe timeout 1 s (integer); DELETE gracePeriodSeconds=0 instead of SIGKILL; dependency downtime emerges from the cluster; no `no_endpoints` class; no kubelet probe log or CPU-seconds.
- **Decision rules written before any real data exists (descriptive, n=5, not statistical tests):** (H-A) conditional gap in `replace-during-dep` arm A is *supported* if RFG_observe > 0 in ≥4/5 runs **and** the replacement overlapped dependency recovery in those runs; *not supported* if ≤0 in all 5 or overlap never occurs (then report "not triggerable under these cluster timings" as its own finding). (H-B) no universal defect: `pod-replace` arm A has RFG_observe ≤ 0 in ≥4/5. (H-C) `dep-restart` arm A shows Ready-but-invalid time > 0 in ≥4/5. (H-D) deep probe reduces Ready-but-invalid time without removing user-visible errors (M1 finding, to be replicated or contradicted). (H-E) arm C observer makes no false "functional" declaration. A result contradicting any of these is reported as such.
- **Pilot:** 4 scenarios × 3 arms × 5 reps at probe period 1 s, arms interleaved per repetition; no 10 s sweep; no significance claims; every raw run preserved including aborted ones.
