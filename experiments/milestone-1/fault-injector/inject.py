"""Fault actions. Each returns after the action has been issued; the runner records the event time."""
import http.client, os, signal, subprocess


def post(port, path, timeout=2.0):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    c.request("POST", path, body=b"{}", headers={"Content-Type": "application/json"})
    r = c.getresponse(); r.read(); c.close()
    return r.status


def degrade_app(port):
    """Application-level degradation: app drops its dependency connection and stops reconnecting
    (models a leaked pool / stuck reconnect loop). Process and listener stay healthy."""
    return post(port, "/admin/degrade")


def recover_app(port):
    """Operator/app recovery: clear state and re-initialise (reconnect + cache warm-up)."""
    return post(port, "/admin/recover")


def kill(proc):
    """SIGKILL (pod killed / node lost: no graceful shutdown)."""
    if proc.poll() is None:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
