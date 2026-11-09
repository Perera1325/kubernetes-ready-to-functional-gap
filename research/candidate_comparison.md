# Candidate comparison (16 candidates)

Scores 1-10 are my judgment, not measurements. Weights: impact 20, novelty 20, evidence 15, gap 15, feasibility 10, measurability 10, adoption 10. Totals computed by script. Novelty is capped by what I could search (web search only; no IEEE/ACM/Scholar access), so no candidate is called 'novel'.

| Rank | Score | # | Candidate | Impact | Novelty | Evidence | Gap | Feas | Measure | Adopt | Evidence status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 7.15 | 1 | Recovery Debt: Ready != functional recovery after pod replacement | 8 | 6 | 6 | 7 | 8 | 9 | 7 | Partly verified (practitioner reports + gray-failure theory + kubelet code); no K8s-specific academic quantification found |
| 2 | 6.65 | 2 | Autoscaler simulation vs real scheduler divergence (CA scale-down/up churn, TopologySpread) | 7 | 5 | 8 | 5 | 8 | 9 | 6 | Verified in source+issue (autoscaler#9287, fix #9288 Apr 2026); instance fixed |
| 3 | 6.1 | 3 | Non-graceful node loss: RWO volume failover delay (VolumeAttachment ~6 min) | 8 | 4 | 7 | 5 | 6 | 8 | 5 | Verified via k/k#112016, #53059, #65392 and Longhorn/SUSE docs; storage-vendor mitigations exist |
| 4 | 6.05 | 8 | Recovery/retry storms after correlated pod/node failure (metastable behaviour in K8s) | 8 | 6 | 3 | 6 | 6 | 7 | 6 | Theory verified (OSDI'22 metastable failures); K8s-specific evidence NOT found yet |
| 5 | 5.4 | 7 | Descheduler-scheduler-ReplicaSet eviction loops (Kivi case C8) | 6 | 4 | 6 | 4 | 7 | 8 | 4 | Verified in Kivi paper (USENIX ATC'24); not independently reproduced |
| 6 | 5.3 | 5 | HPA+VPA incompatibility and multi-scaler conflict | 7 | 3 | 7 | 3 | 6 | 7 | 5 | Verified (autoscaler#1726,#2939,#6060 closed as by-design/documented) |
| 7 | 5.25 | 10 | Operator-application interaction failures (OAT/NSDI'26) | 8 | 3 | 8 | 3 | 4 | 6 | 4 | Verified (NSDI'26, 412 failures, 86 bugs); testing-tool space well covered |
| 8 | 5.2 | 11 | Readiness/liveness probe timeouts under node CPU contention (k/k#89898) | 6 | 3 | 6 | 4 | 7 | 8 | 4 | Issue verified (2020, closed, 166 comments); not re-checked in current release |
| 9 | 5.2 | 9 | Autoscaler misallocation from corrupted metrics under infra faults | 6 | 4 | 5 | 5 | 6 | 7 | 4 | arXiv 2601.04659 verified (VM-level, not K8s HPA specifically); single-author preprint |
| 10 | 5.2 | 4 | Graceful Node Shutdown does not update EndpointSlices (k/k#116965, open) | 6 | 3 | 7 | 3 | 7 | 8 | 4 | Verified (open, sig/node, accepted); narrow bug, maintainers own it |
| 11 | 5.05 | 16 | Terminating-endpoint propagation vs preStop drain races | 6 | 3 | 5 | 4 | 7 | 8 | 4 | KEP-1672/1669 verified stable; residual gaps not yet quantified |
| 12 | 4.95 | 13 | HPA/KEDA/Karpenter/GitOps controller fights | 6 | 5 | 2 | 5 | 6 | 6 | 5 | Only a vendor blog found (weak); needs primary evidence |
| 13 | 4.6 | 14 | Stale/unobserved-state bugs in controllers (Sieve) | 7 | 2 | 8 | 2 | 4 | 6 | 3 | Verified (OSDI'22, 46 bugs); heavily studied |
| 14 | 4.4 | 6 | HPA over-scaling during rolling update (k/k#72775) | 5 | 2 | 6 | 2 | 7 | 8 | 3 | Verified issue (2019, closed); likely addressed; not re-checked in code |
| 15 | 4.0 | 12 | Sidecar/container restart semantics gaps (KEP-4438/5307/5532) | 5 | 2 | 6 | 2 | 5 | 6 | 3 | KEPs verified in repo (beta/alpha); SIG Node actively addressing |
| 16 | 3.85 | 15 | PDB blocking eviction of unhealthy pods | 5 | 1 | 6 | 1 | 6 | 7 | 3 | KEP-3017 verified stable in repo; already solved |
