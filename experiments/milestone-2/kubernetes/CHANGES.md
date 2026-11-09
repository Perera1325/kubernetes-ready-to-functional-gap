# Changes after first real-cluster execution (Milestone 2-A, local WSL2 + Docker Desktop)

Business validation, WAL replay/CRC, cache warm-up, backoff and fault scenarios are NOT modified. Milestone 1 is untouched.

## Patch 1 (2026-11-09) — found while inspecting the first manual run
| File | Change | Why |
|---|---|---|
| `src/collector.py` | `k8s_events.csv` now keeps **every** watch row from the start of the run (`t_run0`, set before cluster preparation) instead of only rows from 60 s before the first recorded event | Preparation (scale-down, scale-up, wait Ready) can exceed 60 s, which would silently drop watch rows (rule: preserve all raw data). Found by code review after the first manual run; the first manual run's file may therefore lack rows older than 60 s before its first event (none of them are used by the analysis; initial pods' creation rows only). |
| `analysis/validate_run.py` (new) | Independent validator recomputed from raw CSVs only: files, streams, sampling gaps, pre-fault errors, replacement-pod identification, overlap, T_func/dependency-functional recomputation vs `summary.json`, timeline | Step 4 of the execution plan ("analysis output matches raw measurements") |
| `tests/test_collector_mock_api.py` | + regression test for the row-window fix; + validator test (accepts a consistent run, rejects a tampered summary) | regression coverage |
| `scripts/diagnose.sh` (new, earlier) | read-only environment diagnostics | Step 1 |

Apply: rebuild the collector image and reload it into Kind: `scripts/build-images.sh && kind load docker-image rfg-collector:m2a --name rfg`.

## Patch 2 (2026-11-09) — raw-data protection (incident)
Incident: running `scripts/run-manual.sh` a second time overwrote `raw-results/manual/` (same fixed name on host and in the results PVC); the first manual run's raw files were lost. Only its `summary.json`, pasted into the chat, survives. The second run (old collector code, before Patch 1) is kept.
| File | Change |
|---|---|
| `scripts/run-collector.sh` | refuses to run if `raw-results/NAME` already exists |
| `scripts/run-manual.sh` | default name `manual-YYYYMMDD-HHMMSS` (unique); also runs `analyze.sh` and the independent validator |
| `scripts/run-pilot.sh` | default name `pilot-YYYYMMDD-HHMMSS`; must not be run without approval |

## Patch 3 (2026-11-09) — environment-variable collision
`scripts/run-manual.sh` / `run-pilot.sh` read `$NAME` for the run name; WSL sets `NAME=<hostname>` (here `Vinod`), so the run was named `Vinod`. Now the override variable is `RUN_NAME`. Also found: the wait loop in `run-collector.sh` can be satisfied by a stale `<name>.EXIT` already in the results volume (this is what made the second `run-manual.sh` return instantly with run-1 data; run-1 raw data was NOT lost). Unique timestamped names avoid it.
Apply on the machine:  `sed -i 's/NAME="${NAME:-/NAME="${RUN_NAME:-/' scripts/run-manual.sh scripts/run-pilot.sh`

## Patch 4 (2026-11-09) — found while running the three smoke runs
| File | Change | Why |
|---|---|---|
| `analysis/validate_run.py` | (a) "store pod rows recorded" is required only for dep-restart / replace-during-dep (it gave a false FAIL in app-degrade and pod-replace); (b) recomputation covers the scenario's affected replicas exactly as M1 (`r0.1` was skipped for dep-restart); (c) timeline now also prints Pod NOT Ready and endpoint NOT READY events; (d) prints summary highlights and the observer result | false FAIL; incomplete cross-check; RQ3/RQ4 evidence |
| `src/collector.py` | `snapshot_pods()`: at run start the state of pods that already exist (e.g. the store) is written to `k8s_events.csv` as `SNAPSHOT` rows | these pods emit no watch events during scenarios that do not touch them, so their state was absent from the run's raw file |
| `tests/test_collector_mock_api.py` | + snapshot test; + regression for the store-row check | |
The three smoke runs themselves were not invalid; only the validator's check was wrong. They need no re-run.
