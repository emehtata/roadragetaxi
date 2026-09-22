"""The client/server wire protocol (client-server-02.md).

A tiny versioned envelope over newline-delimited JSON. Deliberately not
tied to JSON at the call-site level: `encode`/`decode` are the only
places that know the wire format, so swapping to a binary encoding later
only touches this module. No pickle, no raw Python objects on the wire.

Two message shapes cross the boundary:

- client -> server: `{"type": "command", "version": 1, "seq": N, "command": {...}}`
  built by `build_command_message`. `command` mirrors
  `simulation.PlayerCommand`'s fields plus one edge-triggered
  `interact` flag for the discrete "enter/exit vehicle" action.
- server -> client: `{"type": "state", "version": 1, "tick": N, "state": {...}}`
  built by `build_state_message`, applied on the client by
  `apply_server_state`. Only dynamic gameplay state - static map geometry
  never crosses this boundary (see docs/architecture/simulation-rendering.md).

This module must never import pygame, for the same reason simulation.py
doesn't: it's shared, unmodified, by the headless server.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any, Optional

from .geo import angle_diff
from .simulation import PlayerCommand
from .taxi import TaxiPassenger, TaxiTarget

PROTOCOL_VERSION = 1


class ProtocolError(Exception):
    """A malformed message, or one from an incompatible protocol version."""


def encode(message: dict) -> bytes:
    """A message -> one newline-delimited JSON line."""
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict:
    """One line of wire data -> a message dict. Raises ProtocolError on
    anything malformed or from a version this build doesn't understand."""
    try:
        message = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"malformed message: {exc}") from exc
    if not isinstance(message, dict) or "type" not in message:
        raise ProtocolError("message missing 'type'")
    if message.get("version") != PROTOCOL_VERSION:
        raise ProtocolError(
            f"protocol version mismatch: got {message.get('version')!r}, expected {PROTOCOL_VERSION}"
        )
    return message


def build_command_message(command: PlayerCommand, *, interact: bool, seq: int) -> dict:
    payload = asdict(command)
    payload["interact"] = interact
    return {"type": "command", "version": PROTOCOL_VERSION, "seq": seq, "command": payload}


def command_from_message(message: dict) -> tuple[PlayerCommand, bool]:
    """The inverse of `build_command_message` - used by the server."""
    payload = dict(message["command"])
    interact = bool(payload.pop("interact", False))
    command = PlayerCommand(**{k: payload[k] for k in PlayerCommand.__dataclass_fields__ if k in payload})
    return command, interact


def _npc_to_dict(npc) -> dict:
    return {
        "id": npc.vehicle_id,
        "x": npc.x,
        "y": npc.y,
        "heading": npc.heading,
        "speed": npc.speed,
        "color": list(npc.color),
        "vehicle_type": npc.vehicle_type,
        "is_taxi": npc.is_taxi,
        "is_police": npc.is_police,
        "is_on_foot": npc.is_on_foot,
        "fallen": npc.fallen,
        "layer": npc.layer,
        "lod_level": npc.lod_level,
        "turn_signal": npc.turn_signal,
        "turn_signal_elapsed": npc.turn_signal_elapsed,
        "state": npc.state,
        "crashed_timer": npc.crashed_timer,
        "driver_departed": npc.driver_departed,
        "debug_waiting_for": npc.debug_waiting_for,
        "length_m": npc.car.length_m,
        "width_m": npc.car.width_m,
    }


def _pedestrian_to_dict(ped) -> dict:
    return {
        "id": ped.resident_id,
        "x": ped.x,
        "y": ped.y,
        "heading": ped.heading,
        "radius_m": ped.radius_m,
        "color": list(ped.color),
        "state": ped.state,
        "animation_state": ped.animation_state,
        "animation_time": ped.animation_time,
        "curse_timer": ped.curse_timer,
        "curse_text": ped.curse_text,
        "mood": ped.mood,
        "is_cyclist": ped.is_cyclist,
    }


