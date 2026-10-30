#!/usr/bin/env python3
"""Offline LAM (TMS) traffic profile builder; never imported by the game.

PYTHONPATH=src .venv/bin/python tools/lam_profiles.py
docs/lam-traffic-audit.md phases 0-1: downloads Fintraffic's raw per-vehicle
detections (lamraw_<tmsNumber>_<yy>_<ordinal day>.csv) for a few
representative stations and one holiday-free week per season, keeps only
hourly counts per direction (cached; the raw files are ~2.5 MB a day), and
writes normalized weekday/weekend hourly curves, month factors and the
station metadata to src/theroadragetrip/assets/traffic/lam_profiles.json.
It also prints the curves against population.py's estimates.

Source: Fintraffic / digitraffic.fi, license CC 4.0 BY.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
import time
import urllib.error
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from theroadragetrip.digitraffic_road import _default_opener  # noqa: E402
from theroadragetrip.population import MONTH_FACTOR, WEEKDAY_HOURLY, WEEKEND_HOURLY  # noqa: E402

BASE = "https://tie.digitraffic.fi"
HEADERS = {"Accept-Encoding": "gzip", "Digitraffic-User": "RoadRageTrip/lam-profiles"}
OUT = ROOT / "src/theroadragetrip/assets/traffic/lam_profiles.json"
CACHE = Path.home() / ".cache/RoadRageTrip/lam"
PBF = ROOT / "src/theroadragetrip/assets/osm/finland-latest.osm.pbf"
SCHEMA_VERSION = 1

# Every station Fintraffic is gathering data from (the API's list), urban or
# rural from its surroundings (setting_of). Raw files use the tmsNumber.
# One Monday-Sunday week: no public holidays, no clock-change Sunday (a 23- or
# 25-hour day would skew the hourly bins). Special days come later.
WEEKS = [date(2026, 10, 12)]
# Days with traffic of their own, each its own curve (population.special_day):
# the Midsummer weekend (Saturday 20-26 June) and Christmas, 23-27 December.
SPECIAL_DAYS = {"midsummer_eve": date(2026, 6, 19), "midsummer_day": date(2026, 6, 20), "midsummer_sunday": date(2026, 6, 21),
                **{f"christmas_{d}": date(2025, 12, d) for d in range(23, 28)}}
GROUP_MIN_DAYS = 6  # a station with fewer sampled days stays in the file, out of the urban/rural curves


def get(url: str) -> bytes:
    return _default_opener(url, HEADERS)


def hourly_counts(csv_text: str) -> dict:
    """{"1": [24 counts], "2": [24 counts]} of valid detections (faulty 0) by
    local hour and direction. Every vehicle class counts, 8 and 9 included:
    the files mark them valid, although the documented faulty rule says > 7."""
    counts = {"1": [0] * 24, "2": [0] * 24}
    for line in csv_text.splitlines():
        fields = line.split(";")
        if len(fields) >= 13 and fields[12] == "0" and fields[9] in counts and fields[3].isdigit() and int(fields[3]) < 24:
            counts[fields[9]][int(fields[3])] += 1
    return counts


def day_counts(tms: int, day: date, cache: Path):
    """A station-day's hourly counts, from the cache or downloaded; None when unpublished."""
    path = cache / f"{tms}_{day.isoformat()}.json"
    if path.exists():
        return json.loads(path.read_text())
    url = f"{BASE}/api/tms/v1/history/raw/lamraw_{tms}_{day:%y}_{day.timetuple().tm_yday}.csv"
    try:
        counts = hourly_counts(get(url).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        if error.code not in (403, 404):  # the file store answers a missing day with 403
            raise
        counts = None
    time.sleep(0.5)  # well under the 60 requests a minute an IP may make
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts))
    return counts


