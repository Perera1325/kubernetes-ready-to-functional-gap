"""Emulation of kubelet readiness-probe semantics (NOT the kubelet).
State machine: starts NotReady; Ready after successThreshold consecutive successes;
NotReady after failureThreshold consecutive failures. HTTP 200-399 = success.
First probe happens at initialDelay + uniform(0, period) like the kubelet's randomised start."""
import http.client, random, threading, time


class ReadinessState:
    def __init__(self, failure_threshold=3, success_threshold=1):
        self.ft, self.st = failure_threshold, success_threshold
        self.ready = False
        self.succ = self.fail = 0

    def observe(self, ok):
        """Feed one probe result; return True if readiness changed."""
        if ok:
            self.succ += 1; self.fail = 0
            if not self.ready and self.succ >= self.st:
                self.ready = True
                return True
        else:
            self.fail += 1; self.succ = 0
            if self.ready and self.fail >= self.ft:
                self.ready = False
                return True
        return False


def http_probe(port, path, timeout_s):
    t0 = time.monotonic_ns()
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout_s)
        c.request("GET", path)
        r = c.getresponse(); r.read(); c.close()
        return 200 <= r.status < 400, time.monotonic_ns() - t0, str(r.status)
    except Exception as e:
        return False, time.monotonic_ns() - t0, type(e).__name__


class Prober(threading.Thread):
    def __init__(self, name, probe_fn, period_s, failure_threshold, success_threshold,
                 initial_delay_s, seed, on_transition=None):
        super().__init__(daemon=True)
        self.name_, self.probe_fn, self.period = name, probe_fn, period_s
        self.state = ReadinessState(failure_threshold, success_threshold)
        self.initial_delay = initial_delay_s
        self.rng = random.Random(seed)
        self.stop_ev = threading.Event()
        self.on_transition = on_transition
        self.log = []          # (t_ns, ok, latency_ns, detail)
        self.transitions = [(time.monotonic_ns(), False, "launch")]

    @property
    def ready(self):
        return self.state.ready

    def run(self):
        if self.stop_ev.wait(self.initial_delay + self.rng.uniform(0, self.period)):
            return
        nxt = time.monotonic()
        while not self.stop_ev.is_set():
            ok, lat, det = self.probe_fn()
            t = time.monotonic_ns()
            self.log.append((t, ok, lat, det))
            if self.state.observe(ok):
                self.transitions.append((t, self.state.ready, det))
                if self.on_transition:
                    self.on_transition(self.name_, self.state.ready, t)
            nxt += self.period
            if self.stop_ev.wait(max(0.0, nxt - time.monotonic())):
                return

    def stop(self):
        self.stop_ev.set()