def _passenger_to_dict(passenger: Optional[TaxiPassenger]) -> Optional[dict]:
    if passenger is None:
        return None
    return {
        "name": passenger.name,
        "gender": passenger.gender,
        "weight_kg": passenger.weight_kg,
        "is_drunk": passenger.is_drunk,
        "motion_sickness": passenger.motion_sickness,
        "nausea_warning_timer": passenger.nausea_warning_timer,
        "nausea_resolved": passenger.nausea_resolved,
        "pickup": {
            "x": passenger.pickup.x, "y": passenger.pickup.y, "address": passenger.pickup.address,
            "radius_m": passenger.pickup.radius_m,
        },
        "dropoff": {
            "x": passenger.dropoff.x, "y": passenger.dropoff.y, "address": passenger.dropoff.address,
            "radius_m": passenger.dropoff.radius_m,
        },
    }


def build_state_message(
    *, tick: int, world, car, on_foot: bool, player_pedestrian, game_time_seconds: float,
    camx: float, camy: float, rage_power: float, water_elapsed: float,
    should_stop: bool = False, city_summary: Optional[tuple] = None,
) -> dict:
    """Everything the Pygame client needs to render one frame, and nothing
    static (see module docstring). Called once per server tick."""
    weather = world.weather
    taxi_mgr = world.taxi_mgr
    traffic_mgr = world.traffic_mgr
    state = {
        "game_time_seconds": game_time_seconds,
        "sim_time": traffic_mgr.sim_time,
        "on_foot": on_foot,
        # The camera-follow lookahead depends on car speed/heading, which
        # only the server computes - see architecture doc's note that a
        # real multi-client future should move this client-side instead.
        "camx": camx,
        "camy": camy,
        "rage_power": rage_power,
        "water_elapsed": water_elapsed,
        "player": {
            "x": car.x, "y": car.y, "heading": car.heading, "speed": car.speed,
            "braking": car.braking, "trip_m": car.trip_m, "odometer_m": car.odometer_m,
            "engine_on": car.engine_on, "fuel_l": car.fuel_l,
            "fuel_capacity_l": car.fuel_capacity_l,
            "fuel_consumption_l_per_100km": car.fuel_consumption_l_per_100km,
            "curb_mass_kg": car.curb_mass_kg,
            "driver_mass_kg": car.driver_mass_kg,
            "passenger_mass_kg": car.passenger_mass_kg,
        },
        "player_pedestrian": {
            "x": player_pedestrian.x, "y": player_pedestrian.y, "heading": player_pedestrian.heading,
        },
        "npcs": [_npc_to_dict(npc) for npc in world.npc_manager.vehicles],
        "pedestrians": [_pedestrian_to_dict(p) for p in world.pedestrian_mgr.pedestrians if p.resident_id is not None],
        "weather": {"weather_type": weather.weather_type.value, "wetness": weather.wetness},
        "taxi": {
            "state": taxi_mgr.state,
            "total_score": taxi_mgr.total_score,
            "completed_fares": taxi_mgr.completed_fares,
            "balance_cents": taxi_mgr.balance_cents,
            "notification_msg": taxi_mgr.notification_msg,
            "notification_timer": taxi_mgr.notification_timer,
            "taxi_smoke_timer": taxi_mgr.taxi_smoke_timer,
            "current_passenger": _passenger_to_dict(taxi_mgr.current_passenger),
        },
        # Career-mode session end (score threshold reached -> next city or
        # completed). Not fully wired end-to-end this phase - see
        # docs/architecture/simulation-rendering.md's known limitations.
        "should_stop": should_stop,
        "city_summary": list(city_summary) if city_summary is not None else None,
    }
    return {"type": "state", "version": PROTOCOL_VERSION, "tick": tick, "state": state}


