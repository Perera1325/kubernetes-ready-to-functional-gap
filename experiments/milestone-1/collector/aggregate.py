"""Aggregate all results/*/summary.json into results/aggregate.csv + aggregate.md (descriptive only)."""
import csv, glob, json, os, statistics, sys

METRICS = ["rfg_observe_max_s", "ready_nonfunctional_s", "false_notready_s", "tx_error_duration_s",
           "tx_invalid_business", "tx_no_endpoints", "tx_conn_error", "static_error_duration_s",
           "zero_endpoint_s", "probe_requests", "dep_ops_probe"]


def q(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return "n/a"
    return f"{statistics.median(v):.2f} [{v[0]:.2f}-{v[-1]:.2f}]"


def main(resdir):
    runs = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(resdir, "*", "summary.json")))]
    groups = {}
    for r in runs:
        groups.setdefault((r["scenario"], r["arm"]), []).append(r)
    with open(os.path.join(resdir, "aggregate.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "arm", "n", "n_recovered_all", "pre_fault_invalid_total"] + METRICS)
        for (s, a), rs in sorted(groups.items()):
            w.writerow([s, a, len(rs), sum(1 for r in rs if r["replicas_recovered"] and r["tx_recovered"]),
                        sum(r["pre_fault_invalid_G"] + r["pre_fault_invalid_U"] for r in rs)] +
                       [q([r.get(m) for r in rs]) for m in METRICS])
    with open(os.path.join(resdir, "aggregate.md"), "w") as f:
        f.write("Median [min-max] per cell. Descriptive only; small n; LOCAL SIMULATION (no Kubernetes).\n\n")
        f.write("| scenario | arm | n | recovered | " + " | ".join(METRICS) + " |\n|" + "---|" * (len(METRICS) + 4) + "\n")
        for (s, a), rs in sorted(groups.items()):
            rec = sum(1 for r in rs if r["replicas_recovered"] and r["tx_recovered"])
            f.write(f"| {s} | {a} | {len(rs)} | {rec} | " + " | ".join(q([r.get(m) for r in rs]) for m in METRICS) + " |\n")
    return len(runs)


if __name__ == "__main__":
    print(main(sys.argv[1]), "runs aggregated")
