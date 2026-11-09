"""Service emulator: forwards each request to one currently-Ready replica (round robin), like
kube-proxy/EndpointSlices. No ready endpoints -> 503 'no-endpoints'. Dead-but-still-Ready backend
-> 502 'conn-error'. This is what makes readiness lag visible to users."""
import http.client, itertools, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Router:
    def __init__(self, get_ready, port, timeout_s=2.0):
        self.get_ready, self.port, self.timeout = get_ready, port, timeout_s
        self.rr = itertools.count()
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _reply(self, code, body=b"{}", hdrs=None):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _fwd(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else None
                eps = outer.get_ready()
                if not eps:
                    return self._reply(503, hdrs={"X-Router": "no-endpoints"})
                name, port = eps[next(outer.rr) % len(eps)]
                try:
                    c = http.client.HTTPConnection("127.0.0.1", port, timeout=outer.timeout)
                    c.request(self.command, self.path, body=body,
                              headers={"Content-Type": "application/json"})
                    r = c.getresponse(); data = r.read(); c.close()
                    self._reply(r.status, data, {"X-Replica": name})
                except Exception:
                    self._reply(502, hdrs={"X-Router": "conn-error", "X-Replica": name})

            do_GET = do_POST = _fwd

        self.srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.srv.daemon_threads = True
        self.srv.allow_reuse_address = True

    def start(self):
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown(); self.srv.server_close()
