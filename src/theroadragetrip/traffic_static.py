"""Spatial indexes for static NPC collision obstacles."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple


def static_collision_cells(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    cell_size: float,
) -> Iterable[Tuple[int, int]]:
    for cell_x in range(math.floor(min_x / cell_size), math.floor(max_x / cell_size) + 1):
        for cell_y in range(math.floor(min_y / cell_size), math.floor(max_y / cell_size) + 1):
            yield cell_x, cell_y


def build_static_collision_grids(
    buildings: Iterable[Any],
    sceneries: Iterable[Any],
    cell_size: float,
    building_grid: Dict[Tuple[int, int], List[Any]],
    tree_grid: Dict[Tuple[int, int], List[Tuple[float, float]]],
) -> None:
    """Index buildings and trees so NPC collision checks stay local."""
    building_grid.clear()
    tree_grid.clear()
    for building in buildings:
        points = getattr(building, "points_m", ())
        if len(points) < 3:
            continue
        bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
        if bbox == (0.0, 0.0, 0.0, 0.0):
            xs, ys = zip(*points)
            bbox = (min(xs), min(ys), max(xs), max(ys))
        for cell in static_collision_cells(*bbox, cell_size):
            building_grid.setdefault(cell, []).append(building)
    for scenery in sceneries:
        for tree_x, tree_y in getattr(scenery, "trees", ()):
            cell = (math.floor(tree_x / cell_size), math.floor(tree_y / cell_size))
            tree_grid.setdefault(cell, []).append((tree_x, tree_y))


def nearby_static_buildings(
    x: float,
    y: float,
    radius: float,
    cell_size: float,
    building_grid: Dict[Tuple[int, int], List[Any]],
) -> List[Any]:
    buildings = []
    seen = set()
    for cell in static_collision_cells(
        x - radius, y - radius, x + radius, y + radius, cell_size
    ):
        for building in building_grid.get(cell, ()):
            if id(building) not in seen:
                seen.add(id(building))
                buildings.append(building)
    return buildings


def nearby_static_trees(
    x: float,
    y: float,
    radius: float,
    cell_size: float,
    tree_grid: Dict[Tuple[int, int], List[Tuple[float, float]]],
) -> List[Tuple[float, float]]:
    trees = []
    for cell in static_collision_cells(
        x - radius, y - radius, x + radius, y + radius, cell_size
    ):
        trees.extend(tree_grid.get(cell, ()))
    return trees
