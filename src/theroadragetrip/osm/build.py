import collections
from collections import defaultdict
import logging
import math
import time
from typing import Callable, Dict, List, Optional, Set, Tuple



logger = logging.getLogger(__name__)

from .constants import (
    CROSSING_OVERLAP_SEARCH_RADIUS_M,
    DEFAULT_ROAD_HALF_WIDTH_M,
    HIGHWAY_HALF_WIDTH,
    parse_speed_limit_kmh,
)

from .models import (
    Way,
    Water,
    Curb,
    Building,
    ParkingSpace,
    Scenery,
    _building_height,
    _building_levels,
    TrafficLight,
    StopSign,
    YieldSign,
    Place,
    associate_places_with_buildings,
    Crossing,
    TaxiStop,
    BusStop,
    MapData,
)

from .traffic_signals import (
    build_traffic_light_system,
)

from .trees import (
    plant_trees,
)


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


def build_ways(
    elements: List[dict],
    progress_callback: Optional[Callable[[float, str], None]] = None,
    include_bus_stops: bool = True,
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
    named_nodes_raw: List[Tuple[dict, int]] = []
    traffic_signals_raw: List[Tuple[dict, int]] = []
    stop_signs_raw: List[Tuple[dict, int]] = []
    yield_signs_raw: List[Tuple[dict, int]] = []
    crossings_raw: List[Tuple[dict, int]] = []
    taxi_stops_raw: List[Tuple[dict, int]] = []
    bus_stops_raw: List[Tuple[dict, int]] = []
    bus_platforms_raw: List[Tuple[dict, List[int], int]] = []
    entrance_node_ids: set[int] = set()
    ways_by_id: Dict[int, dict] = {}
    ways_raw: List[Tuple[dict, str, List[int]]] = []
    water_raw: List[Tuple[dict, List[int]]] = []
    curb_raw: List[Tuple[dict, List[int]]] = []
    building_raw: List[Tuple[dict, List[int]]] = []
    parking_space_raw: List[Tuple[dict, List[int], Optional[int]]] = []
    scenery_raw: List[Tuple[dict, List[int]]] = []
    named_ways_raw: List[Tuple[dict, List[int]]] = []
    parking_space_nodes_raw: List[Tuple[dict, int]] = []
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
            elif "name" in tags:
                named_nodes_raw.append((tags, nid))
            if tags.get("highway") == "traffic_signals":
                traffic_signals_raw.append((tags, nid))
            if tags.get("highway") == "stop":
                stop_signs_raw.append((tags, nid))
            if tags.get("highway") == "give_way":
                yield_signs_raw.append((tags, nid))
            if tags.get("highway") == "taxi_stop" or tags.get("amenity") == "taxi":
                taxi_stops_raw.append((tags, nid))
            if include_bus_stops and (tags.get("highway") == "bus_stop" or tags.get("public_transport") in ("platform", "stop_position")):
                bus_stops_raw.append((tags, nid))
            if "entrance" in tags:
                entrance_node_ids.add(nid)
            if tags.get("amenity") == "parking_space":
                parking_space_nodes_raw.append((tags, nid))
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
            if include_bus_stops and tags.get("public_transport") == "platform":
                bus_platforms_raw.append((tags, node_ids, way_id))
            if "building" in tags or "building:part" in tags:
                building_raw.append((tags, node_ids))
            elif tags.get("amenity") == "parking_space":
                parking_space_raw.append((tags, node_ids, way_id))
            elif tags.get("barrier") == "kerb":
                curb_raw.append((tags, node_ids))
            elif tags.get("natural") in ("water", "bay", "strait") or ("waterway" in tags) or tags.get("landuse") == "reservoir":
                water_raw.append((tags, node_ids))
            elif tags.get("amenity") == "parking" or tags.get("landuse") == "parking":
                scenery_raw.append((tags, node_ids))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("wood", "scrub", "grass", "sand", "heath"):
                scenery_raw.append((tags, node_ids))
            elif "highway" in tags:
                highway = tags.get("highway", "unclassified")
                ways_raw.append((tags, highway, node_ids, way_id))
            elif "name" in tags:
                named_ways_raw.append((tags, node_ids))
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
    curbs: List[Curb] = []
    buildings: List[Building] = []
    sceneries: List[Scenery] = []
    places: List[Place] = []
    traffic_lights: List[TrafficLight] = []
    stop_signs: List[StopSign] = []
    yield_signs: List[YieldSign] = []
    crossings: List[Crossing] = []
    taxi_stops: List[TaxiStop] = []
    bus_stops: List[BusStop] = []
    parking_spaces: List[ParkingSpace] = []

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
        kind = (
            "parking"
            if tags.get("amenity") == "parking" or tags.get("landuse") == "parking"
            else tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
        )
        name = tags.get("name")
        sceneries.append(Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox))

    for tags, node_ids, parking_id in parking_space_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts:
            continue
        if len(pts) < 3:
            x, y = pts[0]
            half_width = 1.25
            half_length = 2.5
            pts = [
                (x - half_width, y - half_length),
                (x + half_width, y - half_length),
                (x + half_width, y + half_length),
                (x - half_width, y + half_length),
            ]
            ibbox = (x - half_width, y - half_length, x + half_width, y + half_length)
        parking_spaces.append(
            ParkingSpace(
                points_m=pts,
                bbox=ibbox,
                orientation=tags.get("orientation"),
                osm_id=parking_id,
            )
        )
    for tags, node_id in parking_space_nodes_raw:
        point = nodes_m.get(node_id)
        if point is None:
            continue
        x, y = point
        half_width = 1.25
        half_length = 2.5
        points = [
            (x - half_width, y - half_length),
            (x + half_width, y - half_length),
            (x + half_width, y + half_length),
            (x - half_width, y + half_length),
        ]
        parking_spaces.append(
            ParkingSpace(
                points_m=points,
                bbox=(x - half_width, y - half_length, x + half_width, y + half_length),
                orientation=tags.get("orientation"),
                osm_id=node_id,
            )
        )

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
        try:
            layer = int(float(str(tags.get("layer", 0)).strip()))
        except (TypeError, ValueError):
            layer = 0
        waters.append(Water(points_m=pts, kind=kind, is_polygon=is_poly, name=name, bbox=ibbox, layer=layer))

    for tags, node_ids in curb_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 2:
            continue
        curbs.append(Curb(points_m=pts, bbox=ibbox))

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
        center_x = sum(point[0] for point in pts) / len(pts)
        center_y = sum(point[1] for point in pts) / len(pts)
        entrances = [nodes_m[nid] for nid in node_ids if nid in entrance_node_ids]
        buildings.append(Building(
            points_m=pts,
            name=name,
            housenumber=housenumber,
            street=street,
            height_m=_building_height(tags, pts),
            levels=_building_levels(tags),
            bbox=ibbox,
            venue_type=tags.get("amenity") or tags.get("shop") or (
                tags.get("building")
                if tags.get("building") in {"commercial", "retail", "shop"}
                else None
            ),
            center_m=(center_x, center_y),
            texture_seed=abs(math.sin(center_x * 0.013 + center_y * 0.017)),
            entrances=entrances,
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

        if is_underground and (highway in ("service", "track") or "parking" in tags) and tags.get("service") != "parking_aisle":
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
        is_roundabout = junction_tag == "roundabout"
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
        def parse_lane_count(value: object) -> Optional[int]:
            try:
                return max(1, int(str(value).split(";")[0].strip()))
            except (TypeError, ValueError):
                return None

        lanes_forward = parse_lane_count(tags.get("lanes:forward"))
        lanes_backward = parse_lane_count(tags.get("lanes:backward"))
        lit_tag = str(tags.get("lit", "")).strip().lower() or None
        surface_tag = str(tags.get("surface", "")).strip().lower() or None
        priority_tag = str(tags.get("priority_road", "")).strip().lower()
        is_priority_road = priority_tag in {"yes", "designated", "true", "1"} or junction_tag == "priority"

        ways.append(
            Way(
                points_m=pts,
                highway=highway,
                half_width_m=halfw,
                name=name,
                surface=surface_tag,
                lit=lit_tag,
                is_ice_road=is_ice,
                is_drivable=is_drivable,
                is_busway=is_bus_route,
                oneway=oneway_dir,
                is_roundabout=is_roundabout,
                lanes=lanes_val,
                layer=layer_val,
                is_bridge=is_bridge,
                is_tunnel=is_tunnel,
                speed_limit_kmh=speed_lim,
                bbox=ibbox,
                osm_id=way_id,
                lanes_forward=lanes_forward,
                lanes_backward=lanes_backward,
                turn_lanes=tags.get("turn:lanes") or tags.get("turn:lanes:forward"),
                priority_road=is_priority_road,
                service=tags.get("service"),
            )
        )

    if progress_callback:
        progress_callback(0.965, f"Planting trees ({len(sceneries)} scenery areas)...")
    plant_trees(
        sceneries,
        ways,
        progress_callback=progress_callback,
        progress_start=0.965,
        progress_end=0.97,
    )

    # 5. Multipolygon Relations (stitched into proper closed rings)
    if progress_callback:
        progress_callback(0.97, f"Processing {len(relations_raw)} multipolygon relations...")
    relation_count = len(relations_raw)
    for relation_index, (tags, members) in enumerate(relations_raw):
        if progress_callback and relation_count:
            progress_callback(
                0.97 + 0.01 * relation_index / relation_count,
                f"Processing multipolygon {relation_index + 1}/{relation_count}...",
            )
        outer_way_ids = [
            m["ref"]
            for m in members
            if m.get("type") == "way" and (m.get("role") == "outer" or m.get("role") == "")
        ]
        rings = _stitch_member_ways_into_rings(
            outer_way_ids, ways_by_id, lambda nids: process_node_ids(nids)[0]
        )
        if progress_callback and relation_count:
            progress_callback(
                0.97 + 0.01 * (relation_index + 1) / relation_count,
                f"Processed multipolygon {relation_index + 1}/{relation_count}",
            )
        name = tags.get("name")
        for pts, is_closed in rings:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ibbox = (min(xs), min(ys), max(xs), max(ys))
            if "building" in tags:
                housenumber = tags.get("addr:housenumber")
                street = tags.get("addr:street")
                center_x = sum(point[0] for point in pts) / len(pts)
                center_y = sum(point[1] for point in pts) / len(pts)
                buildings.append(Building(
                    points_m=pts,
                    name=name,
                    housenumber=housenumber,
                    street=street,
                    height_m=_building_height(tags, pts),
                    levels=_building_levels(tags),
                    bbox=ibbox,
                    venue_type=tags.get("amenity") or tags.get("shop") or (
                        tags.get("building")
                        if tags.get("building") in {"commercial", "retail", "shop"}
                        else None
                    ),
                    center_m=(center_x, center_y),
                    texture_seed=abs(math.sin(center_x * 0.013 + center_y * 0.017)),
                ))
            elif tags.get("natural") in ("water", "bay", "strait") or tags.get("landuse") == "reservoir":
                kind = tags.get("natural") or tags.get("landuse") or "water"
                try:
                    layer = int(float(str(tags.get("layer", 0)).strip()))
                except (TypeError, ValueError):
                    layer = 0
                waters.append(Water(points_m=pts, kind=kind, is_polygon=is_closed, name=name, bbox=ibbox, layer=layer))
            elif tags.get("amenity") == "parking" or tags.get("landuse") == "parking":
                sceneries.append(Scenery(points_m=pts, kind="parking", name=name, bbox=ibbox))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("forest", "wood", "scrub", "grass"):
                kind = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
                scenery = Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox)
                plant_trees([scenery], ways)
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

    # 6b. Other named OSM points and areas (e.g. attractions and named venues)
    for tags, nid in named_nodes_raw:
        pt = nodes_m.get(nid)
        if pt:
            places.append(Place(x=pt[0], y=pt[1], name=tags["name"], kind=tags.get("amenity", "poi")))
    for tags, node_ids in named_ways_raw:
        pts, _ = process_node_ids(node_ids)
        if pts:
            places.append(
                Place(
                    x=sum(point[0] for point in pts) / len(pts),
                    y=sum(point[1] for point in pts) / len(pts),
                    name=tags["name"],
                    kind=tags.get("amenity", "poi"),
                )
            )

    for tags, nid in taxi_stops_raw:
        pt = nodes_m.get(nid)
        if pt:
            taxi_stops.append(TaxiStop(x=pt[0], y=pt[1], id=nid))

    for tags, nid in bus_stops_raw:
        pt = nodes_m.get(nid)
        if pt:
            bus_stops.append(
                BusStop(
                    x=pt[0],
                    y=pt[1],
                    name=tags.get("name"),
                    id=nid,
                    shelter=str(tags.get("shelter", "")).lower() in {"yes", "true", "1"},
                )
            )
    for tags, node_ids, way_id in bus_platforms_raw:
        pts, _ = process_node_ids(node_ids)
        if pts:
            bus_stops.append(
                BusStop(
                    x=sum(point[0] for point in pts) / len(pts),
                    y=sum(point[1] for point in pts) / len(pts),
                    name=tags.get("name"),
                    id=way_id,
                    shelter=str(tags.get("shelter", "")).lower() in {"yes", "true", "1"},
                )
            )

    # 7. Traffic signals from OSM nodes.
    #
    # OSM traffic-signal nodes are evidence that an intersection is
    # signal-controlled, not a complete physical description of it - one
    # extract may have a single node for a whole 4-way junction, another
    # may tag only one of its roads. build_traffic_light_system treats
    # these node positions purely as that evidence and derives the actual
    # approaches, signals, and phases from the surrounding road geometry
    # (see osm/traffic_signals.py).
    if traffic_signals_raw:
        signal_points = []
        for tags, nid in traffic_signals_raw:
            point = nodes_m.get(nid)
            if point is None:
                continue
            try:
                signal_layer = int(tags.get("layer", 0))
            except (TypeError, ValueError):
                signal_layer = 0
            signal_points.append((point[0], point[1], signal_layer))
        traffic_lights, logical_intersections = build_traffic_light_system(signal_points, ways)
    else:
        logical_intersections = []

    # 8. Stop signs from OSM nodes
    for tags, nid in stop_signs_raw:
        point = nodes_m.get(nid)
        if point is None:
            continue
        layer_value = 0
        try:
            layer_value = int(tags.get("layer", 0))
        except (TypeError, ValueError):
            pass
        stop_signs.append(StopSign(point[0], point[1], layer=layer_value, id=nid))
    for tags, nid in yield_signs_raw:
        point = nodes_m.get(nid)
        if point is None:
            continue
        try:
            layer_value = int(tags.get("layer", 0))
        except (TypeError, ValueError):
            layer_value = 0
        yield_signs.append(YieldSign(point[0], point[1], layer=layer_value, id=nid))

    # 9. Pedestrian Crossings (suojatiet) from OSM nodes and ways
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
            # The OSM crossing node itself is often digitized a little off the
            # road centerline (up to best_dist=8m in practice) - snap to the
            # nearest point on the matched road so the rendered zebra stripes
            # sit flush on the road surface instead of floating beside it.
            snap_x, snap_y = pt

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
                            snap_x, snap_y = px, py

            crossings.append(
                Crossing(
                    x=snap_x,
                    y=snap_y,
                    layer=layer_val,
                    id=nid,
                    crossing_type=crossing_type,
                    direction_angle=road_angle if found_orientation else None,
                    width_m=max(3.0, road_half_w * 1.8),
                    length_m=2.4,
                )
            )

        # A compact real junction can map several crossing nodes (one per
        # leg) within a few meters of each other; each sized to its own
        # road's width otherwise bleeds into the open junction and into
        # its neighbors (see CROSSING_OVERLAP_SEARCH_RADIUS_M). Clip every
        # crossing's width to the distance to its nearest neighbor so its
        # stripes never extend past the midpoint between the two.
        for crossing in crossings:
            nearest_dist = CROSSING_OVERLAP_SEARCH_RADIUS_M
            for other in crossings:
                if other is crossing or other.layer != crossing.layer:
                    continue
                dist = math.hypot(other.x - crossing.x, other.y - crossing.y)
                if dist < nearest_dist:
                    nearest_dist = dist
            crossing.width_m = min(crossing.width_m, nearest_dist)

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
    associate_places_with_buildings(buildings, places)

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

    return MapData(
        ways, waters, buildings, sceneries, places, (minx, miny, maxx, maxy),
        traffic_lights, crossings, taxi_stops, bus_stops, parking_spaces, logical_intersections, stop_signs, yield_signs,
        curbs=curbs,
    )
