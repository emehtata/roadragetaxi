"""How many people are around a point: the settlement model shared by the
pedestrian and NPC traffic managers (docs/population-model.md).

People live in, or visit, the mapped buildings around a point. Each building's
OSM type gives its residents or visitors; the municipality the point is in
(kunnat.json.gz, nearest centre) gives how many of those are out walking:
a dense town walks, a rural municipality drives. Pure functions over the
loaded buildings - no per-frame state, and the callers recount only when the
player moves on (a population check, a new 100 m cell).
"""
from __future__ import annotations

import gzip
import json
import logging
import math
from pathlib import Path
from typing import Iterable, Optional

from .residents import CITY_DATA

HOME_TYPES = {"house", "detached", "semidetached_house", "bungalow", "farm"}
FLAT_TYPES = {"apartments", "residential", "terrace", "dormitory"}
SEASONAL_TYPES = {"cabin", "hut"}  # summer cottages: mostly empty
DESTINATION_TYPES = {
    "commercial", "retail", "office", "supermarket", "kiosk", "hotel", "school",
    "university", "college", "kindergarten", "hospital", "public", "civic",
    "church", "train_station", "transportation", "sports_hall", "sports_centre",
}
EMPTY_TYPES = {
    "garage", "garages", "shed", "barn", "sauna", "carport", "farm_auxiliary",
    "roof", "service", "greenhouse", "outbuilding", "storage_tank", "boathouse",
    "cowshed", "stable", "hangar", "ruins", "construction", "bunker", "silo",
}
PEOPLE_PER_HOME = 2.5
SEASONAL_PEOPLE = 0.3
SUMMER_CABIN_PEOPLE = 2.0  # June-August: the cottages are lived in
SUMMER_MONTHS = {6, 7, 8}
FLAT_M2_PER_PERSON = 40.0
DESTINATION_M2_PER_VISITOR = 50.0
SMALL_UNTAGGED_M2 = 40.0  # an untagged building smaller than this is a shed or sauna
HOUSE_SIZED_UNTAGGED_M2 = 200.0
OUTDOOR_SHARE = 0.04  # of the people around, how many are out walking at once
URBAN_DENSITY_PER_KM2 = 100.0  # at and above: the full walking share


def footprint_m2(building) -> float:
    points = building.points_m
    return abs(sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])
    )) / 2.0


def building_people(building, month: Optional[int] = None) -> float:
    """Residents or visitors the building accounts for (in `month`, when known)."""
    kind = (getattr(building, "building_type", None) or "yes").lower()
    if kind in EMPTY_TYPES:
        return 0.0
    if kind in SEASONAL_TYPES:
        return SUMMER_CABIN_PEOPLE if month in SUMMER_MONTHS else SEASONAL_PEOPLE
    if kind in HOME_TYPES:
        return PEOPLE_PER_HOME
    area = footprint_m2(building)
    levels = getattr(building, "levels", None) or (
        max(1, round(building.height_m / 3.0)) if getattr(building, "height_is_explicit", False) else None
    )
    if kind in FLAT_TYPES:
        return area * (levels or 3) / FLAT_M2_PER_PERSON
    if kind in DESTINATION_TYPES:
        return area * (levels or 1) / DESTINATION_M2_PER_VISITOR
    # "yes" and everything else: judged by its size
    if area < SMALL_UNTAGGED_M2:
        return 0.0
    if area < HOUSE_SIZED_UNTAGGED_M2 and not levels:
        return PEOPLE_PER_HOME
    return area * (levels or 1) / FLAT_M2_PER_PERSON


def people_within(buildings: Iterable, x: float, y: float, radius: float, month: Optional[int] = None) -> float:
    """People the buildings whose centre is within `radius` account for.
    Each building is counted once, even when it comes from several cells."""
    seen = set()
    total = 0.0
    r_sq = radius * radius
    for building in buildings:
        min_x, min_y, max_x, max_y = building.bbox
        if id(building) in seen or ((min_x + max_x) / 2 - x) ** 2 + ((min_y + max_y) / 2 - y) ** 2 > r_sq:
            continue
        seen.add(id(building))
        total += building_people(building, month)
    return total


