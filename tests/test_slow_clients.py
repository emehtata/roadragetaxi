"""godot-02.md: a slow, non-reading or vanishing client must never stall the
simulation tick, nor hold unbounded memory, nor delay other clients.

`BadClient` is a raw-socket client whose reading is scripted (normal,
slow, never), so the tests don't depend on real network slowness. The
server's kernel send buffer and the client's receive buffer are shrunk so
that "the client isn't reading" fills them after a few KiB, deterministically.
"""

import json
import os
import socket
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SDL_VIDEODRIVER") not in (None, "dummy"),
    reason="requires a headless-safe SDL driver",
)

TICK = 1.0 / 30.0


class BadClient:
    """mode: "normal" reads everything, "slow" reads `bytes_per_read` every
    `read_interval` s, "none" never reads."""

    def __init__(self, server, mode="normal", bytes_per_read=2048, read_interval=0.01):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.sock.connect((server.host, server.port))
        self.mode, self.bytes_per_read, self.read_interval = mode, bytes_per_read, read_interval
        self.messages: list = []
        self._buffer = b""
        self._stop = False
        self._thread = threading.Thread(target=self._read, daemon=True)
        if mode != "none":
            self._thread.start()

    def _read(self):
        self.sock.settimeout(0.05)
        while not self._stop:
            try:
                data = self.sock.recv(self.bytes_per_read if self.mode == "slow" else 1 << 20)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            self._buffer += data
            *lines, self._buffer = self._buffer.split(b"\n")
            self.messages.extend(json.loads(line) for line in lines if line)
            if self.mode == "slow":
                time.sleep(self.read_interval)

    def types(self):
        return [m["type"] for m in list(self.messages)]

    def states(self):
        return [m for m in list(self.messages) if m["type"] == "state"]

    def close(self):
        self._stop = True
        self.sock.close()


@pytest.fixture
def server(monkeypatch):
    from theroadragetrip import transport

    monkeypatch.setattr(transport, "SEND_BUFFER_BYTES", 4096)
    monkeypatch.setattr(transport, "SEND_STALL_TIMEOUT_S", 0.5)
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setattr(sys, "argv", ["prog", "--use-sample", "--no-menu"])
    from theroadragetrip.server import run_server
    from theroadragetrip.server.cli import parse_server_args

    args, config = parse_server_args()
    args.port = 0
    return run_server(args, config)


def _connected(server, count=1, timeout=2.0):
    deadline = time.monotonic() + timeout
    while len(server._clients) < count and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(server._clients) == count


def _run(server, ticks, pause=0.0):
    """Tick like run_forever would; returns each tick's duration (s)."""
    durations = []
    for _ in range(ticks):
        started = time.perf_counter()
        server.tick(TICK)
        durations.append(time.perf_counter() - started)
        if pause:
            time.sleep(pause)
    return durations


def _wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_a_new_client_gets_world_then_chunks_then_states(server):
    client = BadClient(server)
    _connected(server)
    _run(server, 5, pause=0.01)
    assert _wait_for(lambda: len(client.states()) >= 1)
    types = client.types()
    first_state = types.index("state")
    assert types[0] == "world"
    assert set(types[1:first_state]) == {"chunk"} and first_state - 1 == 49
    client.close()


def test_a_slow_reader_does_not_slow_the_tick_and_still_gets_states_in_order(server):
    client = BadClient(server, mode="slow", bytes_per_read=512, read_interval=0.005)
    _connected(server)
    durations = _run(server, 60, pause=0.005)
    assert max(durations) < 0.1  # an empty-world tick is ~1 ms; a blocked send would be seconds
    connection = server._clients[0]
    assert connection.queued() <= 2 + 49  # bounded: the map backlog plus one coalesced state
    assert _wait_for(lambda: len(client.states()) >= 1, timeout=5.0)
    ticks = [m["tick"] for m in client.states()]
    assert ticks == sorted(ticks) and len(set(ticks)) == len(ticks)
    client.close()


