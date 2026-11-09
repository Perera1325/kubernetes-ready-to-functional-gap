#!/usr/bin/env python3
"""Independent validation of ONE real run directory, recomputed from the raw CSVs only (does NOT call the M1/K8s analysis code).
Prints PASS/WARN/FAIL per check and a timeline relative to T_fault. Exit code 1 if any FAIL.  usage: validate_run.py RUN_DIR"""
import csv, json, os, sys
NS = 1e9
res = []
AFF = {"app-degrade": ["r0.1"], "pod-replace": ["r0.2"], "dep-restart": ["r0.1", "r1.1"], "replace-during-dep": ["r0.2", "r1.1"]}  # same as Milestone-1 AFFECTED


def chk(level, name, detail=""):
    res.append((level, name, detail)); print(f"[{level}] {name}" + (f"  -- {detail}" if detail else ""))


def rows(p):
    with open(p) as f: return list(csv.DictReader(f))


def streams(rs):
    d = {}
    for r in rs: d.setdefault(r["stream"], []).append((int(r["t_send_ns"]), r["valid"] == "True", r["cls"], int(r["status"]), r["detail"]))
    for v in d.values(): v.sort()
    return d


def sustained_start(samples, n, span):
    st, c = None, 0
    for t, v in samples:
        if v:
            if c == 0: st = t
            c += 1
            if c >= n and t - st >= span: return st
        else: c, st = 0, None
    return None


