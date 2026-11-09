"""Arm C standalone functional-recovery observer (detection logic only, NOT a controller).
Sends synthetic transactions directly to one replica and declares it 'functional' after N
consecutive valid responses; declares 'functional_lost' on the first invalid response."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client import Stream


class Observer(Stream):
    def __init__(self, name, port, hz, n_consecutive, cache_keys, run_id, events, host="127.0.0.1"):
        super().__init__("OBS:" + name, "tx", hz, port, cache_keys, run_id, on_sample=self._cb, host=host)
        self.n, self.events, self.streak, self.functional = n_consecutive, events, 0, False
        self.target = name

    def _cb(self, rec):
        t, valid = rec[2], rec[6]
        if valid:
            self.streak += 1
            if not self.functional and self.streak >= self.n:
                self.functional = True
                self.events.append((t, self.target, "functional"))
        else:
            self.streak = 0
            if self.functional:
                self.functional = False
                self.events.append((t, self.target, "functional_lost"))
