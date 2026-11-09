# Recommendation: refine and test Recovery Debt as the Ready-to-Functional Gap (RFG)

Status: proposal only. Nothing below has been run. No results are claimed.

## Research questions (refined)
- RQ1: How large and variable is T_func - T_ready after unplanned pod/node failure across workload types (stateless API, queue consumer, StatefulSet DB, model server)?
- RQ2: Does a deep readiness probe written by an expert remove the gap, and at what cost (false NotReady, cascading unreadiness)?
- RQ3: Can an external, opt-in controller reduce user-visible errors during the gap without extra disruption?
- RQ4: Is RFG a better recovery-risk metric than Ready time or availability?

## Definitions
T_fail: fault injected. T_ready: Pod Ready=True. T_func: first moment N consecutive synthetic business transactions succeed (plus idempotency check for queue work). **RFG = T_func - T_ready** (can be <= 0). Also record error-seconds between T_ready and T_func.

## Minimal architecture
- Go + controller-runtime. One CRD `RecoveryProbe`: selector, synthetic transaction (HTTP/gRPC/exec), success criteria N, mode `observe` (default) | `gate`.
- Controller watches Pod conditions/events, starts probing after a Pod turns Ready, records RFG, exports Prometheus histogram `recovery_gap_seconds`.
- `gate` mode: sets a custom Pod condition used via `spec.readinessGates` so traffic waits for functional proof. Never restarts or deletes workloads by default; remediation requires an explicit policy.
- Security: namespaced RBAC (pods get/list/watch, pods/status patch only in gate mode), probes run from the controller, no secrets stored. Failure handling: controller down => condition TTL/fail-open policy chosen per workload. Not using eBPF, ML or a database in v1.

## Experiment
- Environment: kind multi-node (needs install; kubectl/kind are missing here), Chaos Mesh pod-kill and node-drain/kill, load via k6/Locust.
- Arms: A vanilla; B expert deep readiness probe (+Krkn-style health checks as the measurement); C RFG controller (observe and gate).
- Workloads: stateless API + Postgres pool; Redis-stream/RabbitMQ consumer (duplicates counted); StatefulSet Redis or Postgres; optional Ollama model server.
- Variables: workload, fault type, load level, probe thresholds. Measure: T_ready, T_func, RFG, error rate, p99 latency, duplicate processing, false NotReady, controller CPU/mem, API requests.
- Stats: >=30 runs per cell (to be justified by pilot variance), Mann-Whitney U, bootstrap CIs, Cliff's delta; report null results.
- Threats: kind is not production; synthetic transactions define "functional"; deep probe baseline may win.

## Roadmap (summary)
M1 reproduce gap with a hand-written harness (no controller). M2 kind baseline + workloads. M3 CRD + observer. M4 client-go integration and metrics. M5 Grafana dashboards. M6 safety (fail-open, rate limits, dry-run). M7 failure injection campaign. M8 benchmark A/B/C. M9 profile overhead. M10 docs + release. Each milestone needs tests and acceptance criteria; I will detail them after you approve a direction.

## Backup direction
Differential testing of Cluster Autoscaler/Karpenter simulation vs the real scheduler (candidate 2).


---
# UPDATE after Milestone 1 (approval received; original text above preserved)
- Architecture corrected: in gate mode verification starts at T_container_ready, the custom gate stays False until functional criteria pass, T_pod_ready = max(T_container_ready, T_gate_true). RFG_observe = T_func - T_pod_ready; RFG_cr = T_func - T_container_ready. See research/experimental_methodology.md.
- Milestone 1 done as a LOCAL SIMULATION (no Kubernetes available). Results: reports/milestone-1-results.md.
- Hypothesis status: survives in narrowed form only (gap appears when readiness does not reflect a recovering dependency; absent for plain replacement with healthy dependency). RQ3 (a gate that reduces disruption) is at risk: a Pod-level gate has the same coupling as the deep probe (shared readiness => dependency-free endpoint outage, zero endpoints). Contribution may need to shift toward measurement/detection or finer-grained traffic gating.
