"""Analysis of one REAL-Kubernetes run. Reuses the Milestone-1 analysis functions UNCHANGED (src/analyze_m1.py is a byte-identical
copy, verified by tests) and adds Kubernetes-specific timestamps.  Pure functions + a tiny CLI.

Added fields (all seconds relative to T_fault unless stated; collector monotonic clock):
  per replica: t_container_ready_k8s_s, t_pod_ready_k8s_s, t_endpoint_available_s, rfg_endpoint_s = T_func - T_endpoint_available,
               rfg_k8s_podready_s = T_func - T_pod_ready(watch), watch_latency_s (wall receipt - condition lastTransitionTime; +-1 s resolution!)
  run:         dep_functional_s, dep_pod_running_s, dep_pod_ready_s, replacement_app_listen_s, replacement_started_before_dep_functional,
               unexpected_notes
"""
import csv, datetime, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import analyze_m1 as m1
NS = 1e9


def _rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def iso_to_ns(s):
    try:
        return int(datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp() * NS)
    except Exception:
        return None


def extras(cfg, scenario, events, k8s, oracle, dep, base):
    """k8s: list of dict rows from k8s_events.csv; dep: dependency stream rows (tuples like oracle)."""
    ev = lambda name, rep=None: next((e[0] for e in events if e[1] == name and (rep is None or e[2] == rep)), None)
    t_fault = ev("fault"); out = {}
    podname = {e[2]: e[3] for e in events if e[1] == "pod_map"}
    per = base["per_replica"]
    for rep in m1.AFFECTED[scenario]:
        pn = podname.get(rep); d = {}
        pr = [r for r in k8s if r["kind"] == "pod" and r["name"] == pn]
        first = lambda cond: next((int(r["t_mono_ns"]) for r in pr if cond(r)), None)
        after = (lambda r: True) if (scenario in m1.REPLACEMENT and rep == "r0.2") else (lambda r: int(r["t_mono_ns"]) >= t_fault)
        t_run = first(lambda r: r["running"] == "1" and after(r))
        t_ccr = first(lambda r: r["container_ready"] == "1" and after(r))
        t_pr = first(lambda r: r["pod_ready"] == "1" and after(r))
        epr = [int(r["t_mono_ns"]) for r in k8s if r["kind"] == "endpoint" and r["type"] == "READY" and r["name"] == pn
               and ((scenario in m1.REPLACEMENT and rep == "r0.2") or int(r["t_mono_ns"]) >= t_fault)]
        t_ep = epr[0] if epr else None
        g = sorted((x[2], x[6]) for x in oracle if x[0] == "G:" + rep)
        inv, tf = m1.func_time(g, t_fault, cfg["truth"]["n"], int(cfg["truth"]["span_s"] * NS))
        wl = []
        for r in pr:
            if r["pod_ready"] == "1" and r["ltt_ready"]:
                tl = iso_to_ns(r["ltt_ready"])
                if tl is not None: wl.append((int(r["t_wall_ns"]) - tl) / NS)
        d.update({"t_pod_running_seen_s": m1.sec(t_fault, t_run), "t_container_ready_k8s_s": m1.sec(t_fault, t_ccr),
                  "t_pod_ready_k8s_s": m1.sec(t_fault, t_pr), "t_endpoint_available_s": m1.sec(t_fault, t_ep),
                  "rfg_k8s_podready_s": m1.sec(t_pr, tf), "rfg_endpoint_s": m1.sec(t_ep, tf),
                  "watch_latency_s_first_ready": wl[0] if wl else None})
        # first successful response from this replica (it is listening) - replacement pods only
        if scenario in m1.REPLACEMENT and rep == "r0.2":
            ls = next((x[2] for x in sorted(oracle, key=lambda z: z[2]) if x[0] == "G:" + rep and x[4] > 0), None)
            d["app_listen_s"] = m1.sec(t_fault, ls)
        out[rep] = d
    run = {}
    dk = ev("dep_kill")
    if dk is not None:
        ds = sorted((x[2], x[6]) for x in dep)
        inv = m1.first_invalid(ds, dk)
        f = next((t for t, v in ds if inv is not None and t > inv and v), None)
        run["dep_unavailable_s"] = m1.sec(inv, f); run["dep_functional_s"] = m1.sec(t_fault, f)
        run["dep_pod_running_s"] = m1.sec(t_fault, next((e[0] for e in events if e[1] == "dep_pod_running" and e[0] > dk), None))
        run["dep_pod_ready_s"] = m1.sec(t_fault, next((e[0] for e in events if e[1] == "dep_pod_ready" and e[0] > dk), None))
        if scenario == "replace-during-dep" and f is not None:
            ls = out.get("r0.2", {}).get("app_listen_s")
            run["replacement_app_listen_s"] = ls
            run["replacement_started_before_dep_functional"] = (ls is not None and (t_fault + ls * NS) < f)
            run["replacement_overlap_margin_s"] = None if ls is None else m1.sec(t_fault + ls * NS, f)
    run["unexpected_notes"] = [e[3] for e in events if e[1] == "NOTE"]
    run["aborted"] = any(e[1] == "ABORT" for e in events)
    return out, run


def main(rd):
    cfg, events, trans, user, oracle, obs, stats = m1.load_run(rd)
    meta = cfg["_run"]
    res = m1.analyze_data(cfg, meta["scenario"], meta["arm"], events, trans, user, oracle, obs, stats)
    cv = lambda r: (r["stream"], int(r["seq"]), int(r["t_send_ns"]), int(r["latency_ns"]), int(r["status"]), r["cls"], r["valid"] == "True", r["replica"], r["detail"])
    dep = [cv(r) for r in _rows(os.path.join(rd, "dependency.csv"))]
    k8s = _rows(os.path.join(rd, "k8s_events.csv"))
    pe, pr = extras(cfg, meta["scenario"], events, k8s, oracle, dep, res)
    for rep, d in pe.items(): res["per_replica"][rep].update(d)
    res.update(pr); res["run_id"] = meta["run_id"]; res["kind"] = meta["kind"]
    json.dump(res, open(os.path.join(rd, "summary.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1))
