# GitHub investigation
See evidence/github_issues.csv for the register. Key reads:

1. **autoscaler#9287 (created 2026-02-27, closed 2026-04-21).** Cross-component failure: Cluster Autoscaler's simulator deletes the node from its snapshot, so topology domains drop to 2 and the pod "fits"; the real drain only taints the node, the tainted domain keeps 0 pods (minMatchNum=0), and replacements go Pending, so CA scales up again. Reported on AKS, CA 1.32+. It followed fix #8164 (merged 2025-05-30). Fix in git history: commit 03f4ab136 "replace RemoveNodeInfo with tainted ghost node in scale-down simulation", merge of #9288 on 2026-04-21, cherry-picked May 2026. Link between #9288 and #9287 is inferred (same day, same topic); PR text not read. Status: **already solved for this instance**; the class (simulation vs real behaviour) remains.
2. **k/k#116965 (2023-03-28, open).** Graceful Node Shutdown never marks the pod Terminating until it ends, so EndpointSlice keeps routing to it. Accepted, long-term priority. Known bug, owned by SIG Node.
3. **k/k#112016 (2022-08-24, closed 2023-07-20).** Dead node + RWO disk: replacements stuck in ContainerCreating. Closure reason not readable. Vendor docs (Longhorn/SUSE) describe ~6 min before VolumeAttachment cleanup. Known limitation with vendor mitigations.
4. **autoscaler#1726/#2939/#6060.** HPA+VPA on the same metric: closed as by-design/documentation.

Pattern: well-known problems are either fixed, owned, or documented. Genuine gaps are more likely in *measurement and detection across layers* than in single-component bugs.
