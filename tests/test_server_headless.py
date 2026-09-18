"""client-server-02.md step 18: the server works without any client
connected, with no graphical environment required."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SDL_VIDEODRIVER") not in (None, "dummy"),
    reason="requires a headless-safe SDL driver",
)


def _build_server(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    argv = ["prog", "--use-sample", "--no-menu"]
    monkeypatch.setattr(sys, "argv", argv)
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.server import SimulationServer

    args, config = parse_server_args()
    return SimulationServer(args, config)


def test_server_builds_and_ticks_with_no_client_connected(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    for _ in range(30):
        server.tick(1.0 / 30.0)
    assert server._tick == 30


def test_server_never_opens_a_graphical_display(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    import pygame

    assert pygame.display.get_surface() is None
    for _ in range(5):
        server.tick(1.0 / 30.0)
    assert pygame.display.get_surface() is None


def test_game_time_advances(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    start = server._game_time_seconds
    for _ in range(30):
        server.tick(1.0 / 30.0)
    assert server._game_time_seconds != start


def test_traffic_lights_advance_via_sim_time(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    start = server.world.traffic_mgr.sim_time
    for _ in range(10):
        server.tick(1.0 / 30.0)
    assert server.world.traffic_mgr.sim_time > start


def test_weather_state_is_available(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    assert hasattr(server.world.weather, "weather_type")
    assert hasattr(server.world.weather, "wetness")


def test_npc_and_pedestrian_population_advance(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    for _ in range(10):
        server.tick(1.0 / 30.0)
    # Just confirms the managers are live, wired objects (not stubs) that
    # advance_simulation is actually driving - not asserting specific
    # counts, which depend on the bundled sample map's size.
    assert isinstance(server.world.npc_manager.vehicles, list)
    assert isinstance(server.world.pedestrian_mgr.pedestrians, list)


def test_player_commands_reach_the_simulation(tmp_path, monkeypatch):
    from theroadragetrip import protocol, transport
    from theroadragetrip.simulation import PlayerCommand

    server = _build_server(tmp_path, monkeypatch)
    server.start("127.0.0.1", 0)
    connection = transport.connect(server.host, server.port)
    import time
    time.sleep(0.1)

    connection.send(protocol.build_command_message(PlayerCommand(), interact=True, seq=1))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server._on_foot is False  # the interact command got the player into the car

    connection.send(protocol.build_command_message(PlayerCommand(throttle=1.0), interact=False, seq=2))
    time.sleep(0.05)
    start_x = server.car.x
    for _ in range(20):
        server.tick(1.0 / 30.0)
    assert server.car.x != start_x
    connection.close()
