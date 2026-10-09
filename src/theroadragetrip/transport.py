"""The local IPC transport for client-server-02.md: a loopback TCP socket
carrying newline-delimited JSON (see protocol.py for the message shapes).

Plain stdlib `socket` + `threading` + `queue` - no networking framework,
no MQTT, no pickle. TCP over 127.0.0.1 rather than a Unix domain socket
so the same code works unchanged on Windows (this project ships Windows
builds) and is trivially promotable to a real remote transport later by
changing only the host argument.
"""

from __future__ import annotations

import collections
import logging
import queue
import socket
import threading
import time
from typing import Optional

from .protocol import ProtocolError, decode, encode

logger = logging.getLogger(__name__)

_RECV_CHUNK = 4096
_SOCKET_TIMEOUT_S = 0.25  # how often a blocked read/write wakes to check for shutdown

# Outgoing backpressure (per connection): at most this many reliable
# messages waiting (the whole initial map is 49 chunks), and a peer that
# accepts no bytes for this long is disconnected - a non-reading client must
# not hold memory or a thread forever.
MAX_QUEUED_MESSAGES = 256
SEND_STALL_TIMEOUT_S = 10.0
SEND_BUFFER_BYTES: Optional[int] = None  # tests shrink the kernel buffer to make a stall deterministic


class LineJSONConnection:
    """Wraps one connected socket, with two background threads:

    - a reader decodes incoming lines into a queue;
    - a sender writes outgoing messages, so the caller (the server's tick
      loop) never waits on the socket.

    Outgoing messages are of two kinds. `send` queues a reliable message
    (world header, map chunks, unloads, commands): delivered once each, in
    order, bounded by MAX_QUEUED_MESSAGES. `send_state` replaces the one
    pending state snapshot - a client that is behind gets the newest state,
    not a backlog - carrying over the replaced one's one-shot `events`.
    The sender writes every queued reliable message before the pending
    state, so whatever was queued before a state reaches the peer first.

    A peer that is gone, overflows its queue or accepts nothing for
    SEND_STALL_TIMEOUT_S is disconnected (`is_closed`, with `error` saying
    why); its threads end on their own.
    """

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if SEND_BUFFER_BYTES is not None:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER_BYTES)
        self._sock.settimeout(_SOCKET_TIMEOUT_S)
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._buffer = b""
        self._closed = False
        self._error: Optional[Exception] = None
        self._out_lock = threading.Condition()
        self._outgoing: collections.deque = collections.deque()
        self._pending_state: Optional[dict] = None
        self.sent_messages = 0
        self.sent_bytes = 0
        self.coalesced_states = 0
        self._writing = False  # a message taken off the queue is being written
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self._sender = threading.Thread(target=self._send_loop, daemon=True)
        self._sender.start()

    def _read_loop(self) -> None:
        try:
            while not self._closed:
                try:
                    chunk = self._sock.recv(_RECV_CHUNK)
                except socket.timeout:
                    continue  # nothing to read; check for shutdown
                if not chunk:
                    break
                self._buffer += chunk
                while b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        self._queue.put(decode(line))
                    except ProtocolError as exc:
                        # A malformed message or a protocol-version
                        # mismatch is a controlled failure (client-server-
                        # 02.md step 11), not a crash: drop this one
                        # connection, not the server/client process.
                        logger.warning("Dropping connection: %s", exc)
                        self._fail(exc)
                        return
        except OSError as exc:
            if not self._closed:  # not our own close()
                self._fail(exc)
        finally:
            self._closed = True
            with self._out_lock:
                self._out_lock.notify_all()

    def _fail(self, exc: Exception) -> None:
        if self._error is None:
            self._error = exc
        self._closed = True

    def send(self, message: "dict | bytes") -> bool:
        """Queue a reliable message (a dict, or an already encoded line);
        never blocks. False once the connection
        is closed - including by this call, if the queue is full."""
        with self._out_lock:
            if self._closed:
                return False
            if len(self._outgoing) >= MAX_QUEUED_MESSAGES:
                logger.warning("Dropping a client that is not reading: %d messages queued", len(self._outgoing))
                self._fail(ConnectionError("outgoing queue full"))
                self._out_lock.notify_all()
                return False
            self._outgoing.append(message)
            self._out_lock.notify()
            return True

    def send_state(self, message: dict) -> bool:
        """Make `message` the state to send next, replacing one not yet sent
        (its events are kept: prepended to this one's)."""
        with self._out_lock:
            if self._closed:
                return False
            replaced = self._pending_state
            if replaced is not None:
                self.coalesced_states += 1
                earlier = replaced.get("state", {}).get("events") or []
                if earlier:
                    message = {**message, "state": {**message["state"], "events": earlier + message["state"].get("events", [])}}
            self._pending_state = message
            self._out_lock.notify()
            return True

    def queued(self) -> int:
        """Messages waiting to be written (performance readout)."""
        with self._out_lock:
            return len(self._outgoing) + (self._pending_state is not None) + self._writing

    def _next_outgoing(self) -> "Optional[dict | bytes]":
        with self._out_lock:
            self._writing = False
            while not self._closed and not self._outgoing and self._pending_state is None:
                self._out_lock.wait()
            if self._closed:
                return None
            self._writing = True
            if self._outgoing:
                return self._outgoing.popleft()
            message, self._pending_state = self._pending_state, None
            return message

    def _send_loop(self) -> None:
        while True:
            message = self._next_outgoing()
            if message is None:
                return
            data = memoryview(message if isinstance(message, bytes) else encode(message))
            stalled_since = time.monotonic()
            try:
                while data:  # partial writes: keep going from where the socket stopped
                    if self._closed:
                        return
                    try:
                        written = self._sock.send(data)
                    except socket.timeout:
                        written = 0
                    if written:
                        data = data[written:]
                        self.sent_bytes += written
                        stalled_since = time.monotonic()
                    elif time.monotonic() - stalled_since > SEND_STALL_TIMEOUT_S:
                        logger.warning("Dropping a client that stopped reading (no progress for %.0f s)", SEND_STALL_TIMEOUT_S)
                        self._fail(TimeoutError("client stopped reading"))
                        return
            except OSError as exc:
                logger.info("Client connection lost while sending: %s", exc)
                self._fail(exc)
                return
            self.sent_messages += 1

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
        with self._out_lock:
            self._out_lock.notify_all()
        try:
            self._sock.close()
        except OSError:
            pass

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until everything queued has been written (shutdown, tests)."""
        deadline = time.monotonic() + timeout
        while self.queued() and not self._closed and time.monotonic() < deadline:
            time.sleep(0.005)
        return not self.queued()


def connect(host: str, port: int, timeout: float = 5.0) -> LineJSONConnection:
    """Client side: connect to a running server. Raises ConnectionError
    (or a socket.error subclass) if the server is unreachable - callers
    should catch this and fail with a clear message, not a bare traceback."""
    sock = socket.create_connection((host, port), timeout=timeout)
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
