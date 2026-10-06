"""The client/server wire protocol (client-server-02.md).

A tiny versioned envelope over newline-delimited JSON. Deliberately not
tied to JSON at the call-site level: `encode`/`decode` are the only
places that know the wire format, so swapping to a binary encoding later
only touches this module. No pickle, no raw Python objects on the wire.

Message shapes crossing the boundary:

- client -> server: `{"type": "command", "version": 1, "seq": N, "player_id": ..., "command": {...}}`
  built by `build_command_message`. `command` mirrors
  `simulation.PlayerCommand`'s fields plus one edge-triggered
  `interact` flag for the discrete "enter/exit vehicle" action.
  `player_id` says whose input it is; there is one player today,
  `LOCAL_PLAYER_ID`, and a command without one means that player.
- server -> client, once on connect: `{"type": "world", "version": 1, ...}`
  built by `build_world_message`: the map origin, chunk size and the
  client's `player_id`. The Pygame client ignores it (it loads the map
  itself).
- server -> client: `{"type": "chunk", ...}` / `{"type": "chunk_unload", ...}`
  (map_chunks.py): the static map around the player, streamed as it moves.
- server -> client: `{"type": "state", "version": 1, "tick": N, "server_time": s, "state": {...}}`
  built by `build_state_message` every tick, applied on the Pygame client
  by `apply_server_state`. Dynamic gameplay state, plus the tick's
  semantic `events` (sounds, train arrivals) for the client to present.
  `server_time` is simulation seconds since the server started - the
  timeline clients interpolate on.

See docs/architecture/godot-client.md.

This module must never import pygame, for the same reason simulation.py
doesn't: it's shared, unmodified, by the headless server.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any, Optional

from .fuel import fuel_station_price_cents, nearest_fuel_station
from .geo import angle_diff
from .localization import tr
from .rail_bookings import PASSENGER_MET, PASSENGER_WAITING
from .simulation import PlayerCommand
from .taxi import TaxiPassenger, TaxiTarget

PROTOCOL_VERSION = 1
LOCAL_PLAYER_ID = "local_player"  # the only player until there is multiplayer


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


def build_command_message(command: PlayerCommand, *, interact: bool, seq: int,
                          player_id: str = LOCAL_PLAYER_ID, phone: Optional[dict] = None) -> dict:
    payload = asdict(command)
    payload["interact"] = interact
    message = {"type": "command", "version": PROTOCOL_VERSION, "seq": seq, "player_id": player_id, "command": payload}
    if phone is not None:
        message["phone"] = phone
    return message


PHONE_ACTIONS = ("accept", "reject")


def phone_request_from_message(message: dict) -> Optional[dict]:
    """A command's phone request, {"action": "accept"|"reject", "item_id":
    "offer-N"|"booking-N", "request_id": n}, or None (none, or malformed:
    ignored like any bad input, never trusted)."""
    phone = message.get("phone")
    if not isinstance(phone, dict) or phone.get("action") not in PHONE_ACTIONS or not isinstance(phone.get("item_id"), str):
        return None
    return {"action": phone["action"], "item_id": phone["item_id"], "request_id": phone.get("request_id")}


def command_player_id(message: dict) -> str:
    """Whose input a command is (older clients send none: the local player)."""
    return str(message.get("player_id") or LOCAL_PLAYER_ID)


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
        # The waiting customer as Pygame draws them (render/navigation.py
        # draw_taxi_target): where they stand or walk, until they board. A
        # rail booking's customer is a pedestrian of their own instead.
        "ped": [round(passenger.ped_x, 2), round(passenger.ped_y, 2), round(passenger.ped_heading, 3)],
        "is_walking_to_car": passenger.is_walking_to_car,
        "boarded": passenger.boarded,
        "rail_booking": passenger.rail_booking is not None,
    }


def _train_to_dict(train) -> dict:
    service = train.service
    return {
        "id": id(train),
        "label": f"{service.train_type} {service.number}" if service is not None else "",
        "state": train.state,
        "speed": train.current_speed_mps,
        # Each vehicle, front first: x, y, heading, length, look (locomotive, restaurant, ...).
        "cars": [[round(x, 2), round(y, 2), round(heading, 4), length, profile]
                 for x, y, heading, length, profile in train.vehicles()],
    }


def _phone_to_dict(taxi_mgr, car) -> dict:
    """The phone's rows, as the Pygame phone shows them (render/hud.py
    draw_phone_offers): rail bookings first, then ride offers. Only values
    the simulation has - an ordinary offer has no fare until the ride ends."""
    items = []
    for kind, item in taxi_mgr.phone_items():
        if kind == "booking":
            items.append({
                "id": f"booking-{item.id}", "kind": "booking", "status": item.status,
                "name": getattr(item.passenger, "name", "") or "",
                "train": item.train_number, "pickup": item.station, "arrival": f"{item.arrival_at:%H:%M}",
                "dropoff": item.destination.address if item.destination is not None else "",
                "surcharge_cents": item.surcharge_cents,
            })
        else:
            passenger = item.passenger
            items.append({
                "id": f"offer-{item.offer_id}", "kind": "offer", "status": "AVAILABLE",
                "name": passenger.name, "pickup": passenger.pickup.address, "dropoff": passenger.dropoff.address,
                "pickup_distance_m": round(math.hypot(car.x - passenger.pickup.x, car.y - passenger.pickup.y)),
                "trip_distance_m": round(math.hypot(passenger.dropoff.x - passenger.pickup.x, passenger.dropoff.y - passenger.pickup.y)),
                "time_remaining_s": round(item.time_remaining_s, 1),
            })
    # busy: a fare is under way - new offers wait until it ends ("finish or cancel").
    return {"busy": taxi_mgr.current_passenger is not None, "items": items}


def _line(points) -> list:
    return [[round(x, 1), round(y, 1)] for x, y in points]


TRAFFIC_LIGHT_PHASE_RADIUS_M = 600.0  # phases sent for posts this near the player (well past the view)


def traffic_light_render_point(light) -> tuple:
    """Where Pygame draws a light (render/roads.py _traffic_light_render_position):
    shifted right of the lane by its render_offset_m."""
    heading = light.direction_angle or 0.0
    offset = getattr(light, "render_offset_m", 0.0)
    return light.x + math.sin(heading) * offset, light.y - math.cos(heading) * offset


def _traffic_light_phases(traffic_mgr, x: float, y: float) -> dict:
    """{post id: phase} for the posts near (x, y), the id being the light's
    index (map_chunks.ChunkIndex) and the phase TrafficLight.get_state's
    ("green", "yellow", "red", "red+yellow", "all-red") - the client never
    computes one."""
    radius_sq = TRAFFIC_LIGHT_PHASE_RADIUS_M * TRAFFIC_LIGHT_PHASE_RADIUS_M
    return {
        str(index): light.get_state(traffic_mgr.sim_time)
        for index, light in enumerate(traffic_mgr.traffic_lights)
        if getattr(light, "renderable", True) and (light.x - x) ** 2 + (light.y - y) ** 2 <= radius_sq
    }


def _fallen_and_knocked(world, x: float, y: float) -> tuple:
    """Trees felled and posts knocked over this session near (x, y), as
    [x, y, angle(, kind)] - matched by position to the chunks' trees and
    bollards. Only ever grows (taxi.py), so it stays small."""
    radius_sq = TRAFFIC_LIGHT_PHASE_RADIUS_M * TRAFFIC_LIGHT_PHASE_RADIUS_M
    taxi_mgr = world.taxi_mgr
    fallen = []
    for key in getattr(taxi_mgr, "fallen_trees", ()):
        effect = taxi_mgr.tree_effects.get(key, {})
        if "x" in effect and (effect["x"] - x) ** 2 + (effect["y"] - y) ** 2 <= radius_sq:
            fallen.append([round(effect["x"], 1), round(effect["y"], 1), round(effect.get("angle", 0.0), 3)])
    knocked = [
        [round(post.x, 1), round(post.y, 1), round(post.knocked_angle, 3), post.kind]
        for post in getattr(world, "scenery_objects", ())
        if getattr(post, "knocked_angle", None) is not None and (post.x - x) ** 2 + (post.y - y) ** 2 <= radius_sq
    ]
    return fallen, knocked


def _road_to_dict(current_way) -> dict:
    """The road under the taxi as Pygame's HUD names it: the OSM name, else
    the highway type title-cased; None off-road. The limit is the
    simulation's own (None when unknown)."""
    if current_way is None:
        return {"name": None, "speed_limit_kmh": None, "layer": 0, "bridge": False}
    name = getattr(current_way, "name", None) or (getattr(current_way, "highway", None) or "Road").replace("_", " ").title()
    return {"name": name, "speed_limit_kmh": getattr(current_way, "speed_limit_kmh", None),
            # godot-16: the layer the taxi drives on (headlights under a higher road)
            "layer": getattr(current_way, "layer", 0), "bridge": bool(getattr(current_way, "is_bridge", False))}


