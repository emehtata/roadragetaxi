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
from ..geo import clip_polygon_to_rect, point_in_polygon
import math
import random
import time
from typing import List, Optional, Tuple


from ..osm import Scenery, SceneryObject, Way, classify_tree_kind
from ..physics import is_point_on_road


SCENERY_COLORS = {
    # Natural / green (osm/build.py: leisure=*, landuse=*, or natural in
    # wood/scrub/grass/sand/heath all become a Scenery, kind = that raw
    # OSM value) - counts below are from a real regional extract (Oulu),
    # ranked so the frequent ones got picked first. Colors below are
    # calibrated against real aerial/satellite imagery, not an idealized
    # "map app" green - actual tree canopy, mown lawn, and dry scrubland
    # all look meaningfully different from directly overhead.
    "forest": (40, 78, 42),  # dense canopy - darker and less saturated than clean green; individual crowns and shadow gaps mute it
    "wood": (40, 78, 42),
    "scrub": (108, 120, 78),  # low bushes/heath scrub - a dry yellow-olive, not a dark green
    "heath": (136, 124, 92),  # moorland - muted brown-tan, heather's bloom is seasonal, its base cover isn't green
    "park": (100, 145, 80),  # mown lawn + scattered trees - brighter and more yellow than forest canopy
    "garden": (104, 150, 86),
    "meadow": (152, 160, 92),  # unmown grass/wildflowers - lighter and more yellow-green than a maintained lawn
    "grass": (112, 150, 86),
    "greenfield": (150, 165, 110),
    "nature_reserve": (62, 102, 56),
    "pitch": (80, 150, 64),  # maintained turf is more saturated than an ordinary lawn
    "playground": (150, 138, 104),  # rubber/wood-chip soft-fall surfacing, not grass
    "dog_park": (100, 142, 82),
    "track": (176, 96, 70),  # a real running track is a rubberized red/terracotta oval, not grass
    "sand": (196, 180, 130),
    "beach": (206, 192, 150),
    "grassland": (146, 158, 96),  # unmanaged wild grass - between "meadow" and "scrub", more olive than a mown lawn
    "shrubbery": (100, 118, 76),  # planted/ornamental shrubs - denser and greener than open scrub
    "wetland": (118, 130, 96),  # marsh/reed cover - muted olive-green, wetter and duller than dry heath
    # Farmed / cultivated - warm, dry tones, not park-green.
    "farmland": (172, 148, 88),
    "farmyard": (146, 130, 100),
    "allotments": (142, 132, 82),
    "flowerbed": (150, 90, 120),
    "greenhouse_horticulture": (208, 210, 202),  # glass/plastic-roofed greenhouse clusters read as bright pale grey-white from above, not green
    # Built-up zoning - muted, not green (these are usually mostly covered
    # by buildings/roads drawn on top; the fill only shows through gaps).
    # residential is the exception - a muted grass green, since
    # yards/verges are what actually shows through the gaps there.
    "residential": (108, 138, 92),
    "commercial": (112, 108, 104),  # neutral grey, not tinted purple - real commercial-zone roofscapes are grey/brown, not colorful
    "retail": (118, 104, 96),
    "industrial": (98, 96, 94),
    "institutional": (108, 104, 96),
    "education": (108, 104, 96),
    "civil": (108, 104, 96),
    "religious": (98, 94, 86),
    "military": (98, 102, 82),
    "railway": (108, 100, 92),  # matches the ballast bed color under the tracks themselves (render/roads.py:RAILWAY_BALLAST_COLOR)
    "recreation_ground": (98, 142, 78),
    # Bare ground / disturbed land.
    "brownfield": (142, 122, 96),
    "construction": (170, 142, 96),
    "quarry": (130, 124, 116),  # exposed rock/stone - grey, not tan
    "landfill": (112, 102, 82),
    "cemetery": (88, 112, 82),  # mown grass between headstones - green, but muted
    # Water-adjacent leisure (the water body itself is a separate Water,
    # not Scenery - this is the surrounding shore/facility ground).
    "marina": (132, 130, 122),  # dock/pavement grey - the water itself is already drawn separately, this shouldn't also look blue
    "slipway": (132, 130, 122),
    "bathing_place": (152, 168, 128),
    "swimming_pool": (68, 165, 185),  # a real pool is a saturated turquoise-cyan, not a muted blue-grey
    # Sports/recreation facilities without their own building footprint.
    "sports_centre": (122, 110, 94),
    "sports_hall": (122, 110, 94),
    "fitness_centre": (122, 110, 94),
    "fitness_station": (98, 142, 78),
    "stadium": (122, 110, 94),
    "ice_rink": (204, 216, 222),  # outdoor ice - pale blue-white, brighter than the old grey-blue
    "horse_riding": (152, 132, 92),
    "firepit": (100, 90, 70),
    "outdoor_seating": (112, 102, 92),
    "sauna": (112, 92, 72),
    "parking": (98, 98, 98),  # plain asphalt grey, no green/blue tint
    "fuel": (92, 88, 84),  # paved forecourt - close to parking's grey, slightly warmer
}
# Kinds that read as visibly grainy/textured ground in real aerial imagery -
# tree canopy, mown/unmown grass, tilled soil, loose sand - as opposed to
# the flat, mostly-building-covered zoning kinds (commercial, industrial,
# ...) or small point-like facilities, where a speckle texture would just
# be wasted cost under something else drawn on top. See
# _scenery_speckle_positions/_draw_scenery_uncached: same generalized
# procedural-noise idea as _grass_texture_tile - a jittered grid of dots -
# but drawn directly (no intermediate Surface/mask/tile-blit machinery:
# tried that first, and it made cost scale with either polygon *count*
# (many small per-polygon Surfaces) or distinct-color count times the
# *whole visible area* (one shared full-viewport Surface per color) -
# either way a real fps drop, confirmed by benchmarking both against a
# realistic many-small-polygons scene). Direct dot draws instead bound
# cost to each polygon's own (already viewport-clipped) area, the same
# way the flat fill itself is bounded - and tinted from each kind's own
# SCENERY_COLORS entry instead of a hand-picked palette per kind.
_SPECKLE_SCENERY_KINDS = frozenset({
    "forest", "wood", "scrub", "heath", "park", "garden", "meadow", "grass",
    "greenfield", "nature_reserve", "recreation_ground", "dog_park",
    "fitness_station", "cemetery", "farmland", "farmyard", "allotments",
    "sand", "beach", "grassland", "shrubbery", "wetland",
})
_SPECKLE_SPACING_M = 1.3  # world-space grid spacing between candidate dots
_SPECKLE_INSET = 0.15  # keep jitter off the exact cell edge, avoids a visible grid line
_SPECKLE_JITTER_SPAN = 0.7
_SPECKLE_MIN_PX_PER_M = 2.0  # below this the dots would be sub-pixel noise, not texture - skip entirely
# Total speckle dots per *rebuild*, shared across every textured polygon on
# screen - not a per-polygon cap. A per-polygon-only budget still let cost
# scale with polygon count: a real area can have hundreds of small
# textured parcels at once, each individually well under any reasonable
# per-polygon cap, but tens of thousands of world_to_screen+draw.circle
# calls combined - confirmed as the actual cause of a real fps drop by
# benchmarking a many-small-polygons scene. Sharing one budget across the
# whole rebuild means many small polygons simply divide up the same
# fixed total instead of each drawing their own full share on top.
_SPECKLE_GLOBAL_BUDGET = 2200


