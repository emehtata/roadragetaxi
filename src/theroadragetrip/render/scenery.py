from . import common
from .common import (
    SCREEN_W,
    SCREEN_H,
    PX_PER_M,
    CACHE_PADDING_PX,
    _rebuild_or_stale,
    _static_cache_zoom,
    world_to_screen,
    get_viewport_bounds,
)
import math
import random
import time
from typing import List, Optional


from ..osm import Scenery, SceneryObject, Way
from ..physics import is_point_on_road


SCENERY_COLORS = {
    # Natural / green (osm/build.py: leisure=*, landuse=*, or natural in
    # wood/scrub/grass/sand/heath all become a Scenery, kind = that raw
    # OSM value) - counts below are from a real regional extract (Oulu),
    # ranked so the frequent ones got picked first.
    "forest": (32, 95, 32),
    "wood": (32, 95, 32),
    "scrub": (52, 90, 42),
    "heath": (98, 110, 68),
    "park": (42, 120, 42),
    "garden": (45, 125, 45),
    "meadow": (38, 110, 38),
    "grass": (36, 105, 36),
    "greenfield": (150, 165, 110),
    "nature_reserve": (40, 102, 46),
    "pitch": (48, 115, 55),
    "playground": (48, 115, 55),
    "dog_park": (44, 118, 52),
    "track": (52, 108, 58),
    "sand": (160, 150, 110),
    "beach": (170, 160, 115),
    # Farmed / cultivated - warm, dry tones, not park-green.
    "farmland": (190, 175, 110),
    "farmyard": (150, 125, 90),
    "allotments": (140, 130, 80),
    "flowerbed": (150, 90, 120),
    "greenhouse_horticulture": (140, 160, 150),
    # Built-up zoning - muted, not green (these are usually mostly covered
    # by buildings/roads drawn on top; the fill only shows through gaps).
    "residential": (95, 92, 85),
    "commercial": (100, 95, 110),
    "retail": (110, 95, 92),
    "industrial": (90, 90, 95),
    "institutional": (105, 100, 90),
    "education": (105, 100, 90),
    "civil": (105, 100, 90),
    "religious": (95, 90, 82),
    "military": (95, 100, 80),
    "railway": (100, 96, 92),
    "recreation_ground": (60, 115, 62),
    # Bare ground / disturbed land.
    "brownfield": (140, 120, 95),
    "construction": (168, 140, 95),
    "quarry": (120, 110, 100),
    "landfill": (110, 100, 80),
    "cemetery": (70, 95, 70),
    # Water-adjacent leisure (the water body itself is a separate Water,
    # not Scenery - this is the surrounding shore/facility ground).
    "marina": (95, 130, 140),
    "slipway": (95, 130, 140),
    "bathing_place": (150, 165, 125),
    "swimming_pool": (110, 150, 165),
    # Sports/recreation facilities without their own building footprint.
    "sports_centre": (115, 100, 80),
    "sports_hall": (115, 100, 80),
    "fitness_centre": (115, 100, 80),
    "fitness_station": (60, 118, 62),
    "stadium": (115, 100, 80),
    "ice_rink": (170, 190, 200),
    "horse_riding": (150, 130, 90),
    "firepit": (100, 90, 70),
    "outdoor_seating": (110, 100, 90),
    "sauna": (110, 90, 70),
    "parking": (92, 96, 94),
}
TREE_CROWN_COLORS = ((25, 78, 29), (34, 101, 35), (48, 119, 42), (63, 112, 34))
_grass_texture_tile = None


def draw_scenery(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    profiler=None,
) -> None:
    """Draw cached scenery fills (parks, forests, grass, parking, ...).

    Trees are NOT drawn here - see draw_trees(), called separately later
    in the frame (after roads/parking, before buildings) so a scenery
    fill, and more importantly a road or parking surface painted well
    after this static-cached layer, can never end up covering a tree.
    """
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(sceneries), len(sceneries), id(sceneries[-1]) if sceneries else None,
        id(spatial_grid),
        round(camx * cache_zoom / 128.0), round(camy * cache_zoom / 128.0),
        cache_zoom, screen.get_size(),
    )
    if frame_cache_key == common._scenery_frame_cache_key and common._scenery_frame_cache_surface is not None:
        cached_camx, cached_camy = common._scenery_frame_cache_camera
        screen.blit(
            common._scenery_frame_cache_surface,
            (
                round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
                round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
            ),
        )
        return
    if _rebuild_or_stale(screen, "scenery", common._scenery_frame_cache_surface, common._scenery_frame_cache_camera, camx, camy, cache_zoom):
        return
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_scenery_uncached(cache_surface, sceneries, camx, camy, cache_zoom, cache_width, cache_height, spatial_grid)
    if profiler is not None:
        profiler.record("render:scenery_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._scenery_frame_cache_key = frame_cache_key
    common._scenery_frame_cache_surface = cache_surface
    common._scenery_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))


