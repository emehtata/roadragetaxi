import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Bounding box presets: south, west, north, east (lat/lon)
BBOX_PRESETS = {
    "oulu": (64.967444, 25.361832, 65.057276, 25.574488),
    "helsinki": (60.150, 24.88, 60.205, 25.02),
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
    "service": 3.5,
    "track": 3.0,
    "path": 2.0,
    "footway": 2.0,
    "cycleway": 2.0,
}

DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

OVERPASS_HEADERS = {
    "User-Agent": "TheRoadRageTrip/0.1 (https://github.com/theroadragetrip; educational driving game poc)"
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
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


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
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Scenery:
    points_m: List[Tuple[float, float]]
    kind: str
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Place:
    x: float
    y: float
    name: str
    kind: str  # suburb, neighbourhood, quarter, village, town, city


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
) -> List[dict]:
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:25];
    (
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

    force_refresh = os.getenv("OVERPASS_FORCE_REFRESH", "0").lower() in ("1", "true", "yes")
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
    """Stitch member ways into closed polygon rings or continuous linestrings.

    Returns a list of (points_m, is_closed) tuples.
    """
    segments: List[List[int]] = []
    for wid in way_ids:
        way_el = ways_by_id.get(wid)
        if way_el and way_el.get("nodes") and len(way_el["nodes"]) >= 2:
            segments.append(list(way_el["nodes"]))

    rings: List[Tuple[List[Tuple[float, float]], bool]] = []
    while segments:
        chain = segments.pop(0)
        extended = True
        while extended and chain[0] != chain[-1]:
            extended = False
            for i, seg in enumerate(segments):
                if seg[0] == chain[-1]:
                    chain.extend(seg[1:])
                    segments.pop(i)
                    extended = True
                    break
                elif seg[-1] == chain[-1]:
                    chain.extend(reversed(seg[:-1]))
                    segments.pop(i)
                    extended = True
                    break
                elif seg[-1] == chain[0]:
                    chain = seg[:-1] + chain
                    segments.pop(i)
                    extended = True
                    break
                elif seg[0] == chain[0]:
                    chain = list(reversed(seg[1:])) + chain
                    segments.pop(i)
                    extended = True
                    break

        is_closed = len(chain) >= 4 and chain[0] == chain[-1]
        pts = process_node_ids_fn(chain)
        if pts and len(pts) >= 2:
            rings.append((pts, is_closed))

    return rings


def build_ways(
    elements: List[dict],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Tuple[List[Way], List[Water], List[Building], List[Scenery], List[Place], Tuple[float, float, float, float]]:
    """Convert OSM elements to EPSG:3067 meters.

    Returns:
      - ways in EPSG:3067 meters
      - waters in EPSG:3067 meters
      - buildings in EPSG:3067 meters
      - sceneries (parks, forests, green areas) in EPSG:3067 meters
      - places (suburbs, neighbourhoods, districts) with metric coordinates
      - world bounds (minx, miny, maxx, maxy) in meters
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
        elif el_type == "way":
            tags = el.get("tags", {})
            node_ids = el.get("nodes", [])
            ways_by_id[el.get("id")] = el
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
                ways_raw.append((tags, highway, node_ids))
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
        buildings.append(Building(points_m=pts, name=name, housenumber=housenumber, street=street, bbox=ibbox))

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
    for tags, highway, node_ids in ways_raw:
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
        # Check car access
        motorcar = tags.get("motorcar")
        vehicle = tags.get("vehicle")
        access = tags.get("access")

        if motorcar in ("no", "private") or vehicle in ("no", "private") or access in ("no", "private"):
            is_drivable = False
        elif motorcar in ("yes", "designated", "permissive"):
            is_drivable = True
        elif highway in non_drivable_highways:
            is_drivable = False
        else:
            is_drivable = True

        ways.append(
            Way(
                points_m=pts,
                highway=highway,
                half_width_m=halfw,
                name=name,
                is_ice_road=is_ice,
                is_drivable=is_drivable,
                bbox=ibbox,
            )
        )

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
                buildings.append(Building(points_m=pts, name=name, housenumber=housenumber, street=street, bbox=ibbox))
            elif tags.get("natural") == "water" or tags.get("landuse") == "reservoir":
                kind = tags.get("natural") or tags.get("landuse") or "water"
                waters.append(Water(points_m=pts, kind=kind, is_polygon=is_closed, name=name, bbox=ibbox))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("wood", "scrub", "grass"):
                kind = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
                sceneries.append(Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox))
            elif "place" in tags and name and pts:
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                places.append(Place(x=cx, y=cy, name=name, kind=tags.get("place", "suburb")))

    # 6. Place nodes (suburbs, neighbourhoods, districts)
    for tags, nid in place_nodes_raw:
        pt = nodes_m.get(nid)
        if pt:
            places.append(Place(x=pt[0], y=pt[1], name=tags["name"], kind=tags.get("place", "suburb")))

    t_total = time.time() - t_start
    logger.info(
        "Map generation complete in %.3fs: %d roads, %d waters, %d buildings, %d scenery polygons, %d places",
        t_total,
        len(ways),
        len(waters),
        len(buildings),
        len(sceneries),
        len(places),
    )

    if progress_callback:
        progress_callback(
            1.0,
            f"Ready ({len(ways)} roads, {len(places)} districts, {len(buildings)} buildings, {len(waters)} waters)",
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

    return ways, waters, buildings, sceneries, places, (minx, miny, maxx, maxy)


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
        fetch_func=fetch_osm_ways,
        build_func=build_ways,
        cooldown_s: float = 5.0,
    ):
        self.ways = ways
        self.waters = waters if waters is not None else []
        self.buildings = buildings if buildings is not None else []
        self.sceneries = sceneries if sceneries is not None else []
        self.places = places if places is not None else []
        self.bounds = bounds
        self.transformer = transformer
        self.fetch_func = fetch_func
        self.build_func = build_func
        self.cooldown_s = cooldown_s
        self.lock = threading.Lock()
        self.is_fetching = False
        self.fetch_progress = 0.0
        self.last_fetch_time = 0.0
        # Load known dead-end boundaries from disk cache
        self.dead_ends: List[dict] = load_dead_ends_cache()

    def get_bounds(self) -> Tuple[float, float, float, float]:
        with self.lock:
            return self.bounds

    def get_progress(self) -> float:
        with self.lock:
            return self.fetch_progress

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
            elif car.x > maxx - margin_m:
                direction = "east"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - overlap
                    fetch_maxx = car.x + tile_size_m
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True

            if not expanded:
                if car.y < miny + margin_m:
                    direction = "south"
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_miny = car.y - tile_size_m
                        fetch_maxy = car.y + overlap
                        fetch_minx = car.x - half_span
                        fetch_maxx = car.x + half_span
                        expanded = True
                elif car.y > maxy - margin_m:
                    direction = "north"
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_miny = car.y - overlap
                        fetch_maxy = car.y + tile_size_m
                        fetch_minx = car.x - half_span
                        fetch_maxx = car.x + half_span
                        expanded = True

            if not expanded:
                return False

            self.is_fetching = True
            self.fetch_progress = 0.1
            self.last_fetch_time = now
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
            res = self.build_func(elems)
            with self.lock:
                self.fetch_progress = 0.9
            if len(res) == 6:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds = res
            elif len(res) == 5:
                new_ways, new_waters, new_buildings, new_sceneries, new_bounds = res
                new_places = []
            elif len(res) == 3:
                new_ways, new_waters, new_bounds = res
                new_buildings, new_sceneries, new_places = [], [], []
            else:
                new_ways, new_bounds = res[0], res[-1]
                new_waters, new_buildings, new_sceneries, new_places = [], [], [], []

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
                self.ways.extend(new_ways)
                self.waters.extend(new_waters)
                self.buildings.extend(new_buildings)
                self.sceneries.extend(new_sceneries)
                self.places.extend(new_places)
                minx = min(self.bounds[0], new_bounds[0])
                miny = min(self.bounds[1], new_bounds[1])
                maxx = max(self.bounds[2], new_bounds[2])
                maxy = max(self.bounds[3], new_bounds[3])
                self.bounds = (minx, miny, maxx, maxy)
                self.last_fetch_time = time.time()
                self.fetch_progress = 1.0
                self.is_fetching = False
            logger.info(
                "Auto-fetched and added %d ways, %d waters, %d buildings, %d scenery, %d places; new bounds: %s",
                len(new_ways),
                len(new_waters),
                len(new_buildings),
                len(new_sceneries),
                len(new_places),
                self.bounds,
            )
        except Exception as e:
            logger.warning("Auto-fetch failed: %s", e)
            with self.lock:
                self.is_fetching = False
                self.fetch_progress = 0.0
