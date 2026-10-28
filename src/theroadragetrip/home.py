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
DOOR_REACH_M = 2.5  # on foot this close to a house's front door: E goes in
DOOR_HINT_M = 12.0  # front doors this close are marked on the map, on foot
DOOR_HINTS = 6  # at most this many, nearest first
DOORSTEP_M = 1.0  # leaving, the player stands this far outside the door

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


def load_home_building_key(path: Path, city: str, *, in_save: bool = False) -> Optional[str]:
    data = _load_all(path)
    homes = data.get("homes", {}) if in_save else data
    home = homes.get(city) if isinstance(homes, dict) else None
    key = home.get("building_key") if isinstance(home, dict) else None
    return key if isinstance(key, str) else None


def save_home(path: Path, city: str, home: Home, *, in_save: bool = False, building_key: Optional[str] = None) -> None:
    """This city's home; the other cities' homes are kept."""
    data = _load_all(path)
    homes = data.setdefault("homes", {}) if in_save else data
    if not isinstance(homes, dict):
        homes = data["homes"] = {}
    homes[city] = {"x": home[0], "y": home[1], "heading": home[2]}
    if building_key is not None:
        homes[city]["building_key"] = building_key
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


def home_building_key(building) -> str:
    """Reuse the generated house parking identity; importers do not retain OSM IDs."""
    from .parking import _house_parking_key

    return "footprint:" + ",".join(f"{value:.2f}" for value in _house_parking_key(building))


def find_home_building(x: float, y: float, building_grid, parking_spaces=(), key=None):
    """Resolve only the loaded map near the saved yard, never fetch another area."""
    from shapely.geometry import Point
    from .interior import footprint
    from .parking import _house_parking_key

    if building_grid is None:
        return None
    r = DRIVEWAY_HOUSE_M
    bay_keys = {space.source_building_key for space in parking_spaces or ()
                if getattr(space, "source_building_key", None) is not None
                and is_point_on_parking_space(x, y, [space])}
    candidates = []
    for building in building_grid.ways_in_rect(x - r, y - r, x + r, y + r):
        if not _building_is_house_by_tag(building) or getattr(building, "map_level", None) not in (None, 0):
            continue
        if key is not None and home_building_key(building) != key:
            continue
        if key is None and bay_keys and _house_parking_key(building) not in bay_keys:
            continue
        shape = footprint(building.points_m)
        if shape is not None and shape.distance(Point(x, y)) <= r:
            candidates.append((shape.distance(Point(x, y)), home_building_key(building), building))
    return min(candidates, key=lambda row: row[:2])[2] if candidates else None


def plan_entrance(plan: dict):
    """The plan's front door in map metres: (door middle, doorstep outside), or None."""
    door = next((d for d in plan.get("doors", ()) if d.get("rooms", [None])[0] == -1), None)
    origin = plan.get("origin")
    if door is None or origin is None:
        return None
    (ax, ay), (bx, by) = door["points"]
    lx, ly = door["leaf"]
    length = math.dist((ax, ay), (lx, ly)) or 1.0
    nx, ny = (lx - ax) / length, (ly - ay) / length  # into the house
    mx, my = origin[0] + (ax + bx) / 2, origin[1] + (ay + by) / 2
    return (mx, my), (mx - nx * DOORSTEP_M, my - ny * DOORSTEP_M)


def house_bay(building, parking_spaces):
    """The generated parking bay of this house, or None."""
    from .parking import _house_parking_key

    key = _house_parking_key(building)
    return next((space for space in parking_spaces or () if getattr(space, "source_building_key", None) == key), None)


def house_plan(building, parking_spaces) -> dict:
    """Any house's floor plan, its front door toward the mapped entrance nearest its
    yard bay, else the bay, else the generator's own choice: the same door whoever lives there."""
    from .interior import generate_floor_plan

    bay = house_bay(building, parking_spaces)
    yard = None if bay is None else tuple(sum(p[i] for p in bay.points_m) / len(bay.points_m) for i in (0, 1))
    entrances = getattr(building, "entrances", ()) or ()
    entry = (min(entrances, key=lambda p: math.dist(p, yard)) if yard else entrances[0]) if entrances else yard
    key = home_building_key(building)
    plan = generate_floor_plan(key, building.points_m, entry)
    address = " ".join(str(v) for v in (getattr(building, "street", None), getattr(building, "housenumber", None)) if v)
    return dict(plan, name=getattr(building, "name", None) or address or key)
