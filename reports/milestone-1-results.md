# Milestone 1 experimental results (new experimental findings; the 2026-11-09 investigation is unchanged)

LOCAL SIMULATION, no Kubernetes. 60 runs (4 scenarios x 3 arms x 5 repetitions), 0 aborted, all recovered. Raw data: experiments/milestone-1/results/run1. Descriptive medians; n=5 per cell.

| Scenario | Arm | Ready but functionally invalid (s, median [min-max], summed over affected replicas) | Wrong/failed tx | Dependency-free endpoint outage (s) | No Ready endpoint (s) | Notes |
|---|---|---|---|---|---|---|
| pod-replace | A | 0.00 [0-0] | 17 conn errors | 2.00 | 0 | RFG negative in 15/15 (max -0.02 s): replacement functional before Ready |
| dep-restart | A | 7.30 [7.20-7.55] | 73 invalid_business | 0 | 0 | ~3.6 s per replica |
| dep-restart | B (deep) | 5.10 [4.20-5.40] | 58 invalid + 20 no-endpoint | 1.00 | 1.00 | |
| dep-restart | C | 7.20 | 72 | 0 | 0 | same user effect as A by design |
| replace-during-dep | A | 4.85 [4.40-5.00] | 37 invalid + 28 conn | 1.90 | 0 | RFG_observe of replacement: 1.28, 1.44, 0.91, 1.27, 0.84 s (5/5 positive) |
| replace-during-dep | B | 2.45 [2.15-2.95] | 23 invalid + 7 no-endpoint + 36 conn | 3.30 | 0.37 | RFG negative |
| app-degrade | A | 3.20 [3.15-3.25] | 32 invalid | 0 | 0 | gap true by construction |
| app-degrade | B | 2.95 [2.00-2.95] | 29 invalid | 0 | 0 | |

(Full table: results/run1/aggregate.md.)

## What the data support
1. A Pod can stay (or become) Ready while valid business transactions fail: 15/15 arm-A runs in the three dependency/degradation scenarios show it. For a *replacement* Pod it needs a dependency that is still recovering (replace-during-dep: RFG_observe 0.84-1.44 s, 5/5).
2. It is NOT generic: with a healthy dependency, plain pod replacement shows no gap (RFG negative in 15/15), because warm-up here costs ~0.2 s.
3. The deep probe (B) is not a clear win and is not dominated: it cuts silent wrong answers and Ready-but-invalid time (7.3 -> 5.1 s in dep-restart) but did not shorten user-visible error duration (dep-restart 3.7 s A vs 3.95 s B; ranges overlap) and it took down a dependency-free endpoint for ~1 s and left zero Ready endpoints for up to ~1 s, plus 14-22 dependency calls per run from probes.
4. The standalone observer detected loss ~0.05-0.10 s after ground truth and confirmed recovery within about +/-0.25 s of the truth criterion, with 0 premature declarations in 30 observations (it uses a slightly shorter window than truth, so "early" is expected). Overhead: ~108 extra requests per run, CPU median 1.28 s vs 1.14 s (A) — single-run CPU readings, noisy.

## What they do not show
Prevalence or magnitude in real Kubernetes; sensitivity to backoff/replay size/probe period; queue-consumer behaviour; gate mode (not implemented); any statistical significance.