def _station_price_cents(world, car) -> Optional[int]:
    """Price at the nearest pump within refuelling range of the car - the
    same lookup and price refuelling uses (simulation.py), as main() does."""
    station = nearest_fuel_station(getattr(world, "scenery_objects", ()), car.x, car.y)
    return fuel_station_price_cents(station) if station is not None else None


def _meet_to_dict(taxi_mgr, player_pedestrian, language: str) -> Optional[dict]:
    """The meet & greet in progress, as Pygame's main() shows it: the
    panel's three lines (taxi_mgr.meet_prompt, localized here) and, while
    the passenger is out at the station, who the arrow points at."""
    meet = taxi_mgr.meet_prompt(player_pedestrian)
    if meet is None:
        return None
    booking, action = meet
    pedestrian = booking.passenger.pedestrian
    arrow = None
    if pedestrian is not None and booking.status in (PASSENGER_WAITING, PASSENGER_MET):  # not while still at their origin
        arrow = {"id": getattr(pedestrian, "resident_id", None), "x": round(pedestrian.x, 2), "y": round(pedestrian.y, 2),
                 "radius_m": getattr(pedestrian, "radius_m", 0.45)}
    return {
        "status": booking.status,
        "lines": [
            tr(language, "meet_title", name=booking.passenger.name or "?"),
            f"{booking.train_number} | {booking.station}",
            tr(language, action, station=booking.station, arrival=f"{booking.arrival_at:%H:%M}"),
        ],
        "arrow": arrow,
    }


