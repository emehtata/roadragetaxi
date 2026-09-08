import collections
import concurrent.futures
from collections import defaultdict
import json
import logging
import math
import multiprocessing
import os
import random
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from ..geo import dist_point_to_segment, point_in_polygon
from ..tile_streaming import TileCoord, active_tiles, tile_bbox, tile_changes, world_to_tile

logger = logging.getLogger(__name__)

from .models import (
    Way,
    Scenery,
)


def plant_trees(
    sceneries: List[Scenery],
    ways: List[Way],
    progress_callback: Optional[Callable[[float, str], None]] = None,
    progress_start: float = 0.0,
    progress_end: float = 1.0,
) -> None:
    """Add deterministic tree centers to green areas while keeping them off roads."""
    tree_density = {
        "forest": 100.0,
        "wood": 100.0,
        "scrub": 250.0,
        "park": 1800.0,
        "garden": 1800.0,
    }
    total = len(sceneries)
    for scenery_index, scenery in enumerate(sceneries):
        if progress_callback and total:
            progress_callback(
                progress_start
                + (progress_end - progress_start) * scenery_index / total,
                f"Planting trees ({scenery_index}/{total} scenery areas)...",
            )
        kind = scenery.kind.lower()
        density = tree_density.get(kind)
        if density is None or len(scenery.points_m) < 3:
            continue
        minx, miny, maxx, maxy = scenery.bbox
        area = max(0.0, (maxx - minx) * (maxy - miny))
        target = min(80, max(1, int(area / density)))
        rng = random.Random(f"{round(minx)}:{round(miny)}:{kind}")
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
            scenery.tree_variations.append(abs(math.sin(x * 12.9898 + y * 78.233)))
    if progress_callback:
        progress_callback(progress_end, f"Planted trees in {total} scenery areas")


def remove_trees_under_roads(sceneries: List[Scenery], ways: List[Way]) -> None:
    """Remove tree centers covered by drivable road geometry."""
    road_ways = [way for way in ways if getattr(way, "is_drivable", True)]
    if not road_ways:
        return

    cell_size = 64.0
    road_grid = defaultdict(list)
    for way in road_ways:
        points = way.points_m
        if len(points) < 2:
            continue
        half_width = way.half_width_m
        minx = min(point[0] for point in points) - half_width
        miny = min(point[1] for point in points) - half_width
        maxx = max(point[0] for point in points) + half_width
        maxy = max(point[1] for point in points) + half_width
        for grid_x in range(math.floor(minx / cell_size), math.floor(maxx / cell_size) + 1):
            for grid_y in range(math.floor(miny / cell_size), math.floor(maxy / cell_size) + 1):
                road_grid[(grid_x, grid_y)].append(way)

    for scenery in sceneries:
        kept_trees = []
        kept_variations = []
        for index, (tree_x, tree_y) in enumerate(scenery.trees):
            covered = False
            candidate_ways = road_grid.get(
                (math.floor(tree_x / cell_size), math.floor(tree_y / cell_size)),
                (),
            )
            for way in candidate_ways:
                half_width = way.half_width_m
                points = way.points_m
                minx = min(point[0] for point in points)
                miny = min(point[1] for point in points)
                maxx = max(point[0] for point in points)
                maxy = max(point[1] for point in points)
                if not (
                    minx - half_width <= tree_x <= maxx + half_width
                    and miny - half_width <= tree_y <= maxy + half_width
                ):
                    continue
                if any(
                    dist_point_to_segment(tree_x, tree_y, p1[0], p1[1], p2[0], p2[1]) <= half_width
                    for p1, p2 in zip(points, points[1:])
                ):
                    covered = True
                    break
            if covered:
                continue
            kept_trees.append((tree_x, tree_y))
            if index < len(scenery.tree_variations):
                kept_variations.append(scenery.tree_variations[index])
        scenery.trees = kept_trees
        scenery.tree_variations = kept_variations