def station_ids() -> list:
    """The ids of the stations currently gathering data."""
    features = json.loads(get(f"{BASE}/api/tms/v1/stations"))["features"]
    return sorted(f["id"] for f in features if f["properties"].get("collectionStatus") == "GATHERING")


def station_meta(station_id: int, cache: Path) -> dict:
    path = cache / f"station_{station_id}.json"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(f"{BASE}/api/tms/v1/stations/{station_id}"))
    feature = json.loads(path.read_text())
    properties = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]
    address = properties.get("roadAddress") or {}
    return {"id": station_id, "tms_number": properties["tmsNumber"], "name": properties["name"], "lon": lon, "lat": lat,
            "road_number": address.get("roadNumber"), "road_section": address.get("roadSection"),
            "distance_from_section_start_m": address.get("distanceFromRoadSectionStart"),
            "carriageway": address.get("carriageway"), "side": address.get("side"),
            "direction1_municipality": properties.get("direction1Municipality"),
            "direction2_municipality": properties.get("direction2Municipality"),
            "free_flow_speed_kmh": [properties.get("freeFlowSpeed1"), properties.get("freeFlowSpeed2")],
            "bearing": properties.get("bearing")}  # direction 1's heading, degrees from north


# -- phase 2: the OSM road each station measures ------------------------------

MATCH_MAX_M = 40.0  # the station's road must pass this close
HEADING_TOLERANCE_DEG = 50.0  # ... along the bearing (either way): API bearings were seen 45 deg off (vt22 Muhos)
COMPETITOR_MARGIN_M = 10.0  # another parallel road this much farther than the match: ambiguous
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified"}  # no ramps (*_link)


def overpass(query: str, path: Path):
    """An Overpass answer's elements, cached at `path`."""
    from theroadragetrip.config import DEFAULT_OVERPASS_ENDPOINTS
    from theroadragetrip.osm.overpass import OVERPASS_HEADERS

    if path.exists():
        return json.loads(path.read_text())
    for attempt in range(6):  # Overpass answers 429/502/504 when busy: the other endpoint, then later
        endpoint = DEFAULT_OVERPASS_ENDPOINTS[attempt % len(DEFAULT_OVERPASS_ENDPOINTS)]
        request = urllib.request.Request(endpoint, data=urllib.parse.urlencode({"data": query}).encode(), headers=OVERPASS_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                elements = json.loads(response.read())["elements"]
            break
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            print(f"Overpass {endpoint}: {error}; retrying", file=sys.stderr)
            time.sleep(5.0 * (attempt + 1))
    else:
        raise RuntimeError(f"Overpass unavailable: {query}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(elements))
    time.sleep(2.0)  # Overpass is shared
    return elements


def osm_ways_near(lat: float, lon: float, cache: Path) -> list:
    """Overpass highway ways within 150 m, with geometry; cached per position."""
    elements = overpass(f'[out:json][timeout:25];way(around:150,{lat},{lon})["highway"];out tags geom;',
                        cache / f"osm_{lat:.5f}_{lon:.5f}.json")
    return [e for e in elements if e["type"] == "way"]


def buildings_near(lat: float, lon: float, cache: Path) -> int:
    """OSM buildings within URBAN_RADIUS_M; cached per position."""
    elements = overpass(f'[out:json][timeout:25];way(around:{URBAN_RADIUS_M:.0f},{lat},{lon})["building"];out count;',
                        cache / f"buildings_{lat:.5f}_{lon:.5f}.json")
    return int(elements[0]["tags"]["ways"])


def _segment_m(lat: float, lon: float, a: list, b: list) -> float:
    """Metres from (lat, lon) to the segment a-b ([lon, lat] each), flat locally."""
    kx = 111320.0 * math.cos(math.radians(lat))
    ax, ay, bx, by = (a[0] - lon) * kx, (a[1] - lat) * 110540.0, (b[0] - lon) * kx, (b[1] - lat) * 110540.0
    length2 = (bx - ax) ** 2 + (by - ay) ** 2
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * (bx - ax) + ay * (by - ay)) / length2))
    return math.hypot(ax + t * (bx - ax), ay + t * (by - ay))


