#!/usr/bin/env python3
"""In-cluster collector / experiment driver for Milestone 2-A (REAL Kubernetes).

One process, one clock (CLOCK_MONOTONIC): it injects faults through the API, watches Pods and EndpointSlices,
and generates all transaction streams, so every timestamp is comparable without cross-machine clock sync.

  run        run scenarios x arms x reps, write raw data per run (M1-compatible files + Kubernetes watch rows)
  preflight  verify API permissions, workloads and the dependency, then exit

Timestamps recorded (all collector monotonic ns): T_fault (just before the fault API call is sent), pod Created/Running/
ContainerReady/PodReady *as received on the watch*, T_endpoint_available/removed (EndpointSlice watch), streams G/U/static/D.
Pod condition lastTransitionTime and container startedAt are kept as raw strings (1 s resolution, node clock) and are NOT used
for sub-second claims."""
import argparse, copy, csv, http.client, json, os, platform, socket, sys, threading, time, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "application"))
from client import Stream
from kube import Kube, Recorder
from observer import Observer

SC_AFFECTED = {"app-degrade": ["r0.1"], "pod-replace": ["r0.2"],
               "dep-restart": ["r0.1", "r1.1"], "replace-during-dep": ["r0.2", "r1.1"]}
REPLACEMENT = {"pod-replace", "replace-during-dep"}
HDR = ["stream", "seq", "t_send_ns", "latency_ns", "status", "cls", "valid", "replica", "detail"]


def pod_view(o):
    st, md, sp = o.get("status", {}), o["metadata"], o.get("spec", {})
    conds = {c["type"]: c for c in st.get("conditions", [])}
    cs = (st.get("containerStatuses") or [{}])[0]
    run = (cs.get("state") or {}).get("running") or {}
    return {"name": md["name"], "phase": st.get("phase", ""), "ip": st.get("podIP", ""),
            "container_ready": bool(cs.get("ready", False)), "restarts": cs.get("restartCount", 0),
            "pod_ready": conds.get("Ready", {}).get("status") == "True",
            "ltt_ready": conds.get("Ready", {}).get("lastTransitionTime", ""),
            "started_at": run.get("startedAt", ""), "running": bool(run),
            "deleting": bool(md.get("deletionTimestamp")), "node": sp.get("nodeName", ""),
            "app": md.get("labels", {}).get("app", ""), "arm_dep": md.get("labels", {}).get("rfg-deployment", ""),
            "created": md.get("creationTimestamp", "")}


class DStream(threading.Thread):
    """Dependency PING stream (stream D): is the dependency itself answering? PONG only; -LOADING/refused/timeouts invalid."""
    def __init__(self, host, port, hz=10):
        super().__init__(daemon=True); self.host, self.port, self.hz = host, port, hz
        self.records = []; self.stop_ev = threading.Event()

    def one(self, seq):
        t0 = time.monotonic_ns(); cls, det = "conn_error", "exception"
        try:
            s = socket.create_connection((self.host, self.port), timeout=0.5)
            s.settimeout(0.5); s.sendall(b"PING\n")
            r = s.recv(64); s.close()
            if r.startswith(b"PONG"): cls, det = "ok", "PONG"
            elif r.startswith(b"-LOADING"): cls, det = "loading", "-LOADING"
            else: cls, det = "http_error", r[:20].decode("utf-8", "replace")
        except Exception as e:
            det = type(e).__name__
        lat = time.monotonic_ns() - t0
        return ("D:store", seq, t0, lat, 200 if cls == "ok" else 0, cls, cls == "ok", "store", det)

    def run(self):
        nxt, seq = time.monotonic(), 0
        while not self.stop_ev.is_set():
            self.records.append(self.one(seq)); seq += 1
            nxt += 1.0 / self.hz; d = nxt - time.monotonic()
            if d > 0 and self.stop_ev.wait(d): return
            if d < -1.0: nxt = time.monotonic()

    def stop(self): self.stop_ev.set()