def _lerp_angle(a: float, b: float, alpha: float) -> float:
    """Shortest-path angle interpolation (radians) - a plain lerp would
    spin the long way round whenever a heading crosses the +-pi seam."""
    diff = angle_diff(b, a)
    return a + diff * alpha


def interpolate_state(prev: dict, curr: dict, alpha: float) -> dict:
    """Visual-only blend between two received state snapshots (client-
    server-02.md step 10). `alpha` is clamped to [0, 1] - this never
    extrapolates past the newest authoritative snapshot, and it never
    feeds back into anything the server treats as authoritative; it only
    changes what gets rendered this frame."""
    alpha = max(0.0, min(1.0, alpha))
    # A shallow copy is enough: every key this function overwrites below
    # (player/npcs/pedestrians) is fully replaced, never mutated in
    # place, and every other key (weather/taxi/...) is only ever read by
    # the caller, never mutated - a deepcopy here was pure waste, run
    # once per render frame on a dict containing every NPC/pedestrian.
    blended = dict(curr)

    def blend_entity(prev_entity: Optional[dict], curr_entity: dict) -> dict:
        if prev_entity is None:
            return curr_entity
        merged = dict(curr_entity)
        merged["x"] = prev_entity["x"] + (curr_entity["x"] - prev_entity["x"]) * alpha
        merged["y"] = prev_entity["y"] + (curr_entity["y"] - prev_entity["y"]) * alpha
        merged["heading"] = _lerp_angle(prev_entity["heading"], curr_entity["heading"], alpha)
        return merged

    blended["player"] = blend_entity(prev.get("player"), curr["player"])

    prev_npcs = {n["id"]: n for n in prev.get("npcs", [])}
    blended["npcs"] = [blend_entity(prev_npcs.get(n["id"]), n) for n in curr["npcs"]]

    prev_peds = {p["id"]: p for p in prev.get("pedestrians", [])}
    blended["pedestrians"] = [blend_entity(prev_peds.get(p["id"]), p) for p in curr["pedestrians"]]

    return blended


def apply_server_state(world, car, state: dict, *, player_pedestrian) -> dict:
    """Apply a received state dict onto local shadow objects. Never calls
    `.update()`/AI methods on any manager - entities only ever change here,
    driven entirely by the server's authoritative snapshot.

    Returns the handful of scalars the caller doesn't already hold a
    reference to: on_foot, game_time_seconds, camx, camy, should_stop,
    city_summary.
    """
    player = state["player"]
    car.x, car.y, car.heading, car.speed = player["x"], player["y"], player["heading"], player["speed"]
    car.braking = player["braking"]
    car.trip_m = player["trip_m"]
    car.odometer_m = player["odometer_m"]
    car.engine_on = player["engine_on"]
    car.fuel_capacity_l = player.get("fuel_capacity_l", car.fuel_capacity_l)
    car.fuel_l = player.get("fuel_l", car.fuel_l)
    car.fuel_consumption_l_per_100km = player.get(
        "fuel_consumption_l_per_100km", car.fuel_consumption_l_per_100km
    )
    car.curb_mass_kg = player.get("curb_mass_kg", car.curb_mass_kg)
    car.driver_mass_kg = player.get("driver_mass_kg", car.driver_mass_kg)
    car.passenger_mass_kg = player.get("passenger_mass_kg", car.passenger_mass_kg)

    ped = state["player_pedestrian"]
    player_pedestrian.x, player_pedestrian.y, player_pedestrian.heading = ped["x"], ped["y"], ped["heading"]

    _reconcile_npcs(world.npc_manager.vehicles, state["npcs"])
    _reconcile_pedestrians(world.pedestrian_mgr.pedestrians, state["pedestrians"])

    world.traffic_mgr.sim_time = state["sim_time"]

    weather = state["weather"]
    world.weather.weather_type = type(world.weather.weather_type)(weather["weather_type"])
    world.weather.wetness = weather["wetness"]

    taxi = state["taxi"]
    taxi_mgr = world.taxi_mgr
    taxi_mgr.state = taxi["state"]
    taxi_mgr.total_score = taxi["total_score"]
    taxi_mgr.completed_fares = taxi["completed_fares"]
    taxi_mgr.balance_cents = taxi.get("balance_cents", taxi_mgr.balance_cents)
    taxi_mgr.notification_msg = taxi["notification_msg"]
    taxi_mgr.notification_timer = taxi["notification_timer"]
    taxi_mgr.taxi_smoke_timer = taxi["taxi_smoke_timer"]
    taxi_mgr.current_passenger = _passenger_from_dict(taxi["current_passenger"])

    return {
        "on_foot": state["on_foot"],
        "game_time_seconds": state["game_time_seconds"],
        "camx": state["camx"],
        "camy": state["camy"],
        "rage_power": state["rage_power"],
        "water_elapsed": state["water_elapsed"],
        "should_stop": state.get("should_stop", False),
        "city_summary": state.get("city_summary"),
    }


