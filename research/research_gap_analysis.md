# Research gap analysis (top 3)

Classification uses: already solved / known limitation with existing solutions / underexplored opportunity / potentially novel / insufficient evidence.

| Capability | K8s built-in | Existing tools | Academic | Proposed (RFG) |
|---|---|---|---|---|
| Know Pod is Ready | Yes (probes) | Yes | - | Reuses |
| Measure time from Ready to functional recovery | No | Krkn health checks (test-time), custom scripts | Chen 2025 measures impact, not this gap | Yes, as a first-class metric |
| Runtime detection after unplanned replacement | No | Mesh outlier detection (request-level, unverified here) | Gray failure theory only | Yes |
| Gate traffic on functional recovery | Readiness gates (needs controller) | Per-vendor operators | None found | Yes, opt-in |
| Cross-workload comparison | No | No | None found | Yes (experiment) |

1. **Recovery Debt -> refined "Ready-to-Functional Gap (RFG)".** Classification: **underexplored research opportunity** (not "novel"). Conceptual prior art (gray failure) and tooling for measurement exist; the gap is a systematic, Kubernetes-specific quantification plus a safe runtime detector/gate, compared against a good deep-probe baseline. Biggest risk: a well-designed deep readiness probe may already close most of the gap.
2. **Simulation-vs-reality divergence in autoscaling/consolidation (CA#9287 class).** Classification: **known limitation, instance fixed**. Opportunity: differential testing of CA/Karpenter simulation against real scheduler. Kivi is related prior art. Karpenter not examined.
3. **RWO volume failover after node loss.** Classification: **known limitation with existing solutions** (vendor policies, force-delete). Little new research angle without new evidence.
Retry/recovery storms (candidate 8): **insufficient evidence** for Kubernetes; worth a pilot.


---
# UPDATE after Milestone 1 (simulation evidence only)
- Deep-probe competitor: partially closes the gap (less Ready-but-invalid time) but adds cascading unavailability and probe load; not dominated, not sufficient. Classification of RFG stays **underexplored opportunity**; evidence is simulated, not Kubernetes.
- New open question: does a readiness-gate controller differ from a deep probe in user-visible effect? Untested.
