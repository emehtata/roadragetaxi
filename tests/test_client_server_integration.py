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


def _tick_until(server, condition, timeout=2.0):
    """Tick until `condition()` - the server notices a closed client on its
    reader thread, which shares the GIL with the test client's (busy
    parsing map chunks), so a fixed sleep is flaky."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
        server.tick(1.0 / 30.0)
    return condition()


def test_client_disconnect_is_handled_cleanly(monkeypatch):
    from theroadragetrip import transport

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert len(server._clients) == 1

    connection.close()
    # a tick's _apply_incoming_messages prunes closed connections
    assert _tick_until(server, lambda: len(server._clients) == 0)


def _all_messages(connection):
    time.sleep(0.05)
    return connection.try_recv_all()


def test_a_new_client_first_gets_the_map_then_states_with_trains_and_events(monkeypatch):
    """What the Godot client relies on: a world header (origin, its
    player_id), the map chunks around the player, then per-tick states
    carrying trains and semantic events."""
    from theroadragetrip import map_chunks, protocol, transport
    from theroadragetrip.simulation import PlayerCommand

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    messages = _all_messages(connection)
    assert [m["type"] for m in messages] == ["world"]
    assert messages[0]["player_id"] == protocol.LOCAL_PLAYER_ID
    assert messages[0]["chunk_size_m"] == map_chunks.CHUNK_SIZE_M

    server.tick(1.0 / 30.0)
    messages = _all_messages(connection)
    chunks = [m for m in messages if m["type"] == "chunk"]
    assert len(chunks) == (2 * map_chunks.LOAD_RADIUS + 1) ** 2
    assert messages[-1]["type"] == "state"  # the map arrives before the state that needs it
    roads = [road for chunk in chunks for road in chunk["roads"]]
    assert roads and all(len(point) == 2 for point in roads[0]["points"])
    assert {"half_width_m", "drivable"} <= set(roads[0])
    assert "kind" not in roads[0]

    connection.send(protocol.build_command_message(PlayerCommand(), interact=True, seq=1))  # get in
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    state = _all_messages(connection)[-1]
    assert state["type"] == "state" and isinstance(state["state"]["trains"], list)
    # getting in opens the door, once (godot-03.md: the Stable Audio door-open sound)
    assert [e for e in state["state"]["events"] if e.get("group", "").startswith("vehicle.door")] == [
        {"type": "sound", "group": "vehicle.door_open"}]
    server.tick(1.0 / 30.0)
    assert _all_messages(connection)[-1]["state"]["events"] == []  # each event is sent once
    connection.close()


def test_a_client_can_reconnect_and_gets_the_map_again(monkeypatch):
    from theroadragetrip import transport

    server = _start_server(monkeypatch)
    first = transport.connect(server.host, server.port)
    time.sleep(0.05)
    first.close()
    assert _tick_until(server, lambda: not server._clients)
    second = transport.connect(server.host, server.port)
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    types = [m["type"] for m in _all_messages(second)]
    assert types[0] == "world" and "state" in types
    second.close()


def test_a_departed_clients_input_stops_driving(monkeypatch):
    """Regression: the last command (held throttle) kept driving the taxi
    after its client disconnected."""
    from theroadragetrip import protocol, transport
    from theroadragetrip.simulation import PlayerCommand

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    connection.send(protocol.build_command_message(PlayerCommand(throttle=1.0, engine_on=True), interact=False, seq=1))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server._latest_command.throttle == 1.0
    connection.close()
    assert _tick_until(server, lambda: server._latest_command == PlayerCommand())


def test_the_simulation_runs_without_any_client(monkeypatch):
    server = _start_server(monkeypatch)
    start = server.world.traffic_mgr.sim_time
    for _ in range(30):
        server.tick(1.0 / 30.0)
    assert server._tick == 30 and server.world.traffic_mgr.sim_time > start


def _chunk_messages(connection):
    messages = _all_messages(connection)
    return ([m["chunk_id"] for m in messages if m["type"] == "chunk"],
            [m["chunk_id"] for m in messages if m["type"] == "chunk_unload"])


def test_map_chunks_follow_the_player_without_resending(monkeypatch):
    from theroadragetrip import map_chunks, transport

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    first, _ = _chunk_messages(connection)
    assert len(first) == len(set(first)) == 49

    server.tick(1.0 / 30.0)  # same place: nothing new
    assert _chunk_messages(connection) == ([], [])

    player = server.world.player_pedestrian  # on foot at start
    player.x += map_chunks.CHUNK_SIZE_M  # one chunk east (a teleport: tests the plan, not walking)
    server.tick(1.0 / 30.0)
    loaded, dropped = _chunk_messages(connection)
    assert len(loaded) == 7 and not set(loaded) & set(first)  # just the new column
    assert dropped == []  # the far west column is still within the unload radius
    player.x += map_chunks.CHUNK_SIZE_M
    server.tick(1.0 / 30.0)
    loaded, dropped = _chunk_messages(connection)
    assert len(loaded) == 7 and len(dropped) == 7 and set(dropped) <= set(first)
    connection.close()


def test_commands_carry_the_player_id_and_others_are_ignored(monkeypatch):
    from theroadragetrip import protocol, transport
    from theroadragetrip.simulation import PlayerCommand

    message = protocol.build_command_message(PlayerCommand(), interact=False, seq=1)
    assert message["player_id"] == protocol.LOCAL_PLAYER_ID
    assert protocol.command_player_id({"type": "command"}) == protocol.LOCAL_PLAYER_ID  # older clients

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    connection.send(protocol.build_command_message(PlayerCommand(throttle=1.0), interact=False, seq=1, player_id="someone_else"))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server._latest_command == PlayerCommand()
    connection.send(protocol.build_command_message(PlayerCommand(throttle=1.0), interact=False, seq=2))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server._latest_command.throttle == 1.0
    state = [m for m in _all_messages(connection) if m["type"] == "state"][-1]
    assert "player_id" not in state["state"]  # sent once in the world header, not repeated at 30 Hz
    assert state["server_time"] > 0
    connection.close()


def _phone_round(server, connection, **phone):
    from theroadragetrip import protocol
    from theroadragetrip.simulation import PlayerCommand

    connection.send(protocol.build_command_message(PlayerCommand(), interact=False, seq=1, phone=phone))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    state = [m for m in _all_messages(connection) if m["type"] == "state"][-1]["state"]
    return state, [e for e in state["events"] if e["type"] == "phone_result"]


def test_the_phone_shows_offers_and_answers_by_id(monkeypatch):
    """godot-05: phone rows come from the simulation; a client accepts or
    rejects one by id, once, and hears the outcome as a phone_result."""
    from theroadragetrip import transport

    server = _start_server(monkeypatch)
    taxi_mgr = server.world.taxi_mgr
    taxi_mgr.offers = []
    offers = taxi_mgr.generate_offers(server.car.x, server.car.y, count=3)
    assert len(offers) >= 2, "the sample map should offer rides"
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    phone = [m for m in _all_messages(connection) if m["type"] == "state"][-1]["state"]["phone"]
    ids = [item["id"] for item in phone["items"]]
    assert phone["busy"] is False and len(set(ids)) == len(ids) == len(offers)
    first = phone["items"][0]
    assert first["kind"] == "offer" and first["name"] == offers[0].passenger.name
    assert first["pickup"] == offers[0].passenger.pickup.address and first["dropoff"] == offers[0].passenger.dropoff.address
    assert first["pickup_distance_m"] >= 0 and first["trip_distance_m"] > 0 and "fare" not in first  # no fare before the ride

    state, results = _phone_round(server, connection, action="reject", item_id=ids[1], request_id=1)
    assert results == [{"type": "phone_result", "action": "reject", "item_id": ids[1], "request_id": 1, "ok": True, "reason": ""}]
    assert ids[1] not in [item["id"] for item in state["phone"]["items"]]
    assert {"type": "sound", "group": "ui.reject"} in state["events"]

    state, results = _phone_round(server, connection, action="accept", item_id=ids[0], request_id=2)
    assert results[0]["ok"] is True and taxi_mgr.current_passenger is offers[0].passenger
    assert state["phone"] == {"busy": True, "items": []}
    state, results = _phone_round(server, connection, action="accept", item_id=ids[0], request_id=3)
    assert results[0]["ok"] is False and results[0]["reason"] == "gone"  # a repeat changes nothing
    assert taxi_mgr.current_passenger is offers[0].passenger

    state, results = _phone_round(server, connection, action="steal", item_id=ids[0])
    assert results == []  # malformed phone requests are ignored
    connection.close()


def test_a_refuel_press_buys_fuel_once(monkeypatch):
    """godot-final-01: `refuel` is edge-triggered like `interact`. The server
    replays the latest command every tick, so a held `refuel: true` used to buy
    again each tick ("tank full" then overwrote the purchase), and a press
    followed by another command within one tick was lost."""
    from types import SimpleNamespace

    from theroadragetrip import protocol, transport
    from theroadragetrip.fuel import calculate_fuel_purchase, fuel_station_price_cents
    from theroadragetrip.simulation import PlayerCommand

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    connection.send(protocol.build_command_message(PlayerCommand(), interact=True, seq=1))  # get in
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server._on_foot is False
    car, taxi_mgr = server.car, server.world.taxi_mgr
    station = SimpleNamespace(kind="fuel", x=car.x + 5.0, y=car.y, id=4242)
    server.world.scenery_objects = list(getattr(server.world, "scenery_objects", ())) + [station]
    car.speed = 0.0
    car.fuel_l = 10.0
    taxi_mgr.balance_cents = 100_000
    expected = calculate_fuel_purchase(10.0, car.fuel_capacity_l, 100_000, fuel_station_price_cents(station))

    # The press, then (within the same tick) the next ordinary command.
    connection.send(protocol.build_command_message(PlayerCommand(refuel=True), interact=False, seq=2))
    connection.send(protocol.build_command_message(PlayerCommand(), interact=False, seq=3))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    time.sleep(0.05)
    assert [e for e in _all_messages(connection)[-1]["state"]["events"] if e.get("group") == "taxi.refuel"]  # the pump sound, once
    for _ in range(4):
        server.tick(1.0 / 30.0)
    time.sleep(0.05)
    assert car.fuel_l == pytest.approx(min(car.fuel_capacity_l, 10.0 + expected.liters))
    assert taxi_mgr.balance_cents == 100_000 - expected.cost_cents  # charged once
    assert "fuel_tank_full" not in taxi_mgr.notification_msg and taxi_mgr.notification_msg  # the purchase notice stays
    state = _all_messages(connection)[-1]["state"]
    assert state["player"]["fuel_l"] == pytest.approx(car.fuel_l)  # what the client's gauge shows
    assert state["taxi"]["balance_cents"] == taxi_mgr.balance_cents

    # A full tank - even after idling a sliver away since the fill-up (the
    # receipt said "0.0 l" yet cost a cent) - then an empty purse: nothing is bought.
    balance = taxi_mgr.balance_cents
    car.fuel_l = car.fuel_capacity_l - 0.004
    connection.send(protocol.build_command_message(PlayerCommand(refuel=True), interact=False, seq=4))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert taxi_mgr.balance_cents == balance
    from theroadragetrip.localization import tr
    assert taxi_mgr.notification_msg in (tr("fi", "fuel_tank_full"), tr("en", "fuel_tank_full"))
    car.fuel_l = 5.0
    taxi_mgr.balance_cents = 0
    connection.send(protocol.build_command_message(PlayerCommand(refuel=True), interact=False, seq=5))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert car.fuel_l == 5.0 and taxi_mgr.balance_cents == 0

    # Out of range: no station within 8 m.
    server.world.scenery_objects.remove(station)
    taxi_mgr.balance_cents = 100_000
    connection.send(protocol.build_command_message(PlayerCommand(refuel=True), interact=False, seq=6))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert car.fuel_l == 5.0 and taxi_mgr.balance_cents == 100_000
    connection.close()


def test_a_road_rage_press_acts_once_and_a_new_client_sees_the_shout(monkeypatch):
    """godot-final-05: `road_rage` is edge-triggered like refuel; the shout
    is server state a client connecting mid-shout receives."""
    from theroadragetrip import protocol, transport
    from theroadragetrip.simulation import RAGE_SHOUTS, PlayerCommand

    assert PlayerCommand().road_rage is False
    decoded, _ = protocol.command_from_message(protocol.decode(protocol.encode(
        protocol.build_command_message(PlayerCommand(road_rage=True), interact=False, seq=1))))
    assert decoded.road_rage is True

    server = _start_server(monkeypatch)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    server._rage_power = 0.9
    connection.send(protocol.build_command_message(PlayerCommand(road_rage=True), interact=False, seq=1))
    connection.send(protocol.build_command_message(PlayerCommand(), interact=False, seq=2))  # the next ordinary command, same tick
    time.sleep(0.05)
    for _ in range(10):
        server.tick(1.0 / 30.0)
    assert server._latest_command.road_rage is False
    assert server._rage_power == pytest.approx(0.65, abs=0.02)  # spent once, not each tick
    later = transport.connect(server.host, server.port)  # joins during the shout
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert _tick_until(server, lambda: any(m.get("type") == "state" for m in _peek(later)))
    state = [m for m in _seen[later] if m.get("type") == "state"][-1]["state"]
    assert state["road_rage"]["text"] in RAGE_SHOUTS and 0.0 < state["road_rage"]["timer"] < 5.0
    connection.close()
    later.close()


_seen: dict = {}


def _peek(connection):
    _seen.setdefault(connection, []).extend(connection.try_recv_all())
    return _seen[connection]