class Cluster:
    """Watchers + state. Lives for the whole collector process."""
    def __init__(self, kube, ns, svc, store_svc):
        self.k, self.ns, self.svc, self.store_svc = kube, ns, svc, store_svc
        self.rec = Recorder()            # k8s watch rows
        self.pods = {}                   # name -> view
        self.ep_ready = {}               # pod name -> bool (as seen in EndpointSlices for the app Service)
        self.slice_pods = {}             # slice name -> {pod: ready}
        self.lock = threading.RLock(); self.listeners = []
        self.stop = threading.Event()

    def start(self):
        sel = urllib.parse.quote("app in (rfg-app,rfg-store)")
        esl = urllib.parse.quote(f"kubernetes.io/service-name={self.svc}")
        threading.Thread(target=self.k.watch, args=(f"/api/v1/namespaces/{self.ns}/pods", self._pod, self.stop, sel), daemon=True).start()
        threading.Thread(target=self.k.watch, args=(f"/apis/discovery.k8s.io/v1/namespaces/{self.ns}/endpointslices", self._es, self.stop, esl), daemon=True).start()

    def _pod(self, typ, obj, tm, tw):
        v = pod_view(obj)
        with self.lock:
            prev = self.pods.get(v["name"])
            if typ == "DELETED": self.pods.pop(v["name"], None)
            else: self.pods[v["name"]] = v
        self.rec.add((tm, tw, "pod", typ, v["name"], v["app"], v["phase"], v["ip"], int(v["running"]), int(v["container_ready"]),
                      int(v["pod_ready"]), v["ltt_ready"], v["started_at"], int(v["deleting"]), v["node"], v["restarts"], ""))
        for f in list(self.listeners):
            f(typ, v, prev, tm)

    def _es(self, typ, obj, tm, tw):
        name = obj["metadata"]["name"]; eps = []
        for e in obj.get("endpoints") or []:
            c = e.get("conditions", {}); ref = (e.get("targetRef") or {}).get("name", "")
            eps.append({"pod": ref, "ready": c.get("ready", True) is not False, "serving": c.get("serving", True) is not False,
                        "terminating": bool(c.get("terminating", False))})
        with self.lock:
            if typ == "DELETED": self.slice_pods.pop(name, None)
            else: self.slice_pods[name] = {e["pod"]: e["ready"] for e in eps}
            agg = {}
            for d in self.slice_pods.values():
                for p, r in d.items(): agg[p] = agg.get(p, False) or r
            changed = {p: r for p, r in agg.items() if self.ep_ready.get(p) != r} | {p: False for p in self.ep_ready if p not in agg and self.ep_ready[p]}
            self.ep_ready = agg
        self.rec.add((tm, tw, "endpointslice", typ, name, "", "", "", 0, 0, 0, "", "", 0, "", 0, json.dumps(eps)))
        for p, r in changed.items():
            self.rec.add((tm, tw, "endpoint", "READY" if r else "NOTREADY", p, "", "", "", 0, 0, int(r), "", "", 0, "", 0, name))