def _draw_scenery_uncached(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw parks, forests, and green spaces intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    visible_sceneries = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else sceneries
    )
    for sc in visible_sceneries:
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(sc.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in sc.points_m]
        color = SCENERY_COLORS.get(sc.kind.lower(), (38, 105, 38))
        pygame.draw.polygon(screen, color, pts)


CONSTRUCTION_FENCE_COLOR = (235, 140, 30)  # hi-vis hazard orange
_FENCE_DASH_M = 1.5
_FENCE_GAP_M = 1.0


def draw_construction_fences(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Outline landuse=construction sceneries with a dashed hazard fence.

    Uncached like draw_curbs/draw_crossings - construction zones are rare
    (a few dozen per city), not worth a static-cache slot.
    """
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 20.0)
    candidates = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else sceneries
    )
    thickness = max(1, int(0.25 * px_per_m))

    for sc in candidates:
        if sc.kind.lower() != "construction":
            continue
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(sc.points_m) < 3:
            continue
        ring = list(sc.points_m)
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        common._draw_dashed_polyline(
            screen, ring, camx, camy, px_per_m, screen_w, screen_h,
            CONSTRUCTION_FENCE_COLOR, thickness, _FENCE_DASH_M, _FENCE_GAP_M,
        )


def draw_trees(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    tree_effects=None,
    fallen_trees=None,
    spatial_grid=None,
    ways: Optional[List[Way]] = None,
    road_spatial_grid=None,
    profiler=None,
) -> None:
    """Draw cached trees, on top of everything ground-level drawn earlier
    in the frame - scenery fills, water, roads, parking spaces.

    Deliberately NOT part of draw_scenery()'s cache, and called from main
    after draw_ways()/draw_parking_spaces(), not before: a real OSM tree
    (osm/trees.py plants every one it finds, regardless of what other
    polygon it geometrically overlaps - a park's tree can sit right at the
    edge of a bordering parking lot or a big landuse area) must never end
    up invisible under a road or parking surface painted over it later in
    the frame. Has its own static cache, same as every other map layer -
    an active tree_effect/fallen_tree (shake, falling, leaf particles - a
    tree the player just hit) forces the uncached path, same as the old
    combined scenery+trees pass used to, since those animate every frame
    and a cache can't represent that.
    """
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    if tree_effects or fallen_trees:
        _draw_trees_uncached(
            screen, sceneries, camx, camy, px_per_m, screen_w, screen_h,
            tree_effects, fallen_trees, spatial_grid, ways, road_spatial_grid,
        )
        return

    frame_cache_key = (
        id(sceneries), len(sceneries), id(sceneries[-1]) if sceneries else None,
        id(ways), id(spatial_grid), id(road_spatial_grid),
        round(camx * cache_zoom / 128.0), round(camy * cache_zoom / 128.0),
        cache_zoom, screen.get_size(),
    )
    if frame_cache_key == common._tree_frame_cache_key and common._tree_frame_cache_surface is not None:
        cached_camx, cached_camy = common._tree_frame_cache_camera
        screen.blit(
            common._tree_frame_cache_surface,
            (
                round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
                round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
            ),
        )
        return
    if _rebuild_or_stale(screen, "trees", common._tree_frame_cache_surface, common._tree_frame_cache_camera, camx, camy, cache_zoom):
        return
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_trees_uncached(
        cache_surface, sceneries, camx, camy, cache_zoom, cache_width, cache_height,
        None, None, spatial_grid, ways, road_spatial_grid,
    )
    if profiler is not None:
        profiler.record("render:trees_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._tree_frame_cache_key = frame_cache_key
    common._tree_frame_cache_surface = cache_surface
    common._tree_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))


def _draw_trees_uncached(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    tree_effects=None,
    fallen_trees=None,
    spatial_grid=None,
    ways: Optional[List[Way]] = None,
    road_spatial_grid=None,
) -> None:
    """Draw every tree. Bounded the same way regardless of cache/uncached
    path: tree_budget-limited and viewport-culled, so cost stays
    proportional to what's on screen, not the whole loaded map."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)
    tree_budget = max(600, screen_w * screen_h // 400)

    def tree_is_on_road(tree_x: float, tree_y: float) -> bool:
        return ways is not None and is_point_on_road(
            tree_x,
            tree_y,
            ways=ways,
            spatial_grid=road_spatial_grid,
            car_roads_only=True,
        )

    visible_sceneries = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else sceneries
    )
    for sc in visible_sceneries:
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        trees = getattr(sc, "trees", [])
        if not trees:
            continue
        visible_tree_count = sum(
            1 for tree_x, tree_y in trees
            if vminx <= tree_x <= vmaxx
            and vminy <= tree_y <= vmaxy
            and not tree_is_on_road(tree_x, tree_y)
        )
        tree_step = max(1, math.ceil(visible_tree_count / tree_budget))
        for tree_index, (tree_x, tree_y) in enumerate(trees):
            if not (vminx <= tree_x <= vmaxx and vminy <= tree_y <= vmaxy):
                continue
            if tree_is_on_road(tree_x, tree_y):
                continue
            tree_key = (id(sc), tree_index)
            effect = (tree_effects or {}).get(tree_key, {})
            if tree_step > 1 and tree_index % tree_step and tree_key not in (fallen_trees or set()) and effect.get("shake", 0.0) <= 0.0:
                continue
            sx, sy = world_to_screen(tree_x, tree_y, camx, camy, px_per_m, screen_w, screen_h)
            shake = effect.get("shake", 0.0)
            if shake > 0.0:
                sx += math.sin(shake * 42.0) * max(1, int(2.0 * px_per_m))
            tree_variations = getattr(sc, "tree_variations", ())
            variation = (
                tree_variations[tree_index]
                if tree_index < len(tree_variations)
                else abs(math.sin(tree_x * 12.9898 + tree_y * 78.233))
            )
            size = 0.72 + variation * 0.62
            trunk = max(1, int(0.7 * size * px_per_m))
            trunk_height = max(2, int(1.5 * size * px_per_m))
            crown = max(2, int(2.2 * size * px_per_m))
            trunk_color = (78 + int(22 * variation), 52 + int(18 * variation), 27)
            crown_color = TREE_CROWN_COLORS[min(len(TREE_CROWN_COLORS) - 1, int(variation * len(TREE_CROWN_COLORS)))]
            if tree_key in (fallen_trees or set()):
                fall_heading = effect.get("angle", 0.0)
                fall_x = sx + math.cos(fall_heading) * 3.2 * px_per_m
                fall_y = sy - math.sin(fall_heading) * 3.2 * px_per_m
                pygame.draw.line(screen, trunk_color, (sx, sy), (fall_x, fall_y), max(2, trunk))
                pygame.draw.circle(screen, crown_color, (int(fall_x), int(fall_y)), crown)
            else:
                pygame.draw.rect(screen, trunk_color, (sx - trunk // 2, sy, trunk, trunk_height))
                pygame.draw.circle(screen, crown_color, (sx, sy - crown // 2), crown)
            leaves_left = effect.get("leaves", 0.0)
            if leaves_left > 0.0:
                for leaf_index in range(8):
                    drift_x = math.sin(leaf_index * 2.7 + (1.2 - leaves_left) * 8.0) * 12.0 * px_per_m
                    drift_y = -(1.2 - leaves_left) * 20.0 * px_per_m + math.cos(leaf_index * 1.9) * 5.0 * px_per_m
                    pygame.draw.circle(screen, (82, 145, 44), (int(sx + drift_x), int(sy - crown + drift_y)), max(1, int(px_per_m * 0.22)))


SCENERY_OBJECT_COLORS = {
    "bench": (120, 82, 45),
    "waste_basket": (58, 66, 56),
    "bicycle_parking": (75, 95, 115),
    "statue": (150, 130, 85),
}
_STATUE_PEDESTAL_COLOR = (110, 110, 105)


def draw_scenery_objects(
    screen,
    scenery_objects: List[SceneryObject],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    profiler=None,
) -> None:
    """Draw cached small decorative OSM point objects - benches, waste
    baskets, bicycle parking, statues/memorials - as simple primitive
    icons (no sprite assets exist in this project; every other point/area
    feature is drawn the same way).

    Called from the same spot as draw_trees(), after roads/parking - same
    reasoning as there (see draw_trees docstring): one of these can sit
    near a road or parking-lot edge just like a real tree can, and must
    not end up invisible under a surface painted over it earlier in the
    frame. No dynamic per-object effects exist (unlike trees), so unlike
    draw_trees() this never needs to bypass its cache.
    """
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(scenery_objects), len(scenery_objects), id(scenery_objects[-1]) if scenery_objects else None,
        round(camx * cache_zoom / 128.0), round(camy * cache_zoom / 128.0),
        cache_zoom, screen.get_size(),
    )
    if frame_cache_key == common._scenery_object_frame_cache_key and common._scenery_object_frame_cache_surface is not None:
        cached_camx, cached_camy = common._scenery_object_frame_cache_camera
        screen.blit(
            common._scenery_object_frame_cache_surface,
            (
                round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
                round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
            ),
        )
        return
    if _rebuild_or_stale(
        screen, "scenery_objects", common._scenery_object_frame_cache_surface,
        common._scenery_object_frame_cache_camera, camx, camy, cache_zoom,
    ):
        return
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_scenery_objects_uncached(cache_surface, scenery_objects, camx, camy, cache_zoom, cache_width, cache_height)
    if profiler is not None:
        profiler.record("render:scenery_objects_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._scenery_object_frame_cache_key = frame_cache_key
    common._scenery_object_frame_cache_surface = cache_surface
    common._scenery_object_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))


def _draw_scenery_objects_uncached(
    screen,
    scenery_objects: List[SceneryObject],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    import pygame

    if not scenery_objects:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 20.0)
    for obj in scenery_objects:
        if not (vminx <= obj.x <= vmaxx and vminy <= obj.y <= vmaxy):
            continue
        sx, sy = world_to_screen(obj.x, obj.y, camx, camy, px_per_m, screen_w, screen_h)
        if obj.kind == "bench":
            width = max(2, int(1.4 * px_per_m))
            depth = max(1, int(0.4 * px_per_m))
            pygame.draw.rect(screen, SCENERY_OBJECT_COLORS["bench"], (sx - width // 2, sy - depth // 2, width, depth))
        elif obj.kind == "waste_basket":
            size = max(2, int(0.6 * px_per_m))
            pygame.draw.rect(screen, SCENERY_OBJECT_COLORS["waste_basket"], (sx - size // 2, sy - size // 2, size, size))
        elif obj.kind == "bicycle_parking":
            color = SCENERY_OBJECT_COLORS["bicycle_parking"]
            size = max(2, int(0.8 * px_per_m))
            pygame.draw.rect(screen, color, (sx - size // 2, sy - size // 4, size, max(1, size // 2)))
            bar_height = max(2, int(0.5 * px_per_m))
            for dx in (-size // 3, 0, size // 3):
                pygame.draw.line(screen, color, (sx + dx, sy - bar_height), (sx + dx, sy), max(1, int(px_per_m * 0.08)))
        elif obj.kind == "statue":
            pedestal_w = max(2, int(0.9 * px_per_m))
            pedestal_h = max(2, int(0.6 * px_per_m))
            pygame.draw.rect(screen, _STATUE_PEDESTAL_COLOR, (sx - pedestal_w // 2, sy, pedestal_w, pedestal_h))
            radius = max(2, int(0.5 * px_per_m))
            pygame.draw.circle(screen, SCENERY_OBJECT_COLORS["statue"], (sx, sy - radius // 2), radius)


def draw_parking_spaces(screen, parking_spaces, camx: float, camy: float, px_per_m: float = PX_PER_M,
                        screen_w: int = SCREEN_W, screen_h: int = SCREEN_H,
                        spatial_grid=None, grid_cell_size: float = 100.0) -> None:
    """Draw OSM parking spaces as small asphalt-colored polygons."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    if spatial_grid is not None:
        cell_size = max(1.0, grid_cell_size)
        min_cell_x = math.floor(vminx / cell_size)
        max_cell_x = math.floor(vmaxx / cell_size)
        min_cell_y = math.floor(vminy / cell_size)
        max_cell_y = math.floor(vmaxy / cell_size)
        visible_spaces = []
        seen_ids = set()
        for cell_x in range(min_cell_x, max_cell_x + 1):
            for cell_y in range(min_cell_y, max_cell_y + 1):
                for space in spatial_grid.get((cell_x, cell_y), ()):
                    space_id = id(space)
                    if space_id not in seen_ids:
                        seen_ids.add(space_id)
                        visible_spaces.append(space)
    else:
        visible_spaces = parking_spaces

    for space in visible_spaces:
        min_x, min_y, max_x, max_y = space.bbox
        if max_x < vminx or min_x > vmaxx or max_y < vminy or min_y > vmaxy:
            continue
        points = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for x, y in space.points_m]
        pygame.draw.polygon(screen, (72, 75, 74), points)
        pygame.draw.lines(screen, (125, 128, 124), True, points, max(1, int(px_per_m * 0.12)))


def _draw_grass_texture_uncached(screen, camx: float, camy: float, px_per_m: float, screen_w: int, screen_h: int) -> None:
    import pygame

    global _grass_texture_tile
    if _grass_texture_tile is None:
        tile_size = 96
        _grass_texture_tile = pygame.Surface((tile_size, tile_size))
        _grass_texture_tile.fill((25, 80, 25))
        rng = random.Random(17)
        for _ in range(150):
            x = rng.randrange(tile_size)
            y = rng.randrange(tile_size)
            color = rng.choice(((35, 96, 31), (42, 105, 35), (20, 70, 24), (58, 112, 39)))
            pygame.draw.line(_grass_texture_tile, color, (x, y), (x + rng.choice((-1, 0, 1)), y - rng.randrange(1, 4)), 1)

    tile_width, tile_height = _grass_texture_tile.get_size()
    origin_x = screen_w // 2 - int(camx * px_per_m)
    origin_y = screen_h // 2 + int(camy * px_per_m)
    start_x = origin_x % tile_width - tile_width
    start_y = origin_y % tile_height - tile_height
    for x in range(start_x, screen_w, tile_width):
        for y in range(start_y, screen_h, tile_height):
            screen.blit(_grass_texture_tile, (x, y))


def draw_grass_texture(
    screen,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: Optional[int] = None,
    screen_h: Optional[int] = None,
    profiler=None,
) -> None:
    """Fill screen with a subtle repeating grass texture.

    Cached exactly like the other static layers (draw_scenery, draw_waters,
    ...): unlike them the tile pattern doesn't depend on any streamed world
    data, only on camera position and zoom, so it never needs
    invalidate_static_caches() - it only goes stale when the camera moves
    past the cache padding or the zoom changes. Was previously redrawn from
    scratch every frame via ~100+ individual small blits (one per 96px tile
    covering the screen); now that happens only on a cache miss, and most
    frames are a single blit of the cached surface.
    """
    import pygame

    if screen_w is None or screen_h is None:
        screen_w, screen_h = screen.get_size()
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        round(camx * cache_zoom / 128.0), round(camy * cache_zoom / 128.0),
        cache_zoom, (screen_w, screen_h),
    )
    if frame_cache_key == common._grass_frame_cache_key and common._grass_frame_cache_surface is not None:
        cached_camx, cached_camy = common._grass_frame_cache_camera
        screen.blit(
            common._grass_frame_cache_surface,
            (
                round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
                round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
            ),
        )
        return
    # A big camera jump (e.g. a debug respawn) can invalidate every static
    # layer's cache on the same frame; sharing the same one-rebuild-per-frame
    # throttle as the other five layers spreads that cost across several
    # frames instead of stalling on one.
    if _rebuild_or_stale(screen, "grass", common._grass_frame_cache_surface, common._grass_frame_cache_camera, camx, camy, cache_zoom):
        return

    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height))
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_grass_texture_uncached(cache_surface, camx, camy, cache_zoom, cache_width, cache_height)
    if profiler is not None:
        profiler.record("render:grass_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._grass_frame_cache_key = frame_cache_key
    common._grass_frame_cache_surface = cache_surface
    common._grass_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))