def prefill_from_pbf(points: list, cache: Path, pbf: Path) -> None:
    """The osm_/buildings_ cache files of the (lat, lon) points still missing
    them, in one pass over the local Finland extract instead of two Overpass
    queries a station. Overpass stays the fallback without osmium or the file."""
    import subprocess

    from theroadragetrip.utils.pbf_index import osmium_command

    points = [(lat, lon) for lat, lon in points
              if not (cache / f"osm_{lat:.5f}_{lon:.5f}.json").exists() or not (cache / f"buildings_{lat:.5f}_{lon:.5f}.json").exists()]
    if not points or not pbf.is_file() or osmium_command() is None:
        return
    filtered, lines = cache / "highways_buildings.osm.pbf", cache / "highways_buildings.geojsonseq"
    if not lines.exists() or lines.stat().st_mtime < pbf.stat().st_mtime:
        print(f"Filtering {pbf.name} for {len(points)} stations (a few minutes)...", file=sys.stderr)
        subprocess.run([osmium_command(), "tags-filter", str(pbf), "w/highway", "w/building", "-O", "-o", str(filtered)], check=True)
        subprocess.run([osmium_command(), "export", str(filtered), "-f", "geojsonseq", "-a", "id", "--geometry-types=linestring,polygon", "-O", "-o", str(lines)], check=True)
    cell = 0.02  # degrees; a station looks one cell around it (> 500 m everywhere in Finland)
    grid: dict = {}
    for index, (lat, lon) in enumerate(points):
        grid.setdefault((math.floor(lat / cell), math.floor(lon / cell)), []).append(index)
    ways, buildings = [[] for _ in points], [0] * len(points)
    with lines.open(encoding="utf-8") as stream:
        for line in stream:
            feature = json.loads(line.lstrip("\x1e"))
            geometry, tags = feature["geometry"], feature["properties"]
            coords = geometry["coordinates"][0] if geometry["type"] == "Polygon" else geometry["coordinates"]
            if geometry["type"] == "MultiPolygon":
                coords = coords[0][0]
            if not coords or not isinstance(coords[0], list):
                continue
            near = {i for lon, lat in coords for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                    for i in grid.get((math.floor(lat / cell) + dy, math.floor(lon / cell) + dx), ())}
            for i in near:
                lat, lon = points[i]
                if "building" in tags and geometry["type"] != "LineString":  # a closed way comes as both
                    buildings[i] += any(_segment_m(lat, lon, c, c) <= URBAN_RADIUS_M for c in coords)
                if "highway" in tags and geometry["type"] == "LineString" and any(_segment_m(lat, lon, a, b) <= 150.0 for a, b in zip(coords, coords[1:])):
                    ways[i].append({"type": "way", "id": int(str(tags.pop("@id", 0)).lstrip("w") or 0),
                                    "tags": {k: v for k, v in tags.items() if not k.startswith("@")},
                                    "geometry": [{"lat": c[1], "lon": c[0]} for c in coords]})
    for i, (lat, lon) in enumerate(points):  # Overpass's answer shapes: osm_ways_near / buildings_near read them
        (cache / f"osm_{lat:.5f}_{lon:.5f}.json").write_text(json.dumps(ways[i]))
        (cache / f"buildings_{lat:.5f}_{lon:.5f}.json").write_text(json.dumps([{"tags": {"ways": str(buildings[i])}}]))


def _heading(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, dy)) % 360.0  # from north, clockwise (x east, y north)


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


CHORD_M = 75.0  # the road's direction: its line within this distance of the station, end to end


