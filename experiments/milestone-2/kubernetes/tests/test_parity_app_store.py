import json, os, subprocess, sys, tempfile, time, unittest, http.client, socket, _path
from rfg_common import validate_tx, chk, price_for, item_index
from client import classify
ROOT = _path.ROOT
PY = sys.executable
CK = 50


def good(tx_id):
    return json.dumps({"id": tx_id, "source": "primary", "value": chk(tx_id),
                       "price": price_for(item_index(tx_id, CK))}).encode()


class TestValidation(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(validate_tx("a", good("a"), CK)[0])

    def test_http200_fallback_is_invalid(self):
        b = json.dumps({"id": "a", "source": "fallback", "value": None, "price": None}).encode()
        ok, d = validate_tx("a", b, CK); self.assertFalse(ok); self.assertIn("fallback", d)

    def test_wrong_value_and_price_and_id(self):
        j = json.loads(good("a"))
        for k, v in (("value", "zzzz"), ("price", -1), ("id", "b")):
            jj = dict(j); jj[k] = v
            self.assertFalse(validate_tx("a", json.dumps(jj).encode(), CK)[0])
        self.assertFalse(validate_tx("a", b"not json", CK)[0])

    def test_classify(self):
        self.assertEqual(classify("tx", 200, {}, b"{}", "a", CK)[0], "invalid_business")
        self.assertEqual(classify("tx", 200, {}, good("a"), "a", CK)[:2], ("ok", True))
        self.assertEqual(classify("tx", 503, {"X-Router": "no-endpoints"}, b"", "a", CK)[0], "no_endpoints")
        self.assertEqual(classify("tx", 502, {"X-Router": "conn-error"}, b"", "a", CK)[0], "conn_error")
        self.assertEqual(classify("tx", 0, {}, b"", "a", CK)[0], "conn_error")
        self.assertEqual(classify("tx", 500, {}, b"", "a", CK)[0], "http_error")
        self.assertEqual(classify("static", 200, {}, b"{}", "a", CK)[:2], ("ok", True))


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def req(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    c.request(method, path, body=body, headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = r.read(); c.close(); return r.status, d


class TestStoreAndApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wal = os.path.join(self.tmp, "w.wal")
        subprocess.check_call([PY, os.path.join(ROOT, "application/store.py"), "--port", "1", "--wal", self.wal,
                               "--loaded-file", "/dev/null", "--make-wal", str(CK), "300000"])
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill(); p.wait()

    def spawn(self, *a):
        p = subprocess.Popen([PY] + list(a), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p); return p

    def test_store_loading_then_app_primary_and_deep_health(self):
        dp, ap = free_port(), free_port()
        loaded = os.path.join(self.tmp, "loaded")
        self.spawn(os.path.join(ROOT, "application/store.py"), "--port", str(dp), "--wal", self.wal, "--loaded-file", loaded)
        time.sleep(0.05)
        # store accepts connections immediately but answers -LOADING until replay completes (if still replaying)
        s = socket.create_connection(("127.0.0.1", dp), timeout=2); f = s.makefile("rwb")
        f.write(b"PING\n"); f.flush(); first = f.readline().decode().strip(); s.close()
        self.assertIn(first, ("-LOADING", "PONG"))
        for _ in range(100):
            if os.path.exists(loaded) and open(loaded).read().strip(): break
            time.sleep(0.05)
        self.spawn(os.path.join(ROOT, "application/app.py"), "--port", str(ap), "--dep-port", str(dp),
                   "--replica", "t", "--marker", os.path.join(self.tmp, "m"), "--cache-keys", str(CK))
        for _ in range(100):
            try:
                if req(ap, "GET", "/healthz/deep")[0] == 200: break
            except Exception: pass
            time.sleep(0.05)
        self.assertEqual(req(ap, "GET", "/healthz/shallow")[0], 200)
        self.assertEqual(req(ap, "GET", "/healthz/deep")[0], 200)
        code, body = req(ap, "POST", "/tx", json.dumps({"id": "t1"}))
        self.assertEqual(code, 200); self.assertTrue(validate_tx("t1", body, CK)[0])

    def test_degraded_app_is_shallow_ready_but_functionally_invalid(self):
        dp, ap = free_port(), free_port()
        loaded = os.path.join(self.tmp, "loaded")
        self.spawn(os.path.join(ROOT, "application/store.py"), "--port", str(dp), "--wal", self.wal, "--loaded-file", loaded)
        for _ in range(100):
            if os.path.exists(loaded) and open(loaded).read().strip(): break
            time.sleep(0.05)
        self.spawn(os.path.join(ROOT, "application/app.py"), "--port", str(ap), "--dep-port", str(dp),
                   "--replica", "t", "--marker", os.path.join(self.tmp, "m"), "--cache-keys", str(CK))
        for _ in range(100):
            try:
                if req(ap, "GET", "/healthz/deep")[0] == 200: break
            except Exception: pass
            time.sleep(0.05)
        req(ap, "POST", "/admin/degrade")
        self.assertEqual(req(ap, "GET", "/healthz/shallow")[0], 200)     # native probe still passes
        self.assertEqual(req(ap, "GET", "/healthz/deep")[0], 503)        # deep probe notices
        code, body = req(ap, "POST", "/tx", json.dumps({"id": "t2"}))
        self.assertEqual(code, 200)                                      # HTTP success...
        self.assertFalse(validate_tx("t2", body, CK)[0])                 # ...but not a valid business result
        req(ap, "POST", "/admin/recover")
        for _ in range(100):
            if req(ap, "GET", "/healthz/deep")[0] == 200: break
            time.sleep(0.05)
        self.assertTrue(validate_tx("t3", req(ap, "POST", "/tx", json.dumps({"id": "t3"}))[1], CK)[0])


if __name__ == "__main__":
    unittest.main()
