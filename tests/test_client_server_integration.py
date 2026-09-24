"""client-server-02.md step 19: a client/server integration test that
exercises the real protocol and transport, with no Pygame client
involved - just a bare transport.LineJSONConnection standing in for one.
"""

import os
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SDL_VIDEODRIVER") not in (None, "dummy"),
    reason="requires a headless-safe SDL driver",
)


def _start_server(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setattr(sys, "argv", ["prog", "--use-sample", "--no-menu"])
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.server import run_server

    args, config = parse_server_args()
    args.port = 0  # let the OS pick a free port - these tests run several servers
    server = run_server(args, config)
    return server


def test_client_connects_receives_state_and_commands_reach_the_simulation(monkeypatch):
    from theroadragetrip import protocol, transport
    from theroadragetrip.simulation import PlayerCommand

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)

    server.tick(1.0 / 30.0)
    time.sleep(0.05)
    initial = connection.try_recv_latest()
    assert initial is not None
    assert initial["type"] == "state"
    assert initial["version"] == protocol.PROTOCOL_VERSION
    assert "player" in initial["state"]
    assert initial["state"]["on_foot"] is True

    connection.send(protocol.build_command_message(PlayerCommand(), interact=True, seq=1))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    connection.send(protocol.build_command_message(PlayerCommand(throttle=1.0, engine_on=True), interact=False, seq=2))
    time.sleep(0.05)
    for _ in range(20):
        server.tick(1.0 / 30.0)
    time.sleep(0.05)

    updated = connection.try_recv_latest()
    assert updated is not None
    assert updated["state"]["on_foot"] is False
    assert updated["state"]["player"]["x"] != initial["state"]["player"]["x"]
    connection.close()


def test_malformed_client_message_does_not_crash_the_server(monkeypatch):
    from theroadragetrip import protocol

    server = _start_server(monkeypatch)
    import socket

    raw = socket.create_connection((server.host, server.port), timeout=2.0)
    raw.sendall(b"not json\n")
    time.sleep(0.05)
    # The server's reader thread should have quietly dropped the
    # connection (decode() raises ProtocolError inside it) rather than
    # taking the tick loop down with it.
    server.tick(1.0 / 30.0)
    assert server._tick == 1
    raw.close()


def test_client_disconnect_is_handled_cleanly(monkeypatch):
    from theroadragetrip import transport

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert len(server._clients) == 1

    connection.close()
    time.sleep(0.05)
    server.tick(1.0 / 30.0)  # this tick's _apply_incoming_messages prunes closed connections
    assert len(server._clients) == 0