def _nearest(points: list, x: float, y: float):
    """(distance m, the way's heading in point order near the station): the
    chord of its points within CHORD_M (a single segment can be a kink on a
    curve), else the nearest segment's."""
    best = (math.inf, 0.0)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length2 = (bx - ax) ** 2 + (by - ay) ** 2
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length2))
        distance = math.hypot(ax + t * (bx - ax) - x, ay + t * (by - ay) - y)
        if distance < best[0]:
            best = (distance, _heading(bx - ax, by - ay))
    near = [(px, py) for px, py in points if math.hypot(px - x, py - y) <= CHORD_M]
    if len(near) >= 2 and math.dist(near[0], near[-1]) > 10.0:
        best = (best[0], _heading(near[-1][0] - near[0][0], near[-1][1] - near[0][1]))
    return best


def _refs(tags: dict) -> set:
    return {token.strip() for token in str(tags.get("ref", "")).replace(";", " ").split() if token.strip()}


def match_station(meta: dict, ways: list, project) -> dict:
    """The OSM way(s) of the station's road and which LAM direction each way's
    forward and backward travel is; or a rejection with its reason. Divided
    roads keep both carriageways."""
    if meta.get("bearing") is None or meta.get("road_number") is None:
        return {"status": "rejected", "reason": "no bearing or road number"}
    x, y = project(meta["lon"], meta["lat"])
    measured = []
    for way in ways:
        points = [project(node["lon"], node["lat"]) for node in way.get("geometry") or [] if node]  # Overpass nulls a missing node
        tags = way.get("tags", {})
        if len(points) >= 2 and tags.get("highway") in MAIN_ROADS:
            distance, heading = _nearest(points, x, y)
            measured.append((distance, heading, way, tags))
    road = [m for m in measured if str(meta["road_number"]) in _refs(m[3]) and m[0] <= MATCH_MAX_M]
    if not road:
        return {"status": "rejected", "reason": f"no ref {meta['road_number']} road within {MATCH_MAX_M:.0f} m"}
    road.sort(key=lambda m: (m[0], m[2]["id"]))
    nearest = road[0]
    if min(_angle(nearest[1], meta["bearing"]), _angle(nearest[1], meta["bearing"] + 180.0)) > HEADING_TOLERANCE_DEG:
        return {"status": "rejected", "reason": f"road heading {nearest[1]:.0f} vs bearing {meta['bearing']}"}

    def parallel(m):
        return min(_angle(m[1], nearest[1]), _angle(m[1], nearest[1] + 180.0)) <= HEADING_TOLERANCE_DEG

    competitors = [m for m in measured if m not in road and parallel(m) and m[0] <= nearest[0] + COMPETITOR_MARGIN_M]
    if competitors:
        other = competitors[0]
        return {"status": "rejected", "reason": f"parallel {other[3].get('highway')} way {other[2]['id']} "
                                                f"({other[3].get('name') or other[3].get('ref') or 'unnamed'}) at {other[0]:.0f} m"}
    matched = []
    for distance, heading, way, tags in (m for m in road if parallel(m)):
        forward = "1" if _angle(heading, meta["bearing"]) < 90.0 else "2"
        backward = "2" if forward == "1" else "1"
        oneway = tags.get("oneway") in ("yes", "true", "1") or tags.get("highway") == "motorway"
        if tags.get("oneway") == "-1":
            forward, backward, oneway = None, backward, True
        matched.append({"osm_id": way["id"], "highway": tags.get("highway"), "name": tags.get("name"), "ref": tags.get("ref"),
                        "distance_m": round(distance, 1), "forward": forward, "backward": None if oneway else backward})
    return {"status": "matched", "ways": matched}


URBAN_RADIUS_M = 500.0
URBAN_MIN_BUILDINGS = 120  # the 11 hand-labelled stations: rural <= 75, urban >= 175


def setting_of(buildings: int) -> str:
    """"urban" among a town's buildings, else "rural". ponytail: a building
    count around the detector; people_within (population.py) if it misjudges."""
    return "urban" if buildings >= URBAN_MIN_BUILDINGS else "rural"