def build_world_message(center: tuple, chunk_size_m: float, player_id: str = LOCAL_PLAYER_ID) -> dict:
    """What a client learns once on connect: the map origin (it draws
    relative to it, for float32 precision), the chunk grid size, and which
    player it controls. The map itself follows as "chunk" messages."""
    return {
        "type": "world", "version": PROTOCOL_VERSION,
        "center": [center[0], center[1]], "chunk_size_m": chunk_size_m, "player_id": player_id,
    }


def build_state_message(
    *, tick: int, world, car, on_foot: bool, player_pedestrian, game_time_seconds: float,
    camx: float, camy: float, rage_power: float, water_elapsed: float,
    should_stop: bool = False, city_summary: Optional[tuple] = None, events: Optional[list] = None,
    server_time: float = 0.0, player_id: str = LOCAL_PLAYER_ID, current_way=None, language: str = "en",
    calendar: Optional[dict] = None, tire_mark: Optional[dict] = None,
) -> dict:
    """Everything the Pygame client needs to render one frame, and nothing
    static (see module docstring). Called once per server tick."""
    weather = world.weather
    taxi_mgr = world.taxi_mgr
    traffic_mgr = world.traffic_mgr
    player_at = (player_pedestrian.x, player_pedestrian.y) if on_foot else (car.x, car.y)
    fallen_trees, knocked_posts = _fallen_and_knocked(world, *player_at)
    state = {
        "fallen_trees": fallen_trees,  # [x, y, angle] (the way the taxi hit it)
        "knocked_posts": knocked_posts,  # [x, y, angle, kind]: bollards and street lamps lying flat
        "player_id": player_id,  # whose `player` / `taxi` this is
        "game_time_seconds": game_time_seconds,
        # {"date": "YYYY-MM-DD", "time_scale": game s per real s, "sun_altitude_deg",
        #  "darkness": 0 day .. 1 night} - the server's calendar and sun (godot-14).
        "calendar": calendar,
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
            "map_level": getattr(car, "map_level", 0),  # 0 surface, < 0 underground (godot-16)
            "braking": car.braking, "trip_m": car.trip_m, "odometer_m": car.odometer_m,
            "engine_on": car.engine_on, "fuel_l": car.fuel_l,
            "fuel_capacity_l": car.fuel_capacity_l,
            "fuel_consumption_l_per_100km": car.fuel_consumption_l_per_100km,
            "idle_fuel_consumption_l_per_hour": car.idle_fuel_consumption_l_per_hour,
            "curb_mass_kg": car.curb_mass_kg,
            "driver_mass_kg": car.driver_mass_kg,
            "passenger_mass_kg": car.passenger_mass_kg,
            "length_m": getattr(car, "length_m", 4.0), "width_m": getattr(car, "width_m", 1.8),
        },
        "player_pedestrian": {
            "x": player_pedestrian.x, "y": player_pedestrian.y, "heading": player_pedestrian.heading,
        },
        "npcs": [_npc_to_dict(npc) for npc in world.npc_manager.vehicles],
        "pedestrians": [_pedestrian_to_dict(p) for p in world.pedestrian_mgr.pedestrians if p.resident_id is not None],
        "trains": [_train_to_dict(t) for t in getattr(getattr(world, "railway_mgr", None), "trains", ())],
        "weather": {"weather_type": weather.weather_type.value, "wetness": weather.wetness,
                    "lightning_intensity": weather.lightning_intensity},  # 1 at a strike, fading (render/weather.py)
        "road": _road_to_dict(current_way),
        # godot-16: the taxi's tyre mark this tick (kind rubber/dirt/sand/snow, intensity, front) or
        # null; which speed camera is flashing (its index in the chunks) or null.
        "tire_mark": tire_mark,
        "speed_camera_flash": taxi_mgr.speed_camera_flash_index if taxi_mgr.speed_camera_flash_timer > 0.0 else None,
        "traffic_lights": _traffic_light_phases(traffic_mgr, *player_at),
        "meet": _meet_to_dict(taxi_mgr, player_pedestrian, language),
        "taxi": {
            "state": taxi_mgr.state,
            "total_score": taxi_mgr.total_score,
            "completed_fares": taxi_mgr.completed_fares,
            "balance_cents": taxi_mgr.balance_cents,
            "notification_msg": taxi_mgr.notification_msg,
            "notification_timer": taxi_mgr.notification_timer,
            # The notice is a speed-camera hit: Pygame centres it with a red border.
            "speed_camera_notice": taxi_mgr.speed_camera_notice_timer > 0.0 and bool(taxi_mgr.speed_camera_notice_msg),
            "taxi_smoke_timer": taxi_mgr.taxi_smoke_timer,
            "current_passenger": _passenger_to_dict(taxi_mgr.current_passenger),
            # The running fare (render/hud.py's mission bar). The meter's three are
            # null until the meter starts, as Pygame shows them only then.
            "elapsed_time": taxi_mgr.elapsed_time,
            "live_fare_cents": taxi_mgr.live_fare_cents if taxi_mgr.fare_started_at is not None else None,
            "fare_distance_m": taxi_mgr.fare_distance_m if taxi_mgr.fare_started_at is not None else None,
            "passenger_happiness": taxi_mgr.passenger_happiness if taxi_mgr.fare_started_at is not None else None,
            # The pump in refuelling range of the taxi (the gauge's "G: REFUEL" price), else null.
            "fuel_station_price_cents": _station_price_cents(world, car),
        },
        "phone": _phone_to_dict(taxi_mgr, car),
        # Career-mode session end (score threshold reached -> next city or
        # completed). Not fully wired end-to-end this phase - see
        # docs/architecture/simulation-rendering.md's known limitations.
        "should_stop": should_stop,
        "city_summary": list(city_summary) if city_summary is not None else None,
        # What happened this tick, for the client to present (sound, UI):
        # {"type": "sound", "group": ...}, {"type": "train_arrived", ...}.
        "events": list(events or ()),
    }
    return {"type": "state", "version": PROTOCOL_VERSION, "tick": tick,
            "server_time": server_time, "state": state}


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
    car.idle_fuel_consumption_l_per_hour = player.get(
        "idle_fuel_consumption_l_per_hour", car.idle_fuel_consumption_l_per_hour
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
        ped_x=data.get("ped", (0.0, 0.0, 0.0))[0],
        ped_y=data.get("ped", (0.0, 0.0, 0.0))[1],
        ped_heading=data.get("ped", (0.0, 0.0, 0.0))[2],
        is_walking_to_car=data.get("is_walking_to_car", False),
        boarded=data.get("boarded", False),
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