def _passenger_from_dict(data: Optional[dict]) -> Optional[TaxiPassenger]:
    if data is None:
        return None
    return TaxiPassenger(
        name=data["name"],
        gender=data["gender"],
        weight_kg=data.get("weight_kg", 85.0),
        is_drunk=data.get("is_drunk", False),
        motion_sickness=data.get("motion_sickness", 0.0),
        nausea_warning_timer=data["nausea_warning_timer"],
        nausea_resolved=data["nausea_resolved"],
        pickup=TaxiTarget(x=data["pickup"]["x"], y=data["pickup"]["y"], address=data["pickup"]["address"], radius_m=data["pickup"]["radius_m"]),
        dropoff=TaxiTarget(x=data["dropoff"]["x"], y=data["dropoff"]["y"], address=data["dropoff"]["address"], radius_m=data["dropoff"]["radius_m"]),
    )


class ShadowVehicle:
    """A client-side stand-in for an NPCVehicle it never runs AI on -
    duck-typed to whatever render.vehicles.draw_npc_cars reads (that
    renderer already treats NPCVehicle itself as a duck-typed interface,
    see npc.NPCVehicle's own docstring)."""

    def __init__(self, vehicle_id: int):
        self.vehicle_id = vehicle_id
        self.x = self.y = self.heading = self.speed = 0.0
        self.color = (150, 155, 165)
        self.vehicle_type = "car"
        self.is_taxi = self.is_police = self.is_on_foot = self.fallen = False
        self.layer = 0
        self.lod_level = 0
        self.turn_signal = ""
        self.turn_signal_elapsed = 0.0
        self.way = None
        # Debug-only fields (F7's population panel etc.) this client has
        # no real value for - it never runs NPC AI/ownership/parking
        # logic, so these are fixed, correctly-typed placeholders rather
        # than left unset (an AttributeError from a debug overlay used
        # to crash the whole game - see NPC-004/client-server-02 history).
        self.vehicle_kind = "traffic"
        self.availability = "AVAILABLE"
        self.state = "CRUISING"
        self.owner_id = None
        self.destination = None
        self.destination_parking_space_id = None
        self.trip_group = None
        self.capacity = 1
        self.available_seats = 0
        self.debug_waiting_for = ""
        self.crashed_timer = 0.0
        self.parking_route = None
        self.parking_route_index = 0
        self.travel_route = None
        self.segment_idx = 0
        self.direction = 1
        self.driver_departed = False
        self.home_position = None
        self.household_id = None
        # draw_car/draw_npc_cars/draw_vehicle_lights/draw_taxi_smoke/
        # draw_taxi_exhaust all read length_m/width_m off the vehicle
        # object itself (getattr(npc, "length_m", 4.0)), not off a
        # nested .car - both need the real synced value, or NPCs always
        # render at the 4.0m/1.8m fallback size regardless of what the
        # server actually sent.
        self.length_m = 4.0
        self.width_m = 1.8

        class _CarShim:
            length_m = 4.0
            width_m = 1.8

        self.car = _CarShim()

    def apply(self, data: dict) -> None:
        self.x, self.y, self.heading, self.speed = data["x"], data["y"], data["heading"], data["speed"]
        self.color = tuple(data["color"])
        self.vehicle_type = data["vehicle_type"]
        self.is_taxi = data["is_taxi"]
        self.is_police = data["is_police"]
        self.is_on_foot = data["is_on_foot"]
        self.fallen = data["fallen"]
        self.layer = data["layer"]
        self.lod_level = data["lod_level"]
        self.turn_signal = data["turn_signal"]
        self.turn_signal_elapsed = data["turn_signal_elapsed"]
        self.state = data.get("state", self.state)
        self.crashed_timer = data.get("crashed_timer", self.crashed_timer)
        self.driver_departed = data.get("driver_departed", self.driver_departed)
        self.debug_waiting_for = data.get("debug_waiting_for", self.debug_waiting_for)
        self.length_m = data["length_m"]
        self.width_m = data["width_m"]
        self.car.length_m = data["length_m"]
        self.car.width_m = data["width_m"]