def main(rd):
    cfg = json.load(open(f"{rd}/config.json")); meta = cfg["_run"]; sc, arm = meta["scenario"], meta["arm"]
    need = ["events.csv", "probe_transitions.csv", "user.csv", "oracle.csv", "dependency.csv", "k8s_events.csv", "stats.json", "config.json", "observer_events.csv", "observer_raw.csv"]
    for f in need:
        ok = os.path.exists(f"{rd}/{f}") and (os.path.getsize(f"{rd}/{f}") > 40 or f.startswith("observer") and arm != "C" or f == "stats.json")
        chk("PASS" if ok else "FAIL", f"file {f} present/non-empty")
    if os.path.exists(f"{rd}/ABORTED.txt"): chk("FAIL", "run aborted", open(f"{rd}/ABORTED.txt").read())
    ev = [(int(r["t_ns"]), r["name"], r["replica"], r["detail"]) for r in rows(f"{rd}/events.csv")]
    E = lambda n, rep=None: next((e[0] for e in ev if e[1] == n and (rep is None or e[2] == rep)), None)
    tf, tsteady, tend = E("fault"), E("steady"), E("end")
    chk("PASS" if None not in (tf, tsteady, tend) else "FAIL", "events fault/steady/end present")
    for e in ev:
        if e[1] in ("NOTE", "ABORT"): chk("WARN", "collector note", e[3])
    G, U, D = streams(rows(f"{rd}/oracle.csv")), streams(rows(f"{rd}/user.csv")), streams(rows(f"{rd}/dependency.csv"))
    pm = {e[2]: e[3] for e in ev if e[1] == "pod_map"}
    want = ["r0.1", "r1.1"] + (["r0.2"] if sc in ("pod-replace", "replace-during-dep") else [])
    for r in want:
        chk("PASS" if ("G:" + r) in G and len(G["G:" + r]) > 50 else "FAIL", f"stream G:{r} present", f"{len(G.get('G:'+r, []))} samples, pod={pm.get(r)}")
    for n in ("tx", "static"): chk("PASS" if len(U.get(n, [])) > 50 else "FAIL", f"user stream {n}", f"{len(U.get(n, []))} samples")
    chk("PASS" if len(D.get("D:store", [])) > 50 else "FAIL", "dependency stream D", f"{len(D.get('D:store', []))} samples")
    chk("PASS" if len(set(pm.values())) == len(pm) else "FAIL", "pod_map names distinct", str(pm))
    # sampling health
    exp = {"G": 1 / cfg["oracle_hz"], "tx": 1 / cfg["user"]["tx_hz"], "static": 1 / cfg["user"]["static_hz"], "D": 1 / cfg["k8s"]["d_hz"]}
    for name, s in list(G.items()) + list(U.items()) + list(D.items()):
        if len(s) < 3: continue
        ts = [x[0] for x in s]; gaps = [(b - a) / NS for a, b in zip(ts, ts[1:])]
        k = "G" if name.startswith("G") else ("D" if name.startswith("D") else name)
        mx = max(gaps)
        chk("PASS" if mx < 1.6 else "WARN", f"{name}: max gap {mx:.2f}s (expected interval {exp[k]:.3f}s, <=1 s timeout)", "")
    # consistency of valid vs class
    bad = sum(1 for d in (G, U, D) for s in d.values() for t, v, c, st, de in s if v != (c == "ok"))
    chk("PASS" if bad == 0 else "FAIL", "valid flag == (class == ok) on every sample", f"{bad} mismatches")
    # pre-fault errors (independent)
    pre = lambda d, names: sum(1 for n in names for t, v, *_ in d.get(n, []) if tsteady <= t < tf and not v)
    pg, pu = pre(G, ["G:r0.1", "G:r1.1"]), pre(U, ["tx", "static"])
    chk("PASS" if pg == 0 and pu == 0 else "FAIL", "no invalid samples between steady state and fault", f"G={pg} U={pu}")
    # classes in the post-fault window (surface unexpected classes)
    cls = {}
    for t, v, c, st, de in U.get("tx", []):
        if t >= tf and not v: cls[(c, st, de)] = cls.get((c, st, de), 0) + 1
    chk("PASS", "user tx failure classes after fault (class,status,detail -> count)", str(cls))
    # k8s evidence
    k = rows(f"{rd}/k8s_events.csv")
    first_k = min((int(r["t_mono_ns"]) for r in k), default=None)
    chk("PASS" if k and first_k <= tsteady else "FAIL", "k8s_events covers the run up to steady state")
    kinds = {r["kind"] for r in k}
    chk("PASS" if {"pod", "endpointslice"} <= kinds else "FAIL", "k8s_events has pod + endpointslice rows", str(kinds))
    chk("PASS" if any(r["kind"] == "endpoint" for r in k) else "WARN", "endpoint READY/NOTREADY transitions recorded")
    if sc in ("dep-restart", "replace-during-dep"):
        chk("PASS" if any(r["app"] == "rfg-store" for r in k) else "FAIL", "store pod rows recorded")
    else:
        chk("PASS", "store pod rows not required (dependency is not faulted in this scenario)")
    # replacement pod identification
    rel = lambda t: None if t is None else (t - tf) / NS
    if "r0.2" in pm:
        pr = [r for r in k if r["kind"] == "pod" and r["name"] == pm["r0.2"]]
        created_after = bool(pr) and min(int(r["t_mono_ns"]) for r in pr) > tf
        chk("PASS" if created_after else "FAIL", "replacement pod first seen AFTER the fault", pm["r0.2"])
        chk("PASS" if pm["r0.2"] not in (pm.get("r0.1"), pm.get("r1.1")) else "FAIL", "replacement is a different pod than the initial two")
        dead = [r for r in k if r["kind"] == "pod" and r["name"] == pm["r0.1"] and r["type"] == "DELETED"]
        chk("PASS" if dead else "WARN", "killed pod r0.1 has a DELETED watch row", pm["r0.1"])
    # recompute T_func / listen / dependency (independent code)
    n, span = cfg["truth"]["n"], int(cfg["truth"]["span_s"] * NS)
    tl = {"fault": 0.0}
    out = {}
    for r in AFF[sc]:
        s = G.get("G:" + r, [])
        inv = next((t for t, v, *_ in s if t >= tf and not v), None)
        f = sustained_start([x[:2] for x in s if inv is not None and x[0] > inv], n, span)
        out[r] = (rel(inv), rel(f)); tl[f"{r} onset"], tl[f"{r} T_func"] = rel(inv), rel(f)
    sm = json.load(open(f"{rd}/summary.json")) if os.path.exists(f"{rd}/summary.json") else None
    if sm:
        for r, (inv, f) in out.items():
            d = sm["per_replica"].get(r, {})
            for key, mine in (("degradation_onset_s", inv), ("t_func_s", f)):
                theirs = d.get(key)
                ok = (mine is None and theirs is None) or (mine is not None and theirs is not None and abs(mine - theirs) < 0.002)
                chk("PASS" if ok else "FAIL", f"summary {key} for {r} matches independent recomputation", f"mine={mine} summary={theirs}")
        dk = E("dep_kill")
        if dk is not None:
            ds = D.get("D:store", []); inv = next((t for t, v, *_ in ds if t >= dk and not v), None)
            fn = next((t for t, v, *_ in ds if inv is not None and t > inv and v), None)
            tl["dep first invalid"], tl["dep functional"] = rel(inv), rel(fn)
            chk("PASS" if sm.get("dep_functional_s") is not None and fn is not None and abs(rel(fn) - sm["dep_functional_s"]) < 0.002 else "FAIL",
                "summary dep_functional_s matches recomputation", f"mine={rel(fn)} summary={sm.get('dep_functional_s')}")
            if "r0.2" in pm:
                ls = next((t for t, v, c, st, de in sorted(G.get("G:r0.2", [])) if st > 0), None)
                tl["r0.2 first response (app listening)"] = rel(ls)
                ov = ls is not None and fn is not None and ls < fn
                chk("PASS" if sm.get("replacement_started_before_dep_functional") == ov else "FAIL", "overlap flag matches recomputation",
                    f"overlap={ov} margin={rel(fn) - rel(ls) if ov else None}")
        uw = [t for t, v, *_ in U.get("tx", []) if t >= tf and not v]
        if uw: tl["user tx first error"], tl["user tx last error"] = rel(uw[0]), rel(uw[-1])
    for e in ev:
        if e[1] in ("kill", "dep_kill", "dep_pod_running", "dep_pod_ready", "recover") and e[0] >= tf: tl.setdefault(e[1] + (" " + e[2] if e[2] else ""), rel(e[0]))
    for r in k:
        if r["kind"] == "pod" and r["name"] in pm.values() and int(r["t_mono_ns"]) >= tf:
            lg = next(a for a, b in pm.items() if b == r["name"])
            if r["pod_ready"] == "1": tl.setdefault(f"{lg} Pod Ready (watch)", rel(int(r["t_mono_ns"])))
        if r["kind"] == "endpoint" and r["type"] == "READY" and int(r["t_mono_ns"]) >= tf and r["name"] in pm.values():
            tl.setdefault(f"{next(a for a, b in pm.items() if b == r['name'])} endpoint READY", rel(int(r["t_mono_ns"])))
    seen_ready = set()
    for r in sorted((x for x in k if x["kind"] == "pod" and x["name"] in pm.values()), key=lambda x: int(x["t_mono_ns"])):
        lg = next(a for a, b in pm.items() if b == r["name"])
        if r["pod_ready"] == "1": seen_ready.add(r["name"])
        elif r["name"] in seen_ready and int(r["t_mono_ns"]) >= tf:
            tl.setdefault(f"{lg} Pod NOT Ready (watch) [{r['type']}]", rel(int(r["t_mono_ns"]))); seen_ready.discard(r["name"])
    for r in k:
        if r["kind"] == "endpoint" and r["type"] == "NOTREADY" and int(r["t_mono_ns"]) >= tf and r["name"] in pm.values():
            tl.setdefault(f"{next(a for a, b in pm.items() if b == r['name'])} endpoint NOT READY", rel(int(r["t_mono_ns"])))
    print("\nTIMELINE (seconds after T_fault, collector monotonic clock; watch events are RECEIPT times)")
    for kx, v in sorted(tl.items(), key=lambda kv: (kv[1] is None, kv[1] or 0)): print(f"  {('%+.3f' % v) if v is not None else '   n/a':>9}  {kx}")
    if sm:
        keys = ["rfg_observe_max_s", "ready_nonfunctional_s", "false_notready_s", "zero_endpoint_s", "tx_error_duration_s", "tx_invalid_business", "tx_conn_error", "tx_http_error", "static_error_duration_s", "probe_requests", "dep_ops_probe", "observer_requests"]
        print("\nSUMMARY HIGHLIGHTS: " + ", ".join(f"{x}={sm[x]:.2f}" if isinstance(sm.get(x), float) else f"{x}={sm.get(x)}" for x in keys))
        if sm.get("observer"): print("OBSERVER: " + json.dumps(sm["observer"]))
    fails = sum(1 for r in res if r[0] == "FAIL"); warns = sum(1 for r in res if r[0] == "WARN")
    print(f"\nRESULT: {'INVALID' if fails else 'VALID'}  ({fails} FAIL, {warns} WARN, {len(res)} checks)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1].rstrip("/")))
