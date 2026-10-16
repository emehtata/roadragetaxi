"""Generated parking for detached houses (the simulation keeps it: NPC
households park there): a short driveway from the nearest road and a few
bays beside the house. No drawing here."""

from __future__ import annotations

import math
from typing import Tuple

from .building_style import _building_is_house_by_tag
from .osm import ParkingSpace
from .performance import advance_chunked


GENERATED_DRIVEWAY_MAX_LENGTH_M = 35.0


GENERATED_HOUSE_PARKING_BAYS = 2


def _nearest_house_driveway(building, ways, road_spatial_grid=None):
    """Return a synthetic (house edge, road edge) driveway when OSM has none."""
    if not _building_is_house_by_tag(building) or len(building.points_m) < 3:
        return None
    minx, miny, maxx, maxy = building.bbox
    margin = GENERATED_DRIVEWAY_MAX_LENGTH_M
    candidates = (
        road_spatial_grid.ways_in_rect(minx - margin, miny - margin, maxx + margin, maxy + margin)
        if road_spatial_grid is not None
        else ways
    )
    candidates = [way for way in candidates if getattr(way, "is_drivable", True)]
    # A mapped driveway wins; never paint a duplicate procedural one.
    for way in candidates:
        if getattr(way, "service", None) != "driveway":
            continue
        for point in way.points_m:
            if minx - 4.0 <= point[0] <= maxx + 4.0 and miny - 4.0 <= point[1] <= maxy + 4.0:
                return None

    facade_points = list(getattr(building, "entrances", ()) or ())
    facade_points.extend(
        ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
        for a, b in zip(building.points_m, building.points_m[1:] + building.points_m[:1])
    )
    best = None
    for way in candidates:
        if getattr(way, "highway", "") in {"motorway", "motorway_link", "trunk", "trunk_link"}:
            continue
        for ax, ay in facade_points:
            for (x1, y1), (x2, y2) in zip(way.points_m, way.points_m[1:]):
                dx, dy = x2 - x1, y2 - y1
                length_sq = dx * dx + dy * dy
                if length_sq <= 1e-9:
                    continue
                t = max(0.0, min(1.0, ((ax - x1) * dx + (ay - y1) * dy) / length_sq))
                centerline_point = (x1 + dx * t, y1 + dy * t)
                to_house_x, to_house_y = ax - centerline_point[0], ay - centerline_point[1]
                centerline_distance = math.hypot(to_house_x, to_house_y)
                edge_offset = min(centerline_distance, max(0.0, getattr(way, "half_width_m", 0.0)))
                if centerline_distance > 1e-9:
                    road_point = (
                        centerline_point[0] + to_house_x / centerline_distance * edge_offset,
                        centerline_point[1] + to_house_y / centerline_distance * edge_offset,
                    )
                else:
                    road_point = centerline_point
                distance = math.hypot(road_point[0] - ax, road_point[1] - ay)
                if distance <= GENERATED_DRIVEWAY_MAX_LENGTH_M and (best is None or distance < best[0]):
                    best = (distance, (ax, ay), road_point)
    return None if best is None else (best[1], best[2])


def _house_parking_key(building):
    bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
    return tuple(round(float(value), 2) for value in bbox)


def _add_house_parking_for_building(building, ways, road_spatial_grid, parking_spaces, existing_keys) -> int:
    """Add two reservable residential bays for one building's driveway
    access, if it has one and doesn't already. Returns bays added (0 or
    GENERATED_HOUSE_PARKING_BAYS). Shared by the synchronous
    generate_detached_house_parking() and its chunked counterpart below."""
    key = _house_parking_key(building)
    if key in existing_keys:
        return 0
    access = _nearest_house_driveway(building, ways, road_spatial_grid)
    if access is None:
        return 0
    house_edge, road_edge = access
    dx, dy = road_edge[0] - house_edge[0], road_edge[1] - house_edge[1]
    access_length = math.hypot(dx, dy)
    if access_length < 5.5:
        return 0
    ux, uy = dx / access_length, dy / access_length
    lateral_x, lateral_y = -uy, ux
    bay_length, bay_width = 5.0, 2.5
    center_distance = bay_length * 0.5 + 0.5
    added = 0
    for bay_index in range(GENERATED_HOUSE_PARKING_BAYS):
        lateral_offset = (bay_index - (GENERATED_HOUSE_PARKING_BAYS - 1) * 0.5) * (bay_width + 0.3)
        center_x = house_edge[0] + ux * center_distance + lateral_x * lateral_offset
        center_y = house_edge[1] + uy * center_distance + lateral_y * lateral_offset
        half_length, half_width = bay_length * 0.5, bay_width * 0.5
        points = [
            (center_x + ux * half_length + lateral_x * half_width, center_y + uy * half_length + lateral_y * half_width),
            (center_x + ux * half_length - lateral_x * half_width, center_y + uy * half_length - lateral_y * half_width),
            (center_x - ux * half_length - lateral_x * half_width, center_y - uy * half_length - lateral_y * half_width),
            (center_x - ux * half_length + lateral_x * half_width, center_y - uy * half_length + lateral_y * half_width),
        ]
        xs, ys = [point[0] for point in points], [point[1] for point in points]
        parking_spaces.append(ParkingSpace(
            points_m=points,
            bbox=(min(xs), min(ys), max(xs), max(ys)),
            orientation=math.atan2(uy, ux),
            source_building_key=key,
            access_path=[house_edge, road_edge],
        ))
        added += 1
    existing_keys.add(key)
    return added


def _existing_house_parking_keys(parking_spaces) -> set:
    return {
        getattr(space, "source_building_key", None)
        for space in parking_spaces
        if getattr(space, "source_building_key", None) is not None
    }


def generate_detached_house_parking(buildings, ways, parking_spaces, road_spatial_grid=None) -> int:
    """Add two reservable residential bays to each generated house access."""
    existing_keys = _existing_house_parking_keys(parking_spaces)
    added = 0
    for building in buildings:
        added += _add_house_parking_for_building(building, ways, road_spatial_grid, parking_spaces, existing_keys)
    return added


def generate_detached_house_parking_chunk(
    buildings, ways, parking_spaces, road_spatial_grid, index: int, budget_s: float,
) -> Tuple[int, int]:
    """Budgeted version of generate_detached_house_parking (bin-loader-
    v3.md: measured up to ~1.9s in one frame against a dense real city
    load, 2376 bays over 20k buildings). Processes buildings[index:] until
    budget_s elapses. Returns (new_index, bays_added_this_call) -
    new_index == len(buildings) once finished. The caller owns `index`
    across calls; parking_spaces is mutated in place exactly like the
    synchronous version, so a partially-processed building list is always
    valid to query (just fewer bays exist yet, never wrong ones)."""
    existing_keys = _existing_house_parking_keys(parking_spaces)
    added = [0]

    def _process(building) -> None:
        added[0] += _add_house_parking_for_building(building, ways, road_spatial_grid, parking_spaces, existing_keys)

    new_index = advance_chunked(buildings, index, budget_s, _process)
    return new_index, added[0]
