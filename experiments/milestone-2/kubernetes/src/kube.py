"""Minimal Kubernetes API client (stdlib only) with watch support.
Every received watch line is stamped with the collector's CLOCK_MONOTONIC (t_mono_ns) and wall clock (t_wall_ns).
Receipt time is when the line was read by this process, NOT when the state changed (watch-receipt latency is real and
is recorded separately; see research/experimental_methodology.md)."""
import http.client, json, os, ssl, threading, time

SA = "/var/run/secrets/kubernetes.io/serviceaccount"


class Kube:
    def __init__(self, host=None, port=None, scheme="https", token=None, ca=None):
        self.scheme = scheme
        self.host = host or os.environ["KUBERNETES_SERVICE_HOST"]
        self.port = int(port or os.environ.get("KUBERNETES_SERVICE_PORT", 443))
        if scheme == "https":
            self.token = token if token is not None else open(f"{SA}/token").read().strip()
            self.ctx = ssl.create_default_context(cafile=ca or f"{SA}/ca.crt")
        else:                                   # plain HTTP is used ONLY by the unit tests' mock API
            self.token, self.ctx = token or "", None

    def _conn(self, timeout):
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=self.ctx)
        return http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def _hdr(self, ctype="application/json"):
        h = {"Accept": "application/json", "Content-Type": ctype}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def request(self, method, path, body=None, ctype="application/json", timeout=10):
        """returns (status, json_or_None, t_before_send_ns, t_after_response_ns)"""
        c = self._conn(timeout)
        data = None if body is None else json.dumps(body)
        t0 = time.monotonic_ns()
        c.request(method, path, body=data, headers=self._hdr(ctype))
        r = c.getresponse(); raw = r.read(); t1 = time.monotonic_ns(); c.close()
        try:
            obj = json.loads(raw) if raw else None
        except ValueError:
            obj = {"raw": raw[:200].decode("utf-8", "replace")}
        return r.status, obj, t0, t1

    # ---- convenience
    def delete_pod(self, ns, name, grace=0):
        return self.request("DELETE", f"/api/v1/namespaces/{ns}/pods/{name}",
                            {"kind": "DeleteOptions", "apiVersion": "v1", "gracePeriodSeconds": grace})

    def scale(self, ns, deployment, replicas):
        return self.request("PATCH", f"/apis/apps/v1/namespaces/{ns}/deployments/{deployment}/scale",
                            {"spec": {"replicas": replicas}}, ctype="application/merge-patch+json")

    def watch(self, path, on_event, stop, label_selector=None, timeout_s=300):
        """list-then-watch loop. on_event(type, obj, t_mono_ns, t_wall_ns). Initial list is delivered as type 'LISTED'."""
        sel = f"labelSelector={label_selector}&" if label_selector else ""
        rv = None
        while not stop.is_set():
            try:
                if rv is None:
                    st, lst, _, _ = self.request("GET", f"{path}?{sel}".rstrip("?&"))
                    if st != 200:
                        time.sleep(1); continue
                    tm, tw = time.monotonic_ns(), time.time_ns()
                    for it in lst.get("items", []):
                        on_event("LISTED", it, tm, tw)
                    rv = lst["metadata"]["resourceVersion"]
                c = self._conn(timeout_s + 10)
                c.request("GET", f"{path}?{sel}watch=1&allowWatchBookmarks=true&resourceVersion={rv}&timeoutSeconds={timeout_s}",
                          headers=self._hdr())
                r = c.getresponse()
                if r.status != 200:
                    rv = None; c.close(); time.sleep(1); continue
                while not stop.is_set():
                    line = r.readline()
                    if not line:
                        break
                    tm, tw = time.monotonic_ns(), time.time_ns()
                    ev = json.loads(line)
                    t, obj = ev["type"], ev["object"]
                    if t == "BOOKMARK":
                        rv = obj["metadata"]["resourceVersion"]; continue
                    if t == "ERROR":                      # e.g. 410 Gone -> relist
                        rv = None; break
                    rv = obj["metadata"]["resourceVersion"]
                    on_event(t, obj, tm, tw)
                c.close()
            except Exception:
                if stop.is_set():
                    return
                time.sleep(0.5)                           # reconnect; resourceVersion kept so no events are lost


class Recorder:
    """Thread-safe append-only rows."""
    def __init__(self):
        self.lock = threading.Lock(); self.rows = []

    def add(self, row):
        with self.lock:
            self.rows.append(row)

    def snapshot(self):
        with self.lock:
            return list(self.rows)
