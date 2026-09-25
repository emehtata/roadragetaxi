"""Real train compositions (trains phase 6): which vehicles a timetable
train is made of, how long each is, and how each is drawn.

assets/train_compositions.json.gz is learned offline by
tools/import_train_compositions.py from Digitraffic (the game never
downloads). A train's composition is resolved once, when it appears:

    1. exact:   observed for this departure date + train number
    2. history: the latest observed for this train number
    3. type:    the latest observed for this train type (IC, S, PYO, ...)
    4. generic: locomotive + 5 wagons

Historical ones are the best knowledge available, not a promise of
today's real consist. Everything the renderer needs per vehicle (length,
centre offset from the front, visual profile) is precomputed here.
"""
from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_COMPOSITIONS_PATH = Path(__file__).with_name("assets") / "train_compositions.json.gz"
SUPPORTED_VERSION = 1
VEHICLE_GAP_M = 1.0
DEFAULT_WAGON_LENGTH_M = 24.0  # the old fixed wagon
# Digitraffic gives wagon lengths but not locomotive lengths.
LOCOMOTIVE_LENGTH_M = {"Sr1": 19.0, "Sr2": 18.96, "Sr3": 19.6, "Dr14": 14.4, "Dr16": 16.1, "Dr19": 19.6}
DEFAULT_LOCOMOTIVE_LENGTH_M = 19.0
MAX_TRAIN_LENGTH_M = 400.0  # longest consists (night trains) are ~360 m

# Visual profiles, green throughout: (base colour, pattern colour or None).
PROFILES = {
    "locomotive": ((12, 48, 24), (240, 240, 235)),  # very dark green, broad white cab front
    "standard": ((46, 125, 60), None),
    "restaurant": ((46, 125, 60), (245, 245, 240)),  # green with a white stripe
    "family": ((96, 170, 92), None),  # lighter green (playground car)
    "pet": ((34, 100, 70), None),  # blue-ish darker green (pet compartment)
}


def vehicle_profile(kind: str, services) -> str:
    """Strongest available information first: a locomotive, then the
    wagon's service flags from Digitraffic; anything else is a standard
    green passenger car."""
    if kind == "locomotive":
        return "locomotive"
    if "catering" in services:
        return "restaurant"
    if "playground" in services:
        return "family"
    if "pet" in services:
        return "pet"
    return "standard"


@dataclass(frozen=True)
class TrainComposition:
    # (length_m, profile name) per vehicle, front first
    vehicles: Tuple[Tuple[float, str], ...]
    source: str = "generic"  # exact / history / type / generic
    observed: str = ""  # departure date of the observation used
    max_speed_kmh: Optional[int] = None
    types: Tuple[str, ...] = ()  # Digitraffic vehicle type per vehicle (Sr3, Ed, ...), when known
    offsets: Tuple[float, ...] = field(default=(), compare=False)  # vehicle centre behind the front
    length_m: float = field(default=0.0, compare=False)

    def __post_init__(self) -> None:
        offsets, front = [], 0.0
        for length, _ in self.vehicles:
            offsets.append(front + length / 2)
            front += length + VEHICLE_GAP_M
        object.__setattr__(self, "offsets", tuple(offsets))
        object.__setattr__(self, "length_m", max(0.0, front - VEHICLE_GAP_M))


# The old fixed look: the last resort only.
GENERIC = TrainComposition(((DEFAULT_WAGON_LENGTH_M, "locomotive"),) + ((DEFAULT_WAGON_LENGTH_M, "standard"),) * 5)


def _from_record(record: dict, source: str) -> TrainComposition:
    vehicles, types = [], []
    for kind, vehicle_type, length, services in record.get("vehicles", []):
        if kind == "locomotive":
            length = length or LOCOMOTIVE_LENGTH_M.get(vehicle_type, DEFAULT_LOCOMOTIVE_LENGTH_M)
        vehicles.append((float(length or DEFAULT_WAGON_LENGTH_M), vehicle_profile(kind, services)))
        types.append(vehicle_type)
    if not vehicles:
        return GENERIC
    return TrainComposition(tuple(vehicles), source, record.get("departure_date", ""), record.get("max_speed_kmh"), tuple(types))


def load_compositions(path: Optional[Path] = None) -> Optional[dict]:
    path = Path(path) if path is not None else DEFAULT_COMPOSITIONS_PATH
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            database = json.load(source)
        if database.get("version") != SUPPORTED_VERSION:
            raise ValueError(f"unsupported version {database.get('version')!r}")
    except FileNotFoundError:
        logger.info("No train composition database (%s): trains use the generic consist", path)
        return None
    except (OSError, ValueError, EOFError) as exc:
        logger.warning("Train composition database unusable (%s): %s", exc, path)
        return None
    return database


def resolve(database: Optional[dict], train_type: str, number: str, day: Optional[date]) -> TrainComposition:
    """exact -> history -> type -> generic (see module docstring)."""
    if database:
        if day is not None and f"{day.isoformat()}|{number}" in database.get("observations", {}):
            return _from_record(database["observations"][f"{day.isoformat()}|{number}"], "exact")
        if number in database.get("latest", {}):
            return _from_record(database["latest"][number], "history")
        if train_type in database.get("by_type", {}):
            return _from_record(database["by_type"][train_type], "type")
    return GENERIC
