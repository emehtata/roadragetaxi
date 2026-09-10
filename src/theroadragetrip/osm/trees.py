from collections import defaultdict
import logging
import math
import random
from typing import Callable, List, Optional, Tuple


from ..geo import dist_point_to_segment, point_in_polygon

logger = logging.getLogger(__name__)

from .models import (
    Way,
    Scenery,
)


# Real OSM genus/species tags (Latin or Finnish common name) that map onto
# one of the three shapes this game actually renders - Finland's three
# dominant forest trees. Matched as a substring of the lowercased tag
# value, so e.g. "Betula pendula" or "Betula pubescens" both hit "betula".
_TREE_SPECIES_KEYWORDS = {
    "picea": "spruce", "kuusi": "spruce", "spruce": "spruce",
    "pinus": "pine", "mänty": "pine", "manty": "pine", "pine": "pine",
    "betula": "birch", "koivu": "birch", "birch": "birch",
}


def classify_tree_kind(tags: dict, x: float, y: float) -> str:
    """Pick a rendered species ("spruce"/"pine"/"birch") for one tree.

    Real OSM data wins outright when it says enough: a genus/species tag
    names the tree directly; leaf_type narrows it to the broadleaf shape
    (birch - the dominant Finnish broadleaf; this game doesn't render a
    separate aspen/oak/etc. shape) or, for "needleleaved", a 50/50 pick
    between the two conifers by position (still deterministic, still
    respects "definitely a conifer").

    With no usable tag at all, mix all three by a deterministic position
    hash, roughly matching real Finnish forest composition (pine-
    dominant, then spruce, then birch) - this is what makes an unspecified
    forest look like a real mixed stand instead of a wall of one shape.
    """
    for tag_name in ("genus", "genus:fi", "species", "species:fi", "taxon"):
        value = str(tags.get(tag_name, "") or "").strip().lower()
        if not value:
            continue
        for keyword, kind in _TREE_SPECIES_KEYWORDS.items():
            if keyword in value:
                return kind
    roll = abs(math.sin(x * 39.425 + y * 11.317))
    leaf_type = str(tags.get("leaf_type", "") or "").strip().lower()
    if leaf_type == "broadleaved":
        return "birch"
    if leaf_type == "needleleaved":
        return "pine" if roll < 0.5 else "spruce"
    if roll < 0.50:
        return "pine"
    if roll < 0.85:
        return "spruce"
    return "birch"


def plant_trees(
    sceneries: List[Scenery],
    ways: List[Way],
    real_trees: Optional[List[Tuple[float, float]]] = None,
    real_tree_tags: Optional[List[dict]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    progress_start: float = 0.0,
    progress_end: float = 1.0,
) -> None:
    """Add deterministic tree centers to green areas while keeping them off roads.

    `real_trees` is the (x, y) meter positions of any real natural=tree OSM
    nodes covering this batch, `real_tree_tags` their OSM tags in the same
    order (genus/species/leaf_type, if surveyed - see classify_tree_kind).
    A scenery area that actually contains some of them uses those exact
    positions instead of procedural placement - some OSM areas (mapped
    parks, tree-lined squares) have every real tree surveyed, and made-up
    trees on top of (or instead of) real ones would just be wrong there.
    Areas with no real tree data fall back to the existing density-based
    procedural placement, unchanged.
    """
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
        if scenery.trees_from_osm:
            continue  # already has real tree positions - never top up with fake ones
        if len(scenery.points_m) < 3:
            continue
        minx, miny, maxx, maxy = scenery.bbox

        # Real OSM tree data wins regardless of scenery kind - a "grass"
        # strip or a "residential"-landuse courtyard can have individually
        # surveyed trees too, not just forest/park/wood/scrub/garden (the
        # only kinds that get *procedural* filling below). Gating this on
        # `kind in tree_density` would silently drop real trees in every
        # other kind of area even though the data says they're there.
        if real_trees:
            matched = [
                (index, x, y) for index, (x, y) in enumerate(real_trees)
                if minx <= x <= maxx and miny <= y <= maxy and point_in_polygon(x, y, scenery.points_m)
            ]
            if matched:
                scenery.trees = [(x, y) for _, x, y in matched]
                scenery.tree_variations = [abs(math.sin(x * 12.9898 + y * 78.233)) for _, x, y in matched]
                scenery.tree_kinds = [
                    classify_tree_kind((real_tree_tags[index] if real_tree_tags else {}) or {}, x, y)
                    for index, x, y in matched
                ]
                scenery.trees_from_osm = True
                continue

        kind = scenery.kind.lower()
        density = tree_density.get(kind)
        if density is None:
            continue
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
            scenery.tree_kinds.append(classify_tree_kind({}, x, y))
    if progress_callback:
        progress_callback(progress_end, f"Planted trees in {total} scenery areas")


def remove_trees_under_roads(sceneries: List[Scenery], ways: List[Way]) -> None:
    """Remove tree centers covered by drivable road geometry.

    Each scenery is only swept once (tracked via
    trees_checked_against_roads): called after every tile-streaming merge
    with the full accumulated ways/sceneries lists, re-scanning sceneries
    already checked in an earlier call got slower every merge as the
    explored map grew, turning into multi-second/main-thread-blocking
    stalls in a large city. A newly loaded scenery still gets checked
    against every currently known road (needed since a neighboring tile's
    road can arrive after this one's trees were planted).
    # ponytail: a road that streams in *after* an old, already-checked
    # scenery next to it (rare - usually the player is moving away from
    # checked ground, not backfilling next to it) won't retroactively
    # clear that scenery's trees. Reset trees_checked_against_roads for
    # sceneries near newly-merged ways if that turns out to matter.
    """
    pending = [scenery for scenery in sceneries if not scenery.trees_checked_against_roads]
    if not pending:
        return
    road_ways = [way for way in ways if getattr(way, "is_drivable", True)]
    if not road_ways:
        for scenery in pending:
            scenery.trees_checked_against_roads = True
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

    for scenery in pending:
        kept_trees = []
        kept_variations = []
        kept_kinds = []
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
            if index < len(scenery.tree_kinds):
                kept_kinds.append(scenery.tree_kinds[index])
        scenery.trees = kept_trees
        scenery.tree_variations = kept_variations
        scenery.tree_kinds = kept_kinds
        scenery.trees_checked_against_roads = True
