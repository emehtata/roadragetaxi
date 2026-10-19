"""Street lights placed on the map - explicit OSM lamps first, then lit
roads at fixed spacing (clear of junctions, roads and buildings), and the
poles of parking lots where back-to-back rows of spots meet. The
simulation server places them once per map (server.place_street_lights);
the Godot client draws them. No drawing here."""

from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

from .geo import dist_point_to_segment, point_in_polygon
from .osm import Building, Way
from .performance import advance_chunked
from .viewport import _segment_viewport_t_range


STREET_LIGHT_SPACING_M = 12.0


# A parking lot's lamps stand where two back-to-back rows of spots meet,
# not along both sides of every aisle (which put them inside the spots):
# one side of each aisle, a spot's depth beyond its edge, sparser.
PARKING_LIGHT_SPACING_M = 24.0


PARKING_SPOT_DEPTH_M = 5.0


PARKING_POLE_CLEARANCE_M = 10.0  # aisle-guessed lamps this close to a row-seam pole are dropped


PARKING_CORNER_SNAP_M = 0.6  # spot corners this close are the same point


def parking_row_lamps(parking_spaces, spacing: float = PARKING_LIGHT_SPACING_M) -> list:
    """Light poles of parking lots whose spots are mapped: at the points
    where four spots meet - two back-to-back rows, between two spots of
    each - about `spacing` apart. [(x, y, direction, pool radius m, all round)]."""
    corners: dict = {}  # snapped corner -> [sum x, sum y, points added, spots]
    snap = PARKING_CORNER_SNAP_M
    for index, space in enumerate(parking_spaces):
        if getattr(space, "osm_id", None) is None or len(space.points_m) < 4:
            continue  # generated house parking has no rows
        points = space.points_m[:-1] if space.points_m[0] == space.points_m[-1] else space.points_m
        for x, y in points:
            key = (round(x / snap), round(y / snap))
            hit = next((k for k in ((key[0] + dx, key[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)) if k in corners), key)
            entry = corners.setdefault(hit, [0.0, 0.0, 0, set()])
            entry[0] += x
            entry[1] += y
            entry[2] += 1
            entry[3].add(index)
    crossings = sorted(
        ((entry[0] / entry[2], entry[1] / entry[2]) for entry in corners.values() if len(entry[3]) >= 4),
        key=lambda point: (round(point[0]), round(point[1])),
    )
    poles: list = []
    for x, y in crossings:  # greedy: one pole per `spacing` along the seams
        if all((x - px) ** 2 + (y - py) ** 2 >= spacing * spacing for px, py, *_ in poles):
            poles.append((x, y, 0.0, 9.0, True))  # True: lights all round, not toward a road
    return poles


STREET_LIGHT_JUNCTION_CLEARANCE_M = 3.0


STREET_LIGHT_BUILDING_DISTANCE_M = 200.0


# lights.md: how far beyond a way's own half-width an explicit OSM
# highway=street_lamp node is still considered "this way's lamp" - covers
# a real curbside/verge/shoulder planting distance (measured against a
# real Oulu extract with actual street_lamp nodes: median distance from a
# lamp to its nearest lighting-eligible road was ~7.4m, 84% within 15m -
# a lamp farther out than this is more likely lighting a footpath/
# courtyard with no meaningful nearby road at all than genuinely
# belonging to a distant one, so it correctly falls through to that
# road's own lit=* synthesis instead of being misattributed).
# Deliberately not the whole STREET_LIGHT_BUILDING_DISTANCE_M "is this
# area urban at all" radius - that answers a different question.
STREET_LIGHT_EXPLICIT_LAMP_MAX_DISTANCE_M = 15.0


STREET_LIGHT_ROAD_INDEX_CELL_M = 24.0


STREET_LIGHT_FOOTPRINT_CELL_M = 24.0


STREET_LIGHT_CACHE_BUDGET_S = 0.004


# Separate from placement's budget above so preparation (building/junction/
# classification/segment indexing) and placement are measured independently.
STREET_LIGHT_PREP_BUDGET_S = 0.004


def _way_has_street_lighting(way: Way) -> bool:
    """Use explicit OSM lighting, with residential streets as the fallback."""
    lit = getattr(way, "lit", None)
    return lit == "yes" or (lit is None and getattr(way, "highway", "") in {"residential", "living_street"})


def _point_is_near_building(
    point: Tuple[float, float],
    buildings: Optional[List[Building]],
    building_grid=None,
) -> bool:
    """Return whether a point is within the taajama building distance."""
    if not buildings:
        return False
    point_x, point_y = point
    candidates = buildings
    if building_grid is not None:
        cell_size = STREET_LIGHT_BUILDING_DISTANCE_M
        cell_x = math.floor(point_x / cell_size)
        cell_y = math.floor(point_y / cell_size)
        candidates = {
            id(building): building
            for nearby_x in (cell_x - 1, cell_x, cell_x + 1)
            for nearby_y in (cell_y - 1, cell_y, cell_y + 1)
            for building in building_grid.get((nearby_x, nearby_y), ())
        }.values()
    for building in candidates:
        points = getattr(building, "points_m", ())
        if len(points) >= 3:
            if point_in_polygon(point_x, point_y, points):
                return True
            if any(
                dist_point_to_segment(
                    point_x, point_y, start[0], start[1], end[0], end[1]
                ) < STREET_LIGHT_BUILDING_DISTANCE_M
                for start, end in zip(points, points[1:] + points[:1])
            ):
                return True
            continue
        bbox = getattr(building, "bbox", None)
        if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        nearest_x = min(max(point_x, bbox[0]), bbox[2])
        nearest_y = min(max(point_y, bbox[1]), bbox[3])
        if (
            (point_x - nearest_x) ** 2 + (point_y - nearest_y) ** 2
            < STREET_LIGHT_BUILDING_DISTANCE_M * STREET_LIGHT_BUILDING_DISTANCE_M
        ):
            return True
    return False


def _way_should_have_street_lighting(
    way: Way,
    buildings: Optional[List[Building]],
    point: Optional[Tuple[float, float]] = None,
    building_grid=None,
) -> bool:
    urban_highways = {
        "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "unclassified", "residential",
        "living_street", "service",
    }
    return _way_has_street_lighting(way) or (
        getattr(way, "lit", None) is None
        and getattr(way, "highway", "") in urban_highways
        and point is not None
        and _point_is_near_building(point, buildings, building_grid)
    )


STREET_LIGHT_URBAN_HIGHWAYS = frozenset({
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential",
    "living_street", "service",
})


STREET_LIGHT_LAMP_INDEX_CELL_M = 200.0


_STREET_LIGHT_PREP_PHASES = (
    "buildings", "parking", "junction_points", "junctions", "classification", "segments", "explicit_lamps",
)


def _record_street_light_stage(profiler, name, started):
    if profiler is not None:
        profiler.record(
            "render:lighting:street_lights:" + name, (time.perf_counter() - started) * 1000.0
        )


def _street_light_way_bbox(way):
    bbox = getattr(way, "bbox", None)
    if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
        xs = [point[0] for point in way.points_m]
        ys = [point[1] for point in way.points_m]
        bbox = (min(xs), min(ys), max(xs), max(ys))
    return bbox


def _way_is_street_light_candidate(way) -> bool:
    return (
        getattr(way, "is_drivable", True)
        and (_way_has_street_lighting(way) or getattr(way, "highway", "") in STREET_LIGHT_URBAN_HIGHWAYS)
        and len(way.points_m) >= 2
    )


def _snapshot_street_light_job(
    key, region, ways, spatial_grid, buildings, building_spatial_grid, street_lamps, street_lamp_grid,
    parking_spaces=None,
):
    """Capture every contributor a job will read, once, from the completed
    grids - later frames never query the live (possibly newer) grids."""
    minx, miny, maxx, maxy = region
    visible_ways = (
        list(spatial_grid.ways_in_rect(minx, miny, maxx, maxy))
        if spatial_grid is not None else list(ways)
    )
    margin = STREET_LIGHT_BUILDING_DISTANCE_M
    nearby_buildings = (
        list(building_spatial_grid.ways_in_rect(minx - margin, miny - margin, maxx + margin, maxy + margin))
        if building_spatial_grid is not None else list(buildings or ())
    )
    # Explicit lamps are matched against each way's whole bbox (ways run
    # past the region), so snapshot the union of those query rectangles.
    explicit_lamps = []
    if street_lamp_grid is not None and street_lamps:
        bounds = None
        for way in visible_ways:
            if not _way_is_street_light_candidate(way):
                continue
            lamp_margin = getattr(way, "half_width_m", 4.0) + STREET_LIGHT_EXPLICIT_LAMP_MAX_DISTANCE_M
            bbox = _street_light_way_bbox(way)
            rect = (bbox[0] - lamp_margin, bbox[1] - lamp_margin, bbox[2] + lamp_margin, bbox[3] + lamp_margin)
            bounds = rect if bounds is None else (
                min(bounds[0], rect[0]), min(bounds[1], rect[1]),
                max(bounds[2], rect[2]), max(bounds[3], rect[3]),
            )
        if bounds is not None:
            explicit_lamps = list(street_lamp_grid.ways_in_rect(*bounds))
    return {
        "key": key,
        "region": region,
        "ways": visible_ways,
        "buildings": nearby_buildings,
        "parking_spaces": [space for space in (parking_spaces or ()) if getattr(space, "bbox", None)
                           and space.bbox[0] <= maxx and space.bbox[2] >= minx
                           and space.bbox[1] <= maxy and space.bbox[3] >= miny],
        "explicit_lamps": explicit_lamps,
        "phase": _STREET_LIGHT_PREP_PHASES[0],
        "cursor": 0,
        "building_grid": {},
        "footprint_grid": {},
        "point_ways": {},
        "junction_items": None,
        "junction_grid": {},
        "way_lit_cache": {},
        "road_grid": {},
        "lamp_grid": {},
        "lamp_order": {},
        "placement_cursor": 0,
        "lamps": [],
        "seen": set(),
    }


def _index_street_light_footprint(work, item):
    bbox = getattr(item, "bbox", None)
    if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
        return
    cell = STREET_LIGHT_FOOTPRINT_CELL_M
    minx, miny, maxx, maxy = work["region"]
    for cell_x in range(math.floor(max(bbox[0], minx) / cell), math.floor(min(bbox[2], maxx) / cell) + 1):
        for cell_y in range(math.floor(max(bbox[1], miny) / cell), math.floor(min(bbox[3], maxy) / cell) + 1):
            work["footprint_grid"].setdefault((cell_x, cell_y), []).append(item)


def _street_light_prep_step(work, phase):
    """Return (items, process_item) for one resumable preparation phase."""
    if phase == "buildings":
        building_grid = work["building_grid"]
        cell_size = STREET_LIGHT_BUILDING_DISTANCE_M

        def add_building(building):
            bbox = getattr(building, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                return
            _index_street_light_footprint(work, building)
            for cell_x in range(math.floor((bbox[0] - cell_size) / cell_size), math.floor((bbox[2] + cell_size) / cell_size) + 1):
                for cell_y in range(math.floor((bbox[1] - cell_size) / cell_size), math.floor((bbox[3] + cell_size) / cell_size) + 1):
                    building_grid.setdefault((cell_x, cell_y), []).append(building)
        return work["buildings"], add_building
    if phase == "parking":
        return work["parking_spaces"], lambda space: _index_street_light_footprint(work, space)
    if phase == "junction_points":
        point_ways = work["point_ways"]

        def add_points(way):
            if getattr(way, "is_drivable", True):
                for point in way.points_m:
                    point_ways.setdefault((round(point[0] / 5.0), round(point[1] / 5.0)), set()).add(id(way))
        return work["ways"], add_points
    if phase == "junctions":
        if work["junction_items"] is None:
            work["junction_items"] = list(work["point_ways"].items())
            work["ways_by_id"] = {id(way): way for way in work["ways"]}
        ways_by_id = work["ways_by_id"]
        junction_grid = work["junction_grid"]

        def add_junction(item):
            key, junction_way_ids = item
            point = (key[0] * 5.0, key[1] * 5.0)
            if len(junction_way_ids) >= 2 and any(
                _way_should_have_street_lighting(ways_by_id[way_id], work["buildings"], point, work["building_grid"])
                for way_id in junction_way_ids
            ):
                cell = (math.floor(point[0] / 40.0), math.floor(point[1] / 40.0))
                junction_grid.setdefault(cell, []).append(point)
        return work["junction_items"], add_junction
    if phase == "classification":
        way_lit_cache = work["way_lit_cache"]

        def classify(way):
            if not getattr(way, "is_drivable", True) or len(way.points_m) < 2:
                way_lit_cache[id(way)] = []
            elif _way_has_street_lighting(way):
                way_lit_cache[id(way)] = [True] * (len(way.points_m) - 1)
            elif getattr(way, "lit", None) == "no" or getattr(way, "highway", "") not in STREET_LIGHT_URBAN_HIGHWAYS:
                way_lit_cache[id(way)] = [False] * (len(way.points_m) - 1)
            else:
                way_lit_cache[id(way)] = [
                    any(
                        _point_is_near_building(sample, work["buildings"], work["building_grid"])
                        for sample in (start, end, ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5))
                    )
                    for start, end in zip(way.points_m, way.points_m[1:])
                ]
        return work["ways"], classify
    if phase == "segments":
        return work["ways"], lambda way: _index_street_light_road(work["road_grid"], way, work["region"])
    lamp_grid, lamp_order = work["lamp_grid"], work["lamp_order"]
    cell_size = STREET_LIGHT_LAMP_INDEX_CELL_M

    def add_lamp(lamp):
        lamp_order[id(lamp)] = len(lamp_order)
        lamp_grid.setdefault((math.floor(lamp.x / cell_size), math.floor(lamp.y / cell_size)), []).append(lamp)
    return work["explicit_lamps"], add_lamp


def _advance_street_light_prep(work, profiler=None) -> bool:
    """Advance preparation phases for up to STREET_LIGHT_PREP_BUDGET_S.
    Returns True once every phase is done and placement can start."""
    deadline = time.perf_counter() + STREET_LIGHT_PREP_BUDGET_S
    while True:
        phase = work["phase"]
        started = time.perf_counter()
        items, process_item = _street_light_prep_step(work, phase)
        work["cursor"] = advance_chunked(items, work["cursor"], deadline - started, process_item)
        _record_street_light_stage(profiler, phase, started)
        if work["cursor"] < len(items):
            return False
        phase_index = _STREET_LIGHT_PREP_PHASES.index(phase) + 1
        work["cursor"] = 0
        if phase_index == len(_STREET_LIGHT_PREP_PHASES):
            work["phase"] = "placement"
            return True
        work["phase"] = _STREET_LIGHT_PREP_PHASES[phase_index]
        if time.perf_counter() >= deadline:
            return False


def _street_light_explicit_lamp_candidates(work, minx, miny, maxx, maxy):
    """Snapshot lamps inside a rect, in the grid query's original order."""
    cell_size = STREET_LIGHT_LAMP_INDEX_CELL_M
    found = {}
    for cell_x in range(math.floor(minx / cell_size), math.floor(maxx / cell_size) + 1):
        for cell_y in range(math.floor(miny / cell_size), math.floor(maxy / cell_size) + 1):
            for lamp in work["lamp_grid"].get((cell_x, cell_y), ()):
                if minx <= lamp.x <= maxx and miny <= lamp.y <= maxy:
                    found[id(lamp)] = lamp
    return sorted(found.values(), key=lambda lamp: work["lamp_order"][id(lamp)])


def _build_street_light_road_index(ways, bounds=None):
    """Index nearby road segments once for lamp-position overlap checks."""
    segment_grid = {}
    for way in ways:
        _index_street_light_road(segment_grid, way, bounds)
    return segment_grid


def _street_light_overlaps_footprint(work, x, y) -> bool:
    cell = STREET_LIGHT_FOOTPRINT_CELL_M
    for item in work["footprint_grid"].get((math.floor(x / cell), math.floor(y / cell)), ()):
        points = getattr(item, "points_m", ())
        if len(points) >= 3 and point_in_polygon(x, y, points):
            return True
    return False


def _index_street_light_road(segment_grid, way, bounds=None):
    cell_size = STREET_LIGHT_ROAD_INDEX_CELL_M
    if not getattr(way, "is_drivable", True) or len(way.points_m) < 2:
        return
    half_width = getattr(way, "half_width_m", 3.0)
    for first, second in zip(way.points_m, way.points_m[1:]):
        if bounds is not None:
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            segment_length = math.hypot(dx, dy)
            if segment_length < 1e-6:
                continue
            clipped = _segment_viewport_t_range(
                first[0], first[1], dx / segment_length, dy / segment_length,
                segment_length,
                bounds[0] - half_width, bounds[1] - half_width,
                bounds[2] + half_width, bounds[3] + half_width,
            )
            if clipped is None:
                continue
            first = (
                first[0] + dx / segment_length * clipped[0],
                first[1] + dy / segment_length * clipped[0],
            )
            second = (
                first[0] + dx / segment_length * (clipped[1] - clipped[0]),
                first[1] + dy / segment_length * (clipped[1] - clipped[0]),
            )
        min_cell_x = math.floor((min(first[0], second[0]) - half_width) / cell_size)
        max_cell_x = math.floor((max(first[0], second[0]) + half_width) / cell_size)
        min_cell_y = math.floor((min(first[1], second[1]) - half_width) / cell_size)
        max_cell_y = math.floor((max(first[1], second[1]) + half_width) / cell_size)
        segment = (first, second, half_width)
        for cell_x in range(min_cell_x, max_cell_x + 1):
            for cell_y in range(min_cell_y, max_cell_y + 1):
                segment_grid.setdefault((cell_x, cell_y), []).append(segment)


def _advance_street_light_placement(work) -> bool:
    """Place lamps way by way for up to STREET_LIGHT_CACHE_BUDGET_S, always
    finishing the current way. Returns True once every way is placed."""
    cached_lamps = work["lamps"]
    road_segment_grid = work["road_grid"]
    junction_grid = work["junction_grid"]
    way_lit_cache = work["way_lit_cache"]
    region_vminx, region_vminy, region_vmaxx, region_vmaxy = work["region"]
    lamp_spacing = STREET_LIGHT_SPACING_M
    junction_cell_size = 40.0
    # lights.md requirement 1-3: explicit OSM lamp-pole positions are
    # the primary source whenever mapped, not merely a decoration on
    # top of the lit=*-driven synthesis below - a real lamp claimed
    # here is never also re-placed by the fixed-spacing fallback.
    # Tracked across the whole rebuild (not per-way) so a lamp near
    # two ways at a junction isn't placed twice.
    seen_explicit_lamp_ids = work["seen"]
    ways = work["ways"]
    deadline = time.perf_counter() + STREET_LIGHT_CACHE_BUDGET_S
    while work["placement_cursor"] < len(ways):
        way = ways[work["placement_cursor"]]
        work["placement_cursor"] += 1
        if not _way_is_street_light_candidate(way):
            if time.perf_counter() >= deadline:
                break
            continue
        half_width = getattr(way, "half_width_m", 4.0)
        explicit_lamps_for_way = []
        if work["explicit_lamps"]:
            margin = half_width + STREET_LIGHT_EXPLICIT_LAMP_MAX_DISTANCE_M
            bbox = _street_light_way_bbox(way)
            candidates = _street_light_explicit_lamp_candidates(
                work, bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin,
            )
            for lamp in candidates:
                if id(lamp) in seen_explicit_lamp_ids:
                    continue
                if _street_light_overlaps_footprint(work, lamp.x, lamp.y):
                    continue
                nearest_segment = min(
                    zip(way.points_m, way.points_m[1:]),
                    key=lambda segment: dist_point_to_segment(lamp.x, lamp.y, *segment[0], *segment[1]),
                )
                if dist_point_to_segment(lamp.x, lamp.y, *nearest_segment[0], *nearest_segment[1]) > margin:
                    continue
                explicit_lamps_for_way.append((lamp, nearest_segment))
        if explicit_lamps_for_way:
            # Real data found for this way - use it exclusively (not
            # blended with the synthetic spacing below) and move on.
            for lamp, (seg_start, seg_end) in explicit_lamps_for_way:
                seen_explicit_lamp_ids.add(id(lamp))
                seg_dx = seg_end[0] - seg_start[0]
                seg_dy = seg_end[1] - seg_start[1]
                seg_len = math.hypot(seg_dx, seg_dy) or 1.0
                road_direction = math.atan2(seg_dy / seg_len, seg_dx / seg_len)
                pool_radius_m = half_width + STREET_LIGHT_EXPLICIT_LAMP_MAX_DISTANCE_M * 0.5
                cached_lamps.append((lamp.x, lamp.y, road_direction, pool_radius_m))
            if time.perf_counter() >= deadline:
                break
            continue
        parking_aisle = getattr(way, "service", None) == "parking_aisle"
        lamp_spacing = PARKING_LIGHT_SPACING_M if parking_aisle else STREET_LIGHT_SPACING_M
        # A street is lit from one side (Finnish practice): the left of its
        # drawing direction, the other side if that spot is taken. A one-way
        # carriageway (a divided road's half) from its left, the median - its
        # twin carriageway's lamps there are the same row (see the merge below).
        oneway = getattr(way, "oneway", 0)
        sides = (1.0,) if parking_aisle else ((1.0, -1.0) if oneway >= 0 else (-1.0, 1.0))
        distance_to_lamp = lamp_spacing / 2.0 if parking_aisle else 0.0
        segment_lengths = getattr(way, "segment_lengths", ())
        segment_lighting = way_lit_cache.get(id(way), ())
        for segment_index, (start, end) in enumerate(zip(way.points_m, way.points_m[1:])):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            segment_length = (
                segment_lengths[segment_index]
                if segment_index < len(segment_lengths)
                else math.hypot(dx, dy)
            )
            if segment_length < 1.0:
                continue
            segment_phase = distance_to_lamp
            edge_distance = half_width + (PARKING_SPOT_DEPTH_M if parking_aisle else 1.0)
            clipped = _segment_viewport_t_range(
                start[0], start[1], dx / segment_length, dy / segment_length,
                segment_length,
                region_vminx - edge_distance, region_vminy - edge_distance,
                region_vmaxx + edge_distance, region_vmaxy + edge_distance,
            )
            if clipped is None:
                distance_to_lamp = (segment_phase - segment_length) % lamp_spacing
                if distance_to_lamp < 1e-9:
                    distance_to_lamp = lamp_spacing
                continue
            placement_limit = clipped[1]
            if distance_to_lamp < clipped[0]:
                distance_to_lamp += math.ceil(
                    (clipped[0] - distance_to_lamp) / lamp_spacing
                ) * lamp_spacing
            while distance_to_lamp <= placement_limit:
                fraction = distance_to_lamp / segment_length
                lamp_x = start[0] + dx * fraction
                lamp_y = start[1] + dy * fraction
                normal_x = -dy / segment_length
                normal_y = dx / segment_length
                if segment_index < len(segment_lighting) and segment_lighting[segment_index]:
                    # A street: each side at its edge. A parking aisle: one lamp,
                    # the first free spot from the row seam inwards, either side -
                    # tight lots put the seam on the next aisle (Raksila).
                    candidates = (
                        [(side, half_width + depth) for depth in (PARKING_SPOT_DEPTH_M, PARKING_SPOT_DEPTH_M / 2.0, 1.0)
                         for side in (1.0, -1.0)]
                        if parking_aisle else [(side, edge_distance) for side in sides]
                    )
                    for side, edge_distance in candidates:
                        world_x = lamp_x + normal_x * edge_distance * side
                        world_y = lamp_y + normal_y * edge_distance * side
                        if _point_overlaps_indexed_road(
                            world_x, world_y, road_segment_grid
                        ) or _street_light_overlaps_footprint(work, world_x, world_y):
                            continue
                        junction_cell_x = math.floor(world_x / junction_cell_size)
                        junction_cell_y = math.floor(world_y / junction_cell_size)
                        if any(
                            (world_x - junction_x) ** 2 + (world_y - junction_y) ** 2
                            < STREET_LIGHT_JUNCTION_CLEARANCE_M * STREET_LIGHT_JUNCTION_CLEARANCE_M
                            for cell_x in (junction_cell_x - 1, junction_cell_x, junction_cell_x + 1)
                            for cell_y in (junction_cell_y - 1, junction_cell_y, junction_cell_y + 1)
                            for junction_x, junction_y in junction_grid.get((cell_x, cell_y), ())
                        ):
                            continue
                        if not parking_aisle and _lamp_stands_near(work, world_x, world_y):
                            break  # a median's lamp, placed from the twin carriageway
                        road_direction = math.atan2(-normal_y * side, -normal_x * side)
                        pool_radius_m = edge_distance + half_width + 1.0
                        cached_lamps.append((world_x, world_y, road_direction, pool_radius_m))
                        cell = STREET_LIGHT_MERGE_M
                        work.setdefault("placed_grid", {}).setdefault(
                            (math.floor(world_x / cell), math.floor(world_y / cell)), []).append((world_x, world_y))
                        break  # one lamp per spot: one side of the street
                distance_to_lamp += lamp_spacing
            distance_to_lamp = (segment_phase - segment_length) % lamp_spacing
            if distance_to_lamp < 1e-9:
                distance_to_lamp = lamp_spacing
        if time.perf_counter() >= deadline:
            break
    return work["placement_cursor"] >= len(ways)


STREET_LIGHT_MERGE_M = 12.0  # a synthetic lamp this close to another is the same pole


def _lamp_stands_near(work, x, y) -> bool:
    cell = STREET_LIGHT_MERGE_M
    grid = work.get("placed_grid", {})
    cx, cy = math.floor(x / cell), math.floor(y / cell)
    return any(
        (x - px) ** 2 + (y - py) ** 2 < cell * cell
        for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1)
        for px, py in grid.get((gx, gy), ())
    )


def _point_overlaps_indexed_road(point_x, point_y, segment_grid) -> bool:
    cell_size = STREET_LIGHT_ROAD_INDEX_CELL_M
    candidates = segment_grid.get(
        (math.floor(point_x / cell_size), math.floor(point_y / cell_size)), ()
    )
    return any(
        dist_point_to_segment(point_x, point_y, first[0], first[1], second[0], second[1])
        <= half_width
        for first, second, half_width in candidates
    )
