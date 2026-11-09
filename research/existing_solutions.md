# Existing solutions vs Recovery Debt
- **Readiness/startup probes + readiness gates (K8s built-in):** per-container, local signal (code: prober/worker.go). Deep-check probes are possible but the Kubernetes docs-level guidance (see NHI, Expedia blog) warns they couple readiness to dependencies and can cause cascading unreadiness. Readiness gates exist but need an external controller to set the condition.
- **Chaos tools (Chaos Mesh, Krkn):** Krkn has continuous HTTP health checks that record downtime start/end/duration. Measures; does not gate or remediate. Its own article says a Ready pod does not prove transactions succeed.
- **Service mesh outlier detection, Argo Rollouts/Flagger analysis:** request-level signals for traffic/rollout decisions; aimed at deployments, not at unplanned pod replacement. (Not verified in this session.)
- **Operator-specific logic (e.g. database operators):** app-aware but per-product.