class ShadowPedestrian:
    """A client-side stand-in for a Pedestrian it never runs AI on."""

    def __init__(self, resident_id: int):
        self.resident_id = resident_id
        self.x = self.y = self.heading = 0.0
        self.radius_m = 0.45
        self.color = (200, 200, 200)
        self.state = "walking"
        self.animation_state = "walking"
        self.animation_time = 0.0
        self.curse_timer = 0.0
        self.curse_text = "@#*!%"
        self.mood = "normal"
        self.is_cyclist = False
        self.way = None
        self.speed = 0.0
        self.layer = 0
        # Debug-only/secondary render fields this client has no real
        # value for (it never runs pedestrian AI) - correctly-typed
        # placeholders so debug overlays and the resident popup degrade
        # gracefully instead of crashing on a missing attribute.
        self.route = None
        self.destination = None
        self.crossing = None
        self.is_player = False
        self.blood_alcohol_promille = 0.0
        self.linked_building_entrance = None
        self.activity = None

    def apply(self, data: dict) -> None:
        self.x, self.y, self.heading = data["x"], data["y"], data["heading"]
        self.radius_m = data["radius_m"]
        self.color = tuple(data["color"])
        self.state = data["state"]
        self.animation_state = data["animation_state"]
        self.animation_time = data["animation_time"]
        self.curse_timer = data["curse_timer"]
        self.curse_text = data["curse_text"]
        self.mood = data["mood"]
        self.is_cyclist = data["is_cyclist"]


def _reconcile_npcs(vehicles: list, npc_states: list[dict]) -> None:
    by_id = {npc.vehicle_id: npc for npc in vehicles if isinstance(npc, ShadowVehicle)}
    seen = set()
    for data in npc_states:
        vid = data["id"]
        seen.add(vid)
        shadow = by_id.get(vid)
        if shadow is None:
            shadow = ShadowVehicle(vid)
            vehicles.append(shadow)
        shadow.apply(data)
    vehicles[:] = [npc for npc in vehicles if not isinstance(npc, ShadowVehicle) or npc.vehicle_id in seen]


def _reconcile_pedestrians(pedestrians: list, ped_states: list[dict]) -> None:
    by_id = {p.resident_id: p for p in pedestrians if isinstance(p, ShadowPedestrian)}
    seen = set()
    for data in ped_states:
        pid = data["id"]
        seen.add(pid)
        shadow = by_id.get(pid)
        if shadow is None:
            shadow = ShadowPedestrian(pid)
            pedestrians.append(shadow)
        shadow.apply(data)
    pedestrians[:] = [p for p in pedestrians if not isinstance(p, ShadowPedestrian) or p.resident_id in seen]
