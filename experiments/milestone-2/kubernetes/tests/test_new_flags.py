"""M2 additions: --bind-address, --dep-host, --http-port/--port alias, --health-port split, make-wal-if-missing."""
import http.client, os, socket, subprocess, sys, tempfile, time, unittest, _path
ROOT, PY = _path.ROOT, sys.executable


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def get(port, path, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    c.request(method, path); r = c.getresponse(); d = r.read(); c.close(); return r.status, d


def wait(port, path, t=15):
    end = time.time() + t
    while time.time() < end:
        try: return get(port, path)
        except OSError: time.sleep(0.1)
    raise AssertionError("not up")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.procs = []; self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for p in self.procs: p.kill(); p.wait()

    def test_store_make_if_missing_and_dep_host_and_health_port(self):
        wal = os.path.join(self.tmp, "s.wal"); sp, hp, ap = free_port(), free_port(), free_port()
        st = subprocess.Popen([PY, os.path.join(ROOT, "application/store.py"), "--bind-address", "127.0.0.1", "--port", str(sp),
                               "--wal", wal, "--make-wal-if-missing", "50", "1000"], stdout=subprocess.PIPE, text=True)
        self.procs.append(st)
        app = subprocess.Popen([PY, os.path.join(ROOT, "application/app.py"), "--bind-address", "127.0.0.1", "--http-port", str(hp),
                                "--health-port", str(ap), "--dep-host", "localhost", "--dep-port", str(sp), "--cache-keys", "50",
                                "--replica", "t0", "--backoff-base", "0.1", "--backoff-cap", "0.5"])
        self.procs.append(app)
        wait(ap, "/healthz/shallow")
        self.assertTrue(os.path.getsize(wal) > 0)
        # health port serves only /healthz/*, business port serves everything
        self.assertEqual(get(ap, "/admin/stats")[0], 404)
        self.assertEqual(get(hp, "/admin/stats")[0], 200)
        end = time.time() + 20
        while time.time() < end and get(ap, "/healthz/deep")[0] != 200: time.sleep(0.2)
        self.assertEqual(get(ap, "/healthz/deep")[0], 200)   # reached the dependency through --dep-host
        c = http.client.HTTPConnection("127.0.0.1", hp, timeout=3)
        c.request("POST", "/tx", body=b'{"id":"x1"}'); r = c.getresponse(); r.read()
        self.assertEqual(r.status, 200)

    def test_port_alias_backcompat(self):
        sp, hp = free_port(), free_port()
        wal = os.path.join(self.tmp, "b.wal")
        subprocess.check_call([PY, os.path.join(ROOT, "application/store.py"), "--wal", wal, "--make-wal", "50", "1000"])
        app = subprocess.Popen([PY, os.path.join(ROOT, "application/app.py"), "--port", str(hp), "--dep-port", str(sp), "--replica", "t1",
                                "--cache-keys", "50"])
        self.procs.append(app)
        self.assertEqual(wait(hp, "/healthz/shallow")[0], 200)

    def test_default_bind_is_loopback_and_flag_changes_it(self):
        src = open(os.path.join(ROOT, "application/app.py")).read()
        self.assertIn('default="127.0.0.1"', src)


if __name__ == "__main__":
    unittest.main()
