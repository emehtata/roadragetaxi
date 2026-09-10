import concurrent.futures
import logging
import math
import multiprocessing
import threading
import time
from typing import List, Optional, Set, Tuple


from ..tile_streaming import TileCoord, active_tiles, tile_bbox, tile_changes, world_to_tile

logger = logging.getLogger(__name__)

from .models import (
    Way,
    Water,
    Curb,
    Building,
    ParkingSpace,
    Scenery,
    LogicalIntersection,
    TrafficLight,
    StopSign,
    YieldSign,
    Place,
    associate_places_with_buildings,
    Crossing,
    BusStop,
    SceneryObject,
    SpeedBump,
)

from .cache import (
    load_osm_cache,
)

from .overpass import (
    fetch_osm_ways,
)

from .build import (
    build_ways,
)

from .trees import (
    plant_trees,
)


def _snap_projected_bbox(
    bbox: Tuple[float, float, float, float], tile_size_m: float
) -> Tuple[float, float, float, float]:
    """Normalize auto-fetch bounds so nearby requests share one cache key."""
    step = max(1.0, tile_size_m)
    minx, miny, maxx, maxy = bbox
    return (
        math.floor(minx / step) * step,
        math.floor(miny / step) * step,
        math.ceil(maxx / step) * step,
        math.ceil(maxy / step) * step,
    )


def _map_object_key(obj) -> tuple:
    """Return a stable key for deduplicating overlapping auto-fetch results."""
    object_id = getattr(obj, "osm_id", None)
    if object_id is None:
        object_id = getattr(obj, "id", None)
    if object_id is None:
        # LogicalIntersection has neither osm_id/id nor points_m/x/y, so it
        # fell through to the final (name, kind, x, y) fallback below - all
        # None/0.0 for every instance, colliding every intersection after
        # the first onto one key and silently dropping the rest on later
        # tile merges.
        object_id = getattr(obj, "intersection_id", None)
    if object_id is not None:
        return (type(obj).__name__, "id", object_id)

    points = getattr(obj, "points_m", None)
    if points:
        bbox = getattr(obj, "bbox", None)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            shape = tuple(round(value, 1) for value in bbox)
        else:
            shape = tuple(round(value, 1) for point in (points[0], points[-1]) for value in point)
        return (type(obj).__name__, getattr(obj, "kind", None), getattr(obj, "name", None), shape, len(points))

    return (
        type(obj).__name__,
        getattr(obj, "name", None),
        getattr(obj, "kind", None),
        round(getattr(obj, "x", 0.0), 1),
        round(getattr(obj, "y", 0.0), 1),
    )


DEFAULT_TILE_MEMORY_BUDGET_MB = 768.0
# Without /proc (no live memory reading available), fall back to a hard
# ceiling on how many inactive tiles can stay resident, so behavior is still
# bounded rather than growing without limit.
MAX_INACTIVE_RESIDENT_TILES = 80
# How many oldest-inactive tiles to unload per over-budget check. Freeing
# memory back to the OS after dropping references isn't instant/guaranteed
# (CPython's allocator often keeps it in its own free lists), so re-checking
# memory after every single tile would be false precision; a fixed batch
# makes steady progress and self-corrects over a few more tile transitions
# if pressure persists.
INACTIVE_TILE_EVICTION_BATCH = 6
# Minimum time a tile must have sat inactive before it's even a candidate
# for eviction - independent of memory pressure. A long real play session
# routinely already sits over tile_memory_budget_mb just from everything
# else loaded (pygame, the rest of the process, a big already-streamed
# world), so without this floor a tile became eligible the instant it left
# the active window: a player driving one tile over and immediately back
# (a very common "quick look, then return" movement) evicted the tile they
# just left before they had any chance to return to it, forcing a real
# re-fetch and re-merge on the way back - defeating the entire point of
# keeping recently-left tiles resident (see _evict_inactive_tiles).
MIN_INACTIVE_S_BEFORE_EVICTION = 20.0


