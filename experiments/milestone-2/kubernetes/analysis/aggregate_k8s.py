"""Aggregate REAL-Kubernetes summaries -> aggregate.csv/.md (descriptive only: median [min-max], n small, no significance claims).
Never reads Milestone-1 data unless --compare-m1 is given, and then writes a SEPARATE comparison file; simulation and real
numbers are never mixed in one table row."""
import argparse, csv, glob, json, os, statistics

METRICS = ["rfg_observe_max_s", "rfg_endpoint_max_s", "ready_nonfunctional_s", "false_notready_s", "tx_error_duration_s", "tx_invalid_business",
           "tx_conn_error", "static_error_duration_s", "zero_endpoint_s", "dep_unavailable_s"]


def q(v):
    v = sorted(x for x in v if x is not None)
    return "n/a" if not v else f"{statistics.median(v):.2f} [{v[0]:.2f}-{v[-1]:.2f}] (n={len(v)})"


def flat(r):
    r = dict(r)
    ep = [d.get("rfg_endpoint_s") for d in r.get("per_replica", {}).values() if d.get("rfg_endpoint_s") is not None]
    r["rfg_endpoint_max_s"] = max(ep) if ep else None
    return r


def main(resdir):
    runs = [flat(json.load(open(p))) for p in sorted(glob.glob(os.path.join(resdir, "*", "summary.json")))]
    aborted = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(resdir, "*", "ABORTED.txt")))
    groups = {}
    for r in runs: groups.setdefault((r["scenario"], r["arm"]), []).append(r)
    with open(os.path.join(resdir, "aggregate.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scenario", "arm", "n", "n_recovered_all", "pre_fault_invalid_total"] + METRICS)
        for (s, a), rs in sorted(groups.items()):
            w.writerow([s, a, len(rs), sum(1 for r in rs if r["replicas_recovered"] and r["tx_recovered"]),
                        sum(r["pre_fault_invalid_G"] + r["pre_fault_invalid_U"] for r in rs)] + [q([r.get(m) for r in rs]) for m in METRICS])
    with open(os.path.join(resdir, "aggregate.md"), "w") as f:
        f.write("REAL KUBERNETES (Kind) runs. Median [min-max] per cell; descriptive only; small n; no significance claims.\n\n")
        f.write("| scenario | arm | n | recovered | " + " | ".join(METRICS) + " |\n|" + "---|" * (len(METRICS) + 4) + "\n")
        for (s, a), rs in sorted(groups.items()):
            rec = sum(1 for r in rs if r["replicas_recovered"] and r["tx_recovered"])
            f.write(f"| {s} | {a} | {len(rs)} | {rec} | " + " | ".join(q([r.get(m) for r in rs]) for m in METRICS) + " |\n")
        if aborted: f.write("\nABORTED runs (raw data preserved): " + ", ".join(aborted) + "\n")
    return len(runs), aborted


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("resdir"); a = ap.parse_args()
    print(main(a.resdir))
