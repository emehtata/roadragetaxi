"""The driver's home (H): a house yard chosen once per city, kept between
gigs within a save; afterwards H takes the taxi there (R still goes to a taxi stand).

A yard is a detached house's generated parking bay (parking.py) or a mapped
driveway with a house beside it - off the street, at someone's house.
Homes are kept as map metres (ETRS-TM35FIN), the same in every session.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional, Tuple

from .building_style import _building_is_house_by_tag
from .physics import is_point_on_parking_space

DRIVEWAY_HOUSE_M = 25.0  # a driveway point this close to a house is its yard
SAME_HOME_M = 10.0  # H this close to the saved home: already home, nothing to confirm
CONFIRM_S = 6.0  # a second H within this long makes a new yard the home

Home = Tuple[float, float, float]  # x, y, heading


def homes_path(config_path: Path) -> Path:
    return config_path.parent / "homes.json"


def _load_all(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_home(path: Path, city: str, *, in_save: bool = False) -> Optional[Home]:
    data = _load_all(path)
    homes = data.get("homes", {}) if in_save else data
    home = homes.get(city) if isinstance(homes, dict) else None
    try:
        return float(home["x"]), float(home["y"]), float(home["heading"])
    except (TypeError, KeyError, ValueError):
        return None


def save_home(path: Path, city: str, home: Home, *, in_save: bool = False) -> None:
    """This city's home; the other cities' homes are kept."""
    data = _load_all(path)
    homes = data.setdefault("homes", {}) if in_save else data
    if not isinstance(homes, dict):
        homes = data["homes"] = {}
    homes[city] = {"x": home[0], "y": home[1], "heading": home[2]}
    _write_homes(path, data)


def clear_homes(path: Path, *, in_save: bool = False) -> None:
    data = _load_all(path) if in_save else {}
    if in_save:
        data["homes"] = {}
    _write_homes(path, data)


def _write_homes(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def at_house_yard(x: float, y: float, current_way, parking_spaces, building_grid) -> bool:
    house_bays = [space for space in parking_spaces or () if getattr(space, "source_building_key", None) is not None]
    if is_point_on_parking_space(x, y, house_bays):
        return True
    if getattr(current_way, "service", None) != "driveway" or building_grid is None:
        return False
    r = DRIVEWAY_HOUSE_M
    return any(
        _building_is_house_by_tag(building)
        and building.bbox[0] - r <= x <= building.bbox[2] + r and building.bbox[1] - r <= y <= building.bbox[3] + r
        for building in building_grid.ways_in_rect(x - r, y - r, x + r, y + r)
    )


def is_same_home(home: Optional[Home], x: float, y: float) -> bool:
    return home is not None and math.dist(home[:2], (x, y)) <= SAME_HOME_M