def _current_process_memory_mb() -> Optional[float]:
    """Best-effort *current* resident memory for this process, in MB.

    Reads /proc/self/status on Linux - a live figure, unlike
    resource.getrusage()'s ru_maxrss, which is a high-water mark that never
    drops even after memory is freed, making it useless for noticing
    pressure has eased off. Returns None on platforms without /proc (e.g.
    Windows, macOS) so callers fall back to a proxy heuristic (resident
    tile count) instead of taking on a dependency like psutil just for this.
    """
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def _extend_unique(target: list, new_items: list) -> int:
    known = {_map_object_key(item) for item in target}
    unique_items = [item for item in new_items if _map_object_key(item) not in known]
    target.extend(unique_items)
    return len(unique_items)


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
        traffic_lights: Optional[List[TrafficLight]] = None,
        stop_signs: Optional[List[StopSign]] = None,
        crossings: Optional[List[Crossing]] = None,
        bus_stops: Optional[List[BusStop]] = None,
        parking_spaces: Optional[List[ParkingSpace]] = None,
        logical_intersections: Optional[List[LogicalIntersection]] = None,
        yield_signs: Optional[List[YieldSign]] = None,
        curbs: Optional[List[Curb]] = None,
        scenery_objects: Optional[List[SceneryObject]] = None,
        speed_bumps: Optional[List[SpeedBump]] = None,
        fetch_func=fetch_osm_ways,
        build_func=build_ways,
        cooldown_s: float = 5.0,
        build_in_process: bool = False,
        world_cache_manager=None,
        tile_memory_budget_mb: float = DEFAULT_TILE_MEMORY_BUDGET_MB,
    ):
        self.ways = ways
        self.waters = waters if waters is not None else []
        self.buildings = buildings if buildings is not None else []
        self.sceneries = sceneries if sceneries is not None else []
        self.places = places if places is not None else []
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.stop_signs = stop_signs if stop_signs is not None else []
        self.crossings = crossings if crossings is not None else []
        self.bus_stops = bus_stops if bus_stops is not None else []
        self.parking_spaces = parking_spaces if parking_spaces is not None else []
        self.logical_intersections = logical_intersections if logical_intersections is not None else []
        self.yield_signs = yield_signs if yield_signs is not None else []
        self.curbs = curbs if curbs is not None else []
        self.scenery_objects = scenery_objects if scenery_objects is not None else []
        self.speed_bumps = speed_bumps if speed_bumps is not None else []
        self.bounds = bounds
        self.transformer = transformer
        self.fetch_func = fetch_func
        self.build_func = build_func
        self.cooldown_s = cooldown_s
        self.build_in_process = build_in_process
        self.world_cache_manager = world_cache_manager
        self._build_executor = None
        self.lock = threading.Lock()
        self.is_fetching = False
        self.fetch_progress = 0.0
        self.last_fetch_time = 0.0
        self.last_trigger_reason = ""
        self._last_edge_check_time = 0.0
        self._edge_check_interval_s = 0.1
        self._attempted_endpoints: Set[Tuple[int, str]] = set()
        self._completed_fetch_targets: Set[Tuple[float, float, float, float]] = set()
        self._endpoint_connection_cache: dict[tuple[int, int, int], bool] = {}
        self.player_tile: Optional[TileCoord] = None
        self.start_tile: Optional[TileCoord] = None
        self.active_tiles: set[TileCoord] = set()
        self.loaded_tiles: set[TileCoord] = set()
        self.pending_tiles: set[TileCoord] = set()
        self._completed_tile_batches: list[list[tuple[TileCoord, object]]] = []
        self._tile_retry_after = 0.0
        self.map_revision = 0
        self.last_tile_load_ms = 0.0
        self.last_tile_integration_ms = 0.0
        self.last_tile_unload_ms = 0.0
        self._tile_objects: dict[TileCoord, dict[str, dict[tuple, object]]] = {}
        self._object_tiles: dict[str, dict[tuple, set[TileCoord]]] = {}
        # Tiles that left the active window but aren't unloaded yet - kept
        # resident (map_revision-cheap on their own, since staying loaded
        # touches nothing) so a player who immediately doubles back doesn't
        # force a re-fetch, and so the actual unload cost is only paid when
        # memory pressure (or, without /proc, a hard tile-count ceiling)
        # says it's worth it. Value is the time.monotonic() the tile went
        # inactive, for oldest-first eviction.
        self._inactive_tile_since: dict[TileCoord, float] = {}
        self.tile_memory_budget_mb = tile_memory_budget_mb
        self.last_process_memory_mb: Optional[float] = None
        # Load known dead-end boundaries from disk cache
        self.dead_ends: List[dict] = []

    def get_bounds(self) -> Tuple[float, float, float, float]:
        with self.lock:
            return self.bounds

    def get_progress(self) -> float:
        with self.lock:
            return self.fetch_progress

    def get_fetching(self) -> bool:
        with self.lock:
            return self.is_fetching

    def get_trigger_reason(self) -> str:
        with self.lock:
            return self.last_trigger_reason

    def get_map_revision(self) -> int:
        with self.lock:
            return self.map_revision

    def get_tile_metrics(self) -> dict[str, object]:
        with self.lock:
            relative_tile = None
            if self.player_tile is not None and self.start_tile is not None:
                relative_tile = TileCoord(
                    self.player_tile.x - self.start_tile.x,
                    self.player_tile.y - self.start_tile.y,
                )
            return {
                "player_tile": self.player_tile,
                "relative_tile": relative_tile,
                "tiles_in_memory": len(self.loaded_tiles),
                "tiles_pending": len(self.pending_tiles),
                "tiles_inactive_resident": len(self._inactive_tile_since),
                "process_memory_mb": self.last_process_memory_mb,
                "tile_load_ms": self.last_tile_load_ms,
                "tile_integration_ms": self.last_tile_integration_ms,
                "tile_unload_ms": self.last_tile_unload_ms,
            }

    def update_player_tile(
        self, x: float, y: float,
    ) -> Optional[tuple[TileCoord, set[TileCoord], set[TileCoord]]]:
        """Return tile additions/removals only when the player changes tile."""
        current_tile = world_to_tile(x, y)
        with self.lock:
            if self.start_tile is None:
                self.start_tile = current_tile
            if current_tile == self.player_tile:
                return None
            previous_tiles = self.active_tiles
            current_tiles = set(active_tiles(current_tile))
            added, removed = tile_changes(previous_tiles, current_tiles)
            self.player_tile = current_tile
            self.active_tiles = current_tiles
            return current_tile, added, removed

    def start_tile_streaming(self, x: float, y: float) -> bool:
        """Load newly required tiles in a background thread."""
        previous_player_tile = self.player_tile
        transition = self.update_player_tile(x, y)
        with self.lock:
            if transition is not None:
                _, _, removed = transition
                now = time.monotonic()
                for tile in removed:
                    self._inactive_tile_since.setdefault(tile, now)
                # A tile that's active again (the player came right back)
                # is no longer an eviction candidate.
                for tile in self.active_tiles:
                    self._inactive_tile_since.pop(tile, None)
                unload_started = time.perf_counter()
                self._evict_inactive_tiles(now)
                self.last_tile_unload_ms = (time.perf_counter() - unload_started) * 1000.0
            missing = self.active_tiles - self.loaded_tiles - self.pending_tiles
            wall_time = time.time()
            if (
                not missing
                or self.is_fetching
                or time.monotonic() < self._tile_retry_after
                # Crossing tiles quickly (driving fast) used to fire a new
                # Overpass request the instant the previous one finished,
                # with nothing else pacing them - fast enough to get an IP
                # rate-limited/blocked by public endpoints. The still-missing
                # tiles just wait for the next call once the cooldown clears.
                or wall_time - self.last_fetch_time < self.cooldown_s
            ):
                return False
            self.pending_tiles.update(missing)
            self.is_fetching = True
            self.fetch_progress = 0.0
            self.last_fetch_time = wall_time
            request_tiles = set(self.active_tiles)
            current_tile = self.player_tile
            if previous_player_tile is not None and current_tile is not None:
                delta_x = current_tile.x - previous_player_tile.x
                delta_y = current_tile.y - previous_player_tile.y
                if delta_x and not delta_y:
                    # +sign(delta_x): the genuinely new leading column, not
                    # the trailing one - it was `-` here, which kept only
                    # already-loaded columns and silently skipped querying
                    # the new column's territory at all on every straight
                    # cardinal move (the common case while driving).
                    edge_x = current_tile.x + (1 if delta_x > 0 else -1)
                    request_tiles = {
                        tile for tile in request_tiles
                        if tile.x in {current_tile.x, edge_x}
                    }
                elif delta_y and not delta_x:
                    edge_y = current_tile.y + (1 if delta_y > 0 else -1)
                    request_tiles = {
                        tile for tile in request_tiles
                        if tile.y in {current_tile.y, edge_y}
                    }
            request_tiles = tuple(sorted(request_tiles))
            logger.info(
                "Tile streaming transition: player_tile=%s missing=%d request_tiles=%d bbox_world=%s",
                self.player_tile,
                len(missing),
                len(request_tiles),
                self._tiles_bbox(request_tiles),
            )
        threading.Thread(
            target=self._background_tile_fetch,
            args=(tuple(sorted(missing)), request_tiles),
            daemon=True,
        ).start()
        return True

    def start_initial_tile_streaming(self) -> bool:
        """Fetch missing tiles for the initial active 3x3 region once."""
        with self.lock:
            missing = self.active_tiles - self.loaded_tiles - self.pending_tiles
            if not missing or self.is_fetching:
                return False
            self.pending_tiles.update(missing)
            self.is_fetching = True
            self.fetch_progress = 0.0
            request_tiles = tuple(sorted(self.active_tiles))
            logger.info(
                "Initial tile streaming: missing=%d request_tiles=%d bbox_world=%s",
                len(missing),
                len(request_tiles),
                self._tiles_bbox(request_tiles),
            )
        threading.Thread(
            target=self._background_tile_fetch,
            args=(tuple(sorted(missing)), request_tiles),
            daemon=True,
        ).start()
        return True

    @staticmethod
    def _tiles_bbox(tiles: tuple[TileCoord, ...]) -> tuple[float, float, float, float]:
        boxes = [tile_bbox(tile) for tile in tiles]
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ) if boxes else (0.0, 0.0, 0.0, 0.0)

    def initialize_player_tile(self, x: float, y: float) -> TileCoord:
        """Seed tile tracking from the already loaded startup world."""
        current_tile = world_to_tile(x, y)
        with self.lock:
            self.player_tile = current_tile
            self.start_tile = current_tile
            self.active_tiles = set(active_tiles(current_tile))
            self._register_existing_world()
            # Startup bbox is the complete active 1.5 km region.
            self.loaded_tiles = set(self.active_tiles)
            self._unload_tiles(set(self._tile_objects) - self.active_tiles)
        return current_tile

    def _register_existing_world(self) -> None:
        sections = {
            "ways": self.ways,
            "waters": self.waters,
            "buildings": self.buildings,
            "sceneries": self.sceneries,
            "places": self.places,
            "traffic_lights": self.traffic_lights,
            "crossings": self.crossings,
            "bus_stops": self.bus_stops,
            "parking_spaces": self.parking_spaces,
            "logical_intersections": self.logical_intersections,
            "stop_signs": self.stop_signs,
            "yield_signs": self.yield_signs,
            "curbs": self.curbs,
            "scenery_objects": self.scenery_objects,
            "speed_bumps": self.speed_bumps,
        }
        for section, objects in sections.items():
            for item in objects:
                key = _map_object_key(item)
                owners = self._object_tiles.setdefault(section, {}).setdefault(key, set())
                for tile in self._item_tiles(item):
                    owners.add(tile)
                    self._tile_objects.setdefault(tile, {}).setdefault(section, {})[key] = item

    @staticmethod
    def _item_tiles(item) -> set[TileCoord]:
        bbox = getattr(item, "bbox", None)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            min_x, min_y, max_x, max_y = bbox
        elif hasattr(item, "x") and hasattr(item, "y"):
            min_x = max_x = item.x
            min_y = max_y = item.y
        elif getattr(item, "center", None) is not None:
            # LogicalIntersection: no bbox/x/y/points_m, so this used to
            # fall through to the points_m branch below, get an empty
            # tuple, and return set() - meaning owned_tiles was *always*
            # empty for it in the real (non-force_tile) tile-streaming
            # merge path, so every logical intersection from every
            # streamed tile was silently dropped, unconditionally.
            cx, cy = item.center
            radius = getattr(item, "radius_m", 0.0) or 0.0
            min_x, max_x = cx - radius, cx + radius
            min_y, max_y = cy - radius, cy + radius
        else:
            points = getattr(item, "points_m", ())
            if not points:
                return set()
            min_x = min(point[0] for point in points)
            min_y = min(point[1] for point in points)
            max_x = max(point[0] for point in points)
            max_y = max(point[1] for point in points)
        first = world_to_tile(min_x, min_y)
        last = world_to_tile(max_x, max_y)
        return {
            TileCoord(tile_x, tile_y)
            for tile_x in range(first.x, last.x + 1)
            for tile_y in range(first.y, last.y + 1)
        }

    def _background_tile_fetch(
        self,
        tiles: tuple[TileCoord, ...],
        request_tiles: tuple[TileCoord, ...],
    ) -> None:
        loaded = []
        load_started = time.perf_counter()
        try:
            min_x = min(tile_bbox(tile)[0] for tile in request_tiles)
            min_y = min(tile_bbox(tile)[1] for tile in request_tiles)
            max_x = max(tile_bbox(tile)[2] for tile in request_tiles)
            max_y = max(tile_bbox(tile)[3] for tile in request_tiles)
            lon1, lat1 = self.transformer.transform(min_x, min_y)
            lon2, lat2 = self.transformer.transform(max_x, max_y)
            bbox = (min(lat1, lat2), min(lon1, lon2), max(lat1, lat2), max(lon1, lon2))
            if self.world_cache_manager is not None:
                world = self.world_cache_manager.preload_region(bbox).result()
            else:
                world = self.build_func(self.fetch_func(bbox))
            loaded.append((tiles, request_tiles, world))
            with self.lock:
                self.fetch_progress = 1.0
            load_ms = (time.perf_counter() - load_started) * 1000.0

            with self.lock:
                self._completed_tile_batches.append(loaded)
                self.last_tile_load_ms = load_ms
                self.is_fetching = False
                self.fetch_progress = 1.0
                logger.info(
                    "Tile streaming loaded: tiles=%d ways=%d load_ms=%.1f",
                    len(tiles),
                    len(world.ways),
                    load_ms,
                )
        except Exception as exc:
            logger.warning("Tile streaming failed: %s", exc)
            with self.lock:
                for tile in tiles:
                    self.pending_tiles.discard(tile)
                self._tile_retry_after = time.monotonic() + 1.0
                self.is_fetching = False
                self.fetch_progress = 0.0

    def integrate_completed_tiles(self, max_tiles: int = 1) -> int:
        """Integrate a bounded number of background tile results per frame."""
        with self.lock:
            batches = self._completed_tile_batches
            self._completed_tile_batches = []
            active_tiles_now = set(self.active_tiles)
        if not batches:
            return 0
        started = time.perf_counter()
        integrated = 0
        with self.lock:
            remaining = max(1, max_tiles)
            for batch in batches:
                for tile_group, request_tiles, world in batch:
                    self.pending_tiles.difference_update(tile_group)
                    active_group = set(tile_group) & active_tiles_now
                    if not active_group or remaining <= 0:
                        continue
                    ownership_tiles = set(request_tiles) & active_tiles_now
                    self._merge_tile_world_for_tiles(ownership_tiles, world)
                    self.loaded_tiles.update(active_group)
                    integrated += len(active_group)
                    remaining -= 1
            if integrated:
                self.map_revision += 1
                logger.info(
                    "Tile integration complete: integrated_tiles=%d ways=%d map_revision=%d",
                    integrated,
                    len(self.ways),
                    self.map_revision,
                )
            self.last_tile_integration_ms = (time.perf_counter() - started) * 1000.0
        return integrated

    def _merge_tile_world_for(self, tile: TileCoord, world) -> None:
        self._merge_tile_world_for_tiles({tile}, world, force_tile=True)

    def _merge_tile_world_for_tiles(
        self, tiles: set[TileCoord], world, force_tile: bool = False,
    ) -> None:
        sections = {
            "ways": self.ways,
            "waters": self.waters,
            "buildings": self.buildings,
            "sceneries": self.sceneries,
            "places": self.places,
            "traffic_lights": self.traffic_lights,
            "crossings": self.crossings,
            "bus_stops": self.bus_stops,
            "parking_spaces": self.parking_spaces,
            "logical_intersections": self.logical_intersections,
            "stop_signs": self.stop_signs,
            "yield_signs": self.yield_signs,
            "curbs": self.curbs,
            "scenery_objects": self.scenery_objects,
            "speed_bumps": self.speed_bumps,
        }
        for section, target in sections.items():
            new_items = getattr(world, section, ())
            if not new_items:
                continue
            # _object_tiles[section] already tracks exactly the set of keys
            # currently present in `target` (kept in lockstep by this method
            # and _unload_tiles), so it doubles as an O(1) "is this key
            # already known" membership test. Previously this rebuilt a
            # fresh key set from the *entire* existing target list on every
            # call - for the "ways"/"buildings" sections that cost grows
            # with how much of the map is already loaded, not with how much
            # is actually new, so it got slower the longer a play session
            # ran and turned every tile merge (main.py calls this on the
            # main thread) into a longer stall the more of the map was
            # already streamed in.
            section_owners = self._object_tiles.setdefault(section, {})
            for item in new_items:
                key = _map_object_key(item)
                owned_tiles = tiles if force_tile else self._item_tiles(item) & tiles
                if not owned_tiles:
                    continue
                for tile in owned_tiles:
                    self._tile_objects.setdefault(tile, {}).setdefault(section, {})[key] = item
                owners = section_owners.get(key)
                is_new_key = owners is None
                if is_new_key:
                    owners = set()
                    section_owners[key] = owners
                owners.update(owned_tiles)
                if is_new_key:
                    target.append(item)
        world_bounds = getattr(world, "bounds", None)
        if world_bounds and world_bounds != (0.0, 0.0, 0.0, 0.0):
            self.bounds = (
                min(self.bounds[0], world_bounds[0]),
                min(self.bounds[1], world_bounds[1]),
                max(self.bounds[2], world_bounds[2]),
                max(self.bounds[3], world_bounds[3]),
            )
        associate_places_with_buildings(self.buildings, self.places)

    def _unload_tiles(self, tiles: set[TileCoord]) -> None:
        if not tiles:
            return
        sections = {
            "ways": self.ways,
            "waters": self.waters,
            "buildings": self.buildings,
            "sceneries": self.sceneries,
            "places": self.places,
            "traffic_lights": self.traffic_lights,
            "crossings": self.crossings,
            "bus_stops": self.bus_stops,
            "parking_spaces": self.parking_spaces,
            "logical_intersections": self.logical_intersections,
            "stop_signs": self.stop_signs,
            "yield_signs": self.yield_signs,
            "curbs": self.curbs,
            "scenery_objects": self.scenery_objects,
            "speed_bumps": self.speed_bumps,
        }
        # Collect every key actually losing its last owner across *all*
        # unloading tiles first, then filter each section's list once at the
        # end. Rebuilding a section's list per removed key (as this used to
        # do) was O(total items in that section) *per key*, so unloading a
        # single tile's worth of exclusively-owned objects in an
        # already-large, well-explored world turned into the same kind of
        # multi-second stall as the tree/road-merge amortization bugs fixed
        # earlier - this is the tile-streaming equivalent of that.
        keys_to_remove: dict[str, set] = {}
        any_removed = False
        for tile in tiles:
            tile_objects = self._tile_objects.pop(tile, {})
            self.loaded_tiles.discard(tile)
            for section, objects in tile_objects.items():
                owners_by_key = self._object_tiles.get(section, {})
                for key in objects:
                    owners = owners_by_key.get(key, set())
                    owners.discard(tile)
                    if owners:
                        continue
                    owners_by_key.pop(key, None)
                    keys_to_remove.setdefault(section, set()).add(key)
            if tile_objects:
                any_removed = True
                self.map_revision += 1
        for section, keys in keys_to_remove.items():
            target = sections[section]
            target[:] = [item for item in target if _map_object_key(item) not in keys]
        if any_removed:
            associate_places_with_buildings(self.buildings, self.places)

    def _evict_inactive_tiles(self, now: float) -> None:
        """Unload resident-but-inactive tiles once memory pressure - or,
        where live memory can't be read, a hard tile-count ceiling - says
        it's worth paying the cost, rather than the instant a tile leaves
        the active window. A player who doubles right back finds it still
        loaded (no re-fetch), and the actual unload cost only lands when it
        buys something back.

        That "doubles right back" guarantee needs every tile to survive at
        least MIN_INACTIVE_S_BEFORE_EVICTION regardless of memory pressure:
        a long real session routinely already sits over budget just from
        everything else loaded, so without this floor "should_evict" is
        true essentially always, and a tile became a candidate the instant
        it went inactive - evicting the one tile a quick there-and-back
        move needs kept, before the player ever got a chance to return.
        """
        if not self._inactive_tile_since:
            return
        memory_mb = _current_process_memory_mb()
        if memory_mb is not None:
            self.last_process_memory_mb = memory_mb
            should_evict = memory_mb > self.tile_memory_budget_mb
        else:
            should_evict = len(self._inactive_tile_since) > MAX_INACTIVE_RESIDENT_TILES
        if not should_evict:
            return
        eligible = [
            tile for tile, since in self._inactive_tile_since.items()
            if now - since >= MIN_INACTIVE_S_BEFORE_EVICTION
        ]
        if not eligible:
            return
        oldest_first = sorted(eligible, key=self._inactive_tile_since.get)
        to_evict = set(oldest_first[:INACTIVE_TILE_EVICTION_BATCH])
        for tile in to_evict:
            self._inactive_tile_since.pop(tile, None)
        self._unload_tiles(to_evict)

    def is_known_dead_end(self, car_x: float, car_y: float, direction: str, tolerance_m: float = 300.0) -> bool:
        """Check if vehicle is near a recorded dead-end in the given expansion direction."""
        for entry in self.dead_ends:
            if entry.get("direction") == direction:
                dx = entry.get("x", 0.0) - car_x
                dy = entry.get("y", 0.0) - car_y
                if (dx * dx + dy * dy) ** 0.5 < tolerance_m:
                    return True
        return False

    def _nearest_way_endpoint(self, car_x: float, car_y: float, max_distance: float) -> Optional[Way]:
        """Find the closest drivable road with an endpoint near the car."""
        nearest_way = None
        nearest_distance = max_distance
        for way in self.ways:
            if not getattr(way, "is_drivable", False) or len(way.points_m) < 2:
                continue
            endpoint_distance = min(
                math.hypot(car_x - way.points_m[0][0], car_y - way.points_m[0][1]),
                math.hypot(car_x - way.points_m[-1][0], car_y - way.points_m[-1][1]),
            )
            if endpoint_distance <= nearest_distance:
                nearest_way = way
                nearest_distance = endpoint_distance
        return nearest_way

    def get_endpoint_fetch_audit(
        self,
        car,
        margin_m: float,
        tile_size_m: float,
        current_way: Optional[Way] = None,
    ) -> dict:
        """Return the road-endpoint fetch decision inputs for runtime diagnostics."""
        with self.lock:
            lookahead_m = min(
                tile_size_m * 0.5,
                max(margin_m, max(0.0, car.speed) * 8.0),
            )
            endpoint_way = current_way or self._nearest_way_endpoint(car.x, car.y, lookahead_m)
            if endpoint_way is None or len(endpoint_way.points_m) < 2:
                return {"status": "no_nearby_drivable_endpoint", "lookahead_m": lookahead_m}

            endpoint_candidates = (
                (endpoint_way.points_m[0], endpoint_way.points_m[1]),
                (endpoint_way.points_m[-1], endpoint_way.points_m[-2]),
            )
            endpoint, previous = min(
                endpoint_candidates,
                key=lambda candidate: math.hypot(car.x - candidate[0][0], car.y - candidate[0][1]),
            )
            endpoint_distance = math.hypot(car.x - endpoint[0], car.y - endpoint[1])
            approach_x = endpoint[0] - previous[0]
            approach_y = endpoint[1] - previous[1]
            approach_length = math.hypot(approach_x, approach_y)
            heading_alignment = (
                (math.cos(car.heading) * approach_x + math.sin(car.heading) * approach_y) / approach_length
                if approach_length > 0.0 else -1.0
            )
            endpoint_index = 0 if endpoint is endpoint_way.points_m[0] else -1
            cache_key = (id(endpoint_way), endpoint_index, len(self.ways))
            connected = self._endpoint_connection_cache.get(cache_key)
            if connected is None:
                connected = any(
                    other is not endpoint_way
                    and getattr(other, "is_drivable", False)
                    and any(
                        math.hypot(endpoint[0] - point[0], endpoint[1] - point[1])
                        <= max(12.0, endpoint_way.half_width_m + getattr(other, "half_width_m", 3.0))
                        for point in getattr(other, "points_m", ())
                    )
                    for other in self.ways
                )
                self._endpoint_connection_cache[cache_key] = connected
            direction = "east" if abs(approach_x) >= abs(approach_y) and approach_x >= 0 else "west"
            if abs(approach_y) > abs(approach_x):
                direction = "north" if approach_y >= 0 else "south"
            endpoint_key = (id(endpoint_way), direction)
            return {
                "status": "evaluated",
                "way": {
                    "osm_id": endpoint_way.osm_id,
                    "highway": endpoint_way.highway,
                    "name": endpoint_way.name,
                },
                "endpoint": list(endpoint),
                "endpoint_distance_m": endpoint_distance,
                "lookahead_m": lookahead_m,
                "heading_alignment": heading_alignment,
                "connected_to_drivable_road": connected,
                "already_attempted": endpoint_key in self._attempted_endpoints,
                "known_dead_end": self.is_known_dead_end(car.x, car.y, direction),
            }

    def start_if_needed(
        self,
        car,
        auto_fetch: bool,
        margin_m: float,
        tile_size_m: float,
        current_way: Optional[Way] = None,
    ) -> bool:
        if not auto_fetch:
            return False
        with self.lock:
            now = time.monotonic()
            if now - self._last_edge_check_time < self._edge_check_interval_s:
                return False
            self._last_edge_check_time = now
            if self.is_fetching:
                return False
            wall_time = time.time()
            if wall_time - self.last_fetch_time < self.cooldown_s:
                return False

            minx, miny, maxx, maxy = self.bounds
            expanded = False
            trigger_reason = ""
            # Expand in the direction the car is approaching or heading
            fetch_minx, fetch_miny, fetch_maxx, fetch_maxy = minx, miny, maxx, maxy
            direction = ""

            # Determine expansion boxes centered around car's position with overlap into existing area
            half_span = tile_size_m / 2.0
            overlap = max(margin_m, 500.0)
            lookahead_m = min(
                half_span,
                max(margin_m, max(0.0, car.speed) * 8.0),
            )
            ahead_x = car.x + math.cos(car.heading) * lookahead_m
            ahead_y = car.y + math.sin(car.heading) * lookahead_m

            if car.x < minx + margin_m or ahead_x < minx + margin_m:
                direction = "west"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - tile_size_m
                    fetch_maxx = car.x + overlap
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True
                    trigger_reason = "bbox west edge"
            elif car.x > maxx - margin_m or ahead_x > maxx - margin_m:
                direction = "east"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - overlap
                    fetch_maxx = car.x + tile_size_m
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True
                    trigger_reason = "bbox east edge"

            if not expanded:
                if car.y < miny + margin_m or ahead_y < miny + margin_m:
                    direction = "south"
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_miny = car.y - tile_size_m
                        fetch_maxy = car.y + overlap
                        fetch_minx = car.x - half_span
                        fetch_maxx = car.x + half_span
                        expanded = True
                        trigger_reason = "bbox south edge"

            if not expanded and (car.y > maxy - margin_m or ahead_y > maxy - margin_m):
                direction = "north"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_miny = car.y - overlap
                    fetch_maxy = car.y + tile_size_m
                    fetch_minx = car.x - half_span
                    fetch_maxx = car.x + half_span
                    expanded = True
                    trigger_reason = "bbox north edge"

            endpoint_way = current_way or self._nearest_way_endpoint(car.x, car.y, lookahead_m)
            if not expanded and endpoint_way is not None and len(endpoint_way.points_m) >= 2:
                endpoint_candidates = (
                    (endpoint_way.points_m[0], endpoint_way.points_m[1]),
                    (endpoint_way.points_m[-1], endpoint_way.points_m[-2]),
                )
                endpoint, previous = min(
                    endpoint_candidates,
                    key=lambda candidate: math.hypot(car.x - candidate[0][0], car.y - candidate[0][1]),
                )
                endpoint_distance = math.hypot(car.x - endpoint[0], car.y - endpoint[1])
                approach_x = endpoint[0] - previous[0]
                approach_y = endpoint[1] - previous[1]
                approach_length = math.hypot(approach_x, approach_y)
                heading_alignment = (
                    (math.cos(car.heading) * approach_x + math.sin(car.heading) * approach_y) / approach_length
                    if approach_length > 0.0 else -1.0
                )
                endpoint_index = 0 if endpoint is endpoint_way.points_m[0] else -1
                cache_key = (id(endpoint_way), endpoint_index, len(self.ways))
                connected = self._endpoint_connection_cache.get(cache_key)
                if connected is None:
                    connected = any(
                        other is not endpoint_way
                        and getattr(other, "is_drivable", False)
                        and any(
                            math.hypot(endpoint[0] - point[0], endpoint[1] - point[1])
                            <= max(12.0, endpoint_way.half_width_m + getattr(other, "half_width_m", 3.0))
                            for point in getattr(other, "points_m", ())
                        )
                        for other in self.ways
                    )
                    self._endpoint_connection_cache[cache_key] = connected
                direction = "east" if abs(approach_x) >= abs(approach_y) and approach_x >= 0 else "west"
                if abs(approach_y) > abs(approach_x):
                    direction = "north" if approach_y >= 0 else "south"
                endpoint_key = (id(endpoint_way), direction)
                if (
                    endpoint_distance <= lookahead_m
                    and not connected
                    and heading_alignment > 0.2
                    and endpoint_key not in self._attempted_endpoints
                ):
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_minx = car.x - (tile_size_m if approach_x < 0 else overlap)
                        fetch_maxx = car.x + (tile_size_m if approach_x >= 0 else overlap)
                        fetch_miny = car.y - (tile_size_m if approach_y < 0 else overlap)
                        fetch_maxy = car.y + (tile_size_m if approach_y >= 0 else overlap)
                        expanded = True
                        trigger_reason = "road endpoint"
                        self._attempted_endpoints.add((id(endpoint_way), direction))

            if not expanded:
                return False

            fetch_bbox = (fetch_minx, fetch_miny, fetch_maxx, fetch_maxy)
            target = _snap_projected_bbox(fetch_bbox, tile_size_m)
            if target in self._completed_fetch_targets:
                return False
            self.is_fetching = True
            self.fetch_progress = 0.1
            self.last_fetch_time = wall_time
            self.last_trigger_reason = trigger_reason
            car_pos = (car.x, car.y)

        t = threading.Thread(
            target=self._background_fetch,
            args=(fetch_bbox, direction, car_pos, target),
            daemon=True,
        )
        t.start()
        return True

    def _background_fetch(
        self,
        fetch_bbox: Tuple[float, float, float, float],
        direction: str = "",
        car_pos: Tuple[float, float] = (0.0, 0.0),
        target_bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        if target_bbox is None:
            target_bbox = fetch_bbox
        new_minx, new_miny, new_maxx, new_maxy = fetch_bbox
        try:
            lon1, lat1 = self.transformer.transform(new_minx, new_miny)
            lon2, lat2 = self.transformer.transform(new_maxx, new_maxy)
            car_lon, car_lat = self.transformer.transform(car_pos[0], car_pos[1])
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

        try:
            with self.lock:
                self.fetch_progress = 0.25
            area_bbox = (south, west, north, east)
            if self.world_cache_manager is not None:
                target_minx, target_miny, target_maxx, target_maxy = target_bbox
                target_lon1, target_lat1 = self.transformer.transform(target_minx, target_miny)
                target_lon2, target_lat2 = self.transformer.transform(target_maxx, target_maxy)
                target_bbox_ll = (
                    min(target_lat1, target_lat2),
                    min(target_lon1, target_lon2),
                    max(target_lat1, target_lat2),
                    max(target_lon1, target_lon2),
                )
                area_id = self.world_cache_manager.area_id(target_bbox_ll)
                res = self.world_cache_manager.preload(area_id, target_bbox_ll).result()
                elems = None
            else:
                elems = load_osm_cache(area_bbox, point=(car_lat, car_lon))
                if elems is None:
                    logger.info("Auto-fetch cache miss at car point (%.6f, %.6f); requesting network", car_lat, car_lon)
                    elems = self.fetch_func(area_bbox)
                else:
                    logger.info("Auto-fetch cache hit at car point (%.6f, %.6f); network skipped", car_lat, car_lon)
            with self.lock:
                self.fetch_progress = 0.65
            if self.world_cache_manager is None:
                if self.build_in_process:
                    context = multiprocessing.get_context("spawn")
                    try:
                        if self._build_executor is None:
                            self._build_executor = concurrent.futures.ProcessPoolExecutor(
                                max_workers=1, mp_context=context
                            )
                        res = self._build_executor.submit(self.build_func, elems).result()
                    except (concurrent.futures.process.BrokenProcessPool, OSError) as exc:
                        logger.warning("Auto-fetch process build failed; retrying in background thread: %s", exc)
                        if self._build_executor is not None:
                            self._build_executor.shutdown(wait=False, cancel_futures=True)
                            self._build_executor = None
                        res = self.build_func(elems)
                else:
                    res = self.build_func(elems)
            with self.lock:
                self.fetch_progress = 0.9
            new_crossings = getattr(res, "crossings", [])
            new_stop_signs = getattr(res, "stop_signs", [])
            new_bus_stops = getattr(res, "bus_stops", [])
            new_parking_spaces = getattr(res, "parking_spaces", [])
            new_logical_intersections = getattr(res, "logical_intersections", [])
            new_yield_signs = getattr(res, "yield_signs", [])
            new_curbs = getattr(res, "curbs", [])
            new_scenery_objects = getattr(res, "scenery_objects", [])
            new_speed_bumps = getattr(res, "speed_bumps", [])
            if len(res) == 8:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds, new_traffic_lights, new_crossings = res
            elif len(res) == 7:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds, new_traffic_lights = res
            elif len(res) == 6:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds = res
                new_traffic_lights = getattr(res, "traffic_lights", [])
            elif len(res) == 5:
                new_ways, new_waters, new_buildings, new_sceneries, new_bounds = res
                new_places, new_traffic_lights = [], []
            elif len(res) == 3:
                new_ways, new_waters, new_bounds = res
                new_buildings, new_sceneries, new_places, new_traffic_lights = [], [], [], []
            else:
                new_ways, new_bounds = res[0], res[-1]
                new_waters, new_buildings, new_sceneries, new_places, new_traffic_lights = [], [], [], [], []

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
                with self.lock:
                    self.dead_ends.append(entry)

            with self.lock:
                known_way_ids = {
                    way.osm_id for way in self.ways if getattr(way, "osm_id", None) is not None
                }
                unique_new_ways = [
                    way for way in new_ways
                    if way.osm_id is None or way.osm_id not in known_way_ids
                ]
                plant_trees(new_sceneries, self.ways + unique_new_ways)
                self.ways.extend(unique_new_ways)
                added_waters = _extend_unique(self.waters, new_waters)
                added_buildings = _extend_unique(self.buildings, new_buildings)
                added_sceneries = _extend_unique(self.sceneries, new_sceneries)
                added_places = _extend_unique(self.places, new_places)
                associate_places_with_buildings(self.buildings, self.places)
                added_traffic_lights = _extend_unique(self.traffic_lights, new_traffic_lights)
                added_stop_signs = _extend_unique(self.stop_signs, new_stop_signs)
                added_crossings = _extend_unique(self.crossings, new_crossings)
                added_bus_stops = _extend_unique(self.bus_stops, new_bus_stops)
                added_parking_spaces = _extend_unique(self.parking_spaces, new_parking_spaces)
                _extend_unique(self.logical_intersections, new_logical_intersections)
                _extend_unique(self.yield_signs, new_yield_signs)
                _extend_unique(self.curbs, new_curbs)
                _extend_unique(self.scenery_objects, new_scenery_objects)
                _extend_unique(self.speed_bumps, new_speed_bumps)
                minx = min(self.bounds[0], new_bounds[0])
                miny = min(self.bounds[1], new_bounds[1])
                maxx = max(self.bounds[2], new_bounds[2])
                maxy = max(self.bounds[3], new_bounds[3])
                self.bounds = (minx, miny, maxx, maxy)
                self.last_fetch_time = time.time()
                self._completed_fetch_targets.add(target_bbox)

            # Rebuilding the segment index can be expensive; keep the game loop
            # responsive while the background fetch finishes indexing new roads.
            with self.lock:
                self.fetch_progress = 1.0
                self.is_fetching = False
            logger.info(
                "Auto-fetched and added %d ways, %d waters, %d buildings, %d scenery, %d places, %d traffic lights, %d crossings; new bounds: %s",
                len(unique_new_ways),
                added_waters,
                added_buildings,
                added_sceneries,
                added_places,
                added_traffic_lights,
                added_crossings,
                self.bounds,
            )
        except Exception as e:
            logger.warning("Auto-fetch failed: %s", e)
            with self.lock:
                self.is_fetching = False
                self.fetch_progress = 0.0

    def shutdown(self) -> None:
        """Stop the persistent map-building worker, if it was started."""
        if self._build_executor is not None:
            self._build_executor.shutdown(wait=False, cancel_futures=True)
            self._build_executor = None
