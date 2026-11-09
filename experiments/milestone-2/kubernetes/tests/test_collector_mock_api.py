"""MOCK-API tests of the Milestone-2 collector plumbing. These do NOT exercise Kubernetes: the API server below is a ~80-line fake.
They verify: watch parsing/ordering/reconnect, fault-injection request shape, pod->logical-replica mapping, raw-file writing,
and that the analysis (M1 functions reused unchanged + k8s extras) computes the right numbers on a constructed run."""
import copy, csv, http.server, json, os, socketserver, sys, tempfile, threading, time, unittest, _path
SRC = _path.ROOT
sys.path.insert(0, SRC); sys.path.insert(0, os.path.join(SRC, "..", "analysis"))
import collector, kube, analyze_k8s, analyze_m1
CFG = json.load(open(os.path.join(SRC, "..", "configs", "k8s-baseline.json")))


class Mock:
    def __init__(self):
        self.log, self.events, self.rv, self.lock = [], [], 100, threading.Lock()
        self.initial = {"pods": [], "endpointslices": []}; self.drop_after = None
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def _json(self, code, obj):
                b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b)))
                self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
            def do_GET(self):
                p, _, q = self.path.partition("?"); kind = "pods" if p.endswith("/pods") else "endpointslices"
                if "watch=1" not in q:
                    return self._json(200, {"metadata": {"resourceVersion": str(outer.rv)}, "items": outer.initial[kind]})
                rv = int(q.split("resourceVersion=")[1].split("&")[0])
                self.send_response(200); self.send_header("Transfer-Encoding", "chunked"); self.send_header("Content-Type", "application/json"); self.end_headers()
                def chunk(o):
                    d = (json.dumps(o) + "\n").encode(); self.wfile.write(b"%x\r\n" % len(d) + d + b"\r\n"); self.wfile.flush()
                chunk({"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": str(rv)}}})
                sent, t0 = 0, time.time()
                while time.time() - t0 < 5:
                    with outer.lock: todo = [e for e in outer.events if e[0] > rv and e[1] == kind]
                    for e in todo:
                        chunk({"type": e[2], "object": e[3]}); rv = e[0]; sent += 1
                        if outer.drop_after and sent >= outer.drop_after:       # simulate a dropped watch connection
                            outer.drop_after = None; self.wfile.write(b"0\r\n\r\n"); self.close_connection = True; return
                    time.sleep(0.02)
                self.wfile.write(b"0\r\n\r\n"); self.close_connection = True
            def _body(self): return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            def do_DELETE(self):
                outer.log.append(("DELETE", self.path, self._body())); self._json(200, {"kind": "Status"})
            def do_PATCH(self):
                outer.log.append(("PATCH", self.path, self._body(), self.headers.get("Content-Type"))); self._json(200, {"kind": "Scale"})

        class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True
        self.srv = S(("127.0.0.1", 0), H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def push(self, kind, typ, obj):
        with self.lock:
            self.rv += 1; obj["metadata"]["resourceVersion"] = str(self.rv); self.events.append((self.rv, kind, typ, obj))

    def close(self): self.srv.shutdown(); self.srv.server_close()


def pod(name, app="rfg-app", ready=False, ip="10.0.0.1", running=True, restarts=0, deleting=False, ltt="2026-01-01T00:00:03Z"):
    md = {"name": name, "labels": {"app": app}, "creationTimestamp": "2026-01-01T00:00:00Z"}
    if deleting: md["deletionTimestamp"] = "2026-01-01T00:00:05Z"
    return {"metadata": md, "spec": {"nodeName": "w1"}, "status": {
        "phase": "Running", "podIP": ip, "conditions": [{"type": "Ready", "status": "True" if ready else "False", "lastTransitionTime": ltt}],
        "containerStatuses": [{"ready": ready, "restartCount": restarts, "state": {"running": {"startedAt": ltt}} if running else {"waiting": {}}}]}}


def eslice(pods):
    return {"metadata": {"name": "rfg-app-abc"}, "endpoints": [{"targetRef": {"name": n}, "conditions": {"ready": r}} for n, r in pods]}


def wait(cond, t=5):
    end = time.time() + t
    while time.time() < end:
        if cond(): return True
        time.sleep(0.02)
    return False


class TestWatch(unittest.TestCase):
    def test_list_watch_order_reconnect_and_endpoint_transitions(self):
        m = Mock(); m.initial["pods"] = [pod("store-0", "rfg-store", True), pod("a1", ready=True)]
        cl = collector.Cluster(kube.Kube("127.0.0.1", m.port, "http"), "rfg", "rfg-app", "rfg-store")
        try:
            cl.start()
            self.assertTrue(wait(lambda: len(cl.pods) == 2))
            m.drop_after = 1                                            # connection dropped after first event -> must resume without loss
            m.push("pods", "ADDED", pod("a2", ready=False, ip="10.0.0.2", running=False))
            m.push("pods", "MODIFIED", pod("a2", ready=True, ip="10.0.0.2"))
            m.push("endpointslices", "MODIFIED", eslice([("a1", True), ("a2", False)]))
            m.push("endpointslices", "MODIFIED", eslice([("a1", True), ("a2", True)]))
            m.push("pods", "DELETED", pod("a1", ready=True))
            self.assertTrue(wait(lambda: "a1" not in cl.pods and cl.ep_ready.get("a2") is True))
            rows = [r for r in cl.rec.snapshot() if r[2] == "pod" and r[4] == "a2"]
            self.assertEqual([r[3] for r in rows], ["ADDED", "MODIFIED"])           # none lost across the drop, order kept
            self.assertEqual([r[10] for r in rows], [0, 1])
            tm = [r[0] for r in cl.rec.snapshot()]; self.assertEqual(tm, sorted(tm))  # monotonic receipt stamps
            self.assertTrue(all(r[1] > 1700000000000000000 for r in cl.rec.snapshot()))             # wall clock recorded too
            ep = [(r[3], r[4]) for r in cl.rec.snapshot() if r[2] == "endpoint"]
            self.assertIn(("READY", "a2"), ep); self.assertIn(("READY", "a1"), ep)
        finally:
            cl.stop.set(); m.close()

    def test_fault_requests_have_expected_shape(self):
        m = Mock(); k = kube.Kube("127.0.0.1", m.port, "http")
        try:
            st, *_ = k.delete_pod("rfg", "a1", 0); self.assertEqual(st, 200)
            k.scale("rfg", "rfg-app-deep", 2)
            d = m.log[0]; self.assertEqual(d[0], "DELETE"); self.assertTrue(d[1].endswith("/namespaces/rfg/pods/a1"))
            self.assertEqual(d[2]["gracePeriodSeconds"], 0)
            p = m.log[1]; self.assertEqual(p[0], "PATCH"); self.assertEqual(p[2], {"spec": {"replicas": 2}})
            self.assertEqual(p[3], "application/merge-patch+json"); self.assertIn("/deployments/rfg-app-deep/scale", p[1])
        finally: m.close()


class FakeStream:
    def __init__(self, recs): self.records = recs
    def stop(self): pass


def rec(stream, t, valid, status=200, cls=None, replica=""):
    return (stream, 0, t, 1000000, status if valid or status == 0 else 200, cls or ("ok" if valid else "conn_error"), valid, replica, "")


class TestRunLogicAndAnalysis(unittest.TestCase):
    def setUp(self):
        self.cl = collector.Cluster(None, "rfg", "rfg-app", "rfg-store")
        self.r = collector.K8sRun(self.cl, copy.deepcopy(CFG), "pod-replace", "A", 1, tempfile.mkdtemp())

    def test_replacement_gets_logical_name_and_transitions(self):
        r = self.r; r.armed = True; r.replacements = ["r0.2"]; r.logical = {"pa": "r0.1"}
        started = []; r.start_stream = lambda lg, v: (started.append((lg, v["ip"])), r.g.__setitem__(lg, FakeStream([])))
        v1 = collector.pod_view(pod("pc", ready=False, ip="10.1.1.9", running=False)); r.on_pod("ADDED", v1, None, 10)
        v2 = collector.pod_view(pod("pc", ready=True, ip="10.1.1.9")); r.on_pod("MODIFIED", v2, v1, 20)
        self.assertEqual(r.logical["pc"], "r0.2"); self.assertEqual(started, [("r0.2", "10.1.1.9")])
        self.assertEqual([(t, rd) for t, rd, _ in r.trans["r0.2"]], [(10, False), (20, True)])
        v3 = collector.pod_view(pod("pc", ready=True, restarts=1, ip="10.1.1.9")); r.on_pod("MODIFIED", v3, v2, 30)
        self.assertTrue(any("unexpected container restart" in n[1] for n in r.notes))
        r.on_pod("DELETED", v3, v3, 40); self.assertEqual(r.trans["r0.2"][-1][:2], (40, False))
        v4 = collector.pod_view(pod("pz", ip="10.1.1.7")); r.on_pod("ADDED", v4, None, 50)      # a second, unplanned pod
        self.assertEqual(r.logical["pz"], "x1.1"); self.assertTrue(any("unexpected extra app pod" in n[1] for n in r.notes))

    def test_write_and_analyze_constructed_run(self):
        r, B, s = self.r, int(1e12), int(1e9)
        t_fault = B + 10 * s
        r.events = [(B, "pod_map", "r0.1", "pa"), (B, "pod_map", "r1.1", "pb"), (B + 11 * s, "pod_map", "r0.2", "pc"),
                    (B + 5 * s, "steady", "", ""), (t_fault, "fault", "", ""), (t_fault + 1000, "kill", "r0.1", ""), (B + 30 * s, "end", "", "")]
        r.trans = {"r0.1": [(B, True, "snapshot"), (t_fault + int(0.2 * s), False, "deleted")], "r1.1": [(B, True, "snapshot")],
                   "r0.2": [(t_fault + int(0.3 * s), False, "created"), (t_fault + int(4.0 * s), True, "watch")]}
        def stream(name, bad_from, bad_to, rep="", lo=B + 5 * s, hi=B + 28 * s, step=int(0.05 * s)):
            return [rec(name, t, not (bad_from <= t < bad_to), replica=rep) for t in range(lo, hi, step)]
        r.g = {"r0.1": FakeStream(stream("G:r0.1", 0, 0)), "r1.1": FakeStream(stream("G:r1.1", 0, 0)),
               "r0.2": FakeStream(stream("G:r0.2", 0, t_fault + int(6.0 * s), lo=t_fault + int(0.3 * s)))}   # functional only at +6.0 s
        r.tx = FakeStream(stream("tx", t_fault, t_fault + 3 * s)); r.static = FakeStream(stream("static", 0, 0))
        r.dstream = FakeStream(stream("D:store", 0, 0)); r.obs, r.obs_events, r.stats, r.notes = {}, [], {"probe_requests": 0, "dep_ops_probe": 0}, []
        for st in (r.tx, r.static):
            st.records = [x[:1] + x[1:] for x in st.records]
        r.cl.rec.add((t_fault + int(0.4 * s), 1770000000000000000, "pod", "ADDED", "pc", "rfg-app", "Pending", "", 0, 0, 0, "", "", 0, "w1", 0, ""))
        r.cl.rec.add((t_fault + int(1.5 * s), 1770000000000000000, "pod", "MODIFIED", "pc", "rfg-app", "Running", "10.1.1.9", 1, 0, 0, "", "", 0, "w1", 0, ""))
        r.cl.rec.add((t_fault + int(4.0 * s), 1770000000000000000, "pod", "MODIFIED", "pc", "rfg-app", "Running", "10.1.1.9", 1, 1, 1, "2026-01-01T00:00:03Z", "", 0, "w1", 0, ""))
        r.cl.rec.add((t_fault + int(4.6 * s), 1770000000000000000, "endpoint", "READY", "pc", "", "", "", 0, 0, 1, "", "", 0, "", 0, "rfg-app-abc"))
        r.write()
        for f in ("events.csv", "probe_transitions.csv", "user.csv", "oracle.csv", "dependency.csv", "observer_events.csv", "k8s_events.csv", "stats.json", "config.json"):
            self.assertTrue(os.path.exists(os.path.join(r.rd, f)), f)
        res = analyze_k8s.main(r.rd); d = res["per_replica"]["r0.2"]
        self.assertAlmostEqual(d["t_pod_ready_s"], 4.0, places=2)                    # from M1 function on watch transitions
        self.assertAlmostEqual(d["t_func_s"], 6.0, delta=0.12)
        self.assertAlmostEqual(d["rfg_observe_s"], 2.0, delta=0.12)                  # Ready for ~2 s before functional
        self.assertAlmostEqual(d["t_endpoint_available_s"], 4.6, places=2)
        self.assertAlmostEqual(d["rfg_endpoint_s"], 1.4, delta=0.12)
        self.assertAlmostEqual(d["t_pod_ready_k8s_s"], 4.0, places=2); self.assertAlmostEqual(d["t_pod_running_seen_s"], 1.5, places=2)
        self.assertGreater(res["ready_nonfunctional_s"], 1.5)
        self.assertGreater(res["tx_error_duration_s"], 2.5)
        self.assertEqual(res["pre_fault_invalid_G"], 0)
        self.assertIsNotNone(d["watch_latency_s_first_ready"])

    def test_snapshot_rows_for_preexisting_pods(self):
        r = self.r; r.cl.pods["rfg-store-0"] = collector.pod_view(pod("rfg-store-0", "rfg-store", True))
        r.snapshot_pods(5); rows = [x for x in r.cl.rec.snapshot() if x[3] == "SNAPSHOT"]
        self.assertEqual([(x[0], x[4], x[5], x[10]) for x in rows], [(5, "rfg-store-0", "rfg-store", 1)])

    def test_k8s_events_keep_rows_from_run_start_regression(self):
        # regression: rows older than 60 s before the first run event used to be dropped silently
        r, s = self.r, int(1e9)
        r.t_run0 = 1000 * s
        r.events = [(1200 * s, "fault", "", ""), (1210 * s, "end", "", "")]
        r.cl.rec.add((1001 * s, 1700000000000000000, "pod", "ADDED", "old-early-row", "rfg-app", "Pending", "", 0, 0, 0, "", "", 0, "", 0, ""))
        r.cl.rec.add((900 * s, 1700000000000000000, "pod", "ADDED", "before-run", "rfg-app", "Pending", "", 0, 0, 0, "", "", 0, "", 0, ""))
        r.trans, r.g, r.obs, r.obs_events, r.stats, r.notes = {}, {}, {}, [], {}, []
        r.tx = r.static = r.dstream = FakeStream([])
        r.write(); names = [x["name"] for x in csv.DictReader(open(os.path.join(r.rd, "k8s_events.csv")))]
        self.assertIn("old-early-row", names); self.assertNotIn("before-run", names)

    def test_validator_accepts_consistent_run_and_rejects_tampered_summary(self):
        import io, contextlib, validate_run
        self.test_write_and_analyze_constructed_run()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = validate_run.main(self.r.rd)
        out = buf.getvalue(); self.assertIn("TIMELINE", out); self.assertNotIn("[FAIL] store pod rows", out)   # regression: not required for pod-replace
        self.assertNotIn("[FAIL] summary t_func_s", out)
        sj = os.path.join(self.r.rd, "summary.json"); d = json.load(open(sj)); d["per_replica"]["r0.2"]["t_func_s"] += 0.5; json.dump(d, open(sj, "w"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = validate_run.main(self.r.rd)
        self.assertEqual(rc, 1); self.assertIn("[FAIL] summary t_func_s for r0.2", buf.getvalue())

    def test_m1_analysis_copy_is_byte_identical(self):
        a = open(os.path.join(SRC, "analyze_m1.py"), "rb").read()
        b = open(os.path.join(SRC, "..", "..", "..", "milestone-1", "collector", "analyze.py"), "rb").read()
        self.assertEqual(a, b)

    def test_validation_logic_byte_identical_to_m1(self):
        for f in ("rfg_common.py",):
            self.assertEqual(open(os.path.join(SRC, "application", f), "rb").read(),
                             open(os.path.join(SRC, "..", "..", "..", "milestone-1", "application", f), "rb").read())


if __name__ == "__main__":
    unittest.main()
