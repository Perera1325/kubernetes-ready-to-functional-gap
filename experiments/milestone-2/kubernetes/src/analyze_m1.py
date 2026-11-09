"""Analysis of one run (pure functions, unit-tested). All times are CLOCK_MONOTONIC nanoseconds.

Timestamps (see research/experimental_methodology.md):
  T_fault            fault injected
  T_container_ready  first native-readiness-probe success transition (container ready)
  T_pod_ready        overall Pod Ready. Observe mode / single container / no gate: == T_container_ready.
                     If a 'gate_true' event exists for the replica: max(T_container_ready, gate_true).
  T_func             start of the first SUSTAINED functional window on the ground-truth stream G
                     (>= n consecutive valid transactions spanning >= span_s) after degradation onset.
  RFG_observe = T_func - T_pod_ready ;  RFG_cr = T_func - T_container_ready
"""
import csv, json, os, sys
NS = 1e9


def sustained_start(samples, n, span_ns):
    start, cnt = None, 0
    for t, v in samples:
        if v:
            if cnt == 0:
                start = t
            cnt += 1
            if cnt >= n and t - start >= span_ns:
                return start
        else:
            cnt, start = 0, None
    return None


def sustained_confirm(samples, n, span_ns):
    """Time of the sample that COMPLETES the first sustained window (earliest moment an observer could know)."""
    start, cnt = None, 0
    for t, v in samples:
        if v:
            if cnt == 0:
                start = t
            cnt += 1
            if cnt >= n and t - start >= span_ns:
                return t
        else:
            cnt, start = 0, None
    return None


def first_invalid(samples, t0):
    for t, v in samples:
        if t >= t0 and not v:
            return t
    return None


def ready_at(trans, t):
    r = False
    for tt, rd, *_ in trans:
        if tt <= t:
            r = rd
        else:
            break
    return r


def func_time(samples, t_fault, n, span_ns):
    inv = first_invalid(samples, t_fault)
    if inv is None:
        return None, None
    return inv, sustained_start([s for s in samples if s[0] > inv], n, span_ns)


AFFECTED = {"app-degrade": ["r0.1"], "pod-replace": ["r0.2"],
            "dep-restart": ["r0.1", "r1.1"], "replace-during-dep": ["r0.2", "r1.1"]}
REPLACEMENT = {"pod-replace", "replace-during-dep"}


def sec(a, b):
    return None if a is None or b is None else (b - a) / NS


