"""Gig save slots: one JSON file per slot under <config dir>/saves.

A slot is the gig car file (odometer, fuel, money: career.save_gig_odometer
keeps writing those after every fare) plus what a continued game needs:
the city, a map box around the car, the game time, the car's pose, the score
a fare in progress (passengers aboard), and the homes chosen in each city.
Other simulation state is not kept: the city's
traffic, residents and weather are generated again.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Optional

from .taxi import TaxiPassenger, TaxiState, TaxiTarget

logger = logging.getLogger(__name__)

SLOT_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BOX_HALF_DEG = 1.5 / 111.0  # a 3 km box around the car, like the launcher's custom start


def saves_dir(config_path: Path) -> Path:
    return config_path.parent / "saves"


def slot_path(config_path: Path, name: str) -> Path:
    if not SLOT_NAME.match(name):
        raise ValueError(f"Invalid save slot name: {name!r}")
    return saves_dir(config_path) / f"{name}.json"


def read_slot(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def list_slots(config_path: Path) -> list:
    """The launcher's slot menu: newest first, a summary of each."""
    rows = []
    for path in saves_dir(config_path).glob("*.json"):
        data = read_slot(path)
        if not data.get("city"):
            continue  # a new game never saved: only its car's odometer, nothing to continue
        rows.append({
            "name": path.stem, "path": str(path), "city": data.get("city", ""), "place_name": data.get("place_name", ""),
            "game_time": data.get("game_time", ""), "balance_cents": data.get("balance_cents", 0),
            "fare": data.get("fare") is not None, "saved_at": data.get("saved_at", 0),
        })
    return sorted(rows, key=lambda row: row["saved_at"], reverse=True)


def _target(data: dict) -> TaxiTarget:
    known = {f.name for f in fields(TaxiTarget)}
    return TaxiTarget(**{key: value for key, value in data.items() if key in known})


def _passenger_data(passenger: TaxiPassenger) -> dict:
    return {
        "name": passenger.name, "gender": passenger.gender, "weight_kg": passenger.weight_kg,
        "is_drunk": passenger.is_drunk, "motion_sickness": passenger.motion_sickness,
        "nausea_delay": passenger.nausea_delay, "nausea_resolved": passenger.nausea_resolved,
        "nausea_vomited": passenger.nausea_vomited,
        "pickup": asdict(passenger.pickup), "dropoff": asdict(passenger.dropoff),
        "ped": [passenger.ped_x, passenger.ped_y, passenger.ped_heading, passenger.ped_speed],  # waiting at pickup
        "companions": [_passenger_data(member) for member in passenger.companions],
    }


def _passenger(data: dict, boarded: bool = True) -> TaxiPassenger:
    ped = data.get("ped") or [data["pickup"]["x"], data["pickup"]["y"], 0.0, 2.0]
    passenger = TaxiPassenger(
        name=data["name"], pickup=_target(data["pickup"]), dropoff=_target(data["dropoff"]),
        gender=data.get("gender", "woman"), weight_kg=data.get("weight_kg", 75.0),
        ped_x=ped[0], ped_y=ped[1], ped_heading=ped[2], ped_speed=ped[3],
        boarded=boarded, is_drunk=data.get("is_drunk", False),
        motion_sickness=data.get("motion_sickness", 0.0), nausea_delay=data.get("nausea_delay", 0.0),
        nausea_resolved=data.get("nausea_resolved", False), nausea_vomited=data.get("nausea_vomited", False),
    )
    passenger.companions = [_passenger(member, boarded) for member in data.get("companions", [])]
    return passenger


def fare_data(taxi_mgr) -> Optional[dict]:
    """The accepted fare: passengers aboard (with the running meter), or
    still waiting at the pickup (or walking to the taxi: waiting again on
    load). A rail booking's customer is a station pedestrian of this session
    only: that fare is not kept."""
    passenger = taxi_mgr.current_passenger
    if passenger is None:
        return None
    if taxi_mgr.state in (TaxiState.WAITING_FOR_PICKUP, TaxiState.CLIENT_WALKING_TO_CAR):
        if passenger.rail_booking is not None:
            return None
        return {"state": TaxiState.WAITING_FOR_PICKUP, "passenger": _passenger_data(passenger)}
    if taxi_mgr.state != TaxiState.DRIVING_TO_DROPOFF:
        return None
    return {
        "state": TaxiState.DRIVING_TO_DROPOFF,
        "passenger": _passenger_data(passenger),
        "elapsed_time": taxi_mgr.elapsed_time,
        "fare_started_at": taxi_mgr.fare_started_at.isoformat() if taxi_mgr.fare_started_at else None,
        "fare_start_odometer_m": taxi_mgr.fare_start_odometer_m,
        "fare_distance_m": taxi_mgr.fare_distance_m,
        "live_fare_cents": taxi_mgr.live_fare_cents,
        "passenger_happiness": taxi_mgr.passenger_happiness,
        "trip_distance_m": taxi_mgr.trip_distance_m,
    }


def restore_fare(taxi_mgr, data: Optional[dict]) -> bool:
    if not data:
        return False
    pickup_ahead = data.get("state") == TaxiState.WAITING_FOR_PICKUP
    try:
        taxi_mgr.current_passenger = _passenger(data["passenger"], boarded=not pickup_ahead)
    except (KeyError, TypeError, IndexError) as exc:
        logger.warning("Saved fare could not be restored: %s", exc)
        return False
    taxi_mgr.offers = []
    if pickup_ahead:  # accepted, the customer waiting where they stood
        taxi_mgr.state = TaxiState.WAITING_FOR_PICKUP
        taxi_mgr.elapsed_time = 0.0
        return True
    taxi_mgr.state = TaxiState.DRIVING_TO_DROPOFF
    taxi_mgr.elapsed_time = data.get("elapsed_time", 0.0)
    started = data.get("fare_started_at")
    taxi_mgr.fare_started_at = datetime.fromisoformat(started) if started else None
    taxi_mgr.fare_start_odometer_m = data.get("fare_start_odometer_m")
    taxi_mgr.fare_distance_m = data.get("fare_distance_m", 0.0)
    taxi_mgr.live_fare_cents = data.get("live_fare_cents", 0)
    taxi_mgr.passenger_happiness = data.get("passenger_happiness", 50.0)
    taxi_mgr.trip_distance_m = data.get("trip_distance_m", 0.0)
    return True


def write_slot(path: Path, *, car, taxi_mgr, calendar, city: str, place_name: str, latlon) -> None:
    """The whole slot, atomically; `latlon` is the car's (latitude, longitude)."""
    latitude, longitude = latlon
    from math import cos, radians
    half_lon = BOX_HALF_DEG / max(0.1, cos(radians(latitude)))
    data = read_slot(path)  # keeps anything career.save_gig_odometer wrote
    data.update({
        "odometer_m": max(0.0, car.odometer_m), "fuel_l": max(0.0, car.fuel_l),
        "balance_cents": max(0, int(taxi_mgr.balance_cents)),
        "city": city, "place_name": place_name,
        "bbox": f"{latitude - BOX_HALF_DEG:.6f},{longitude - half_lon:.6f},{latitude + BOX_HALF_DEG:.6f},{longitude + half_lon:.6f}",
        "game_time": calendar.current.isoformat(),
        "car": {"x": car.x, "y": car.y, "heading": car.heading},
        "total_score": taxi_mgr.total_score, "completed_fares": taxi_mgr.completed_fares,
        "fare": fare_data(taxi_mgr), "saved_at": time.time(),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