def mean_curve(days: list) -> list:
    return [sum(day[h] for day in days) / len(days) for h in range(24)] if days else [0.0] * 24


def profile(days_by_date: dict, special: dict = None) -> dict:
    """Weekday/weekend hourly curves (both directions and each one) as shares of
    the average weekday's peak hour - population.py's convention - and each
    sampled month's average weekday total against the sampled months' mean."""
    def total(counts):
        return [counts["1"][h] + counts["2"][h] for h in range(24)]

    weekdays = [counts for day, counts in days_by_date.items() if day.weekday() < 5]
    weekends = [counts for day, counts in days_by_date.items() if day.weekday() >= 5]
    peak = max(mean_curve([total(c) for c in weekdays])) or 1.0

    def shares(days, key=None):
        return [round(v / peak, 3) for v in mean_curve([total(c) if key is None else c[key] for c in days])]

    months = {}
    for day, counts in days_by_date.items():
        if day.weekday() < 5:
            months.setdefault(day.month, []).append(sum(total(counts)))
    month_daily = {m: sum(v) / len(v) for m, v in months.items()}
    mean_daily = sum(month_daily.values()) / len(month_daily) if month_daily else 1.0
    return {
        "weekday_hourly": shares(weekdays), "weekend_hourly": shares(weekends),
        "weekday_hourly_direction": {d: shares(weekdays, d) for d in ("1", "2")},
        "weekend_hourly_direction": {d: shares(weekends, d) for d in ("1", "2")},
        "month_factor": {str(m): round(v / mean_daily, 3) for m, v in sorted(month_daily.items())},
        # each special day's own counts, against the same ordinary weekday peak: volume and shape
        "special_hourly": {key: [round(v / peak, 3) for v in total(counts)] for key, counts in (special or {}).items()},
        "weekday_peak_vehicles_per_hour": round(peak),
        "days_used": {"weekday": len(weekdays), "weekend": len(weekends)},
    }


def peak_density(station: dict):
    """Vehicles per km (both directions) at the station's average weekday peak
    hour: the measured flow over its free-flow speed (slightly low in a
    congested hour, when cars go slower and stand closer); None without both."""
    flow = station["profile"].get("weekday_peak_vehicles_per_hour")
    speeds = [v for v in station.get("free_flow_speed_kmh") or () if v]
    return round(flow / (sum(speeds) / len(speeds)), 2) if flow and speeds else None


