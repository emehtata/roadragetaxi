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
  client's `player_id`.
- server -> client: `{"type": "chunk", ...}` / `{"type": "chunk_unload", ...}`
  (map_chunks.py): the static map around the player, streamed as it moves.
- server -> client: `{"type": "state", "version": 1, "tick": N, "server_time": s, "state": {...}}`
  built by `build_state_message` every tick. Dynamic gameplay state, plus the tick's
  semantic `events` (sounds, train arrivals) for the client to present.
  `server_time` is simulation seconds since the server started - the
  timeline clients interpolate on.

See docs/architecture/godot-client.md."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import date
from typing import Optional

from .activities.plugins.ice_hockey import puck_positions
from .activities.beach import BEACH_ACTIVITIES
from .activities.plugins.golf import GOLF_ACTIVITIES
from .activities.plugins.soccer import ball_positions
from .fuel import fuel_station_price_cents, nearest_fuel_station
from .holiday_events import santa_costume
from .localization import tr
from .rail_bookings import PASSENGER_MET, PASSENGER_WAITING
from .simulation import PlayerCommand
from .taxi import TaxiPassenger

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


COMMAND_RANGES = {  # the analogue inputs and their valid range; the rest are flags
    "throttle": (0.0, 1.0), "brake": (0.0, 1.0), "steer_left": (0.0, 1.0), "steer_right": (0.0, 1.0),
    "forward": (-1.0, 1.0), "turn": (-1.0, 1.0),
}


def _command_field(name: str, value):
    """`value` as the command field `name` expects, or None when it isn't one."""
    if name in COMMAND_RANGES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        low, high = COMMAND_RANGES[name]
        return float(min(high, max(low, value)))
    return value if isinstance(value, bool) else None


def command_from_message(message: dict) -> tuple[PlayerCommand, bool]:
    """The inverse of `build_command_message` - used by the server. Client
    input is never trusted: a field of the wrong type keeps its default,
    analogue inputs are clamped to their range, and a missing or malformed
    payload is no input. A bad command must not stop the server's tick."""
    payload = message.get("command")
    if not isinstance(payload, dict):
        return PlayerCommand(), False
    fields = {}
    for name in PlayerCommand.__dataclass_fields__:
        value = _command_field(name, payload.get(name))
        if value is not None:
            fields[name] = value
    return PlayerCommand(**fields), payload.get("interact") is True


def _resident_to_dict(resident) -> Optional[dict]:
    if resident is None:
        return None
    return {
        "id": resident.resident_id,
        "name": f"{resident.first_name} {resident.surname}".strip(),
        "gender": resident.gender,
        "birth_date": resident.birth_date.isoformat(),
        "mode": resident.mode,
    }


def _npc_to_dict(npc, residents=None) -> dict:
    residents = residents or {}
    occupant_ids = set(getattr(npc, "occupant_ids", ()) or ()) | set(getattr(npc, "passenger_ids", ()) or ())
    if getattr(npc, "current_driver_id", None) is not None:
        occupant_ids.add(npc.current_driver_id)
    row = {
        "id": npc.vehicle_id,
        "x": npc.x,
        "y": npc.y,
        "heading": npc.heading,
        "speed": npc.speed,
        "color": list(npc.color),
        "vehicle_type": npc.vehicle_type,
        "is_taxi": npc.is_taxi,
        "taxi_fare": getattr(getattr(npc, "taxi_job", None), "passenger_aboard", False),  # its roof light
        "bus_line": getattr(getattr(getattr(npc, "bus_job", None), "line", None), "ref", None),  # a line bus's number
        "is_police": npc.is_police,
        "is_on_foot": npc.is_on_foot,
        "fallen": npc.fallen,
        "curse_timer": getattr(npc, "curse_timer", 0.0),  # a bumped driver's curse bubble
        "curse_text": getattr(npc, "curse_text", ""),
        "layer": npc.layer,
        "lod_level": npc.lod_level,
        "turn_signal": npc.turn_signal,
        "turn_signal_elapsed": npc.turn_signal_elapsed,
        "state": npc.state,
        "braking": bool(getattr(npc, "braking", False)),
        "crashed_timer": npc.crashed_timer,
        "driver_departed": npc.driver_departed,
        "debug_waiting_for": npc.debug_waiting_for,
        "length_m": npc.car.length_m,
        "width_m": npc.car.width_m,
        "owner": _resident_to_dict(residents.get(npc.owner_id)),
        "occupants": [_resident_to_dict(residents[resident_id]) for resident_id in sorted(occupant_ids) if resident_id in residents],
    }
    trailer = npc.trailer_body() if hasattr(npc, "trailer_body") else None
    if trailer is not None:  # a towed trailer, swinging on its hitch: [x, y, heading, length, width, kind]
        row["trailer"] = [round(trailer.x, 2), round(trailer.y, 2), round(trailer.heading, 3),
                          trailer.length_m, trailer.width_m, trailer.kind]
    return row