def municipality_at(x: float, y: float) -> Optional[dict]:
    """The kunnat.json.gz entry whose centre is nearest (x, y), None without the data."""
    from .taxi import municipality_points  # its projected centres; imported late, taxi is heavy
    nearest = min(
        (p for p in municipality_points() if p[4] is None),
        key=lambda p: (p[1] - x) ** 2 + (p[2] - y) ** 2,
        default=None,
    )
    return CITY_DATA.get(nearest[0].casefold()) if nearest else None


def walking_share(municipality: Optional[dict]) -> float:
    """OUTDOOR_SHARE, less where the municipality is sparse (1.9/km2 in Sysmä
    walks 0.42 of it, Helsinki all). Unknown: the full share."""
    if not municipality:
        return OUTDOOR_SHARE
    density = float(municipality.get("väestöntiheys_henkiloa_km2") or 0.0)
    return OUTDOOR_SHARE * (0.4 + 0.6 * min(1.0, density / URBAN_DENSITY_PER_KM2))


def walkers_within(buildings: Iterable, x: float, y: float, radius: float, municipality: Optional[dict]) -> int:
    """People out walking within `radius`: none without buildings, at least
    one where anybody lives."""
    people = people_within(buildings, x, y, radius)
    return math.ceil(people * walking_share(municipality)) if people else 0


# --- Traffic demand (docs/population-model.md, "Traffic demand") ---------
# Share of the day's peak hour, by hour. ESTIMATES shaped like Finnish
# automatic traffic counts (Fintraffic LAM): weekday peaks 7-8 and 15-17, a
# night trough near 2-3 % of the peak; weekends without a morning peak.
# The fallback: measured curves (LAM_PROFILES, below) replace them when present.
WEEKDAY_HOURLY = [0.04, 0.025, 0.02, 0.02, 0.04, 0.15, 0.45, 0.85, 0.8, 0.6, 0.6, 0.65,
                  0.7, 0.7, 0.75, 0.9, 1.0, 0.85, 0.65, 0.5, 0.4, 0.3, 0.18, 0.09]
WEEKEND_HOURLY = [0.08, 0.06, 0.04, 0.03, 0.03, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.75,
                  0.8, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.45, 0.35, 0.25, 0.18, 0.12]
# Month: less in deep winter, most in summer (estimate)
MONTH_FACTOR = {1: 0.88, 2: 0.9, 3: 0.95, 4: 0.97, 5: 1.0, 6: 1.05, 7: 1.0, 8: 1.05, 9: 1.0, 10: 0.97, 11: 0.95, 12: 0.92}
# Passing traffic a road carries whoever lives along it, as a share of a
# town centre's moving traffic (estimate, by OSM highway class).
THROUGH_TRAFFIC = {"motorway": 0.6, "trunk": 0.45, "primary": 0.3, "secondary": 0.15, "tertiary": 0.06}
LAM_PROFILES = Path(__file__).parent / "assets" / "traffic" / "lam_profiles.json.gz"
# Local people as a share of a town centre's at which traffic follows the urban
# curves fully; below, it blends toward the rural ones (a suburb counts as urban).
URBAN_PEOPLE_FRACTION = 0.5


def _interpolated_months(sampled: dict) -> dict:
    """{month: factor} for all twelve from a few sampled months, linear around
    the year; the estimate (MONTH_FACTOR) from fewer than two."""
    if len(sampled) < 2:
        return dict(MONTH_FACTOR)
    out = {}
    for month in range(1, 13):
        back = next(d for d in range(12) if (month - 1 - d) % 12 + 1 in sampled)  # months since the last sample
        ahead = next(d for d in range(12) if (month - 1 + d) % 12 + 1 in sampled)  # months to the next one
        before, after = sampled[(month - 1 - back) % 12 + 1], sampled[(month - 1 + ahead) % 12 + 1]
        out[month] = round(before + (after - before) * back / (back + ahead) if back + ahead else before, 3)
    return out


