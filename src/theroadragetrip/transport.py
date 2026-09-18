"""The local IPC transport for client-server-02.md: a loopback TCP socket
carrying newline-delimited JSON (see protocol.py for the message shapes).

Plain stdlib `socket` + `threading` + `queue` - no networking framework,
no MQTT, no pickle. TCP over 127.0.0.1 rather than a Unix domain socket
so the same code works unchanged on Windows (this project ships Windows
builds) and is trivially promotable to a real remote transport later by
changing only the host argument.
"""

from __future__ import annotations

import queue
import socket
import threading
from typing import Optional

from .protocol import decode, encode

_RECV_CHUNK = 4096


class LineJSONConnection:
    """Wraps one connected socket. A background thread reads and decodes
    incoming lines into a queue; `send` is a plain blocking `sendall`
    (small JSON lines on a loopback socket - never a stall worth async'ing
    away). Safe to use from server or client, one instance per connection.
    """

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._buffer = b""
        self._closed = False
        self._error: Optional[Exception] = None
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        try:
            while True:
                chunk = self._sock.recv(_RECV_CHUNK)
                if not chunk:
                    break
                self._buffer += chunk
                while b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    if line:
                        self._queue.put(decode(line))
        except OSError as exc:
            self._error = exc
        finally:
            self._closed = True

    def send(self, message: dict) -> bool:
        """Best-effort send; returns False (never raises) once the peer is
        gone, so a slow/dead client can't take down the server's tick loop."""
        try:
            self._sock.sendall(encode(message))
            return True
        except OSError:
            self._closed = True
            return False

    def try_recv_latest(self) -> Optional[dict]:
        """Drain the queue and return only the newest message - state
        snapshots are latest-wins, never a backlog to catch up on."""
        latest = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                return latest

    def try_recv_all(self) -> list[dict]:
        """Drain the queue in order - used for edge-triggered messages
        (e.g. an `interact` command) where every one matters, not just
        the newest."""
        messages = []
        while True:
            try:
                messages.append(self._queue.get_nowait())
            except queue.Empty:
                return messages

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def error(self) -> Optional[Exception]:
        return self._error

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass


def connect(host: str, port: int, timeout: float = 5.0) -> LineJSONConnection:
    """Client side: connect to a running server. Raises ConnectionError
    (or a socket.error subclass) if the server is unreachable - callers
    should catch this and fail with a clear message, not a bare traceback."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(None)
    return LineJSONConnection(sock)


class Listener:
    """Server side: accepts connections on a background thread and hands
    each one to `on_connect` as a LineJSONConnection."""

    def __init__(self, host: str, port: int, on_connect):
        self._on_connect = on_connect
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(5)
        self.host, self.port = self._sock.getsockname()[:2]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while True:
            try:
                client_sock, _addr = self._sock.accept()
            except OSError:
                return
            self._on_connect(LineJSONConnection(client_sock))

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
