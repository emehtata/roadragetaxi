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


def test_owned_dog_travels_with_its_one_pedestrian_owner():
    from types import SimpleNamespace as Row

    dog = Row(x=8.5, y=2.4, heading=0.2, size="large", color=(86, 57, 37), sniffing=True)
    ped = Row(resident_id=7, x=10.0, y=2.0, heading=0.0, radius_m=0.45, color=(1, 2, 3),
              state="performing_activity", animation_state="idle", animation_time=0.0,
              curse_timer=0.0, curse_text="", mood="normal", is_cyclist=False,
              blood_alcohol_promille=0.0, activity=Row(plugin_id="dog_walking"), dog=dog)

    walker = protocol._pedestrian_to_dict(ped)

    assert walker["activity"] == "dog_walking"
    assert walker["dog"] == {"x": 8.5, "y": 2.4, "heading": 0.2, "size": "large",
                             "color": [86, 57, 37], "sniffing": True}


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


def test_state_rows_leave_out_defaults_and_round_floats():
    from theroadragetrip.protocol import compact_row
    row = {"id": 4, "x": 427016.293847, "y": 7217324.812233, "heading": -1.70123456, "thief": False, "layer": 0,
           "occupants": [], "owner": None, "curse_timer": 0.0, "mood": "normal", "color": [1, 2, 3], "is_taxi": True}
    assert compact_row(row) == {"id": 4, "x": 427016.29, "y": 7217324.81, "heading": -1.701, "color": [1, 2, 3], "is_taxi": True}
    assert compact_row({"layer": 1, "curse_timer": 0.4, "mood": "annoyed"}) == {"layer": 1, "curse_timer": 0.4, "mood": "annoyed"}


def test_residents_are_sent_only_for_the_inspected_entity():
    from types import SimpleNamespace
    from theroadragetrip.protocol import _inspected
    assert _inspected({"kind": "npc", "id": 7}, "npc", 7) and not _inspected({"kind": "npc", "id": 7}, "npc", 8)
    assert not _inspected(None, "pedestrian", 7) and not _inspected({"kind": "npc", "id": 7}, "pedestrian", 7)
    from theroadragetrip.protocol import _pedestrian_to_dict
    from theroadragetrip.pedestrian import Pedestrian
    ped = Pedestrian(x=0.0, y=0.0, heading=0.0, speed=1.0, base_speed=1.0, way=None, segment_idx=0, direction=1,
                     color=(1, 2, 3), resident_id=5)
    residents = {5: SimpleNamespace(resident_id=5, name="Aino", birth_date="2000-01-01", gender="female", age=26,
                                    household_id=None, mode="walking", personality={})}
    assert _pedestrian_to_dict(ped, residents, person=False)["resident"] is None