def load_measured_curves(path: Path = LAM_PROFILES) -> Optional[dict]:
    """{"urban"|"rural": {"weekday_hourly", "weekend_hourly", "month_factor"}}
    measured at Fintraffic LAM stations (tools/lam_profiles.py), or None (the
    estimates stay) when the file is missing or unreadable."""
    try:
        data = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        curves = {}
        for setting in ("urban", "rural"):
            group = data["groups"][setting]
            stations = [s for s in data["stations"] if s["setting"] == setting and s["id"] in data["group_stations"]]
            months = {}
            for station in stations:
                for month, factor in station["profile"]["month_factor"].items():
                    months.setdefault(int(month), []).append(factor)
            curves[setting] = {"weekday_hourly": group["weekday_hourly"], "weekend_hourly": group["weekend_hourly"],
                               "special_hourly": group.get("special_hourly", {}),
                               "month_factor": _interpolated_months({m: sum(v) / len(v) for m, v in months.items()})}
            assert len(curves[setting]["weekday_hourly"]) == len(curves[setting]["weekend_hourly"]) == 24
        return curves
    except (OSError, ValueError, KeyError, TypeError, AssertionError, ZeroDivisionError):
        logging.getLogger(__name__).warning("No measured traffic curves in %s: using the estimates", path)
        return None


MEASURED_CURVES = load_measured_curves()
# A road takes a LAM station's own curves when its ref names the station's road
# and it passes this close: the shape along one numbered road changes slowly.
STATION_REACH_M = 5000.0
STATION_MIN_DAYS = 6  # one sampled week, a day may be missing


def _station_peak_density(station: dict) -> Optional[float]:
    """Its measured weekday peak flow over its free-flow speed: vehicles per km, both directions."""
    flow = station["profile"].get("weekday_peak_vehicles_per_hour")
    speeds = [v for v in station.get("free_flow_speed_kmh") or () if v]
    return flow / (sum(speeds) / len(speeds)) if flow and speeds else None


def load_class_densities(path: Path = LAM_PROFILES) -> dict:
    """{"urban"|"rural": {highway: vehicles per km at the weekday peak hour}}: the
    LAM stations' medians by matched road class (tools/lam_profiles.py), with the
    streets no station measures (tertiary down to living streets) as estimates
    scaled from the measured secondary roads (SIDE_STREET_SHARE). {} without the file."""
    try:
        groups = json.loads(gzip.decompress(path.read_bytes()))["groups"]
        out = {}
        for setting in ("urban", "rural"):
            measured = dict(groups[setting]["peak_density_per_km"])
            base = measured.get("secondary", measured.get("primary", 0.0))
            for highway, share in SIDE_STREET_SHARE.items():
                measured.setdefault(highway, base * share)
            out[setting] = measured
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return {}


# No LAM station stands on these: estimates, as a share of the measured
# secondary-road density of the same setting.
SIDE_STREET_SHARE = {"tertiary": 0.7, "unclassified": 0.4, "residential": 0.4, "living_street": 0.1}


def load_station_curves(path: Path = LAM_PROFILES) -> list:
    """The reviewed stations with enough sampled days: road number, game
    coordinates and their own curves; [] without the file. Matched to OSM, or
    rejected only for a missing bearing: the curves are both directions'
    totals, so the road number and position are enough."""
    try:
        data = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        return [{"name": s["name"], "road": str(s["road_number"]), "x": s["x_m"], "y": s["y_m"],
                 "weekday_hourly": s["profile"]["weekday_hourly"], "weekend_hourly": s["profile"]["weekend_hourly"],
                 "special_hourly": s["profile"].get("special_hourly", {}),
                 "month_factor": _interpolated_months({int(m): f for m, f in s["profile"]["month_factor"].items()}),
                 "peak_density_per_km": _station_peak_density(s)}
                for s in data["stations"]
                if s.get("road_number") is not None and sum(s["profile"]["days_used"].values()) >= STATION_MIN_DAYS
                and (s.get("osm_match", {}).get("status") == "matched" or s.get("osm_match", {}).get("reason") == "no bearing or road number")]
    except (OSError, ValueError, KeyError, TypeError):
        return []


MEASURED_STATIONS = load_station_curves()
CLASS_DENSITIES = load_class_densities()
_stations_by_road: dict = {}  # road number -> its stations: hundreds Finland-wide
for _station in MEASURED_STATIONS:
    _stations_by_road.setdefault(_station["road"], []).append(_station)
_station_by_way: dict = {}  # OSM way id -> its station (or None), found once per road


