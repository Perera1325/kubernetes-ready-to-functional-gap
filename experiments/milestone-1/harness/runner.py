#!/usr/bin/env python3
"""Run one or many experiments. LOCAL SIMULATION: real OS processes (dependency store, app replicas),
kubelet-semantics probe emulation, Service emulation. Not Kubernetes.
usage: runner.py --config C --scenarios a,b --arms A,B,C --reps N --out results/DIR"""
import argparse, copy, csv, json, os, platform, shutil, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in ("application", "fault-injector", "transaction-client", "collector", "harness"):
    sys.path.insert(0, os.path.join(ROOT, d))
import analyze, inject
from client import Stream
from observer import Observer
from prober import Prober, http_probe
from router import Router

PY = sys.executable
DEP_PORT, ROUTER_PORT = 27001, 27002


class Replica:
    pass


class Run:
    def __init__(self, cfg, scenario, arm, rep, rd, wal_base, seed):
        self.cfg, self.scenario, self.arm, self.rep, self.rd, self.seed = cfg, scenario, arm, rep, rd, seed
        self.wal_base = wal_base
        self.events, self.obs_events = [], []
        self.replicas = {}          # name -> Replica
        self.port_ctr = 27010
        self.dep = None
        self.obs_started = set()
        self.run_id = f"{scenario}__{arm}__{rep:02d}"

    def ev(self, name, replica="", detail="", t=None):
        self.events.append((t or time.monotonic_ns(), name, replica, detail))

    # ---- processes
    def start_dep(self):
        loaded = os.path.join(self.rd, "dep_loaded.txt")
        if os.path.exists(loaded):
            os.remove(loaded)
        self.dep = subprocess.Popen([PY, os.path.join(ROOT, "application/store.py"), "--port", str(DEP_PORT),
                                     "--wal", os.path.join(self.rd, "store.wal"), "--loaded-file", loaded],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ev("dep_launch")
        threading.Thread(target=self._watch_loaded, args=(loaded,), daemon=True).start()

    def _watch_loaded(self, path):
        while not os.path.exists(path) or not open(path).read().strip():
            time.sleep(0.02)
            if self.dep.poll() is not None:
                return
        t = int(open(path).read().split()[0])
        self.ev("dep_loaded", t=t)

    def wait_dep_loaded(self, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if any(e[1] == "dep_loaded" for e in self.events):
                return
            time.sleep(0.05)
        raise RuntimeError("dependency did not load")

    def launch(self, rid, inc):
        cfg, name = self.cfg, f"{rid}.{inc}"
        r = Replica(); r.name, r.rid = name, rid
        self.port_ctr += 1; r.port = self.port_ctr
        marker = os.path.join(self.rd, f"marker_{name}")
        t_launch = time.monotonic_ns()
        r.proc = subprocess.Popen([PY, os.path.join(ROOT, "application/app.py"), "--port", str(r.port),
                                   "--dep-port", str(DEP_PORT), "--replica", name, "--marker", marker,
                                   "--cache-keys", str(cfg["cache_keys"]),
                                   "--backoff-base", str(cfg["app"]["backoff_base_s"]),
                                   "--backoff-cap", str(cfg["app"]["backoff_cap_s"])],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ev("replica_launch", name, t=t_launch)
        path = "/healthz/deep" if self.arm == "B" else "/healthz/shallow"
        p = cfg["probe"]
        r.prober = Prober(name, lambda: http_probe(r.port, path, p["timeout_s"]), p["period_s"],
                          p["failure_threshold"], p["success_threshold"], p["initial_delay_s"],
                          seed=self.seed * 1000 + hash(name) % 997, on_transition=self._on_ready)
        r.prober.transitions[0] = (t_launch, False, "launch")
        r.oracle = Stream("G:" + name, "tx", cfg["oracle_hz"], r.port, cfg["cache_keys"], self.run_id)
        r.observer = None
        self.replicas[name] = r
        r.prober.start(); r.oracle.start()
        for _ in range(200):
            if os.path.exists(marker) and open(marker).read().strip():
                self.ev("app_listen", name, t=int(open(marker).read())); break
            time.sleep(0.02)
        return r

    def _on_ready(self, name, ready, t):
        self.ev("ready" if ready else "notready", name, t=t)
        if ready and self.arm == "C" and name not in self.obs_started:
            self.obs_started.add(name)
            r = self.replicas[name]
            r.observer = Observer(name, r.port, self.cfg["observer"]["hz"], self.cfg["observer"]["n"],
                                  self.cfg["cache_keys"], self.run_id, self.obs_events)
            r.observer.start()

    def kill_replica(self, name):
        r = self.replicas[name]
        inject.kill(r.proc)
        self.ev("kill", name)
        r.oracle.stop()
        if r.observer:
            r.observer.stop()

    def alive(self):
        return [r for r in self.replicas.values() if r.proc.poll() is None]

    # ---- helpers
    def ready_eps(self):
        return [(r.name, r.port) for r in self.replicas.values() if r.prober.ready]

    def settled(self, t_fault, affected):
        if time.monotonic_ns() - t_fault < self.cfg["min_post_s"] * 1e9:
            return False
        for n in affected:
            r = self.replicas.get(n)
            if r is None or not r.oracle.recent_valid(40):
                return False
        return (self.tx.recent_valid(40) and self.static.recent_valid(20) and
                all(r.prober.ready for r in self.alive()))

    def execute(self):
        cfg, sc = self.cfg, self.scenario
        sp = cfg["scenario_params"]
        shutil.copy(self.wal_base, os.path.join(self.rd, "store.wal"))
        self.start_dep(); self.wait_dep_loaded()
        for i in range(cfg["replicas"]):
            self.launch(f"r{i}", 1)
        self.router = Router(self.ready_eps, ROUTER_PORT); self.router.start()
        self.tx = Stream("tx", "tx", cfg["user"]["tx_hz"], ROUTER_PORT, cfg["cache_keys"], self.run_id)
        self.static = Stream("static", "static", cfg["user"]["static_hz"], ROUTER_PORT, cfg["cache_keys"], self.run_id)
        self.tx.start(); self.static.start()
        # steady state
        t0 = time.time()
        while time.time() - t0 < 90:
            if (all(r.prober.ready and r.oracle.recent_valid(40) for r in self.alive())
                    and self.tx.recent_valid(40) and self.static.recent_valid(20)):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("no steady state")
        self.ev("steady")
        time.sleep(cfg["steady_hold_s"])
        t_fault = time.monotonic_ns(); self.ev("fault")
        affected = analyze.AFFECTED[sc]
        if sc == "app-degrade":
            inject.degrade_app(self.replicas["r0.1"].port)
            time.sleep(sp["degrade_hold_s"])
            inject.recover_app(self.replicas["r0.1"].port); self.ev("recover", "r0.1")
        elif sc == "pod-replace":
            self.kill_replica("r0.1"); self.launch("r0", 2)
        elif sc == "dep-restart":
            inject.kill(self.dep); self.ev("dep_kill")
            time.sleep(sp["dep_downtime_s"]); self.start_dep()
        elif sc == "replace-during-dep":
            inject.kill(self.dep); self.ev("dep_kill"); self.kill_replica("r0.1")
            time.sleep(sp["dep_downtime_s"]); self.start_dep(); self.launch("r0", 2)
        deadline = time.time() + cfg["max_post_s"]
        while time.time() < deadline and not self.settled(t_fault, affected):
            time.sleep(0.25)
        time.sleep(cfg["tail_s"])
        self.ev("end")
        self.collect_stats()
        self.stop_all()

    def collect_stats(self):
        import http.client
        st = {"probe_requests": 0, "dep_ops_probe": 0, "app_cpu_s": 0.0, "observer_requests": 0}
        tck = os.sysconf("SC_CLK_TCK")
        for r in self.replicas.values():
            if r.proc.poll() is not None:
                continue
            try:
                c = http.client.HTTPConnection("127.0.0.1", r.port, timeout=2)
                c.request("GET", "/admin/stats"); j = json.loads(c.getresponse().read()); c.close()
                st["probe_requests"] += j["probe_requests"]; st["dep_ops_probe"] += j["dep_ops_probe"]
                f = open(f"/proc/{r.proc.pid}/stat").read().rsplit(")", 1)[1].split()
                st["app_cpu_s"] += (int(f[11]) + int(f[12])) / tck
            except Exception:
                pass
            if r.observer:
                st["observer_requests"] += len(r.observer.records)
        self.stats = st

    def stop_all(self):
        for s in (self.tx, self.static):
            s.stop()
        for r in self.replicas.values():
            r.prober.stop(); r.oracle.stop()
            if r.observer:
                r.observer.stop()
        time.sleep(0.3)
        self.router.stop()
        for r in self.replicas.values():
            inject.kill(r.proc)
        if self.dep and self.dep.poll() is None:
            inject.kill(self.dep)

    def write(self):
        rd = self.rd
        def w(name, header, rows):
            with open(os.path.join(rd, name), "w", newline="") as f:
                cw = csv.writer(f); cw.writerow(header); cw.writerows(rows)
        w("events.csv", ["t_ns", "name", "replica", "detail"], sorted(self.events))
        w("probe_transitions.csv", ["t_ns", "replica", "ready", "detail"],
          [(t, n, rd_, d) for n, r in self.replicas.items() for t, rd_, d in r.prober.transitions])
        w("probe_log.csv", ["t_ns", "replica", "ok", "latency_ns", "detail"],
          [(t, n, ok, l, d) for n, r in self.replicas.items() for t, ok, l, d in r.prober.log])
        hdr = ["stream", "seq", "t_send_ns", "latency_ns", "status", "cls", "valid", "replica", "detail"]
        w("user.csv", hdr, self.tx.records + self.static.records)
        w("oracle.csv", hdr, [x for r in self.replicas.values() for x in r.oracle.records])
        w("observer_raw.csv", hdr, [x for r in self.replicas.values() if r.observer for x in r.observer.records])
        w("observer_events.csv", ["t_ns", "replica", "event"], sorted(self.obs_events))
        json.dump(self.stats, open(os.path.join(rd, "stats.json"), "w"))
        cfg = copy.deepcopy(self.cfg)
        cfg["_run"] = {"run_id": self.run_id, "scenario": self.scenario, "arm": self.arm, "rep": self.rep,
                       "seed": self.seed, "python": platform.python_version(), "platform": platform.platform(),
                       "cpus": os.cpu_count(), "kind": "LOCAL SIMULATION (no Kubernetes)",
                       "wall_start": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        json.dump(cfg, open(os.path.join(rd, "config.json"), "w"), indent=1)


def run_one(cfg, scenario, arm, rep, outdir, wal_base, seed):
    rd = os.path.join(outdir, f"{scenario}__{arm}__{rep:02d}")
    shutil.rmtree(rd, ignore_errors=True); os.makedirs(rd)
    r = Run(cfg, scenario, arm, rep, rd, wal_base, seed)
    try:
        r.execute()
    except Exception as e:
        r.ev("ABORT", detail=repr(e))
        try:
            r.stats = {}; r.stop_all()
        except Exception:
            pass
        open(os.path.join(rd, "ABORTED.txt"), "w").write(repr(e))
        return None
    r.write()
    return analyze.main(rd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(ROOT, "configs/baseline.json"))
    ap.add_argument("--scenarios", default="app-degrade,pod-replace,dep-restart,replace-during-dep")
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--rep-start", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(ROOT, "results/run1"))
    ap.add_argument("--wal-dir", default="/tmp/rfg_wal")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    os.makedirs(a.out, exist_ok=True); os.makedirs(a.wal_dir, exist_ok=True)
    wal = os.path.join(a.wal_dir, f"base_{cfg['store']['items']}_{cfg['store']['fill']}.wal")
    if not os.path.exists(wal):
        subprocess.check_call([PY, os.path.join(ROOT, "application/store.py"), "--port", "1", "--wal", wal,
                               "--loaded-file", "/dev/null", "--make-wal", str(cfg["store"]["items"]), str(cfg["store"]["fill"])])
    shutil.copy(a.config, os.path.join(a.out, "experiment_config.json"))
    # interleave arms within each repetition to spread drift across arms
    for rep in range(a.rep_start, a.rep_start + a.reps):
        for sc in a.scenarios.split(","):
            for arm in a.arms.split(","):
                t0 = time.time()
                res = run_one(cfg, sc, arm, rep, a.out, wal, seed=rep)
                print(f"{sc:20s} arm={arm} rep={rep} {'ABORTED' if res is None else 'ok'} {time.time()-t0:.1f}s", flush=True)
                time.sleep(0.5)


if __name__ == "__main__":
    main()