class K8sRun:
    def __init__(self, cl, cfg, scenario, arm, rep, rd):
        self.cl, self.cfg, self.scenario, self.arm, self.rep, self.rd = cl, cfg, scenario, arm, rep, rd
        self.k = cl.k; self.ns = cl.ns; self.kc = cfg["k8s"]
        self.events, self.obs_events, self.trans = [], [], {}
        self.logical, self.g, self.obs = {}, {}, {}
        self.run_id = f"{scenario}__{arm}__{rep:02d}"
        self.lk = threading.RLock(); self.n_extra = 0; self.notes = []

    def ev(self, name, replica="", detail="", t=None):
        self.events.append((t or time.monotonic_ns(), name, replica, detail))

    def snapshot_pods(self, t):
        """k8s_events must show the state of pods that already exist at run start (e.g. the store), not only later changes"""
        with self.cl.lock: snap = list(self.cl.pods.values())
        for v in snap:
            self.cl.rec.add((t, time.time_ns(), "pod", "SNAPSHOT", v["name"], v["app"], v["phase"], v["ip"], int(v["running"]), int(v["container_ready"]),
                             int(v["pod_ready"]), v["ltt_ready"], v["started_at"], int(v["deleting"]), v["node"], v["restarts"], ""))

    def note(self, s):
        self.notes.append((time.monotonic_ns(), s)); self.ev("NOTE", detail=s)

    # ---- pod bookkeeping (watch callback) -----------------------------------------------------------
    def on_pod(self, typ, v, prev, tm):
        if v["app"] == "rfg-store":
            if typ == "DELETED": self.ev("dep_pod_deleted", "store", t=tm)
            elif prev is None or (prev["pod_ready"] != v["pod_ready"]) or (prev["running"] != v["running"]):
                self.ev("dep_pod_" + ("ready" if v["pod_ready"] else ("running" if v["running"] else "pending")), "store", t=tm)
            return
        if v["app"] != "rfg-app": return
        with self.lk:
            lg = self.logical.get(v["name"])
            if lg is None and typ != "DELETED" and getattr(self, "armed", False):
                lg = self.assign(v)
            if lg is None: return
            tr = self.trans.setdefault(lg, [])
            if prev is not None and prev["restarts"] != v["restarts"]:
                self.note(f"unexpected container restart of {lg} ({v['name']}): {prev['restarts']}->{v['restarts']}")
            if typ == "DELETED":
                if not tr or tr[-1][1]: tr.append((tm, False, "deleted"))
                self.stop_stream(lg); return
            if prev is None and not tr: tr.append((tm, False, "created"))
            if v["pod_ready"] != (tr[-1][1] if tr else False) and tr:
                tr.append((tm, v["pod_ready"], "watch"))
            elif not tr: tr.append((tm, v["pod_ready"], "watch"))
            if v["ip"] and lg not in self.g and not v["deleting"]: self.start_stream(lg, v)
            if v["pod_ready"] and self.arm == "C" and lg not in self.obs and v["ip"]:
                o = Observer(lg, self.kc["app_port"], self.cfg["observer"]["hz"], self.cfg["observer"]["n"], self.cfg["cache_keys"],
                             self.run_id, self.obs_events, host=v["ip"])
                self.obs[lg] = o; o.start()

    def assign(self, v):
        pending = getattr(self, "replacements", [])
        if self.scenario in REPLACEMENT and pending:
            lg = pending.pop(0)
        else:
            self.n_extra += 1; lg = f"x{self.n_extra}.1"
            self.note(f"unexpected extra app pod {v['name']} -> {lg}")
        self.logical[v["name"]] = lg; self.ev("pod_map", lg, v["name"]); return lg

    def start_stream(self, lg, v):
        s = Stream("G:" + lg, "tx", self.cfg["oracle_hz"], self.kc["app_port"], self.cfg["cache_keys"], self.run_id, host=v["ip"])
        self.g[lg] = s; s.start()

    def stop_stream(self, lg):
        s = self.g.get(lg)
        if s: s.stop()
        o = self.obs.get(lg)
        if o: o.stop()

    # ---- cluster state helpers -------------------------------------------------------------------------
    def app_pods(self): 
        with self.cl.lock: return {n: v for n, v in self.cl.pods.items() if v["app"] == "rfg-app"}

    def store_ok(self):
        with self.cl.lock: sp = [v for v in self.cl.pods.values() if v["app"] == "rfg-store"]
        return len(sp) == 1 and sp[0]["pod_ready"] and not sp[0]["deleting"] and DStream(self.kc["store_host"], self.kc["store_port"]).one(0)[6]

    def wait(self, cond, timeout, what):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if cond(): return
            time.sleep(0.1)
        raise RuntimeError("timeout waiting for " + what)

    def prepare(self):
        dep = self.kc["deployments"]; target = dep[self.arm]
        for d in set(dep.values()):
            self.k.scale(self.ns, d, 0)
        self.wait(lambda: not self.app_pods(), 120, "all app pods gone")
        self.wait(self.store_ok, 180, "dependency Ready and functional")
        st = self.k.scale(self.ns, target, self.cfg["replicas"])[0]
        if st not in (200, 201): raise RuntimeError(f"scale failed {st}")
        self.wait(lambda: len([p for p in self.app_pods().values() if p["pod_ready"] and not p["deleting"]]) == self.cfg["replicas"]
                  and len(self.app_pods()) == self.cfg["replicas"], 180, "app pods Ready")

    def settled(self, t_fault, affected):
        if time.monotonic_ns() - t_fault < self.cfg["min_post_s"] * 1e9: return False
        for lg in affected:
            s = self.g.get(lg)
            if s is None or not s.recent_valid(40): return False
        ap = self.app_pods()
        return (self.tx.recent_valid(40) and self.static.recent_valid(20) and ap and
                all(p["pod_ready"] for p in ap.values()) and self.cl.ep_ready and
                all(self.cl.ep_ready.get(n) for n in ap))

    # ---- execution ------------------------------------------------------------------------------------------
    def execute(self):
        cfg, sc, kc = self.cfg, self.scenario, self.kc
        t_run0 = time.monotonic_ns(); self.t_run0 = t_run0     # k8s_events.csv keeps EVERY watch row from here on
        self.armed = False
        self.snapshot_pods(t_run0)
        self.prepare()
        self.dstream = DStream(kc["store_host"], kc["store_port"], kc.get("d_hz", 10)); self.dstream.start()
        # logical names for the initial replicas: r0.1 / r1.1 in sorted pod-name order; snapshot their current state
        self.cl.listeners.append(self.on_pod)
        with self.lk:
            for i, n in enumerate(sorted(self.app_pods())):
                lg = f"r{i}.1"; self.logical[n] = lg; self.ev("pod_map", lg, n)
                v = self.cl.pods[n]; self.trans[lg] = [(time.monotonic_ns(), v["pod_ready"], "snapshot")]
                if v["ip"]: self.start_stream(lg, v)
                if v["pod_ready"] and self.arm == "C" and v["ip"]:
                    o = Observer(lg, kc["app_port"], cfg["observer"]["hz"], cfg["observer"]["n"], cfg["cache_keys"], self.run_id,
                                 self.obs_events, host=v["ip"]); self.obs[lg] = o; o.start()
            self.replacements = ["r0.2"] if sc in ("pod-replace", "replace-during-dep") else []
            self.armed = True
        self.tx = Stream("tx", "tx", cfg["user"]["tx_hz"], kc["service_port"], cfg["cache_keys"], self.run_id, host=kc["service_host"])
        self.static = Stream("static", "static", cfg["user"]["static_hz"], kc["service_port"], cfg["cache_keys"], self.run_id, host=kc["service_host"])
        self.tx.start(); self.static.start()
        self.wait(lambda: all(self.g.get(l) and self.g[l].recent_valid(40) for l in ("r0.1", "r1.1")) and self.tx.recent_valid(40)
                  and self.static.recent_valid(20) and self.dstream.records and self.dstream.records[-1][6], 120, "steady state")
        self.ev("steady"); time.sleep(cfg["steady_hold_s"])
        sp = cfg["scenario_params"]; t_fault = time.monotonic_ns(); self.ev("fault", t=t_fault)
        vict = next(n for n, l in self.logical.items() if l == "r0.1"); vip = self.cl.pods[vict]["ip"]
        if sc == "app-degrade":
            self.post(vip, "/admin/degrade"); time.sleep(sp["degrade_hold_s"]); self.post(vip, "/admin/recover"); self.ev("recover", "r0.1")
        elif sc == "pod-replace":
            st, _, t0, t1 = self.k.delete_pod(self.ns, vict, 0); self.ev("kill_api", "r0.1", f"status={st} sent={t0} done={t1}", t=t1); self.ev("kill", "r0.1", t=t1)
        elif sc == "dep-restart":
            st, _, t0, t1 = self.k.delete_pod(self.ns, kc["store_pod"], 0); self.ev("dep_kill", "store", f"status={st} sent={t0}", t=t1)
        elif sc == "replace-during-dep":
            st, _, t0, t1 = self.k.delete_pod(self.ns, kc["store_pod"], 0); self.ev("dep_kill", "store", f"status={st} sent={t0}", t=t1)
            st, _, t0, t1 = self.k.delete_pod(self.ns, vict, 0); self.ev("kill_api", "r0.1", f"status={st} sent={t0} done={t1}", t=t1); self.ev("kill", "r0.1", t=t1)
        deadline = time.time() + cfg["max_post_s"]; aff = SC_AFFECTED[sc]
        while time.time() < deadline and not self.settled(t_fault, aff): time.sleep(0.25)
        if time.time() >= deadline: self.note("max_post_s reached before settled criterion")
        time.sleep(cfg["tail_s"]); self.ev("end")
        self.collect_stats()
        self.finish()

    def post(self, ip, path):
        try:
            c = http.client.HTTPConnection(ip, self.kc["app_port"], timeout=3); c.request("POST", path, body=b"{}"); c.getresponse().read(); c.close()
        except Exception as e:
            self.note(f"POST {path} to {ip} failed: {e!r}")

    def collect_stats(self):
        st = {"probe_requests": 0, "dep_ops_probe": 0, "observer_requests": 0}
        for n, v in self.app_pods().items():
            try:
                c = http.client.HTTPConnection(v["ip"], self.kc["app_port"], timeout=2); c.request("GET", "/admin/stats")
                j = json.loads(c.getresponse().read()); c.close()
                st["probe_requests"] += j["probe_requests"]; st["dep_ops_probe"] += j["dep_ops_probe"]
            except Exception: pass
        st["observer_requests"] = sum(len(o.records) for o in self.obs.values())
        self.stats = st

    def finish(self):
        for s in [self.tx, self.static, self.dstream] + list(self.g.values()) + list(self.obs.values()): s.stop()
        time.sleep(0.3)
        if self.on_pod in self.cl.listeners: self.cl.listeners.remove(self.on_pod)
        self.k.scale(self.ns, self.kc["deployments"][self.arm], 0)

    def write(self):
        rd = self.rd
        def w(name, header, rows):
            with open(os.path.join(rd, name), "w", newline="") as f:
                cw = csv.writer(f); cw.writerow(header); cw.writerows(rows)
        w("events.csv", ["t_ns", "name", "replica", "detail"], sorted(self.events))
        w("probe_transitions.csv", ["t_ns", "replica", "ready", "detail"],
          [(t, n, r, d) for n, tr in self.trans.items() for t, r, d in tr])
        w("probe_log.csv", ["t_ns", "replica", "ok", "latency_ns", "detail"], [])   # kubelet probe log is not observable from the API
        w("user.csv", HDR, self.tx.records + self.static.records)
        w("oracle.csv", HDR, [x for s in self.g.values() for x in s.records])
        w("dependency.csv", HDR, self.dstream.records)
        w("observer_raw.csv", HDR, [x for o in self.obs.values() for x in o.records])
        w("observer_events.csv", ["t_ns", "replica", "event"], sorted(self.obs_events))
        t0 = getattr(self, "t_run0", None) or (min(e[0] for e in self.events) - int(60e9)); t1 = max(e[0] for e in self.events) + int(5e9)
        w("k8s_events.csv", ["t_mono_ns", "t_wall_ns", "kind", "type", "name", "app", "phase", "pod_ip", "running", "container_ready",
                              "pod_ready", "ltt_ready", "started_at", "deleting", "node", "restarts", "detail"],
          [r for r in self.cl.rec.snapshot() if t0 <= r[0] <= t1])
        json.dump(self.stats, open(os.path.join(rd, "stats.json"), "w"))
        cfg = copy.deepcopy(self.cfg)
        cfg["_run"] = {"run_id": self.run_id, "scenario": self.scenario, "arm": self.arm, "rep": self.rep, "python": platform.python_version(),
                       "platform": platform.platform(), "kind": "REAL KUBERNETES (Kind) - in-cluster collector",
                       "wall_start": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "notes": self.notes}
        json.dump(cfg, open(os.path.join(rd, "config.json"), "w"), indent=1)


