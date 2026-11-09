"""Continuous synthetic business transactions with strict validation.
Classes: ok | invalid_business (HTTP 200 but payload wrong) | http_error | no_endpoints | conn_error."""
import http.client, json, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "application"))
from rfg_common import validate_tx


def classify(kind, status, headers, body, tx_id, cache_keys):
    if status == 0:
        return "conn_error", False, "exception"
    r = headers.get("X-Router")
    if r == "no-endpoints":
        return "no_endpoints", False, r
    if r == "conn-error":
        return "conn_error", False, r
    if status >= 500 or status != 200:
        return "http_error", False, str(status)
    if kind == "tx":
        ok, det = validate_tx(tx_id, body, cache_keys)
        return ("ok", True, det) if ok else ("invalid_business", False, det)
    return "ok", True, "ok"


class Stream(threading.Thread):
    """Rate-paced (absolute schedule) request stream. rec: (stream,seq,t_send_ns,lat_ns,status,cls,valid,replica,detail)"""
    def __init__(self, name, kind, hz, port, cache_keys, run_id, timeout_s=1.0, on_sample=None):
        super().__init__(daemon=True)
        self.name_, self.kind, self.hz, self.port = name, kind, hz, port
        self.cache_keys, self.run_id, self.timeout = cache_keys, run_id, timeout_s
        self.on_sample = on_sample
        self.stop_ev = threading.Event()
        self.records = []

    def one(self, seq):
        tx_id = f"{self.run_id}-{self.name_}-{seq}"
        t0 = time.monotonic_ns()
        status, headers, body = 0, {}, b""
        try:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
            if self.kind == "tx":
                c.request("POST", "/tx", body=json.dumps({"id": tx_id}),
                          headers={"Content-Type": "application/json"})
            else:
                c.request("GET", "/static/ping")
            r = c.getresponse(); body = r.read(); status = r.status
            headers = dict(r.getheaders()); c.close()
        except Exception:
            pass
        lat = time.monotonic_ns() - t0
        cls, valid, det = classify(self.kind, status, headers, body, tx_id, self.cache_keys)
        return (self.name_, seq, t0, lat, status, cls, valid, headers.get("X-Replica", ""), det)

    def run(self):
        interval = 1.0 / self.hz
        nxt = time.monotonic()
        seq = 0
        while not self.stop_ev.is_set():
            rec = self.one(seq); seq += 1
            self.records.append(rec)
            if self.on_sample:
                self.on_sample(rec)
            nxt += interval
            d = nxt - time.monotonic()
            if d > 0:
                if self.stop_ev.wait(d):
                    return
            elif d < -1.0:
                nxt = time.monotonic()  # fell far behind; resync (documented limitation)

    def stop(self):
        self.stop_ev.set()

    def recent_valid(self, n):
        r = self.records[-n:]
        return len(r) >= n and all(x[6] for x in r)