def _speckle_color(base: Tuple[int, int, int], variant: float) -> Tuple[int, int, int]:
    """A brightness-jittered variant of a base color - the same noise idea
    _grass_texture_tile uses, generalized to work from any kind's own
    color instead of a hand-picked per-kind palette."""
    factor = 0.72 + variant * 0.56
    return tuple(max(0, min(255, int(channel * factor))) for channel in base)


def _grid_hash(seed: int, gx: int, gy: int) -> int:
    """Cheap deterministic hash of (seed, gx, gy) - one call yields enough
    mixed bits for both jitter axes and the color variant (see
    _scenery_speckle_positions), instead of three separate calls. Used
    instead of constructing a fresh random.Random() per grid cell - a
    textured scenery polygon can cover hundreds of cells, and even a
    single extra Python function call per cell measurably adds up over a
    whole rebuild's worth of them."""
    h = (seed * 1000003 + gx) & 0xFFFFFFFF
    h = (h * 1000003 + gy) & 0xFFFFFFFF
    return h


def _scenery_speckle_positions(
    points_m: List[Tuple[float, float]], seed: int,
    vminx: float, vminy: float, vmaxx: float, vmaxy: float,
    max_points: int,
) -> List[Tuple[float, float, float]]:
    """World-space speckle positions for one scenery polygon, capped at
    max_points (the caller passes whatever's left of the shared per-
    rebuild _SPECKLE_GLOBAL_BUDGET - see _draw_scenery_uncached).

    The scan grid is bounded to the *intersection* of this polygon's own
    bbox and the viewport - not the polygon's full extent - so a small
    parcel only ever scans its own small area, and (this is the part
    that actually matters for a large polygon under 40 points, so never
    run through draw_scenery's own clip_polygon_to_rect) a polygon that
    extends well past the visible area doesn't waste the whole scan on
    its invisible part before ever reaching the visible one.

    When the intersected area has more grid cells than max_points, a 2D
    stride subsamples the *whole* scan range evenly rather than capping
    after the first N cells found in raster order - capping by early-
    return instead of striding was a real bug: for a polygon bigger than
    what's on screen, "first N cells" can be entirely the off-screen band
    before the visible region even starts, silently drawing zero dots
    despite "succeeding" (no error, no count-zero warning - just an
    invisible no-op every rebuild).

    Seeded from the scenery's own geometry, not the viewport (stable
    across cache rebuilds and camera pans - the same real-world spot
    always lands on the same candidate point, unlike a per-rebuild random
    draw, which would make the texture visibly reshuffle itself every
    time the camera moves)."""
    if max_points <= 0:
        return []
    xs = [p[0] for p in points_m]
    ys = [p[1] for p in points_m]
    minx = max(min(xs), vminx)
    maxx = min(max(xs), vmaxx)
    miny = max(min(ys), vminy)
    maxy = min(max(ys), vmaxy)
    if minx >= maxx or miny >= maxy:
        return []
    spacing = _SPECKLE_SPACING_M
    start_gx = int(minx // spacing)
    end_gx = int(maxx // spacing) + 1
    start_gy = int(miny // spacing)
    end_gy = int(maxy // spacing) + 1
    cols = max(1, end_gx - start_gx)
    rows = max(1, end_gy - start_gy)
    total_cells = cols * rows
    stride = 1
    if total_cells > max_points:
        stride = max(1, math.ceil(math.sqrt(total_cells / max_points)))
    points: List[Tuple[float, float, float]] = []
    for gx in range(start_gx, end_gx, stride):
        for gy in range(start_gy, end_gy, stride):
            h = _grid_hash(seed, gx, gy)
            jx = (h & 0xFFF) / 4095.0
            jy = ((h >> 12) & 0xFFF) / 4095.0
            x = gx * spacing + (_SPECKLE_INSET + jx * _SPECKLE_JITTER_SPAN) * spacing
            y = gy * spacing + (_SPECKLE_INSET + jy * _SPECKLE_JITTER_SPAN) * spacing
            if point_in_polygon(x, y, points_m):
                variant = ((h >> 24) & 0xFF) / 255.0
                points.append((x, y, variant))
                if len(points) >= max_points:
                    return points
    return points


TREE_CROWN_COLORS = ((25, 78, 29), (34, 101, 35), (48, 119, 42), (63, 112, 34))
# Finland's three dominant forest trees (see osm/trees.py:classify_tree_kind
# for how a tree gets assigned one) - distinguished by crown color/size only
# (_draw_trees_uncached), not by silhouette: straight overhead, a standing
# tree's own canopy hides its trunk and any species-specific outline
# completely, so every kind draws as the same irregular circle blob
# (_irregular_crown_points), just a different palette. trunk_color is still
# used for a *fallen* tree (drawn lying down, trunk visible - see
# draw_trees' docstring) - BIRCH_TRUNK_COLOR whitish, spruce/pine brown.
TREE_CROWN_PALETTES = {
    "spruce": ((14, 54, 20), (18, 64, 24), (24, 76, 30)),
    "pine": ((88, 108, 42), (102, 122, 50), (118, 136, 60)),
    "birch": TREE_CROWN_COLORS,
}
BIRCH_TRUNK_COLOR = (222, 218, 206)
# How far outside the tight viewport a fallen/shaking tree still counts
# as "could affect what's on screen" (see draw_trees below). Must safely
# exceed the static tree cache's own effective padding
# (CACHE_PADDING_PX / cache_zoom, in meters) at every zoom level so a
# tree this check calls "not nearby" is also genuinely outside the
# region a cache rebuild would actually draw - at the lowest zoom the
# game allows (~2.9 px/m), that's already ~77m; 150m keeps a comfortable
# margin above that without needing to import CACHE_PADDING_PX and
# recompute it here.
_TREE_EFFECT_NEARBY_PADDING_M = 150.0
_TREE_CROWN_POINTS = 8
_TREE_CROWN_JITTER = (0.78, 1.15)  # radius multiplier range - a perfect
# circle/cone/ellipse reads as a diagram, not foliage; a straight-down
# view of a real canopy is an irregular blob, not a precise geometric
# shape.


def _irregular_crown_points(cx: float, cy: float, radius: float, seed) -> List[Tuple[int, int]]:
    """Deterministic, position-seeded blob approximating a circle - looks
    like foliage seen from directly above, and (seeded from the tree's own
    world position, not anything per-frame/per-rebuild) draws the exact
    same shape every time this tree is on screen, not a new random blob
    each cache rebuild."""
    rng = random.Random(seed)
    points = []
    for i in range(_TREE_CROWN_POINTS):
        angle = (2.0 * math.pi * i) / _TREE_CROWN_POINTS + rng.uniform(-0.2, 0.2)
        r = radius * rng.uniform(*_TREE_CROWN_JITTER)
        points.append((int(cx + math.cos(angle) * r), int(cy + math.sin(angle) * r)))
    return points
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
        *common._phased_cache_grid_cell("scenery", camx, camy, cache_zoom),
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

    # See draw_buildings' identical margin fix for the full reasoning: a
    # rebuild always re-queries with the *current* camera position, so it
    # catches a huge scenery polygon (a whole forest) astride the edge
    # just as correctly with a small margin as a large one - the margin
    # only needs to cover the between-rebuilds camera drift
    # (CACHE_PADDING_PX/px_per_m, ~11m at a typical zoom), not the
    # polygon's own size. 80m was selecting and filling thousands of
    # scenery polygons tens of meters past anything the cache could ever
    # show before its next rebuild - a real "culprit: rendering" cost.
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 20.0)

    visible_sceneries = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else sceneries
    )
    show_speckles = px_per_m >= _SPECKLE_MIN_PX_PER_M
    dot_radius = max(1, round(px_per_m * 0.1))
    speckle_budget = _SPECKLE_GLOBAL_BUDGET
    for sc in visible_sceneries:
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(sc.points_m) < 3:
            continue
        points_m = sc.points_m
        # Same fix as draw_waters: a real forest/farmland relation's bbox
        # can span tens of kilometers while only a handful of its points
        # are ever near the camera - pygame.draw.polygon's fill cost scales
        # with how far off-surface the points run, not with what's actually
        # visible, so a huge, mostly-off-screen ring can cost hundreds of
        # ms per rebuild despite drawing nothing. Clip in world space first.
        if len(points_m) > 40:
            points_m = clip_polygon_to_rect(points_m, vminx, vminy, vmaxx, vmaxy)
            if len(points_m) < 3:
                continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in points_m]
        kind = sc.kind.lower()
        color = SCENERY_COLORS.get(kind, (38, 105, 38))
        pygame.draw.polygon(screen, color, pts)
        if show_speckles and kind in _SPECKLE_SCENERY_KINDS and speckle_budget > 0:
            seed = hash(bb) if bb else hash(points_m[0])
            speckles = _scenery_speckle_positions(points_m, seed, vminx, vminy, vmaxx, vmaxy, speckle_budget)
            speckle_budget -= len(speckles)
            for wx, wy, variant in speckles:
                sx, sy = world_to_screen(wx, wy, camx, camy, px_per_m, screen_w, screen_h)
                pygame.draw.circle(screen, _speckle_color(color, variant), (sx, sy), dot_radius)


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
            CONSTRUCTION_FENCE_COLOR, thickness, vminx, vminy, vmaxx, vmaxy,
            dash_m=_FENCE_DASH_M, gap_m=_FENCE_GAP_M,
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

    But only when one of them is actually near enough to be visible.
    taxi.py's fallen_trees only ever grows (a knocked-over tree stays
    fallen for the rest of the session, never removed) and tree_effects
    keeps a fallen tree's entry forever too (its own cleanup explicitly
    skips deleting one) - so treating *any* entry anywhere in the whole
    loaded map as a reason to go uncached, as this used to, meant one
    single tree falling anywhere permanently disabled the tree cache for
    the rest of the session: every frame from then on paid a full live
    redraw of every visible tree (confirmed via a real drive: avg
    render:trees cost jumped from ~0.7ms to ~7ms/frame, sustained for
    4800+ consecutive frames after the first fall, never recovering).
    Each effect carries its own world position (see taxi.py's
    check_tree_collision) precisely so this can check that instead.
    """
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    if tree_effects or fallen_trees:
        vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(
            camx, camy, px_per_m, screen_w, screen_h, _TREE_EFFECT_NEARBY_PADDING_M
        )

        def _effect_is_near(effect) -> bool:
            ex, ey = effect.get("x"), effect.get("y")
            # No stored position - can't verify, so stay conservative and
            # treat it as visible rather than risk rendering it wrong.
            return ex is None or ey is None or (vminx <= ex <= vmaxx and vminy <= ey <= vmaxy)

        affected_nearby = any(_effect_is_near(effect) for effect in (tree_effects or {}).values())
        if not affected_nearby and fallen_trees:
            # A fallen tree's effect entry is never deleted (see above), so
            # this should always already be covered by tree_effects - but
            # fall back to checking fallen_trees' own keys directly in case
            # that invariant is ever broken elsewhere.
            affected_nearby = any(
                _effect_is_near((tree_effects or {}).get(key, {})) for key in fallen_trees
            )
        if affected_nearby:
            _draw_trees_uncached(
                screen, sceneries, camx, camy, px_per_m, screen_w, screen_h,
                tree_effects, fallen_trees, spatial_grid, ways, road_spatial_grid,
            )
            return

    frame_cache_key = (
        id(sceneries), len(sceneries), id(sceneries[-1]) if sceneries else None,
        id(ways), id(spatial_grid), id(road_spatial_grid),
        *common._phased_cache_grid_cell("trees", camx, camy, cache_zoom),
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
            tree_kinds = getattr(sc, "tree_kinds", ())
            kind = (
                tree_kinds[tree_index] if tree_index < len(tree_kinds)
                # Scenery cached before tree_kinds existed - classify on the
                # fly (no tags to go on, same as any other untagged tree)
                # rather than leave it stuck as the old one-shape-fits-all
                # look until the area happens to get re-fetched.
                else classify_tree_kind({}, tree_x, tree_y)
            )
            size = 0.72 + variation * 0.62
            trunk = max(1, int(0.7 * size * px_per_m))
            crown = max(2, int((1.9 if kind == "pine" else 2.2) * size * px_per_m))
            if kind == "birch":
                trunk_color = BIRCH_TRUNK_COLOR
            elif kind == "pine":
                trunk_color = (112 + int(20 * variation), 70 + int(14 * variation), 36)
            else:
                trunk_color = (78 + int(22 * variation), 52 + int(18 * variation), 27)
            palette = TREE_CROWN_PALETTES.get(kind, TREE_CROWN_COLORS)
            crown_color = palette[min(len(palette) - 1, int(variation * len(palette)))]
            if tree_key in (fallen_trees or set()):
                fall_heading = effect.get("angle", 0.0)
                fall_x = sx + math.cos(fall_heading) * 3.2 * px_per_m
                fall_y = sy - math.sin(fall_heading) * 3.2 * px_per_m
                pygame.draw.line(screen, trunk_color, (sx, sy), (fall_x, fall_y), max(2, trunk))
                pygame.draw.circle(screen, crown_color, (int(fall_x), int(fall_y)), crown)
            else:
                # Straight overhead, a standing tree's own canopy hides its
                # trunk completely - no rect/silhouette drawn here, just the
                # irregular crown blob centered on the tree's actual position.
                seed = hash((round(tree_x, 2), round(tree_y, 2)))
                pygame.draw.polygon(screen, crown_color, _irregular_crown_points(sx, sy, crown, seed))
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
    "picnic_table": (135, 95, 55),
    "firepit": (60, 58, 55),
    "fountain": (90, 165, 185),
    "fuel": (185, 90, 60),
    "gate": (100, 92, 80),
    "bollard": (48, 48, 46),
}
_STATUE_PEDESTAL_COLOR = (110, 110, 105)
_FIREPIT_FLAME_COLOR = (216, 120, 40)
_FOUNTAIN_SPRAY_COLOR = (220, 240, 245)


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
    baskets, bicycle parking, statues/memorials, picnic tables, firepits,
    fountains, fuel stations, gates, bollards - as simple primitive
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
        *common._phased_cache_grid_cell("scenery_objects", camx, camy, cache_zoom),
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
        elif obj.kind == "picnic_table":
            width = max(2, int(1.6 * px_per_m))
            depth = max(2, int(0.9 * px_per_m))
            pygame.draw.rect(screen, SCENERY_OBJECT_COLORS["picnic_table"], (sx - width // 2, sy - depth // 2, width, depth))
        elif obj.kind == "firepit":
            radius = max(2, int(0.5 * px_per_m))
            pygame.draw.circle(screen, SCENERY_OBJECT_COLORS["firepit"], (sx, sy), radius, max(1, radius // 3))
            pygame.draw.circle(screen, _FIREPIT_FLAME_COLOR, (sx, sy), max(1, radius // 2))
        elif obj.kind == "fountain":
            radius = max(2, int(0.7 * px_per_m))
            pygame.draw.circle(screen, SCENERY_OBJECT_COLORS["fountain"], (sx, sy), radius)
            pygame.draw.circle(screen, _FOUNTAIN_SPRAY_COLOR, (sx, sy), max(1, radius // 3))
        elif obj.kind == "fuel":
            width = max(2, int(0.6 * px_per_m))
            height = max(3, int(1.1 * px_per_m))
            pygame.draw.rect(screen, SCENERY_OBJECT_COLORS["fuel"], (sx - width // 2, sy - height, width, height))
        elif obj.kind == "gate":
            half_len = max(2, int(1.0 * px_per_m))
            pygame.draw.line(screen, SCENERY_OBJECT_COLORS["gate"], (sx - half_len, sy), (sx + half_len, sy), max(1, int(px_per_m * 0.15)))
        elif obj.kind == "bollard":
            radius = max(1, int(0.25 * px_per_m))
            pygame.draw.circle(screen, SCENERY_OBJECT_COLORS["bollard"], (sx, sy), radius)


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
        *common._phased_cache_grid_cell("grass", camx, camy, cache_zoom),
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