def station_for_way(way) -> Optional[dict]:
    """The nearest station measuring this road (same ref, within STATION_REACH_M), or None."""
    if way is None or not MEASURED_STATIONS:
        return None
    key = getattr(way, "osm_id", None) or id(way)
    if key not in _station_by_way:
        refs = {token for token in str(getattr(way, "ref", "") or "").replace(";", " ").split()}
        best = None
        for station in (s for ref in refs for s in _stations_by_road.get(ref, ())):
            distance = min(math.hypot(x - station["x"], y - station["y"]) for x, y in way.points_m)
            if distance <= STATION_REACH_M and (best is None or distance < best[0]):
                best = (distance, station)
        _station_by_way[key] = best[1] if best else None
    return _station_by_way[key]
FIXED_PUBLIC_HOLIDAYS = {(1, 1), (1, 6), (5, 1), (12, 6), (12, 24), (12, 25), (12, 26)}


def is_public_holiday(day) -> bool:
    """Finland's fixed-date public holidays and Midsummer Eve and Day (Fri
    and Sat between 19 and 26 June). Easter and Ascension are not covered."""
    if (day.month, day.day) in FIXED_PUBLIC_HOLIDAYS:
        return True
    return day.month == 6 and (19 <= day.day <= 25 and day.weekday() == 4 or 20 <= day.day <= 26 and day.weekday() == 5)


def special_day(day) -> Optional[str]:
    """The key of a day with traffic of its own (tools/lam_profiles.py
    SPECIAL_DAYS): the Midsummer weekend, its Saturday 20-26 June, and
    Christmas, 23-27 December; else None."""
    if day.month == 12 and 23 <= day.day <= 27:
        return f"christmas_{day.day}"
    if day.month == 6:
        for key, saturday_offset in (("midsummer_eve", 1), ("midsummer_day", 0), ("midsummer_sunday", -1)):
            if 20 <= day.day + saturday_offset <= 26 and day.weekday() == (5 - saturday_offset) % 7:
                return key
    return None


def hour_demand(moment, urban: float = 1.0, station: Optional[dict] = None) -> float:
    """Traffic at `moment` as a share of a weekday peak hour; 1.0 without a
    clock. A measuring station's own curves (station_for_way); else measured
    LAM curves when loaded, `urban` 1 the urban ones and 0 the rural ones
    (blended between); else the estimates."""
    if moment is None:
        return 1.0
    special = special_day(moment)  # its own measured curve, volume included: no month factor on top
    if special and station is not None and special in station["special_hourly"]:
        return station["special_hourly"][special][moment.hour]
    if special and MEASURED_CURVES is not None and all(special in MEASURED_CURVES[s]["special_hourly"] for s in ("urban", "rural")):
        return sum(weight * MEASURED_CURVES[setting]["special_hourly"][special][moment.hour]
                   for setting, weight in (("urban", urban), ("rural", 1.0 - urban)))
    free_day = moment.weekday() >= 5 or is_public_holiday(moment)
    key = "weekend_hourly" if free_day else "weekday_hourly"
    if station is not None:
        return station[key][moment.hour] * station["month_factor"][moment.month]
    if MEASURED_CURVES is None:
        return (WEEKEND_HOURLY if free_day else WEEKDAY_HOURLY)[moment.hour] * MONTH_FACTOR[moment.month]
    return sum(weight * MEASURED_CURVES[setting][key][moment.hour] * MEASURED_CURVES[setting]["month_factor"][moment.month]
               for setting, weight in (("urban", urban), ("rural", 1.0 - urban)))


def traffic_demand(local_fraction: float, highway: Optional[str], moment, way=None) -> dict:
    """Moving-traffic demand around the player as a share of the city's
    town-centre peak: the local people's trips plus the road's passing
    traffic, both following the clock. Returns the parts, for diagnostics."""
    local = min(1.0, local_fraction)
    station = station_for_way(way)
    hour = hour_demand(moment, urban=min(1.0, local / URBAN_PEOPLE_FRACTION), station=station)
    through = THROUGH_TRAFFIC.get(highway or "", 0.0)
    # Gameplay nightlife, not commuter traffic counts: Friday/Saturday 18–05.
    nightlife = local * 0.5 if moment is not None and (
        moment.hour >= 18 and moment.weekday() in (4, 5)
        or moment.hour < 5 and moment.weekday() in (5, 6)
    ) else 0.0
    return {
        "local": local, "through": through, "hour": hour, "nightlife": nightlife,
        "lam_station": station["name"] if station else None,
        "demand": max(min(1.0, max(local, through)) * hour, nightlife),
    }