def density_by_class(stations: list) -> dict:
    """{setting: {highway: median peak_density}} of the OSM-matched stations."""
    found: dict = {}
    for station in stations:
        match, density = station.get("osm_match", {}), peak_density(station)
        if match.get("status") == "matched" and density is not None:
            found.setdefault(station["setting"], {}).setdefault(match["ways"][0]["highway"], []).append(density)
    return {setting: {highway: round(sorted(values)[len(values) // 2], 2) for highway, values in sorted(classes.items())}
            for setting, classes in found.items()}


def group_curve(stations: list, key: str) -> list:
    return [round(sum(s["profile"][key][h] for s in stations) / len(stations), 3) for h in range(24)]


def mae(a: list, b: list) -> float:
    return round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 3)


def build(cache: Path) -> dict:
    from pyproj import Transformer

    project = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True).transform  # the game's metres
    stations = []
    metas = [station_meta(station_id, cache) for station_id in station_ids()]
    prefill_from_pbf([(m["lat"], m["lon"]) for m in metas], cache, PBF)
    for meta in metas:
        days, missing = {}, []
        for week in WEEKS:
            for offset in range(7):
                day = week + timedelta(days=offset)
                counts = day_counts(meta["tms_number"], day, cache)
                if counts is None or sum(counts["1"]) + sum(counts["2"]) == 0:
                    missing.append(day.isoformat())
                else:
                    days[day] = counts
        special = {key: counts for key, day in SPECIAL_DAYS.items()
                   if (counts := day_counts(meta["tms_number"], day, cache)) and sum(counts["1"]) + sum(counts["2"])}
        print(f"{meta['name']}: {len(days)} days, {len(missing)} missing, {len(special)} special", file=sys.stderr)
        ways = osm_ways_near(meta["lat"], meta["lon"], cache)
        osm_match = match_station(meta, ways, project)
        setting = setting_of(buildings_near(meta["lat"], meta["lon"], cache))
        x_m, y_m = project(meta["lon"], meta["lat"])  # the game's coordinates: no projection at runtime
        stations.append({**meta, "x_m": round(x_m, 1), "y_m": round(y_m, 1), "setting": setting, "missing_days": missing, "profile": profile(days, special), "osm_match": osm_match})
    complete = [s for s in stations if sum(s["profile"]["days_used"].values()) >= GROUP_MIN_DAYS]
    groups = {setting: {key: group_curve([s for s in complete if s["setting"] == setting], key)
                        for key in ("weekday_hourly", "weekend_hourly")} for setting in ("urban", "rural")}
    for setting, group in groups.items():
        group["special_hourly"] = {}
        for key in SPECIAL_DAYS:
            curves = [s["profile"]["special_hourly"][key] for s in complete
                      if s["setting"] == setting and key in s["profile"]["special_hourly"]]
            if curves:
                group["special_hourly"][key] = [round(sum(c[h] for c in curves) / len(curves), 3) for h in range(24)]
    for setting, densities in density_by_class(complete).items():
        groups[setting]["peak_density_per_km"] = densities
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Fintraffic / digitraffic.fi, license CC 4.0 BY: TMS raw detections (lamraw), valid records only",
        "sample_weeks": [week.isoformat() for week in WEEKS],
        "special_days": {key: day.isoformat() for key, day in SPECIAL_DAYS.items()},
        "convention": "hourly values are shares of the station's average weekday peak hour, local Finnish time",
        "groups": groups, "group_stations": [s["id"] for s in complete], "stations": stations,
    }


def report(data: dict) -> None:
    """The measured curves next to population.py's estimates."""
    print("hour  " + " ".join(f"{h:>5}" for h in range(24)))
    rows = [("est weekday", WEEKDAY_HOURLY), ("est weekend", WEEKEND_HOURLY)]
    for setting, curves in data["groups"].items():
        rows += [(f"{setting} weekday", curves["weekday_hourly"]), (f"{setting} weekend", curves["weekend_hourly"])]
    for name, curve in rows:
        print(f"{name:<14}" + " ".join(f"{v:5.2f}" for v in curve))
    for setting, curves in data["groups"].items():
        print(f"MAE vs estimate, {setting}: weekday {mae(curves['weekday_hourly'], WEEKDAY_HOURLY)}, "
              f"weekend {mae(curves['weekend_hourly'], WEEKEND_HOURLY)}")
    print("\nOSM matches (review each on https://www.openstreetmap.org/way/<id>):")
    for station in data["stations"]:
        match = station["osm_match"]
        if match["status"] == "matched":
            ways = "; ".join(f"{w['osm_id']} {w['highway']} {w['name'] or ''} {w['distance_m']} m fwd={w['forward']} bwd={w['backward']}"
                             for w in match["ways"])
            print(f"  {station['name']:<30} bearing {station['bearing']}: {ways}")
        else:
            print(f"  {station['name']:<30} REJECTED: {match['reason']}")
    for station in data["stations"]:
        factors = station["profile"]["month_factor"]
        print(f"{station['name']:<34} month factors {factors}  (estimate {[MONTH_FACTOR[int(m)] for m in factors]})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--cache", type=Path, default=CACHE, help="hourly counts per station-day (default: %(default)s)")
    args = parser.parse_args()
    data = build(args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    report(data)


if __name__ == "__main__":
    main()