def shown_pedestrians(pedestrian_mgr, camx: float, camy: float) -> list:
    """The pedestrians a client draws: the nearest to the camera, at most the
    population the spawn disc holds (POPULATION_PER_SHOWN x the target) - a
    train's worth of passengers or a big activity crowd no longer floods every
    state. Everyone another system holds (booked rail passengers, stand
    customers) always goes: the phone, the meet arrow and the inspector use them."""
    people = [p for p in pedestrian_mgr.pedestrians if p.resident_id is not None]
    cap = pedestrian_mgr.population_target
    if len(people) <= cap:
        return people
    kept = lambda p: (getattr(p, "held_by", None) is not None or getattr(p, "is_taxi_stop_waiter", False)
                      or getattr(getattr(p, "activity", None), "plugin_id", "") in GOLF_ACTIVITIES + BEACH_ACTIVITIES + ("theme_park", "tennis"))
    always = [p for p in people if kept(p)]
    others = sorted((p for p in people if not kept(p)), key=lambda p: (p.x - camx) ** 2 + (p.y - camy) ** 2)
    return always + others[:max(0, cap - len(always))]


def _pedestrian_to_dict(ped, residents=None, santa_day=None) -> dict:
    row = {
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
        "costume": "santa" if santa_costume(ped, (residents or {}).get(ped.resident_id), santa_day) else "",
        "resident": _resident_to_dict((residents or {}).get(ped.resident_id)),
        "blood_alcohol_promille": getattr(ped, "blood_alcohol_promille", 0.0),
        "bottle": getattr(ped, "bottles", 0) > 0,  # a bottle in hand
        "drinking": getattr(ped, "drinking", False),  # hanging out with it: sips now and then
        "activity": getattr(getattr(ped, "activity", None), "plugin_id", ""),
        "stick_swing": getattr(ped, "stick_swing", 0.0),
        "hockey_goalie": getattr(ped, "hockey_goalie", False),
    }
    activity = getattr(ped, "activity", None)
    if activity is not None and activity.plugin_id in GOLF_ACTIVITIES and "ball" in activity.data:
        row["golf"] = {key: activity.data[key] for key in ("ball", "pin", "club", "phase", "swing", "strokes", "holed")}
    if activity is not None and activity.plugin_id == "beach_games" and activity.group is not None:
        if ped.resident_id == min(activity.group.member_resident_ids, default=None) and "ball" in activity.group.data:
            row["beach_ball"] = list(activity.group.data["ball"])
    if activity is not None and activity.plugin_id == "tennis" and activity.group is not None:
        if ped.resident_id == min(activity.group.member_resident_ids, default=None):
            row["tennis_ball"] = list(activity.group.data["ball"])
    dog = getattr(ped, "dog", None)
    if dog is not None:
        row["dog"] = {
            "x": dog.x, "y": dog.y, "heading": dog.heading, "size": dog.size,
            "color": list(dog.color), "sniffing": dog.sniffing,
        }
    return row


def _passenger_to_dict(passenger: Optional[TaxiPassenger]) -> Optional[dict]:
    if passenger is None:
        return None
    return {
        "name": passenger.name,
        "resident_id": passenger.resident_id,
        "passenger_count": len(passenger.members),
        "companions": [_passenger_to_dict(p) for p in passenger.companions],
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
        # The waiting customer: where they stand or walk, until they board. A
        # rail booking's customer is a pedestrian of their own instead.
        "ped": [round(passenger.ped_x, 2), round(passenger.ped_y, 2), round(passenger.ped_heading, 3)],
        "is_walking_to_car": passenger.is_walking_to_car,
        "boarded": passenger.boarded,
        "rail_booking": passenger.rail_booking is not None,
    }


def _trams_to_dicts(tram_mgr) -> list:
    """Trams drawn like trains (the state's "trains"), their sections their cars."""
    if tram_mgr is None:
        return []
    return [{"id": f"tram-{tram.tram_id}", "state": tram.state, "speed": tram.speed_mps, "line": tram.line or "",
             "cars": [[round(x, 2), round(y, 2), round(h, 4), length, look] for x, y, h, length, look in tram_mgr.cars(tram)]}
            for tram in tram_mgr.trams]


