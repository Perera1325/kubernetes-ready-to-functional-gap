#!/usr/bin/env python3
"""Real TCP key-value dependency with write-ahead-log replay.
Like Redis it accepts connections immediately but answers -LOADING until replay finishes.
Replay time is real work (parse + CRC32 verify of every WAL line), not a sleep."""
import argparse, os, socketserver, sys, threading, time, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rfg_common import price_for


def _crc(b: bytes) -> int:
    return zlib.crc32(b) & 0xFFFFFFFF


def make_wal(path, n_items, n_fill):
    with open(path, "w") as f:
        for i in range(n_items):
            body = f"SET item:{i} {price_for(i)}"
            f.write(f"{_crc(body.encode()):08x} {body}\n")
        for j in range(n_fill):
            body = f"SET fill:{j} {j * 31 % 1000003}"
            f.write(f"{_crc(body.encode()):08x} {body}\n")


class Store:
    def __init__(self, wal):
        self.wal_path = wal
        self.data = {}
        self.items = []
        self.loading = True
        self.lock = threading.Lock()
        self.wal = None
        self.ops = 0

    def replay(self):
        with open(self.wal_path, "rb") as f:
            for raw in f:
                crc_hex, body = raw.rstrip(b"\n").split(b" ", 1)
                if int(crc_hex, 16) != _crc(body):
                    continue  # corrupt tail line: skip
                _, k, v = body.decode().split(" ", 2)
                if k not in self.data and k.startswith("item:"):
                    self.items.append(k)
                self.data[k] = v
        self.wal = open(self.wal_path, "ab")
        self.loading = False

    def set(self, k, v):
        body = f"SET {k} {v}".encode()
        with self.lock:
            if k not in self.data and k.startswith("item:"):
                self.items.append(k)
            self.data[k] = v
            self.wal.write(f"{_crc(body):08x} ".encode() + body + b"\n")
            self.wal.flush()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        S = self.server.store
        for raw in self.rfile:
            parts = raw.decode().strip().split(" ")
            if not parts or not parts[0]:
                continue
            cmd = parts[0].upper()
            if S.loading:
                self.wfile.write(b"-LOADING\n")
                continue
            S.ops += 1
            try:
                if cmd == "PING":
                    out = "PONG\n"
                elif cmd == "SET":
                    S.set(parts[1], parts[2])
                    out = "OK\n"
                elif cmd == "GET":
                    out = S.data.get(parts[1], "NIL") + "\n"
                elif cmd == "SCAN":
                    start, count = int(parts[1]), int(parts[2])
                    out = "".join(f"{k} {S.data[k]}\n" for k in S.items[start:start + count]) + "END\n"
                else:
                    out = "-ERR\n"
            except Exception:
                out = "-ERR\n"
            self.wfile.write(out.encode())


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--wal", required=True)
    ap.add_argument("--loaded-file", required=True)
    ap.add_argument("--make-wal", nargs=2, type=int, metavar=("ITEMS", "FILL"))
    a = ap.parse_args()
    if a.make_wal:
        make_wal(a.wal, *a.make_wal)
        return
    S = Store(a.wal)
    srv = Server(("127.0.0.1", a.port), Handler)
    srv.store = S
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def load():
        t0 = time.monotonic_ns()
        S.replay()
        with open(a.loaded_file, "w") as f:
            f.write(f"{time.monotonic_ns()} {time.monotonic_ns() - t0}\n")
    load()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
