import collections
import concurrent.futures
from collections import defaultdict
import json
import logging
import math
import multiprocessing
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from .geo import dist_point_to_segment, point_in_polygon

logger = logging.getLogger(__name__)

# Top 10 cities of Finland by population with center coordinates (lat, lon)
CITY_CENTERS: Dict[str, Tuple[float, float]] = {
    "Helsinki": (60.169525, 24.935446),
    "Espoo": (60.205000, 24.652000),
    "Tampere": (61.499113, 23.787117),
    "Vantaa": (60.294000, 25.041000),
    "Oulu": (65.012000, 25.468000),
    "Turku": (60.451483, 22.268686),
    "Jyväskylä": (62.241470, 25.720880),
    "Kuopio": (62.892382, 27.677028),
    "Lahti": (60.982674, 25.661509),
    "Sysmä": (61.502271, 25.680613),
}


def bbox_from_center(lat: float, lon: float, size_km: float = 4.0) -> Tuple[float, float, float, float]:
    """Calculate (south, west, north, east) bbox around a center coordinate of size_km x size_km."""
    half_size_km = size_km / 2.0
    # 1 deg latitude is approx 111.0 km
    dlat = half_size_km / 111.0
    # 1 deg longitude varies with latitude
    dlon = half_size_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return (
        round(lat - dlat, 6),
        round(lon - dlon, 6),
        round(lat + dlat, 6),
        round(lon + dlon, 6),
    )


# Bounding box presets: south, west, north, east (lat/lon)
# Generate presets for all top 10 cities (4x4 km area) while preserving lowercase lookups
BBOX_PRESETS: Dict[str, Tuple[float, float, float, float]] = {
    name.lower(): bbox_from_center(lat, lon, size_km=4.0)
    for name, (lat, lon) in CITY_CENTERS.items()
}
DEFAULT_BBOX = BBOX_PRESETS["oulu"]

# Road drawing thickness (in meters, will be scaled)
DEFAULT_ROAD_HALF_WIDTH_M = 3.0

# Simple widths by highway type (half-width meters per direction-ish)
HIGHWAY_HALF_WIDTH = {
    "motorway": 7.0,
    "trunk": 6.5,
    "primary": 6.0,
    "secondary": 5.5,
    "tertiary": 5.0,
    "unclassified": 4.5,
    "residential": 4.5,
    "living_street": 4.0,
    "busway": 4.0,
    "service": 3.5,
    "track": 2.0,
    "path": 1.2,
    "footway": 1.2,
    "cycleway": 1.5,
}

# Standard Finnish default speed limits in km/h by highway type
# - Motorway / moottoritie: 100 or 120 km/h (default 100 km/h general baseline)
# - Trunk / moottoriliikennetie: 80 or 100 km/h
# - Primary / kantatiet & valtatiet: 80 km/h
# - Secondary / seututiet: 80 km/h (or 60 km/h near populated areas)
# - Tertiary / yhdystiet: 60 km/h
# - Urban unclassified / connecting: 50 km/h
# - Residential / taajama-alue: 40 km/h (or 30 km/h)
# - Living street / pihamaa / kävelykatu / pihatie: 20 km/h
# - Service road / tonttiliittymä / pihatie: 30 km/h
# - Busway: 50 km/h
DEFAULT_SPEED_LIMITS_KMH = {
    "motorway": 100,
    "trunk": 80,
    "primary": 80,
    "secondary": 80,
    "tertiary": 60,
    "unclassified": 50,
    "residential": 40,
    "living_street": 20,
    "busway": 50,
    "service": 30,
    "track": 30,
    "path": 20,
    "footway": 20,
    "cycleway": 20,
}


def parse_speed_limit_kmh(maxspeed_tag: Optional[str], highway_type: str) -> int:
    """Parse OSM maxspeed tag into integer km/h with Finnish statutory fallbacks."""
    if maxspeed_tag:
        tag_str = str(maxspeed_tag).strip().lower()
        if tag_str.isdigit():
            return int(tag_str)
        # Handle formats like "50 km/h" or "FI:urban" / "FI:rural"
        if " " in tag_str:
            num_part = tag_str.split()[0]
            if num_part.isdigit():
                return int(num_part)
        if "urban" in tag_str:
            return 50
        if "rural" in tag_str:
            return 80
        if "motorway" in tag_str:
            return 100
        if "living_street" in tag_str:
            return 20

    return DEFAULT_SPEED_LIMITS_KMH.get(highway_type, 50)


DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

OVERPASS_HEADERS = {
    "User-Agent": "TheRoadRageTrip/0.0.1 (https://github.com/theroadragetrip; educational driving game poc)"
}

CACHE_DIR = "osm_cache"
DEAD_ENDS_CACHE_FILE = os.path.join(CACHE_DIR, "dead_ends.json")


