# Literature review (web-search only; see evidence/academic_papers.csv)

| Work | Solved | Partial / assumption |
|---|---|---|
| Sieve (OSDI'22), Acto (SOSP'23), OAT (NSDI'26) | Pre-production testing finds controller/operator bugs (46 / 56 / 86 bugs) | Test-time, operators only; do not measure how long a *healthy-looking* replacement pod stays functionally broken |
| Kivi (ATC'24) | Verifies controller-controller interactions (scheduler/descheduler/ReplicaSet loop) | Models 6 controllers; no zero-false-negative guarantee |
| Gray failure (HotOS'17) | Defines differential observability: detector sees healthy, app is hurt | Position paper; no Kubernetes mechanism |
| Metastable failures (OSDI'22) | Taxonomy; retries sustain >50% of cases | Not Kubernetes-specific |
| Chen et al. 2025 (arXiv 2507.16109) | Chaos Mesh + Locust measure app latency/errors/recovery under K8s faults | Measures impact; no detector or controller; preprint |
| Park 2026 (arXiv 2601.04659) | Fault-corrupted metrics cause autoscaler misallocation | VM autoscaling; single author |

Unanswered: (a) how large is the Ready-to-functional gap across workload types; (b) whether a runtime, Kubernetes-native detector/gate beats a well-written deep readiness probe. Search terms tried: Kubernetes readiness vs application recovery, functional recovery time, controller interactions, stateful recovery. I found no paper that does (a)+(b) together, but my coverage excludes IEEE/ACM/Scholar.
