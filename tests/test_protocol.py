"""client-server-02.md step 13/19: the wire protocol itself, independent
of any real simulation."""

import json

import pytest

from theroadragetrip import protocol
from theroadragetrip.simulation import PlayerCommand


def test_command_round_trips_through_encode_decode():
    command = PlayerCommand(throttle=1.0, steer_left=0.5, sprint=True, refuel=True,
                            lane_assist_enabled=True, respawn=True, cancel_ride=True, reset_trip=True)
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


def test_character_details_reach_godot_state():
    from datetime import date
    from types import SimpleNamespace as Row

    resident = Row(resident_id=7, first_name="Aino", surname="Korhonen", gender="female",
                   birth_date=date(1990, 4, 5), mode="driving")
    npc = Row(vehicle_id=8, x=1.0, y=2.0, heading=0.0, speed=3.0, color=(1, 2, 3),
              vehicle_type="car", is_taxi=False, is_police=False, is_on_foot=False,
              fallen=False, layer=0, lod_level=0, turn_signal="", turn_signal_elapsed=0.0,
              state="DRIVING", braking=False, crashed_timer=0.0, driver_departed=False,
              debug_waiting_for="", car=Row(length_m=4.0, width_m=1.8), owner_id=7,
              occupant_ids=(7,), passenger_ids=(), current_driver_id=7)
    ped = Row(resident_id=7, x=1.0, y=2.0, heading=0.0, radius_m=0.45, color=(1, 2, 3),
              state="walking", animation_state="walking", animation_time=0.0,
              curse_timer=0.0, curse_text="", mood="normal", is_cyclist=False,
              blood_alcohol_promille=0.5, activity=None)
    vehicle = protocol._npc_to_dict(npc, {7: resident})
    walker = protocol._pedestrian_to_dict(ped, {7: resident})
    assert vehicle["owner"]["name"] == "Aino Korhonen"
    assert vehicle["occupants"] == [vehicle["owner"]]
    assert walker["resident"]["birth_date"] == "1990-04-05"
    assert walker["blood_alcohol_promille"] == 0.5


def test_the_waiting_customer_crosses_the_wire():
    """godot-07: a client draws the customer waiting at (or walking to) the
    taxi from these fields."""
    from theroadragetrip.taxi import TaxiPassenger, TaxiTarget

    passenger = TaxiPassenger(
        name="Aino", pickup=TaxiTarget(x=10.0, y=20.0, address="Kirkkokatu 4"),
        dropoff=TaxiTarget(x=500.0, y=-40.0, address="Rautatientori"),
        ped_x=11.5, ped_y=19.0, ped_heading=1.25, is_walking_to_car=True,
    )
    data = protocol._passenger_to_dict(passenger)
    assert data["ped"] == [11.5, 19.0, 1.25] and data["is_walking_to_car"] is True
    assert data["boarded"] is False and data["rail_booking"] is False
    assert json.loads(json.dumps(data)) == data  # plain JSON on the wire


@pytest.mark.parametrize("message", [
    {}, {"command": None}, {"command": [1, 2]}, {"command": "throttle"}, {"command": {}},
])
def test_a_command_without_a_valid_payload_is_no_input(message):
    """These raised in the server's tick, which nothing catches: one bad
    client command stopped the server."""
    command, interact = protocol.command_from_message(message)
    assert command == PlayerCommand() and interact is False


def test_command_fields_of_the_wrong_type_or_range_are_not_trusted():
    command, interact = protocol.command_from_message({"command": {
        "throttle": "full", "brake": float("nan"), "steer_left": 50, "steer_right": -3,
        "forward": True, "turn": -7.5, "sprint": "yes", "refuel": 1, "respawn": True,
        "engine_on": "off", "interact": "true", "unknown_field": 1,
    }})
    assert command == PlayerCommand(steer_left=1.0, steer_right=0.0, turn=-1.0, respawn=True)
    assert interact is False  # only a real true presses the key


def test_extremely_large_json_integers_are_clamped_without_overflow():
    wire = protocol.encode({"type": "command", "version": protocol.PROTOCOL_VERSION,
                            "command": {"throttle": 10**400, "forward": -(10**400)}})
    decoded = protocol.decode(wire.rstrip(b"\n"))
    command, _ = protocol.command_from_message(decoded)
    assert command.throttle == 1.0 and command.forward == -1.0


def test_random_command_payloads_never_raise_and_stay_in_range():
    import random

    rng = random.Random(18)
    junk = [None, True, False, 0, 1, -1, 2.5, -1e9, 1e309, float("nan"), "", "x", [], {}, [1], {"a": 1}]
    names = list(PlayerCommand.__dataclass_fields__) + ["interact", "extra"]
    for _ in range(2000):
        payload = {name: rng.choice(junk) for name in rng.sample(names, rng.randint(0, len(names)))}
        command, interact = protocol.command_from_message({"command": payload})
        assert isinstance(interact, bool)
        for name, (low, high) in protocol.COMMAND_RANGES.items():
            value = getattr(command, name)
            assert isinstance(value, float) and low <= value <= high
        for name in PlayerCommand.__dataclass_fields__:
            if name not in protocol.COMMAND_RANGES:
                assert isinstance(getattr(command, name), bool) or (name == "engine_on" and command.engine_on is None)
