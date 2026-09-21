"""client-server-02.md step 13/19: the wire protocol itself, independent
of any real simulation or Pygame."""

import ast

import pytest

from theroadragetrip import protocol, transport
from theroadragetrip.simulation import PlayerCommand


def _assert_no_pygame_import(module) -> None:
    tree = ast.parse(open(module.__file__).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.split(".")[0] == "pygame" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or node.module.split(".")[0] != "pygame"


def test_command_round_trips_through_encode_decode():
    command = PlayerCommand(throttle=1.0, steer_left=0.5, sprint=True)
    message = protocol.build_command_message(command, interact=True, seq=7)
    wire = protocol.encode(message)
    assert wire.endswith(b"\n")

    decoded = protocol.decode(wire.rstrip(b"\n"))
    assert decoded["type"] == "command"
    assert decoded["seq"] == 7

    round_tripped, interact = protocol.command_from_message(decoded)
    assert round_tripped == command
    assert interact is True


def test_decode_rejects_wrong_protocol_version():
    message = {"type": "command", "version": 999, "command": {}}
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(protocol.encode(message).rstrip(b"\n"))


def test_decode_rejects_malformed_json():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b"not json at all")


def test_decode_rejects_missing_type():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(protocol.encode({"version": protocol.PROTOCOL_VERSION}).rstrip(b"\n"))


def test_reconcile_npcs_adds_updates_and_removes_by_id():
    vehicles = []
    npc_data = {
        "id": 1, "x": 1.0, "y": 2.0, "heading": 0.0, "speed": 3.0, "color": [1, 2, 3],
        "vehicle_type": "car", "is_taxi": False, "is_police": False, "is_on_foot": False,
        "fallen": False, "layer": 0, "lod_level": 0, "turn_signal": "", "turn_signal_elapsed": 0.0,
        "state": "CRASHED", "crashed_timer": 1.5, "driver_departed": True,
        "debug_waiting_for": "accident", "length_m": 4.0, "width_m": 1.8,
    }
    protocol._reconcile_npcs(vehicles, [npc_data])
    assert len(vehicles) == 1
    assert vehicles[0].vehicle_id == 1 and vehicles[0].x == 1.0
    assert vehicles[0].state == "CRASHED"
    assert vehicles[0].crashed_timer == 1.5
    assert vehicles[0].driver_departed is True

    moved = dict(npc_data, x=5.0)
    protocol._reconcile_npcs(vehicles, [moved])
    assert len(vehicles) == 1
    assert vehicles[0].x == 5.0

    protocol._reconcile_npcs(vehicles, [])
    assert vehicles == []


def test_reconcile_pedestrians_adds_updates_and_removes_by_id():
    pedestrians = []
    ped_data = {
        "id": 42, "x": 1.0, "y": 2.0, "heading": 0.0, "radius_m": 0.45, "color": [4, 5, 6],
        "state": "walking", "animation_state": "walking", "animation_time": 0.0,
        "curse_timer": 0.0, "curse_text": "@#*!%", "mood": "normal", "is_cyclist": False,
    }
    protocol._reconcile_pedestrians(pedestrians, [ped_data])
    assert len(pedestrians) == 1
    assert pedestrians[0].resident_id == 42

    protocol._reconcile_pedestrians(pedestrians, [])
    assert pedestrians == []


def test_interpolate_state_blends_positions_and_headings():
    prev = {"player": {"x": 0.0, "y": 0.0, "heading": 0.0}, "npcs": [], "pedestrians": []}
    curr = {"player": {"x": 10.0, "y": 0.0, "heading": 3.0}, "npcs": [], "pedestrians": []}

    blended = protocol.interpolate_state(prev, curr, 0.5)
    assert blended["player"]["x"] == pytest.approx(5.0)
    assert blended["player"]["heading"] == pytest.approx(1.5)


def test_interpolate_state_clamps_alpha_to_0_1():
    prev = {"player": {"x": 0.0, "y": 0.0, "heading": 0.0}, "npcs": [], "pedestrians": []}
    curr = {"player": {"x": 10.0, "y": 0.0, "heading": 0.0}, "npcs": [], "pedestrians": []}

    over = protocol.interpolate_state(prev, curr, 5.0)
    under = protocol.interpolate_state(prev, curr, -5.0)
    assert over["player"]["x"] == pytest.approx(10.0)
    assert under["player"]["x"] == pytest.approx(0.0)


def test_interpolate_state_snaps_in_a_newly_appeared_entity():
    prev = {"player": {"x": 0.0, "y": 0.0, "heading": 0.0}, "npcs": [], "pedestrians": []}
    curr = {
        "player": {"x": 0.0, "y": 0.0, "heading": 0.0},
        "npcs": [{"id": 1, "x": 9.0, "y": 9.0, "heading": 1.0}],
        "pedestrians": [],
    }
    blended = protocol.interpolate_state(prev, curr, 0.5)
    assert blended["npcs"][0]["x"] == 9.0  # no prior sample to blend from - just use curr


def test_no_pygame_reference_in_protocol_module():
    _assert_no_pygame_import(protocol)


def test_no_pygame_reference_in_transport_module():
    _assert_no_pygame_import(transport)