def analyze_data(cfg, scenario, arm, events, trans, user, oracle, obs_events, stats):
    """events: [(t,name,replica,detail)], trans: {replica:[(t,ready,detail)]},
    user/oracle: [(stream,seq,t,lat,status,cls,valid,replica,detail)], obs_events: [(t,replica,event)]"""
    ev = lambda name, rep=None: next((e[0] for e in events if e[1] == name and (rep is None or e[2] == rep)), None)
    t_fault, t_steady, t_end = ev("fault"), ev("steady"), ev("end")
    hz = cfg["oracle_hz"]
    tn, tspan = cfg["truth"]["n"], int(cfg["truth"]["span_s"] * NS)
    un, uspan = cfg["user"]["n"], int(cfg["user"]["span_s"] * NS)
    out = {"scenario": scenario, "arm": arm, "t_fault_s": 0.0}

    # --- harness sanity: nothing may fail between steady state and fault
    out["pre_fault_invalid_G"] = sum(1 for r in oracle if t_steady <= r[2] < t_fault and not r[6])
    out["pre_fault_invalid_U"] = sum(1 for r in user if t_steady <= r[2] < t_fault and not r[6])

    per = {}
    for rep in AFFECTED[scenario]:
        g = sorted((r[2], r[6]) for r in oracle if r[0] == "G:" + rep)
        tr = trans.get(rep, [])
        inv, tf = func_time(g, t_fault, tn, tspan)
        ups = [t for t, rd, *_ in tr if rd and (scenario in REPLACEMENT and rep == "r0.2" or t >= t_fault)]
        t_cr = ups[0] if ups else None
        t_pr = t_cr
        gate = next((e[0] for e in events if e[1] == "gate_true" and e[2] == rep), None)
        if gate is not None and t_cr is not None:
            t_pr = max(t_cr, gate)
        after = [(t, v) for t, v in g if t >= t_fault]
        d = {
            "degradation_onset_s": sec(t_fault, inv),
            "t_func_s": sec(t_fault, tf), "t_container_ready_s": sec(t_fault, t_cr),
            "t_pod_ready_s": sec(t_fault, t_pr),
            "rfg_observe_s": sec(t_pr, tf), "rfg_cr_s": sec(t_cr, tf),
            "ready_nonfunctional_s": sum(1.0 / hz for t, v in after if not v and ready_at(tr, t)),
            "false_notready_s": sum(1.0 / hz for t, v in after if v and not ready_at(tr, t)),
            "manifested": inv is not None, "recovered": (inv is None) or (tf is not None),
        }
        per[rep] = d
    out["per_replica"] = per
    vals = [d["rfg_observe_s"] for d in per.values() if d["rfg_observe_s"] is not None]
    out["rfg_observe_max_s"] = max(vals) if vals else None
    out["ready_nonfunctional_s"] = sum(d["ready_nonfunctional_s"] for d in per.values())
    out["false_notready_s"] = sum(d["false_notready_s"] for d in per.values())
    out["replicas_recovered"] = all(d["recovered"] for d in per.values())

    # stale Ready of a killed replica (detection lag of the probe itself, not RFG)
    if scenario in REPLACEMENT:
        tk = ev("kill", "r0.1")
        down = [t for t, rd, *_ in trans.get("r0.1", []) if t > tk and not rd]
        out["stale_ready_s"] = sec(tk, down[0]) if down else None

    # --- user-visible effect (through the Service emulator)
    for name in ("tx", "static"):
        s = sorted((r[2], r[6], r[5]) for r in user if r[0] == name)
        sv = [(t, v) for t, v, _ in s]
        inv = first_invalid(sv, t_fault)
        tf = sustained_start([x for x in sv if inv is not None and x[0] > inv], un, uspan) if inv else None
        win = [x for x in s if inv is not None and inv <= x[0] and (tf is None or x[0] < tf)]
        out[f"{name}_error_duration_s"] = sec(inv, tf) if inv else 0.0
        out[f"{name}_recovered"] = inv is None or tf is not None
        out[f"{name}_window_requests"] = len(win)
        for c in ("invalid_business", "no_endpoints", "conn_error", "http_error"):
            out[f"{name}_{c}"] = sum(1 for x in win if x[2] == c)
        out[f"{name}_fail_fraction"] = (sum(1 for x in win if not x[1]) / len(win)) if win else 0.0

    # --- zero ready endpoints (cascading unavailability)
    times = sorted({t for tr in trans.values() for t, *_ in tr if t_fault <= t <= t_end} | {t_fault, t_end})
    zero = 0.0
    for a, b in zip(times, times[1:]):
        mid = (a + b) // 2
        if not any(ready_at(tr, mid) for tr in trans.values()):
            zero += (b - a) / NS
    out["zero_endpoint_s"] = zero

    # --- observer (arm C) vs ground truth
    if obs_events:
        guard = int(cfg["observer"]["guard_s"] * NS)
        od = {}
        for rep in AFFECTED[scenario]:
            es = sorted(e for e in obs_events if e[1] == rep)
            g = sorted((r[2], r[6]) for r in oracle if r[0] == "G:" + rep)
            inv, tf = func_time(g, t_fault, tn, tspan)
            tconf = sustained_confirm([x for x in g if inv is not None and x[0] > inv], tn, tspan) if inv else None
            lost = next((t for t, _, e in es if e == "functional_lost" and t >= t_fault), None)
            fn = next((t for t, _, e in es if e == "functional" and t > (lost or t_fault)), None)
            false_f = fn is not None and any(t > fn and t <= fn + guard and not v for t, v in g)
            od[rep] = {"detect_loss_s": sec(inv, lost) if lost and inv else None,
                       "functional_latency_vs_truth_s": sec(tconf, fn),
                       "functional_after_window_start_s": sec(tf, fn),
                       "false_functional": bool(false_f), "declared_functional": fn is not None}
        out["observer"] = od
    out.update({k: v for k, v in stats.items() if k in ("probe_requests", "dep_ops_probe", "app_cpu_s", "observer_requests")})
    return out


def _csv(path):
    with open(path) as f:
        return list(csv.reader(f))[1:]


def load_run(rd):
    cfg = json.load(open(os.path.join(rd, "config.json")))
    events = [(int(a), b, c, d) for a, b, c, d in _csv(os.path.join(rd, "events.csv"))]
    trans = {}
    for a, rep, rd_, det in _csv(os.path.join(rd, "probe_transitions.csv")):
        trans.setdefault(rep, []).append((int(a), rd_ == "True", det))
    cv = lambda r: (r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4]), r[5], r[6] == "True", r[7], r[8])
    user = [cv(r) for r in _csv(os.path.join(rd, "user.csv"))]
    oracle = [cv(r) for r in _csv(os.path.join(rd, "oracle.csv"))]
    obs = [(int(a), b, c) for a, b, c in _csv(os.path.join(rd, "observer_events.csv"))]
    stats = json.load(open(os.path.join(rd, "stats.json")))
    return cfg, events, trans, user, oracle, obs, stats


def main(rd):
    cfg, events, trans, user, oracle, obs, stats = load_run(rd)
    meta = cfg["_run"]
    res = analyze_data(cfg, meta["scenario"], meta["arm"], events, trans, user, oracle, obs, stats)
    res["run_id"] = meta["run_id"]
    json.dump(res, open(os.path.join(rd, "summary.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1))