def _train_to_dict(train) -> dict:
    return {
        "id": id(train),
        "state": train.state,
        "speed": train.current_speed_mps,
        # Each vehicle, front first: x, y, heading, length, look (locomotive, restaurant, ...).
        "cars": [[round(x, 2), round(y, 2), round(heading, 4), length, profile]
                 for x, y, heading, length, profile in train.vehicles()],
    }


def _phone_to_dict(taxi_mgr, car) -> dict:
    """The phone's rows: rail bookings first, then ride offers. Only values
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
                "passenger_count": 1 + len(getattr(passenger, "companions", ())),
                "pickup_distance_m": round(math.hypot(car.x - passenger.pickup.x, car.y - passenger.pickup.y)),
                "trip_distance_m": round(math.hypot(passenger.dropoff.x - passenger.pickup.x, passenger.dropoff.y - passenger.pickup.y)),
                "time_remaining_s": round(item.time_remaining_s, 1),
            })
    # busy: a fare is under way - new offers wait until it ends ("finish or cancel").
    return {"busy": taxi_mgr.has_job(), "items": items}  # a job on: nothing more is accepted


def _line(points) -> list:
    return [[round(x, 1), round(y, 1)] for x, y in points]


TRAFFIC_LIGHT_PHASE_RADIUS_M = 600.0  # phases sent for posts this near the player (well past the view)


def traffic_light_render_point(light) -> tuple:
    """Where a light is drawn: shifted right of the lane by its render_offset_m."""
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


def _broken_hedges(world, x, y):
    manager = world.taxi_mgr
    damage = getattr(manager, "broken_hedges", {})
    if not damage:
        return []
    rows = []
    for railing in manager._nearby_barriers(getattr(world, "railings", ()), x, y, TRAFFIC_LIGHT_PHASE_RADIUS_M):
        fragments = damage.get(manager.hedge_key(railing))
        if fragments is not None:
            rows.append([getattr(railing, "layer", 0), _line(railing.points_m), [_line(piece) for piece in fragments]])
    return rows


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
    """The road under the taxi as the HUD names it: the OSM name, else
    the highway type title-cased; None off-road. The limit is the
    simulation's own (None when unknown)."""
    if current_way is None:
        return {"name": None, "speed_limit_kmh": None, "layer": 0, "bridge": False}
    name = getattr(current_way, "name", None) or (getattr(current_way, "highway", None) or "Road").replace("_", " ").title()
    return {"name": name, "speed_limit_kmh": getattr(current_way, "speed_limit_kmh", None),
            # godot-16: the layer the taxi drives on (headlights under a higher road)
            "layer": getattr(current_way, "layer", 0), "bridge": bool(getattr(current_way, "is_bridge", False))}


NEXT_TRAINS = 5  # the rows of the J board


def railway_state(railway_mgr, x: float, y: float, now) -> dict:
    """state.railway (godot-final-07): every timetabled station with its
    waiting passengers (station ambience), the one nearest (x, y) and its next
    arrivals and departures (the J board), from RailwayManager's own queries
    at the game time `now`. Times are "HH:MM" (game time); {} without one."""
    stations = getattr(railway_mgr, "stations", None) if railway_mgr is not None else None
    if not stations:
        return {}
    passengers = getattr(railway_mgr, "passengers", None)
    rows = []
    for name, point, _, _ in stations:
        waiting = passengers.waiting_count(name) if passengers is not None else 0
        if math.isfinite(point[0]) and math.isfinite(point[1]):
            rows.append({"name": str(name), "x": round(point[0], 2), "y": round(point[1], 2), "waiting": max(0, int(waiting))})
    nearest = min(stations, key=lambda station: math.dist(station[1], (x, y)))[0]

    def calls(found, other_end):
        return [{"time": f"{when:%H:%M}", "train_type": str(call.train_type), "number": str(call.number),
                 other_end: str(getattr(call, other_end)), "track": str(call.track or "")}
                for when, call in found[:NEXT_TRAINS]]

    return {"stations": rows, "nearest_station": str(nearest),
            "arrivals": calls(railway_mgr.next_arrivals(x, y, now, NEXT_TRAINS), "origin"),
            "departures": calls(railway_mgr.next_departures(x, y, now, NEXT_TRAINS), "destination")}


def _finite(value) -> Optional[float]:
    return round(float(value), 2) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _finite_pair(vector) -> list:
    """[east, north] rounded to 1 mm/s; a non-finite component as 0."""
    return [round(v, 3) if math.isfinite(v) else 0.0 for v in vector]


