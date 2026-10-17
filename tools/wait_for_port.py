"""Wait until a TCP port accepts connections, instead of a fixed sleep.

    python tools/wait_for_port.py HOST PORT TIMEOUT_S

Exits 0 once it connects, 1 after TIMEOUT_S (the server failed to start,
or is still loading: see its log). Used by `make godot-selftest` and CI.
"""
import socket
import sys
import time


def wait_for_port(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.2)
    return False


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    host, port, timeout_s = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
    if not wait_for_port(host, port, timeout_s):
        sys.exit(f"nothing listening on {host}:{port} after {timeout_s:.0f} s")
