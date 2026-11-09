#!/usr/bin/env python3
"""HTTP business app. Process/listener comes up immediately; real initialisation (connect to the
dependency, warm a cache by SCANning it) happens in the background. While not initialised the app
degrades gracefully: HTTP 200 with a 'fallback' payload (the realistic gray-failure shape).
Reconnect uses exponential backoff (base/cap configurable) - a normal client library behaviour."""
import argparse, json, os, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rfg_common import chk, item_index


class DepDown(Exception):
    pass


class DepClient:
    def __init__(self, port, base, cap):
        self.port, self.base, self.cap = port, base, cap
        self.lock = threading.Lock()
        self.sock = self.f = None
        self.healthy = False
        self.blocked = False
        self.backoff = base
        self.attempts = 0

    def _down_locked(self):
        self.healthy = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = self.f = None

    def force_down(self):
        with self.lock:
            self._down_locked()

    def try_connect(self):
        self.attempts += 1
        sock = f = None
        try:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
            sock.settimeout(0.5)
            f = sock.makefile("rwb")
            f.write(b"PING\n"); f.flush()
            if f.readline().decode().strip() != "PONG":
                raise IOError("not ready")
        except Exception:
            try:
                if sock: sock.close()
            except Exception:
                pass
            return False
        with self.lock:
            self.sock, self.f, self.healthy = sock, f, True
        return True

    def call(self, line, multi=False):
        with self.lock:
            if not self.healthy:
                raise DepDown()
            try:
                self.f.write(line.encode() + b"\n"); self.f.flush()
                if multi:
                    out = []
                    while True:
                        r = self.f.readline().decode()
                        if r == "" or r.startswith("-"):
                            raise IOError("bad")
                        r = r.rstrip("\n")
                        if r == "END":
                            return out
                        out.append(r)
                r = self.f.readline().decode()
                if r == "" or r.startswith("-"):
                    raise IOError("bad")
                return r.rstrip("\n")
            except Exception:
                self._down_locked()
                raise DepDown()


class App:
    def __init__(self, a):
        self.a = a
        self.dep = DepClient(a.dep_port, a.backoff_base, a.backoff_cap)
        self.cache = {}
        self.cache_ready = False
        self.stats = {"probe_requests": 0, "dep_ops_probe": 0, "tx_requests": 0, "fallbacks": 0}
        self.init_lock = threading.Lock()

    def warm(self):
        cache, off = {}, 0
        while off < self.a.cache_keys:
            n = min(1000, self.a.cache_keys - off)
            for line in self.dep.call(f"SCAN {off} {n}", multi=True):
                k, v = line.split(" ")
                cache[k] = int(v)
            off += n
        self.cache, self.cache_ready = cache, True

    def init_loop(self):
        while True:
            if self.dep.blocked or self.dep.healthy:
                if self.dep.healthy and not self.cache_ready and not self.dep.blocked:
                    try:
                        self.warm()
                    except DepDown:
                        pass
                time.sleep(0.05)
                continue
            if self.dep.try_connect():
                self.dep.backoff = self.dep.base
                try:
                    self.warm()
                except DepDown:
                    pass
            else:
                time.sleep(self.dep.backoff)
                self.dep.backoff = min(self.dep.backoff * 2, self.dep.cap)

    def tx(self, tx_id):
        self.stats["tx_requests"] += 1
        if not self.dep.healthy or not self.cache_ready:
            self.stats["fallbacks"] += 1
            return 200, {"ok": True, "id": tx_id, "source": "fallback", "value": None, "price": None}
        try:
            self.dep.call(f"SET order:{tx_id} {chk(tx_id)}")
            v = self.dep.call(f"GET order:{tx_id}")
        except DepDown:
            return 500, {"ok": False, "error": "dependency"}
        idx = item_index(tx_id, self.a.cache_keys)
        return 200, {"ok": True, "id": tx_id, "source": "primary", "value": v,
                     "price": self.cache.get(f"item:{idx}")}

    def deep_ok(self):
        self.stats["probe_requests"] += 1
        if not self.dep.healthy or not self.cache_ready:
            return False
        try:
            self.stats["dep_ops_probe"] += 1
            return self.dep.call("PING") == "PONG"
        except DepDown:
            return False

    def degrade(self):
        self.dep.blocked = True
        self.cache_ready = False
        self.dep.force_down()

    def recover(self):
        self.cache = {}
        self.cache_ready = False
        self.dep.backoff = self.dep.base
        self.dep.blocked = False


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, obj=None):
            body = json.dumps(obj if obj is not None else {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Replica", app.a.replica)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path
            if p == "/healthz/shallow":
                app.stats["probe_requests"] += 1
                self._send(200)
            elif p == "/healthz/deep":
                self._send(200 if app.deep_ok() else 503)
            elif p == "/static/ping":
                self._send(200, {"pong": True})
            elif p == "/admin/stats":
                self._send(200, dict(app.stats, dep_attempts=app.dep.attempts, healthy=app.dep.healthy,
                                     cache_ready=app.cache_ready))
            else:
                self._send(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b"{}"
            if self.path == "/tx":
                try:
                    tx_id = json.loads(body)["id"]
                except Exception:
                    return self._send(400)
                code, obj = app.tx(tx_id)
                self._send(code, obj)
            elif self.path == "/admin/degrade":
                app.degrade(); self._send(200)
            elif self.path == "/admin/recover":
                app.recover(); self._send(200)
            else:
                self._send(404)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--dep-port", type=int, required=True)
    ap.add_argument("--replica", required=True)
    ap.add_argument("--cache-keys", type=int, default=100000)
    ap.add_argument("--backoff-base", type=float, default=0.5)
    ap.add_argument("--backoff-cap", type=float, default=8.0)
    ap.add_argument("--marker", required=True)
    a = ap.parse_args()
    app = App(a)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(app))
    srv.daemon_threads = True
    srv.allow_reuse_address = True
    threading.Thread(target=app.init_loop, daemon=True).start()
    with open(a.marker, "w") as f:
        f.write(f"{time.monotonic_ns()}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