def test_a_client_that_never_reads_is_dropped_and_the_simulation_keeps_going(server):
    from theroadragetrip import transport

    client = BadClient(server, mode="none")
    _connected(server)
    connection = server._clients[0]
    durations = _run(server, 30, pause=0.01)
    assert max(durations) < 0.1
    assert connection.queued() <= transport.MAX_QUEUED_MESSAGES + 2
    # No progress for SEND_STALL_TIMEOUT_S (0.5 s here) -> dropped.
    assert _wait_for(lambda: connection.is_closed, timeout=3.0)
    assert isinstance(connection.error, TimeoutError)
    _run(server, 2)
    assert server._clients == [] and connection not in server._client_chunks
    assert _wait_for(lambda: not connection._sender.is_alive())
    client.close()


def test_a_client_that_overflows_its_queue_is_dropped(server, monkeypatch):
    from theroadragetrip import transport

    monkeypatch.setattr(transport, "MAX_QUEUED_MESSAGES", 10)
    monkeypatch.setattr(transport, "SEND_STALL_TIMEOUT_S", 60.0)
    client = BadClient(server, mode="none")
    _connected(server)
    connection = server._clients[0]
    _run(server, 1)  # 49 chunks into a 10-message queue
    assert connection.is_closed and isinstance(connection.error, ConnectionError)
    assert connection.queued() <= 11
    _run(server, 2)
    assert server._clients == []
    client.close()


def test_a_client_vanishing_mid_send_ends_its_sender_and_the_simulation_continues(server):
    client = BadClient(server, mode="none")
    _connected(server)
    connection = server._clients[0]
    _run(server, 3)  # its map is now stuck mid-send
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    client.close()  # linger 0: a reset, like a crashed client
    assert _wait_for(lambda: connection.is_closed)
    assert _wait_for(lambda: not connection._sender.is_alive() and not connection._thread.is_alive())
    before = server._tick
    _run(server, 5)
    assert server._tick == before + 5 and server._clients == []


def test_one_stuck_client_does_not_delay_another(server):
    stuck = BadClient(server, mode="none")
    _connected(server)
    normal = BadClient(server)
    _connected(server, 2)
    _run(server, 30, pause=0.01)
    assert _wait_for(lambda: len(normal.states()) >= 25)  # ~every tick, while the other is stuck
    ticks = [m["tick"] for m in normal.states()]
    assert ticks[-1] == server._tick
    stuck.close()
    normal.close()


def test_a_behind_client_gets_the_newest_state_with_every_event(monkeypatch):
    from theroadragetrip import protocol, transport

    monkeypatch.setattr(transport, "SEND_BUFFER_BYTES", 4096)
    listener = socket.create_server(("127.0.0.1", 0))
    peer = socket.socket()
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    peer.connect(listener.getsockname())
    server_side, _ = listener.accept()
    listener.close()
    connection = transport.LineJSONConnection(server_side)
    connection.send({"type": "chunk", "version": 1, "blob": "x" * 500_000})  # the sender is stuck on this
    assert _wait_for(lambda: connection.queued() == 1 and connection._writing)

    def state(tick, group):
        return {"type": "state", "version": protocol.PROTOCOL_VERSION, "tick": tick,
                "state": {"events": [{"type": "sound", "group": group}]}}

    for tick, group in ((1, "vehicle.door_open"), (2, "vehicle.door_close"), (3, "taxi.payment")):
        connection.send_state(state(tick, group))
    assert connection.coalesced_states == 2 and connection.queued() == 2  # the chunk + one state

    received = b""
    peer.settimeout(2.0)
    while received.count(b"\n") < 2:
        received += peer.recv(1 << 16)
    states = [json.loads(line) for line in received.split(b"\n") if line and b'"state"' in line[:20]]
    assert [s["tick"] for s in states] == [3]
    assert [e["group"] for e in states[0]["state"]["events"]] == ["vehicle.door_open", "vehicle.door_close", "taxi.payment"]
    connection.close()
    peer.close()
