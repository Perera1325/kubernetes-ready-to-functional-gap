# Kubernetes Ready-to-Functional Gap (RFG)

When does Kubernetes say **Ready** while the application is **not yet working**? This repository measures that gap on a real
three-node Kubernetes cluster (kind v0.25.0, Kubernetes 1.31) with fault injection, and compares a shallow readiness probe, a
deep probe, and a passive external observer.

> **Status: pilot study.** 60 runs (4 faults x 3 setups x 5 repetitions) on one laptop. Results are directional: medians and
> ranges only, no significance tests. 59 of 60 runs passed independent validation; the 1 flagged run is kept and explained.

## Key findings (pilot, medians of 5 runs)
- With a shallow readiness probe, Pods stayed Ready while failing real requests for about **3.6 s** (app degraded) up to **16 s** (Pod replaced during a database restart; two replicas summed).
- The failures were **HTTP 200 with wrong content**, so status-code monitoring would not catch them.
- A **deep probe** had the lowest Ready-but-invalid time in every scenario, but when a shared dependency restarted it removed both replicas from the Service (median **5.9 s** without a ready Pod) and failed static pages that did not need the dependency.
- A **passive observer** detected loss within 0.05-0.15 s, declared recovery 30/30 times with 0 false declarations, and never changed readiness.
- My earlier local simulation predicted no gap for a plain Pod replacement; on the real cluster 9 of 10 shallow-probe runs showed a small positive gap (0.08-0.62 s).

## Repository layout
| Path | Contents |
|---|---|
| `paper/` | Paper source (`main.tex`, Overleaf-ready), `paper.pdf`, figures and terminal screenshots |
| `data/pilot-20261109/` | Per-run summaries (60), `aggregate.md`/`aggregate.csv`, validation log |
| `experiments/milestone-2/kubernetes/` | Real-cluster harness: app, store, collector, manifests, scripts, validator, tests |
| `experiments/milestone-1/` | Earlier local simulation (kept separate from real measurements) |
| `reports/` | Result reports for milestones 1 and 2-A |
| `research/`, `evidence/` | Initial investigation notes and evidence registers |
| `docs/article/` | Diagrams and charts used in the articles |

## Reproduce
Requires Docker, `kind` and `kubectl` (>= 4 CPUs, >= 8 GiB RAM recommended; on Windows use WSL 2 with Docker Desktop).
```bash
cd experiments/milestone-2/kubernetes
scripts/preflight.sh
scripts/build-images.sh
scripts/create-cluster.sh
scripts/run-manual.sh        # one manual run first
RUN_NAME=my-pilot scripts/run-pilot.sh
scripts/analyze.sh my-pilot
scripts/teardown.sh
```
Details, measurement definitions and known limits are in `experiments/milestone-2/kubernetes/README.md`.

## Method in brief
Three request streams run during each fault: ground truth sent directly to each Pod (20 Hz), user traffic through the Service,
and a dependency ping. A Pod is *functional* when it starts answering correctly and keeps doing so (>= 20 valid samples over >= 1 s).
A separate validator recomputes every run from the raw CSV files (31-36 checks per run).

## Limits
Small sample (5 per cell), one laptop, one probe setting (1 s period, threshold 3), injected faults, Kubernetes 1.31.
Kube-proxy programming latency and probe CPU cost were not measured. In 43 of 60 runs the first user request failed before
measurement began; the cause is unexplained. See the paper for details.

## License
MIT (see `LICENSE`).
