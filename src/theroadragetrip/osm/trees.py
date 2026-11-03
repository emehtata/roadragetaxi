from collections import defaultdict
import logging
import math
from typing import Callable, Iterator, List, Optional, Tuple


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
    """Attach only surveyed natural=tree positions; never synthesize server trees.

    Areas own their mapped trees where possible. Standalone mapped trees get
    point sceneries so streaming and collision queries retain them too.
    """
    assigned = {point for scenery in sceneries if scenery.trees_from_osm for point in scenery.trees}
    total = len(sceneries)
    for scenery_index, scenery in enumerate(sceneries):
        if progress_callback and total:
            progress_callback(
                progress_start
                + (progress_end - progress_start) * scenery_index / total,
                f"Loading OSM trees ({scenery_index}/{total} scenery areas)...",
            )
        if scenery.trees_from_osm:
            continue  # already has real tree positions - never top up with fake ones
        if len(scenery.points_m) < 3:
            continue
        minx, miny, maxx, maxy = scenery.bbox

        scenery.trees = []
        scenery.tree_variations = []
        scenery.tree_kinds = []
        if real_trees:
            matched = [
                (index, x, y) for index, (x, y) in enumerate(real_trees)
                if (x, y) not in assigned and minx <= x <= maxx and miny <= y <= maxy and point_in_polygon(x, y, scenery.points_m)
            ]
            if matched:
                scenery.trees = [(x, y) for _, x, y in matched]
                scenery.tree_variations = [abs(math.sin(x * 12.9898 + y * 78.233)) for _, x, y in matched]
                scenery.tree_kinds = [
                    classify_tree_kind((real_tree_tags[index] if real_tree_tags else {}) or {}, x, y)
                    for index, x, y in matched
                ]
                scenery.trees_from_osm = True
                assigned.update(scenery.trees)
                continue

    for index, (x, y) in enumerate(real_trees or ()):
        if (x, y) in assigned:
            continue
        tags = (real_tree_tags[index] if real_tree_tags else {}) or {}
        sceneries.append(Scenery(points_m=[(x, y)], kind="tree", bbox=(x, y, x, y),
                                 trees=[(x, y)], tree_variations=[abs(math.sin(x * 12.9898 + y * 78.233))],
                                 tree_kinds=[classify_tree_kind(tags, x, y)], trees_from_osm=True))
        assigned.add((x, y))
    if progress_callback:
        progress_callback(progress_end, f"Loaded {len(assigned)} OSM trees")


def remove_trees_under_roads(sceneries: List[Scenery], ways: List[Way]) -> None:
    """Synchronous form of remove_trees_under_roads_steps."""
    for _ in remove_trees_under_roads_steps(sceneries, ways):
        pass


def remove_trees_under_roads_steps(sceneries: List[Scenery], ways: List[Way]) -> Iterator[None]:
    """Remove tree centers covered by drivable road geometry, yielding after
    each road way and each scenery so map sync can spread it over frames
    (a single pass measured ~1.3 s on Oulu). The lists are snapshotted at
    start; each scenery is final (and flagged) as soon as it is swept.

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
    yield
    if not road_ways:
        for scenery in pending:
            scenery.trees_checked_against_roads = True
        yield
        return

    # Index road *segments* (not whole ways), only for cells that hold a
    # pending tree: a long way used to be tested by every tree in every
    # cell its bbox touched, which cost >1 s per merge in Oulu.
    cell_size = 64.0
    tree_cells = {
        (math.floor(tree_x / cell_size), math.floor(tree_y / cell_size))
        for scenery in pending
        for tree_x, tree_y in scenery.trees
    }
    road_grid = defaultdict(list)
    for way in road_ways:
        points = way.points_m
        half_width = way.half_width_m
        for p1, p2 in zip(points, points[1:]):
            segment = (p1[0], p1[1], p2[0], p2[1], half_width)
            for grid_x in range(
                math.floor((min(p1[0], p2[0]) - half_width) / cell_size),
                math.floor((max(p1[0], p2[0]) + half_width) / cell_size) + 1,
            ):
                for grid_y in range(
                    math.floor((min(p1[1], p2[1]) - half_width) / cell_size),
                    math.floor((max(p1[1], p2[1]) + half_width) / cell_size) + 1,
                ):
                    if (grid_x, grid_y) in tree_cells:
                        road_grid[(grid_x, grid_y)].append(segment)
        yield

    for scenery in pending:
        kept_trees = []
        kept_variations = []
        kept_kinds = []
        for index, (tree_x, tree_y) in enumerate(scenery.trees):
            covered = any(
                dist_point_to_segment(tree_x, tree_y, x1, y1, x2, y2) <= half_width
                for x1, y1, x2, y2, half_width in road_grid.get(
                    (math.floor(tree_x / cell_size), math.floor(tree_y / cell_size)),
                    (),
                )
            )
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
        yield