def load_dead_ends_cache() -> List[dict]:
    """Load cached dead-end / empty-tile fetch boundaries."""
    if not os.path.exists(DEAD_ENDS_CACHE_FILE):
        return []
    try:
        with open(DEAD_ENDS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("dead_ends", [])
    except Exception as e:
        logger.warning("Failed to load dead-ends cache: %s", e)
        return []


def save_dead_end_to_cache(entry: dict) -> None:
    """Save a dead-end entry (coordinates, direction/bbox, reason) to cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    dead_ends = load_dead_ends_cache()
    dead_ends.append(entry)
    try:
        with open(DEAD_ENDS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"updated_at": time.time(), "dead_ends": dead_ends}, f, indent=2)
        logger.info("Saved dead-end road record to %s", DEAD_ENDS_CACHE_FILE)
    except Exception as e:
        logger.warning("Failed to save dead-end cache: %s", e)


@dataclass
class Way:
    points_m: List[Tuple[float, float]]
    highway: str
    half_width_m: float
    name: Optional[str] = None
    is_ice_road: bool = False
    is_drivable: bool = True
    is_busway: bool = False
    oneway: int = 0  # 0: two-way, 1: forward direction, -1: backward direction
    lanes: int = 1  # number of lanes
    layer: int = 0  # OSM vertical layer / level (-5 to 5)
    is_bridge: bool = False
    is_tunnel: bool = False
    speed_limit_kmh: int = 50  # Finnish speed limit in km/h
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    osm_id: Optional[int] = None


@dataclass
class Water:
    points_m: List[Tuple[float, float]]
    kind: str
    is_polygon: bool
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Building:
    points_m: List[Tuple[float, float]]
    name: Optional[str] = None
    housenumber: Optional[str] = None
    street: Optional[str] = None
    height_m: float = 8.0
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Scenery:
    points_m: List[Tuple[float, float]]
    kind: str
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    trees: List[Tuple[float, float]] = field(default_factory=list)


def _building_height(tags: Dict[str, Any], points: List[Tuple[float, float]]) -> float:
    """Return OSM height, level-derived height, or a footprint-based default."""
    raw_height = tags.get("height")
    if raw_height:
        try:
            height = float(str(raw_height).lower().replace("m", "").strip())
            if height > 0:
                return max(3.0, min(height, 120.0))
        except (TypeError, ValueError):
            pass

    raw_levels = tags.get("building:levels") or tags.get("levels")
    if raw_levels:
        try:
            levels = float(raw_levels)
            if levels > 0:
                return max(3.0, min(3.2 * levels + 1.5, 120.0))
        except (TypeError, ValueError):
            pass

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    footprint_scale = math.sqrt(max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys))))
    return min(24.0, 5.0 + footprint_scale * 0.18)


@dataclass
class TrafficLight:
    x: float
    y: float
    cycle_time: float = 16.0  # seconds per full cycle
    offset: float = 0.0  # phase offset in seconds (e.g. 0.0 for NS/Main, 8.0 for EW/Cross)
    layer: int = 0
    id: Optional[int] = None
    direction_angle: Optional[float] = None  # Road alignment heading in radians

    def get_state(self, current_time: float) -> str:
        """Return 'red', 'red+yellow', 'green', or 'yellow' for the traffic signal following Finnish sequence.

        In a 16s cycle:
        - 0.0s to 5.5s: Green (5.5s)
        - 5.5s to 7.0s: Yellow (1.5s transition before red)
        - 7.0s to 14.5s: Red (7.5s clearance / waiting)
        - 14.5s to 16.0s: Red+Yellow (1.5s preparation before green)
        Opposing phase has an 8.0s offset.
        """
        t = (current_time + self.offset) % self.cycle_time
        if t < 5.5:
            return "green"
        elif t < 7.0:
            return "yellow"
        elif t < 14.5:
            return "red"
        else:
            return "red+yellow"


@dataclass
class Place:
    x: float
    y: float
    name: str
    kind: str  # suburb, neighbourhood, quarter, village, town, city


@dataclass
class Crossing:
    """Pedestrian crossing (suojatie)."""
    x: float
    y: float
    layer: int = 0
    id: Optional[int] = None
    crossing_type: str = "zebra"  # zebra, marked, uncontrolled, traffic_signals
    direction_angle: Optional[float] = None  # Road axis alignment angle in radians
    width_m: float = 3.5  # Width across road (length of crossing)
    length_m: float = 2.4  # Depth along road (stripe length)


@dataclass
class TaxiStop:
    x: float
    y: float
    id: Optional[int] = None


def load_local_sample(path: str = "sample_osm.json") -> Optional[List[dict]]:
    """Load a small local sample OSM 'elements' list for offline testing.

    Tries the provided path, package-relative samples, and `sample_osm_large.json`.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = [
        path,
        os.path.join(root_dir, path),
        os.path.join(root_dir, "sample_osm.json"),
        "sample_osm_large.json",
        os.path.join(root_dir, "sample_osm_large.json"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("elements")
    return None


def _bbox_cache_path(bbox: Tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    fname = f"bbox_{south}_{west}_{north}_{east}.json"
    safe = fname.replace(".", "p").replace("-", "m")
    return os.path.join(CACHE_DIR, safe)


def load_osm_cache(bbox: Tuple[float, float, float, float]) -> Optional[List[dict]]:
    path = _bbox_cache_path(bbox)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        ts = d.get("fetched_at", 0)
        ttl = int(os.getenv("OSM_CACHE_TTL", str(24 * 3600)))
        if time.time() - ts > ttl:
            return None
        return d.get("elements")
    except Exception as e:
        logger.warning("Failed to read cache %s: %s", path, e)
        return None


def save_osm_cache(bbox: Tuple[float, float, float, float], elements: List[dict]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _bbox_cache_path(bbox)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": time.time(), "elements": elements}, f)
        logger.info("Saved OSM cache to %s", path)
    except Exception as e:
        logger.warning("Failed to save cache %s: %s", path, e)


def fetch_osm_ways(
    bbox: Tuple[float, float, float, float],
    endpoints: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    force_refresh: bool = False,
) -> List[dict]:
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:25];
    (
      node["highway"="traffic_signals"]({south},{west},{north},{east});
      node["highway"="crossing"]({south},{west},{north},{east});
      node["highway"="taxi_stop"]({south},{west},{north},{east});
      node["amenity"="taxi"]({south},{west},{north},{east});
      node["crossing"]({south},{west},{north},{east});
      node["place"~"suburb|neighbourhood|quarter|village|town|city|hamlet"]({south},{west},{north},{east});
      way["highway"]({south},{west},{north},{east});
      way["natural"="water"]({south},{west},{north},{east});
      way["waterway"]({south},{west},{north},{east});
      way["landuse"="reservoir"]({south},{west},{north},{east});
      way["building"]({south},{west},{north},{east});
      way["landuse"~"forest|grass|park|meadow|residential|commercial|industrial|recreation_ground"]({south},{west},{north},{east});
      way["leisure"~"park|garden|pitch|playground"]({south},{west},{north},{east});
      way["natural"~"wood|scrub|grass|sand|heath"]({south},{west},{north},{east});
      way["place"~"suburb|neighbourhood|quarter|village"]({south},{west},{north},{east});
      relation["natural"="water"]({south},{west},{north},{east});
      relation["landuse"="reservoir"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
      relation["leisure"="park"]({south},{west},{north},{east});
      relation["landuse"~"forest|grass|park|meadow"]({south},{west},{north},{east});
      relation["place"~"suburb|neighbourhood|quarter"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """

    if progress_callback:
        progress_callback(0.1, "Checking cache...")

    force_refresh = force_refresh or os.getenv("OVERPASS_FORCE_REFRESH", "0").lower() in ("1", "true", "yes")
    if not force_refresh:
        cached = load_osm_cache(bbox)
        if cached is not None:
            logger.info("Loaded OSM data from local cache")
            if progress_callback:
                progress_callback(0.5, f"Loaded {len(cached)} cached elements")
            return cached

    endpoints = endpoints or DEFAULT_OVERPASS_ENDPOINTS
    env_eps = os.getenv("OVERPASS_ENDPOINTS")
    if env_eps:
        endpoints = [e.strip() for e in env_eps.split(",") if e.strip()]
    last_err = None

    for ep in endpoints:
        for attempt in range(1, 4):
            try:
                if progress_callback:
                    progress_callback(0.25, f"Fetching scenery from {ep[:35]}...")
                r = requests.post(ep, data={"data": query}, headers=OVERPASS_HEADERS, timeout=60)
                if r.status_code >= 500:
                    last_err = Exception(f"{r.status_code} Server Error from {ep}")
                    time.sleep(2 ** (attempt - 1))
                    continue
                r.raise_for_status()
                if progress_callback:
                    progress_callback(0.5, "Parsing OSM payload...")
                data = r.json()
                els = data.get("elements", [])
                logger.info("Loaded OSM data from %s (%d elements)", ep, len(els))
                try:
                    save_osm_cache(bbox, els)
                except Exception:
                    pass
                if progress_callback:
                    progress_callback(0.6, f"Downloaded {len(els)} elements")
                return els
            except requests.exceptions.Timeout as e:
                last_err = e
                logger.warning("Timeout from %s (attempt %d)", ep, attempt)
                time.sleep(2 ** (attempt - 1))
                continue
            except requests.exceptions.ConnectionError as e:
                last_err = e
                logger.warning("Connection error to %s (attempt %d)", ep, attempt)
                time.sleep(2 ** (attempt - 1))
                continue
            except requests.exceptions.HTTPError as e:
                last_err = e
                status = getattr(e.response, "status_code", None)
                if status and 400 <= status < 500:
                    logger.warning("HTTP %s from %s; moving to next endpoint", status, ep)
                    break
                logger.warning("HTTP error from %s (attempt %d): %s", ep, attempt, e)
                time.sleep(2 ** (attempt - 1))
                continue
            except Exception as e:
                last_err = e
                logger.warning("Error when contacting %s: %s", ep, e)
                time.sleep(2 ** (attempt - 1))
                continue

    sample = load_local_sample()
    if sample:
        logger.info("Using local sample OSM data as fallback.")
        if progress_callback:
            progress_callback(0.5, f"Loaded {len(sample)} sample elements")
        return sample
    raise last_err or Exception("Failed to fetch OSM data from any endpoint or local sample.")


def _stitch_member_ways_into_rings(
    way_ids: List[int],
    ways_by_id: Dict[int, dict],
    process_node_ids_fn: Callable[[List[int]], Optional[List[Tuple[float, float]]]],
) -> List[Tuple[List[Tuple[float, float]], bool]]:
    """Stitch member ways into closed polygon rings or continuous linestrings in O(N) time.

    Returns a list of (points_m, is_closed) tuples.
    """
    segments: List[List[int]] = []
    for wid in way_ids:
        way_el = ways_by_id.get(wid)
        if way_el and way_el.get("nodes") and len(way_el["nodes"]) >= 2:
            segments.append(list(way_el["nodes"]))

    if not segments:
        return []

    node_to_segs = defaultdict(list)
    for seg_idx, nodes in enumerate(segments):
        node_to_segs[nodes[0]].append((seg_idx, True))
        node_to_segs[nodes[-1]].append((seg_idx, False))

    used = [False] * len(segments)
    rings: List[Tuple[List[Tuple[float, float]], bool]] = []

    for start_idx in range(len(segments)):
        if used[start_idx]:
            continue
        used[start_idx] = True
        chain = collections.deque(segments[start_idx])

        # Extend forward from chain[-1]
        while chain[0] != chain[-1]:
            end_node = chain[-1]
            found_next = False
            for seg_idx, is_start in node_to_segs[end_node]:
                if not used[seg_idx]:
                    used[seg_idx] = True
                    nodes = segments[seg_idx]
                    if is_start:
                        chain.extend(nodes[1:])
                    else:
                        chain.extend(reversed(nodes[:-1]))
                    found_next = True
                    break
            if not found_next:
                break

        # Extend backward from chain[0]
        while chain[0] != chain[-1]:
            start_node = chain[0]
            found_prev = False
            for seg_idx, is_start in node_to_segs[start_node]:
                if not used[seg_idx]:
                    used[seg_idx] = True
                    nodes = segments[seg_idx]
                    if is_start:
                        for n in nodes[1:]:
                            chain.appendleft(n)
                    else:
                        for n in reversed(nodes[:-1]):
                            chain.appendleft(n)
                    found_prev = True
                    break
            if not found_prev:
                break

        chain_list = list(chain)
        is_closed = len(chain_list) >= 4 and chain_list[0] == chain_list[-1]
        pts = process_node_ids_fn(chain_list)
        if pts and len(pts) >= 2:
            rings.append((pts, is_closed))

    return rings


class MapData(tuple):
    """Container tuple for build_ways results returning 6 elements for backward compatibility while providing traffic_lights and crossings via attributes and slicing."""

    def __new__(cls, ways, waters, buildings, sceneries, places, bounds, traffic_lights=None, crossings=None, taxi_stops=None):
        return super().__new__(cls, (ways, waters, buildings, sceneries, places, bounds))

    def __init__(self, ways, waters, buildings, sceneries, places, bounds, traffic_lights=None, crossings=None, taxi_stops=None):
        self.ways = ways
        self.waters = waters
        self.buildings = buildings
        self.sceneries = sceneries
        self.places = places
        self.bounds = bounds
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.crossings = crossings if crossings is not None else []
        self.taxi_stops = taxi_stops if taxi_stops is not None else []

    @property
    def traffic_signals(self):
        return self.traffic_lights


def build_ways(
    elements: List[dict],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> MapData:
    """Convert OSM elements to EPSG:3067 meters.

    Returns:
      - MapData (ways, waters, buildings, sceneries, places, (minx, miny, maxx, maxy))
        with .traffic_lights attribute, compatible with 6-tuple unpacking `ways, waters, buildings, sceneries, places, bounds = build_ways(...)`.
    """
    t_start = time.time()
    if progress_callback:
        progress_callback(0.65, "Indexing OSM elements...")

    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)

    node_ids_list: List[int] = []
    node_lons: List[float] = []
    node_lats: List[float] = []

    place_nodes_raw: List[Tuple[dict, int]] = []
    traffic_signals_raw: List[Tuple[dict, int]] = []
    crossings_raw: List[Tuple[dict, int]] = []
    taxi_stops_raw: List[Tuple[dict, int]] = []
    ways_by_id: Dict[int, dict] = {}
    ways_raw: List[Tuple[dict, str, List[int]]] = []
    water_raw: List[Tuple[dict, List[int]]] = []
    building_raw: List[Tuple[dict, List[int]]] = []
    scenery_raw: List[Tuple[dict, List[int]]] = []
    relations_raw: List[Tuple[dict, List[dict]]] = []

    for el in elements:
        el_type = el.get("type")
        if el_type == "node":
            nid = el["id"]
            node_ids_list.append(nid)
            node_lons.append(el["lon"])
            node_lats.append(el["lat"])
            tags = el.get("tags", {})
            if "place" in tags and "name" in tags:
                place_nodes_raw.append((tags, nid))
            if tags.get("highway") == "traffic_signals":
                traffic_signals_raw.append((tags, nid))
            if tags.get("highway") == "taxi_stop" or tags.get("amenity") == "taxi":
                taxi_stops_raw.append((tags, nid))
            if tags.get("highway") == "crossing" or tags.get("crossing") in ("zebra", "marked", "uncontrolled", "traffic_signals", "yes"):
                crossings_raw.append((tags, nid))
        elif el_type == "way":
            tags = el.get("tags", {})
            node_ids = el.get("nodes", [])
            way_id = el.get("id")
            if way_id is not None:
                ways_by_id[way_id] = el
            if len(node_ids) < 2:
                continue
            if "building" in tags:
                building_raw.append((tags, node_ids))
            elif tags.get("natural") == "water" or ("waterway" in tags) or tags.get("landuse") == "reservoir":
                water_raw.append((tags, node_ids))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("wood", "scrub", "grass", "sand", "heath"):
                scenery_raw.append((tags, node_ids))
            elif "highway" in tags:
                highway = tags.get("highway", "unclassified")
                ways_raw.append((tags, highway, node_ids, way_id))
        elif el_type == "relation":
            tags = el.get("tags", {})
            if tags.get("type") == "multipolygon":
                members = el.get("members", [])
                relations_raw.append((tags, members))

    logger.info(
        "Parsed %d OSM elements: %d nodes, %d ways, %d relations",
        len(elements),
        len(node_ids_list),
        len(ways_by_id),
        len(relations_raw),
    )

    # Transform coordinates in batch
    nodes_m: Dict[int, Tuple[float, float]] = {}
    if node_ids_list:
        if progress_callback:
            progress_callback(0.70, f"Transforming {len(node_ids_list)} coordinates...")
        logger.info("Transforming %d node coordinates to EPSG:3067...", len(node_ids_list))

        try:
            xs, ys = transformer.transform(node_lons, node_lats)
            if hasattr(xs, "__len__") and len(xs) == len(node_ids_list):
                nodes_m = {nid: (x, y) for nid, x, y in zip(node_ids_list, xs, ys)}
            else:
                nodes_m = {
                    nid: transformer.transform(lon, lat)
                    for nid, lon, lat in zip(node_ids_list, node_lons, node_lats)
                }
        except Exception:
            nodes_m = {
                nid: transformer.transform(lon, lat)
                for nid, lon, lat in zip(node_ids_list, node_lons, node_lats)
            }

    t_transform = time.time() - t_start
    logger.info("Coordinate transformation finished in %.3fs (%d nodes)", t_transform, len(nodes_m))

    ways: List[Way] = []
    waters: List[Water] = []
    buildings: List[Building] = []
    sceneries: List[Scenery] = []
    places: List[Place] = []
    traffic_lights: List[TrafficLight] = []
    crossings: List[Crossing] = []
    taxi_stops: List[TaxiStop] = []

    minx = miny = float("inf")
    maxx = maxy = float("-inf")

    # Helper to convert node_ids to metric coordinates, calculate item bbox, and update global bounds
    def process_node_ids(
        node_ids: List[int],
    ) -> Tuple[Optional[List[Tuple[float, float]]], Tuple[float, float, float, float]]:
        pts = []
        iminx = iminy = float("inf")
        imaxx = imaxy = float("-inf")
        for nid in node_ids:
            pt = nodes_m.get(nid)
            if pt is None:
                return None, (0.0, 0.0, 0.0, 0.0)
            pts.append(pt)
            x, y = pt
            if x < iminx:
                iminx = x
            if x > imaxx:
                imaxx = x
            if y < iminy:
                iminy = y
            if y > imaxy:
                imaxy = y
        return pts, (iminx, iminy, imaxx, imaxy)

    # 1. Scenery polygons (parks, forests, grass)
    if progress_callback:
        progress_callback(0.78, f"Building scenery ({len(scenery_raw)} areas)...")
    for tags, node_ids in scenery_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 3:
            continue
        kind = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
        name = tags.get("name")
        sceneries.append(Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox))

    # 2. Water polygons and waterways
    if progress_callback:
        progress_callback(0.84, f"Building water features ({len(water_raw)} elements)...")
    for tags, node_ids in water_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 2:
            continue
        is_poly = pts[0] == pts[-1]
        kind = tags.get("natural") or tags.get("waterway") or tags.get("landuse") or "water"
        name = tags.get("name")
        waters.append(Water(points_m=pts, kind=kind, is_polygon=is_poly, name=name, bbox=ibbox))

    # 3. Buildings
    if progress_callback:
        progress_callback(0.90, f"Building structures ({len(building_raw)} buildings)...")
    for tags, node_ids in building_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 3:
            continue
        name = tags.get("name")
        housenumber = tags.get("addr:housenumber")
        street = tags.get("addr:street")
        buildings.append(Building(
            points_m=pts,
            name=name,
            housenumber=housenumber,
            street=street,
            height_m=_building_height(tags, pts),
            bbox=ibbox,
        ))

    # 4. Roads (ways)
    if progress_callback:
        progress_callback(0.94, f"Building road network ({len(ways_raw)} ways)...")
    non_drivable_highways = {
        "footway",
        "path",
        "pedestrian",
        "cycleway",
        "steps",
        "bridleway",
        "corridor",
        "track",
    }
    for tags, highway, node_ids, way_id in ways_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 2:
            continue
        # Update road coverage bounds based specifically on drivable roads
        for px, py in pts:
            if px < minx:
                minx = px
            if px > maxx:
                maxx = px
            if py < miny:
                miny = py
            if py > maxy:
                maxy = py
        halfw = HIGHWAY_HALF_WIDTH.get(highway, DEFAULT_ROAD_HALF_WIDTH_M)
        name = tags.get("name") or tags.get("name:fi") or tags.get("name:en") or tags.get("official_name")
        ref_num = tags.get("ref")
        if not name and ref_num:
            # Check if road is a main Finnish valtatie / kantatie / seututie
            if ref_num.startswith("E") or highway in ("motorway", "trunk"):
                name = f"Valtatie {ref_num}"
            elif highway == "primary":
                name = f"Kantatie {ref_num}"
            elif highway in ("secondary", "tertiary"):
                name = f"Seututie {ref_num}"
            else:
                name = f"Yhdystie {ref_num}"
        is_ice = (
            tags.get("ice_road") in ("yes", "seasonal")
            or tags.get("winter_road") in ("yes", "seasonal")
            or tags.get("seasonal") in ("winter", "ice", "yes")
        )
        # Underground / parking garage detection
        # Filter out underground aisles, underground parking garages, or underground tunnel service roads
        parking_tag = tags.get("parking", "")
        parking_aisle = tags.get("service") == "parking_aisle"
        location_tag = tags.get("location", "")
        covered_tag = tags.get("covered", "")
        tunnel_tag = tags.get("tunnel", "")
        level_tag = tags.get("level", "")
        layer_tag = tags.get("layer", "")

        is_underground = (
            location_tag == "underground"
            or parking_tag in ("underground", "multi-storey", "sheds", "carports")
            or covered_tag in ("yes", "arcade")
            or tunnel_tag in ("yes", "building_passage")
        )
        if level_tag:
            try:
                # Negative floor levels (e.g. -1, -2) are underground
                if float(level_tag) < 0:
                    is_underground = True
            except ValueError:
                pass

        # Parse layer integer
        layer_val = 0
        if layer_tag:
            try:
                layer_val = int(layer_tag)
            except ValueError:
                pass
        elif tunnel_tag in ("yes", "building_passage"):
            layer_val = -1
        elif tags.get("bridge") in ("yes", "viaduct", "movable"):
            layer_val = 1

        if layer_val < 0:
            is_underground = True

        # If underground parking/service route, exclude from map
        if is_underground and (parking_aisle or highway in ("service", "track") or "parking" in tags):
            continue

        is_bridge = tags.get("bridge") in ("yes", "viaduct", "movable") or layer_val > 0
        is_tunnel = tunnel_tag in ("yes", "building_passage") or layer_val < 0

        # Check busways and public transport lanes (taxis are legally permitted to drive on bus lanes/busways)
        bus_tag = tags.get("bus")
        psv_tag = tags.get("psv")  # Public service vehicle
        taxi_tag = tags.get("taxi")
        lanes_bus = tags.get("lanes:bus") or tags.get("bus:lanes") or tags.get("lanes:psv")
        is_bus_route = (
            highway == "busway"
            or bus_tag in ("yes", "designated", "permissive", "only")
            or psv_tag in ("yes", "designated", "permissive", "only")
            or taxi_tag in ("yes", "designated", "permissive")
            or bool(lanes_bus)
        )

        # Check car access
        motorcar = tags.get("motorcar")
        vehicle = tags.get("vehicle")
        access = tags.get("access")

        # In Finland, living streets (pihatiet), service drives, and bus lanes are fully allowed for taxis
        if highway == "living_street":
            is_drivable = True
        elif is_bus_route:
            is_drivable = True
        elif taxi_tag in ("yes", "designated", "permissive"):
            is_drivable = True
        elif motorcar in ("no", "private") or vehicle in ("no", "private") or access in ("no", "private"):
            is_drivable = False
        elif motorcar in ("yes", "designated", "permissive"):
            is_drivable = True
        elif highway in non_drivable_highways:
            is_drivable = False
        else:
            is_drivable = True

        # Check oneway driving direction
        # oneway values in OSM: 'yes', '1', 'true', '-1', 'reverse', 'no'
        oneway_tag = str(tags.get("oneway", "")).lower()
        junction_tag = str(tags.get("junction", "")).lower()
        oneway_dir = 0
        if oneway_tag in ("yes", "1", "true"):
            oneway_dir = 1
        elif oneway_tag in ("-1", "reverse"):
            oneway_dir = -1
        elif oneway_tag == "no":
            oneway_dir = 0
        elif highway in ("motorway", "motorway_link") or junction_tag == "roundabout":
            oneway_dir = 1

        # Parse lanes
        lanes_val = 1
        lanes_tag = tags.get("lanes")
        if lanes_tag:
            try:
                lanes_val = max(1, int(str(lanes_tag).split(";")[0].strip()))
            except ValueError:
                pass
        elif oneway_dir != 0:
            # Multi-lane default for wide oneways / motorways
            if highway in ("motorway", "trunk") or halfw >= 6.0:
                lanes_val = 2

        # Parse speed limit (OSM maxspeed tag with Finnish fallback)
        speed_lim = parse_speed_limit_kmh(tags.get("maxspeed"), highway)

        ways.append(
            Way(
                points_m=pts,
                highway=highway,
                half_width_m=halfw,
                name=name,
                is_ice_road=is_ice,
                is_drivable=is_drivable,
                is_busway=is_bus_route,
                oneway=oneway_dir,
                lanes=lanes_val,
                layer=layer_val,
                is_bridge=is_bridge,
                is_tunnel=is_tunnel,
                speed_limit_kmh=speed_lim,
                bbox=ibbox,
                osm_id=way_id,
            )
        )

    # Add deterministic tree centers to green areas, keeping trunks off roads.
    tree_kinds = {"forest", "wood", "scrub", "grass", "meadow", "heath", "park", "garden"}

    def add_trees(scenery: Scenery) -> None:
        if scenery.kind.lower() not in tree_kinds or len(scenery.points_m) < 3:
            return
        minx, miny, maxx, maxy = scenery.bbox
        area = max(0.0, (maxx - minx) * (maxy - miny))
        target = min(80, max(1, int(area / 350.0)))
        rng = random.Random(f"{round(minx)}:{round(miny)}:{scenery.kind.lower()}")
        road_candidates = [
            way for way in ways
            if getattr(way, "is_drivable", True)
            and way.bbox[2] >= minx - way.half_width_m - 3.0
            and way.bbox[0] <= maxx + way.half_width_m + 3.0
            and way.bbox[3] >= miny - way.half_width_m - 3.0
            and way.bbox[1] <= maxy + way.half_width_m + 3.0
        ]
        for _ in range(target * 5):
            if len(scenery.trees) >= target:
                break
            x = rng.uniform(minx, maxx)
            y = rng.uniform(miny, maxy)
            if not point_in_polygon(x, y, scenery.points_m):
                continue
            if any(
                dist_point_to_segment(x, y, p1[0], p1[1], p2[0], p2[1]) < way.half_width_m + 3.0
                for way in road_candidates
                for p1, p2 in zip(way.points_m, way.points_m[1:])
            ):
                continue
            scenery.trees.append((x, y))

    if progress_callback:
        progress_callback(0.965, f"Planting trees ({len(sceneries)} scenery areas)...")
    for scenery in sceneries:
        add_trees(scenery)

    # 5. Multipolygon Relations (stitched into proper closed rings)
    if progress_callback:
        progress_callback(0.97, f"Processing {len(relations_raw)} multipolygon relations...")
    for tags, members in relations_raw:
        outer_way_ids = [
            m["ref"]
            for m in members
            if m.get("type") == "way" and (m.get("role") == "outer" or m.get("role") == "")
        ]
        rings = _stitch_member_ways_into_rings(
            outer_way_ids, ways_by_id, lambda nids: process_node_ids(nids)[0]
        )
        name = tags.get("name")
        for pts, is_closed in rings:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ibbox = (min(xs), min(ys), max(xs), max(ys))
            if "building" in tags:
                housenumber = tags.get("addr:housenumber")
                street = tags.get("addr:street")
                buildings.append(Building(
                    points_m=pts,
                    name=name,
                    housenumber=housenumber,
                    street=street,
                    height_m=_building_height(tags, pts),
                    bbox=ibbox,
                ))
            elif tags.get("natural") == "water" or tags.get("landuse") == "reservoir":
                kind = tags.get("natural") or tags.get("landuse") or "water"
                waters.append(Water(points_m=pts, kind=kind, is_polygon=is_closed, name=name, bbox=ibbox))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("wood", "scrub", "grass"):
                kind = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
                scenery = Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox)
                add_trees(scenery)
                sceneries.append(scenery)
            elif "place" in tags and name and pts:
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                places.append(Place(x=cx, y=cy, name=name, kind=tags.get("place", "suburb")))

    # 6. Place nodes (suburbs, neighbourhoods, districts)
    for tags, nid in place_nodes_raw:
        pt = nodes_m.get(nid)
        if pt:
            places.append(Place(x=pt[0], y=pt[1], name=tags["name"], kind=tags.get("place", "suburb")))

    for tags, nid in taxi_stops_raw:
        pt = nodes_m.get(nid)
        if pt:
            taxi_stops.append(TaxiStop(x=pt[0], y=pt[1], id=nid))

    # 7. Traffic signals from OSM nodes
    # Find road direction at node to assign orthogonal phase offsets for intersecting streets
    if traffic_signals_raw:
        # Build spatial grid for fast candidate lookup
        signals_grid: dict[Tuple[int, int], List[Way]] = defaultdict(list)
        grid_size = 50.0
        for w in ways:
            bbox = getattr(w, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            minx_b, miny_b, maxx_b, maxy_b = bbox
            gx0 = int((minx_b - 5.0) // grid_size)
            gx1 = int((maxx_b + 5.0) // grid_size)
            gy0 = int((miny_b - 5.0) // grid_size)
            gy1 = int((maxy_b + 5.0) // grid_size)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    signals_grid[(gx, gy)].append(w)

        for tags, nid in traffic_signals_raw:
            pt = nodes_m.get(nid)
            if pt:
                layer_tag = tags.get("layer", "")
                layer_val = 0
                if layer_tag:
                    try:
                        layer_val = int(layer_tag)
                    except ValueError:
                        pass

                # Detect road orientation at signal position (0 to pi)
                road_angle = 0.0
                best_dist = 5.0
                found_orientation = False

                gx = int(pt[0] // grid_size)
                gy = int(pt[1] // grid_size)
                candidate_ways = []
                for dx_c in (-1, 0, 1):
                    for dy_c in (-1, 0, 1):
                        candidate_ways.extend(signals_grid.get((gx + dx_c, gy + dy_c), []))

                for w in candidate_ways:
                    if getattr(w, "layer", 0) != layer_val:
                        continue
                    pts = w.points_m
                    for i in range(len(pts) - 1):
                        p1, p2 = pts[i], pts[i + 1]
                        dx = p2[0] - p1[0]
                        dy = p2[1] - p1[1]
                        seg_len = math.hypot(dx, dy)
                        if seg_len > 1e-3:
                            # Distance to line segment
                            t = max(0.0, min(1.0, ((pt[0] - p1[0]) * dx + (pt[1] - p1[1]) * dy) / (seg_len * seg_len)))
                            px = p1[0] + t * dx
                            py = p1[1] + t * dy
                            d = math.hypot(pt[0] - px, pt[1] - py)
                            if d < best_dist:
                                best_dist = d
                                ang = math.atan2(dy, dx) % math.pi  # Normalized direction 0 to pi
                                road_angle = ang
                                found_orientation = True

                # Phase offset: Group into two orthogonal corridors (e.g., North-South vs East-West)
                # If road is closer to EW (angles < pi/4 or > 3pi/4), offset is 0.0s; if NS (pi/4 to 3pi/4), offset is 8.0s.
                if found_orientation:
                    is_north_south = (math.pi * 0.25) <= road_angle < (math.pi * 0.75)
                    phase_offset = 8.0 if is_north_south else 0.0
                else:
                    phase_offset = 0.0

                # Some OSM junctions map one signal node at the center instead of
                # one signal per approach. Split that incomplete representation.
                arm_angles: List[float] = []
                for way_tags, _highway, way_node_ids, _way_id in ways_raw:
                    if nid not in way_node_ids:
                        continue
                    node_index = way_node_ids.index(nid)
                    neighbor_ids = []
                    if node_index > 0:
                        neighbor_ids.append(way_node_ids[node_index - 1])
                    if node_index + 1 < len(way_node_ids):
                        neighbor_ids.append(way_node_ids[node_index + 1])
                    for neighbor_id in neighbor_ids:
                        neighbor = nodes_m.get(neighbor_id)
                        if neighbor is None:
                            continue
                        angle = math.atan2(neighbor[1] - pt[1], neighbor[0] - pt[0])
                        if all(abs((angle - existing + math.pi) % (2 * math.pi) - math.pi) > math.radians(25)
                               for existing in arm_angles):
                            arm_angles.append(angle)

                # Some extracts omit the signal node from the road ways. In
                # that case, recover arms from nearby road geometry.
                if len(arm_angles) < 3:
                    for way in candidate_ways:
                        if getattr(way, "layer", 0) != layer_val or len(way.points_m) < 2:
                            continue
                        closest_segment = min(
                            zip(way.points_m, way.points_m[1:]),
                            key=lambda segment: dist_point_to_segment(
                                pt[0], pt[1], segment[0][0], segment[0][1], segment[1][0], segment[1][1]
                            ),
                        )
                        (p1, p2) = closest_segment
                        if dist_point_to_segment(pt[0], pt[1], p1[0], p1[1], p2[0], p2[1]) > 12.0:
                            continue
                        angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                        for arm_angle in (angle, angle + math.pi):
                            if all(
                                abs((arm_angle - existing + math.pi) % (2 * math.pi) - math.pi)
                                > math.radians(25)
                                for existing in arm_angles
                            ):
                                arm_angles.append(arm_angle)

                if len(arm_angles) >= 3:
                    for arm_index, arm_angle in enumerate(arm_angles):
                        signal_angle = arm_angle % math.pi
                        signal_offset = 8.0 if (math.pi * 0.25) <= signal_angle < (math.pi * 0.75) else 0.0
                        traffic_lights.append(
                            TrafficLight(
                                x=pt[0] + math.cos(arm_angle) * 6.0,
                                y=pt[1] + math.sin(arm_angle) * 6.0,
                                cycle_time=16.0,
                                offset=signal_offset,
                                layer=layer_val,
                                id=nid * 10 + arm_index,
                                direction_angle=signal_angle,
                            )
                        )
                else:
                    traffic_lights.append(
                        TrafficLight(
                            x=pt[0],
                            y=pt[1],
                            cycle_time=16.0,
                            offset=phase_offset,
                            layer=layer_val,
                            id=nid,
                            direction_angle=road_angle if found_orientation else None,
                        )
                    )

    # 8. Pedestrian Crossings (suojatiet) from OSM nodes and ways
    if crossings_raw:
        # Build spatial grid of drivable roads to find road direction and road width at crossing
        roads_grid: dict[Tuple[int, int], List[Way]] = defaultdict(list)
        r_grid_size = 50.0
        for w in ways:
            if not getattr(w, "is_drivable", True):
                continue
            bbox = getattr(w, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            minx_b, miny_b, maxx_b, maxy_b = bbox
            gx0 = int((minx_b - 5.0) // r_grid_size)
            gx1 = int((maxx_b + 5.0) // r_grid_size)
            gy0 = int((miny_b - 5.0) // r_grid_size)
            gy1 = int((maxy_b + 5.0) // r_grid_size)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    roads_grid[(gx, gy)].append(w)

        seen_crossing_locs: Set[Tuple[int, int]] = set()

        for tags, nid in crossings_raw:
            pt = nodes_m.get(nid)
            if not pt:
                continue

            # Deduplicate closely co-located crossing nodes within 2 meters
            loc_key = (int(round(pt[0] / 2.0)), int(round(pt[1] / 2.0)))
            if loc_key in seen_crossing_locs:
                continue
            seen_crossing_locs.add(loc_key)

            layer_tag = tags.get("layer", "")
            layer_val = 0
            if layer_tag:
                try:
                    layer_val = int(layer_tag)
                except ValueError:
                    pass

            crossing_type = tags.get("crossing") or tags.get("crossing_ref") or "zebra"
            road_angle = 0.0
            road_half_w = 3.5
            best_dist = 8.0
            found_orientation = False

            gx = int(pt[0] // r_grid_size)
            gy = int(pt[1] // r_grid_size)
            candidate_roads = []
            for dx_c in (-1, 0, 1):
                for dy_c in (-1, 0, 1):
                    candidate_roads.extend(roads_grid.get((gx + dx_c, gy + dy_c), []))

            for w in candidate_roads:
                if getattr(w, "layer", 0) != layer_val:
                    continue
                pts = w.points_m
                for i in range(len(pts) - 1):
                    p1, p2 = pts[i], pts[i + 1]
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    seg_len = math.hypot(dx, dy)
                    if seg_len > 1e-3:
                        t = max(0.0, min(1.0, ((pt[0] - p1[0]) * dx + (pt[1] - p1[1]) * dy) / (seg_len * seg_len)))
                        px = p1[0] + t * dx
                        py = p1[1] + t * dy
                        d = math.hypot(pt[0] - px, pt[1] - py)
                        if d < best_dist:
                            best_dist = d
                            ang = math.atan2(dy, dx) % math.pi
                            road_angle = ang
                            road_half_w = getattr(w, "half_width_m", 3.5)
                            found_orientation = True

            crossings.append(
                Crossing(
                    x=pt[0],
                    y=pt[1],
                    layer=layer_val,
                    id=nid,
                    crossing_type=crossing_type,
                    direction_angle=road_angle if found_orientation else None,
                    width_m=max(3.0, road_half_w * 1.8),
                    length_m=2.4,
                )
            )

    t_total = time.time() - t_start
    logger.info(
        "Map generation complete in %.3fs: %d roads, %d waters, %d buildings, %d scenery polygons, %d places, %d traffic signals, %d crossings",
        t_total,
        len(ways),
        len(waters),
        len(buildings),
        len(sceneries),
        len(places),
        len(traffic_lights),
        len(crossings),
    )

    if progress_callback:
        progress_callback(
            1.0,
            f"Ready ({len(ways)} roads, {len(places)} districts, {len(buildings)} buildings, {len(waters)} waters, {len(crossings)} crossings)",
        )

    # Fallback if no roads were loaded
    if minx == float("inf") or miny == float("inf"):
        all_pts = []
        for w in waters:
            all_pts.extend(w.points_m)
        for s in sceneries:
            all_pts.extend(s.points_m)
        for b in buildings:
            all_pts.extend(b.points_m)
        if all_pts:
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
        else:
            minx = miny = 0.0
            maxx = maxy = 1000.0

    return MapData(ways, waters, buildings, sceneries, places, (minx, miny, maxx, maxy), traffic_lights, crossings, taxi_stops)


class AutoFetchManager:
    """Background auto-fetch manager for expanding map boundaries dynamically."""

    def __init__(
        self,
        ways: List[Way],
        bounds: Tuple[float, float, float, float],
        transformer,
        waters: Optional[List[Water]] = None,
        buildings: Optional[List[Building]] = None,
        sceneries: Optional[List[Scenery]] = None,
        places: Optional[List[Place]] = None,
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List[Crossing]] = None,
        fetch_func=fetch_osm_ways,
        build_func=build_ways,
        cooldown_s: float = 5.0,
        build_in_process: bool = False,
    ):
        self.ways = ways
        self.waters = waters if waters is not None else []
        self.buildings = buildings if buildings is not None else []
        self.sceneries = sceneries if sceneries is not None else []
        self.places = places if places is not None else []
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.crossings = crossings if crossings is not None else []
        self.bounds = bounds
        self.transformer = transformer
        self.fetch_func = fetch_func
        self.build_func = build_func
        self.cooldown_s = cooldown_s
        self.build_in_process = build_in_process
        self.lock = threading.Lock()
        self.is_fetching = False
        self.fetch_progress = 0.0
        self.last_fetch_time = 0.0
        self.last_trigger_reason = ""
        # Load known dead-end boundaries from disk cache
        self.dead_ends: List[dict] = load_dead_ends_cache()

    def get_bounds(self) -> Tuple[float, float, float, float]:
        with self.lock:
            return self.bounds

    def get_progress(self) -> float:
        with self.lock:
            return self.fetch_progress

    def get_fetching(self) -> bool:
        with self.lock:
            return self.is_fetching

    def get_trigger_reason(self) -> str:
        with self.lock:
            return self.last_trigger_reason

    def is_known_dead_end(self, car_x: float, car_y: float, direction: str, tolerance_m: float = 300.0) -> bool:
        """Check if vehicle is near a recorded dead-end in the given expansion direction."""
        for entry in self.dead_ends:
            if entry.get("direction") == direction:
                dx = entry.get("x", 0.0) - car_x
                dy = entry.get("y", 0.0) - car_y
                if (dx * dx + dy * dy) ** 0.5 < tolerance_m:
                    return True
        return False

    def start_if_needed(self, car, auto_fetch: bool, margin_m: float, tile_size_m: float) -> bool:
        if not auto_fetch:
            return False
        with self.lock:
            if self.is_fetching:
                return False
            now = time.time()
            if now - self.last_fetch_time < self.cooldown_s:
                return False

            minx, miny, maxx, maxy = self.bounds
            expanded = False
            trigger_reason = ""
            # Expand in the direction the car is approaching or heading
            fetch_minx, fetch_miny, fetch_maxx, fetch_maxy = minx, miny, maxx, maxy
            direction = ""

            # Determine expansion boxes centered around car's position with overlap into existing area
            half_span = tile_size_m / 2.0
            overlap = max(margin_m, 500.0)

            if car.x < minx + margin_m:
                direction = "west"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - tile_size_m
                    fetch_maxx = car.x + overlap
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True
                    trigger_reason = "bbox west edge"
            elif car.x > maxx - margin_m:
                direction = "east"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - overlap
                    fetch_maxx = car.x + tile_size_m
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True
                    trigger_reason = "bbox east edge"

            if not expanded:
                if car.y < miny + margin_m:
                    direction = "south"
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_miny = car.y - tile_size_m
                        fetch_maxy = car.y + overlap
                        fetch_minx = car.x - half_span
                        fetch_maxx = car.x + half_span
                        expanded = True
                        trigger_reason = "bbox south edge"

            if not expanded and car.y > maxy - margin_m:
                direction = "north"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_miny = car.y - overlap
                    fetch_maxy = car.y + tile_size_m
                    fetch_minx = car.x - half_span
                    fetch_maxx = car.x + half_span
                    expanded = True
                    trigger_reason = "bbox north edge"

            if not expanded:
                return False

            self.is_fetching = True
            self.fetch_progress = 0.1
            self.last_fetch_time = now
            self.last_trigger_reason = trigger_reason
            target = (fetch_minx, fetch_miny, fetch_maxx, fetch_maxy)
            car_pos = (car.x, car.y)

        t = threading.Thread(target=self._background_fetch, args=(target, direction, car_pos), daemon=True)
        t.start()
        return True

    def _background_fetch(
        self,
        target_bbox: Tuple[float, float, float, float],
        direction: str = "",
        car_pos: Tuple[float, float] = (0.0, 0.0),
    ) -> None:
        new_minx, new_miny, new_maxx, new_maxy = target_bbox
        try:
            lon1, lat1 = self.transformer.transform(new_minx, new_miny)
            lon2, lat2 = self.transformer.transform(new_maxx, new_maxy)
            south = min(lat1, lat2)
            west = min(lon1, lon2)
            north = max(lat1, lat2)
            east = max(lon1, lon2)
        except Exception as e:
            logger.warning("Failed to compute lat/lon bbox for auto-fetch: %s", e)
            with self.lock:
                self.is_fetching = False
                self.fetch_progress = 0.0
            return

        def _bg_progress(fraction: float, msg: str):
            with self.lock:
                self.fetch_progress = fraction

        try:
            with self.lock:
                self.fetch_progress = 0.25
            elems = self.fetch_func((south, west, north, east))
            with self.lock:
                self.fetch_progress = 0.65
            if self.build_in_process:
                context = multiprocessing.get_context("spawn")
                with concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
                    res = executor.submit(self.build_func, elems).result()
            else:
                res = self.build_func(elems)
            with self.lock:
                self.fetch_progress = 0.9
            new_crossings = getattr(res, "crossings", [])
            if len(res) == 8:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds, new_traffic_lights, new_crossings = res
            elif len(res) == 7:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds, new_traffic_lights = res
            elif len(res) == 6:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds = res
                new_traffic_lights = getattr(res, "traffic_lights", [])
            elif len(res) == 5:
                new_ways, new_waters, new_buildings, new_sceneries, new_bounds = res
                new_places, new_traffic_lights = [], []
            elif len(res) == 3:
                new_ways, new_waters, new_bounds = res
                new_buildings, new_sceneries, new_places, new_traffic_lights = [], [], [], []
            else:
                new_ways, new_bounds = res[0], res[-1]
                new_waters, new_buildings, new_sceneries, new_places, new_traffic_lights = [], [], [], [], []

            # Check if fetch returned no new drivable roads in target area (dead end)
            drivable_new = [w for w in new_ways if w.is_drivable]
            if not drivable_new:
                logger.info(
                    "No drivable roads found in direction %s at (%.1f, %.1f); marking as dead end in cache",
                    direction,
                    car_pos[0],
                    car_pos[1],
                )
                entry = {
                    "x": car_pos[0],
                    "y": car_pos[1],
                    "direction": direction,
                    "target_bbox": list(target_bbox),
                    "recorded_at": time.time(),
                }
                save_dead_end_to_cache(entry)
                with self.lock:
                    self.dead_ends.append(entry)

            with self.lock:
                known_way_ids = {
                    way.osm_id for way in self.ways if getattr(way, "osm_id", None) is not None
                }
                unique_new_ways = [
                    way for way in new_ways
                    if way.osm_id is None or way.osm_id not in known_way_ids
                ]
                self.ways.extend(unique_new_ways)
                self.waters.extend(new_waters)
                self.buildings.extend(new_buildings)
                self.sceneries.extend(new_sceneries)
                self.places.extend(new_places)
                self.traffic_lights.extend(new_traffic_lights)
                self.crossings.extend(new_crossings)
                minx = min(self.bounds[0], new_bounds[0])
                miny = min(self.bounds[1], new_bounds[1])
                maxx = max(self.bounds[2], new_bounds[2])
                maxy = max(self.bounds[3], new_bounds[3])
                self.bounds = (minx, miny, maxx, maxy)
                self.last_fetch_time = time.time()

            # Rebuilding the segment index can be expensive; keep the game loop
            # responsive while the background fetch finishes indexing new roads.
            with self.lock:
                self.fetch_progress = 1.0
                self.is_fetching = False
            logger.info(
                "Auto-fetched and added %d ways, %d waters, %d buildings, %d scenery, %d places, %d traffic lights, %d crossings; new bounds: %s",
                len(unique_new_ways),
                len(new_waters),
                len(new_buildings),
                len(new_sceneries),
                len(new_places),
                len(new_traffic_lights),
                len(new_crossings),
                self.bounds,
            )
        except Exception as e:
            logger.warning("Auto-fetch failed: %s", e)
            with self.lock:
                self.is_fetching = False
                self.fetch_progress = 0.0