def _station_price_cents(world, car) -> Optional[int]:
    """Price at the nearest pump within refuelling range of the car - the
    same lookup and price refuelling uses (simulation.py)."""
    station = nearest_fuel_station(getattr(world, "scenery_objects", ()), car.x, car.y)
    return fuel_station_price_cents(station) if station is not None else None


def _meet_to_dict(taxi_mgr, player_pedestrian, language: str) -> Optional[dict]:
    """The meet & greet in progress: the
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


def build_world_message(center: tuple, chunk_size_m: float, player_id: str = LOCAL_PLAYER_ID,
                        city: str = "", forecast: Optional[list] = None) -> dict:
    """What a client learns once on connect: the map origin (it draws
    relative to it, for float32 precision), the chunk grid size, and which
    player it controls; for the start sign the city and the 24-hour
    forecast ([{time, temperature_c, weather, source, wind_speed_mps, wind_from_deg}]). The map itself
    follows as "chunk" messages."""
    return {
        "type": "world", "version": PROTOCOL_VERSION,
        "center": [center[0], center[1]], "chunk_size_m": chunk_size_m, "player_id": player_id,
        "city": city, "forecast": forecast or [],
    }


def build_state_message(
    *, tick: int, world, car, on_foot: bool, player_pedestrian, game_time_seconds: float,
    camx: float, camy: float, rage_power: float, water_elapsed: float,
    should_stop: bool = False, city_summary: Optional[tuple] = None, events: Optional[list] = None,
    server_time: float = 0.0, current_way=None, language: str = "en",
    calendar: Optional[dict] = None, tire_mark: Optional[dict] = None, navigation: Optional[dict] = None,
    road_rage: Optional[dict] = None, railway: Optional[dict] = None, map_loading: str = "",
    map_loading_detail: str = "",
) -> dict:
    """Everything the client needs to render one frame, and nothing
    static (see module docstring). Called once per server tick."""
    weather = world.weather
    taxi_mgr = world.taxi_mgr
    traffic_mgr = world.traffic_mgr
    player_at = (player_pedestrian.x, player_pedestrian.y) if on_foot else (car.x, car.y)
    fallen_trees, knocked_posts = _fallen_and_knocked(world, *player_at)
    residents = getattr(getattr(world, "residents", None), "residents", {})
    santa_day = date.fromisoformat(calendar["date"]) if calendar and calendar.get("holidays", {}).get("santas") else None
    state = {
        "protests": getattr(world, "protests", None).snapshot(camx, camy) if getattr(world, "protests", None) else [],
        "protest_active": bool(getattr(getattr(world, "protests", None), "groups", ())),
        "fallen_trees": fallen_trees,  # [x, y, angle] (the way the taxi hit it)
        "broken_hedges": _broken_hedges(world, *player_at),
        "knocked_posts": knocked_posts,  # [x, y, angle, kind]: bollards and street lamps lying flat
        "game_time_seconds": game_time_seconds,
        # {"date": "YYYY-MM-DD", "time_scale": game s per real s, "sun_altitude_deg",
        #  "moon_altitude_deg", "moon_azimuth_deg", "moon_illumination",
        #  "sun_azimuth_deg" (clockwise from the map's grid north), "darkness": 0 day
        #  .. 1 night} - the server's calendar, sun and Moon (godot-14, rrt-018-shadows).
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
            "engine_on": car.engine_on, "throttle": round(getattr(car, "throttle", 0.0), 2), "fuel_l": car.fuel_l,
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
        "npcs": [_npc_to_dict(npc, residents) for npc in world.npc_manager.vehicles],
        "pedestrians": [_pedestrian_to_dict(p, residents, santa_day) for p in shown_pedestrians(world.pedestrian_mgr, camx, camy)],
        "pucks": puck_positions(),  # ice hockey: [[x, y], ...]
        "balls": ball_positions(),  # soccer: [[x, y], ...]
        "vomit_puddles": [list(point) for point in taxi_mgr.vomit_puddles + world.pedestrian_mgr.vomit_puddles],
        "vomit_footprints": [list(point) for point in world.pedestrian_mgr.vomit_footprints],
        "trains": [_train_to_dict(t) for t in getattr(getattr(world, "railway_mgr", None), "trains", ())]
                  + _trams_to_dicts(getattr(world, "tram_mgr", None)),
        "weather": {"weather_type": weather.weather_type.value, "wetness": weather.wetness,
                    "road_snow": round(weather.road_snow, 1),
                    # 0 clear .. 1 overcast: dims the sunlight and building shadows (rrt-018-shadows)
                    "cloud_cover": round(getattr(weather, "cloud_cover", 0.0), 3),
                    "plowed_cells": [[x, y, round(depth, 1)] for (x, y), depth in weather.plowed_cells.items()
                                     if abs(x * 10.0 - car.x) < 600.0 and abs(y * 10.0 - car.y) < 600.0],
                    "lightning_intensity": weather.lightning_intensity,  # 1 at a strike, fading
                    # For the client's weather audio heavy rain, wind loops.
                    "is_thunderstorm": bool(weather.is_thunderstorm),
                    "wind_vector_mps": _finite_pair(weather.wind_vector_mps),
                    # Historical weather: FMI "observed"/"forecast", else "generated"; the HUD's temperature.
                    "source": getattr(weather, "weather_source", "generated"),
                    "temperature_c": _finite(getattr(weather, "outside_temperature_c", None))},
        "road": _road_to_dict(current_way),
        # The map growing as the taxi nears its edge: "" or fetching / merging / syncing / building.
        "map_loading": map_loading,
        # While fetching: the fetcher's own line, e.g. "Fetching from https://overpass-api.de/api/interpreter (attempt 1/3)...".
        "map_loading_detail": map_loading_detail if map_loading == "fetching" else "",
        # godot-16: the taxi's tyre mark this tick (kind rubber/dirt/sand/snow, intensity, front) or
        # null; which speed camera is flashing (its index in the chunks) or null.
        "tire_mark": tire_mark,
        "speed_camera_flash": taxi_mgr.speed_camera_flash_index if taxi_mgr.speed_camera_flash_timer > 0.0 else None,
        "traffic_lights": _traffic_light_phases(traffic_mgr, *player_at),
        "meet": _meet_to_dict(taxi_mgr, player_pedestrian, language),
        # The route to the taxi target, planned by the server (navigation_route.py): [[x, y], ...], [] while none.
        "navigation": navigation if navigation is not None else {"points": []},
        # The rage shout above the taxi while it lasts ({"text", "timer"} seconds left), else null.
        "road_rage": road_rage,
        # Stations and the nearest one's next trains (railway_state), else {}.
        "railway": railway if railway is not None else {},
        "taxi": {
            "state": taxi_mgr.state,
            "total_score": taxi_mgr.total_score,
            "completed_fares": taxi_mgr.completed_fares,
            "balance_cents": taxi_mgr.balance_cents,
            "notification_msg": taxi_mgr.notification_msg,
            "notification_timer": taxi_mgr.notification_timer,
            # The notice is a speed-camera hit: the client centres it with a red border.
            "speed_camera_notice": taxi_mgr.speed_camera_notice_timer > 0.0 and bool(taxi_mgr.speed_camera_notice_msg),
            "taxi_smoke_timer": taxi_mgr.taxi_smoke_timer,
            "current_passenger": _passenger_to_dict(taxi_mgr.current_passenger),
            # The running fare (the HUD's mission bar). The meter's three are
            # null until the meter starts.
            "elapsed_time": taxi_mgr.elapsed_time,
            "live_fare_cents": taxi_mgr.live_fare_cents if taxi_mgr.fare_started_at is not None else None,
            "fare_distance_m": taxi_mgr.fare_distance_m if taxi_mgr.fare_started_at is not None else None,
            "passenger_happiness": taxi_mgr.passenger_happiness if taxi_mgr.fare_started_at is not None else None,
            # The pump in refuelling range of the taxi (the gauge's "G: REFUEL" price), else null.
            "fuel_station_price_cents": _station_price_cents(world, car),
            "refueling": {"liters": taxi_mgr.refueling.liters, "cost_cents": taxi_mgr.refueling.paid_cents}
            if getattr(taxi_mgr, "refueling", None) is not None else None,
        },
        "phone": _phone_to_dict(taxi_mgr, car),
        # Career-mode session end (score threshold reached -> next city or
        # completed). Not fully wired end-to-end yet.
        "should_stop": should_stop,
        "city_summary": list(city_summary) if city_summary is not None else None,
        # What happened this tick, for the client to present (sound, UI):
        # {"type": "sound", "group": ...}, {"type": "train_arrived", ...}.
        "events": list(events or ()),
    }
    return {"type": "state", "version": PROTOCOL_VERSION, "tick": tick,
            "server_time": server_time, "state": state}