def run_one(cl, cfg, scenario, arm, rep, out):
    rd = os.path.join(out, f"{scenario}__{arm}__{rep:02d}"); os.makedirs(rd, exist_ok=True)
    r = K8sRun(cl, cfg, scenario, arm, rep, rd)
    try:
        r.execute()
    except Exception as e:
        r.ev("ABORT", detail=repr(e))
        try: r.stats = {}; r.finish() if hasattr(r, "tx") else None
        except Exception: pass
        open(os.path.join(rd, "ABORTED.txt"), "w").write(repr(e))
        # preserve whatever raw data exists (never discard a run)
        try:
            for a in ("tx", "static", "dstream"):
                if not hasattr(r, a): setattr(r, a, type("E", (), {"records": []})())
            r.stats = getattr(r, "stats", {}); r.write()
        except Exception: pass
        return None
    r.write(); return r


def make_cluster(cfg, kube=None):
    kc = cfg["k8s"]
    cl = Cluster(kube or Kube(), kc["namespace"], kc["service_name"], kc["store_service"]); cl.start()
    t0 = time.time()
    while time.time() - t0 < 30 and not (cl.pods and True): time.sleep(0.1)
    time.sleep(1.0)
    return cl


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--config", default="/config/k8s-baseline.json")
    r.add_argument("--scenarios", default="app-degrade,pod-replace,dep-restart,replace-during-dep"); r.add_argument("--arms", default="A,B,C")
    r.add_argument("--reps", type=int, default=5); r.add_argument("--rep-start", type=int, default=1); r.add_argument("--out", default="/results/run")
    p = sub.add_parser("preflight"); p.add_argument("--config", default="/config/k8s-baseline.json")
    a = ap.parse_args(); cfg = json.load(open(a.config)); kc = cfg["k8s"]
    cl = make_cluster(cfg)
    if a.cmd == "preflight":
        probe = K8sRun(cl, cfg, "app-degrade", "A", 0, "/tmp")
        print("pods seen:", sorted(cl.pods)); print("store functional:", probe.store_ok())
        for d in set(kc["deployments"].values()):
            print(d, "scale GET:", cl.k.request("GET", f"/apis/apps/v1/namespaces/{cl.ns}/deployments/{d}/scale")[0])
        return
    os.makedirs(a.out, exist_ok=True); json.dump(cfg, open(os.path.join(a.out, "experiment_config.json"), "w"), indent=1)
    for rep in range(a.rep_start, a.rep_start + a.reps):
        for sc in a.scenarios.split(","):
            for arm in a.arms.split(","):
                t0 = time.time(); res = run_one(cl, cfg, sc, arm, rep, a.out)
                print(f"{sc:20s} arm={arm} rep={rep} {'ABORTED' if res is None else 'ok'} {time.time()-t0:.1f}s", flush=True)
                time.sleep(1.0)


if __name__ == "__main__":
    main()
