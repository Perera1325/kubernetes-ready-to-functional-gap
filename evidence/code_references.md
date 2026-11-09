# Code references (verified locally, 2026-11-09)

- kubernetes/kubernetes @ 0e074fb0e0 — `pkg/kubelet/prober/prober_manager.go`
  - `setReadyStateOnKubeletRestart` / `canInheritProbeState`: a replacement container must not inherit the previous container's probe state; Ready forced false when a readiness probe exists.
  - `kubeletRestartGracePeriod`: 10 s grace for containers running before a kubelet restart.
- `pkg/kubelet/prober/worker.go`: readiness result is a per-container streak counter (`resultRun`) compared with `FailureThreshold`/`SuccessThreshold`. Input is only the container's own probe. Nothing in the code I read consults queue state, dependencies or business transactions. NOT a bug: it is the designed contract. I read only the parts above, not the whole prober.
- kubernetes/autoscaler: commit `2511e4485` (merge of #8164, 2025-05-30, touches `cluster-autoscaler/simulator/cluster.go`); commit `03f4ab136` (2026-02-27) "replace RemoveNodeInfo with tainted ghost node in scale-down simulation"; merge `20daa9b09` of #9288 on 2026-04-21 "fix/topology-spread-scaledown-churn".
- kubernetes/enhancements @ 72907de: KEP-3085 pod networking ready condition (stable), KEP-3017 PDB unhealthy pod policy (stable), KEP-1672 terminating endpoints (stable), KEP-5307 container restart policy (beta v1.35), KEP-5532 restart all containers on exit (beta v1.36), KEP-4438 sidecar restart during termination (alpha, v1.38).
