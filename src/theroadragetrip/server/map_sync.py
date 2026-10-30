"""Live map expansion on the server (auto-fetch + map sync).

As the taxi nears the loaded map's edge the AutoFetchManager streams the
neighbouring tiles in the background and merges them into the world's lists
(budgeted per tick). Once a merge settles, the world's derived structures
are brought up to date in order - grids, taxi, traffic and
pedestrian graphs, level structures - each stage resumable and budgeted,
so a tick never stalls for long. Then the street lights of
the new area are placed and the map chunks rebuilt; the server resends the
chunks that changed.
"""

from __future__ import annotations

import logging
import threading
import time

from ..world_loader import level_structures as _level_structures
from ..osm import TILE_MERGE_BUDGET_S, remove_trees_under_roads_steps
from ..performance import MAP_SYNC_BUDGET_S, MAP_SYNC_URGENT_BUDGET_S
from ..parking import generate_detached_house_parking_chunk
from ..physics import connected_drivable_ways
from ..level_transitions import close_garage_roads

logger = logging.getLogger(__name__)


CHUNK_INPUTS_READY = "chunk_inputs_ready"
# A settled merge waits SYNC_SETTLE_S, and while a tile fetch is in flight up
# to SYNC_WAIT_FOR_FETCH_S, before its sync starts: the lookahead tile is
# requested right after the core window or a moment later, as the car moves,
# and one sync then covers both - each is a whole-world rebuild, 1-2 s of work
# over 7-12 s of ticks.
SYNC_SETTLE_S = 1.0
SYNC_WAIT_FOR_FETCH_S = 3.0
INITIAL_PREPARE_TIMEOUT_S = 190.0


def prepare_initial_window(world, timeout_s: float = INITIAL_PREPARE_TIMEOUT_S, progress=None) -> dict[str, object]:
    """Finish a missing initial tile window before gameplay begins.

    Startup has no frame to protect, so doing the merge and one derived-data
    sync here is both faster and smoother than spreading the same work over
    the first playable seconds. Failure or timeout is non-fatal: the ordinary
    MapStreamer sees the still-missing tiles and continues in gameplay.
    """
    manager = world.auto_fetch_manager
    if progress is not None:
        progress("tiles")
    started = time.perf_counter()
    if not manager.start_initial_tile_streaming():
        return {"started": False, "integrated_tiles": 0, "elapsed_s": 0.0}

    logger.info("Cold-start map preparation started")
    deadline = started + timeout_s
    while manager.get_fetching() and time.perf_counter() < deadline:
        if progress is not None:
            progress("tiles", manager.get_progress_message())
        time.sleep(0.02)
    if manager.get_fetching():
        elapsed = time.perf_counter() - started
        logger.warning("Cold-start map preparation timed out after %.1f s; continuing in gameplay", elapsed)
        return {"started": True, "integrated_tiles": 0, "elapsed_s": elapsed, "timed_out": True}

    if progress is not None:
        progress("merging")
    integrated = manager.integrate_completed_tiles()
    if integrated:
        for _stage in map_sync_steps(world):
            if progress is not None:
                progress("indexes", _stage)
        # These changes are already reflected in the initial ChunkIndex built
        # after this function returns; a later runtime merge must not rebuild
        # them as if they were new.
        manager.take_dirty_areas()
    elapsed = time.perf_counter() - started
    logger.info(
        "Cold-start map preparation complete: integrated_tiles=%d elapsed=%.2f s",
        integrated, elapsed,
    )
    return {"started": True, "integrated_tiles": integrated, "elapsed_s": elapsed, "timed_out": False}


def map_sync_steps(world):
    """The map sync stages 1..14 as one generator: each `yield` is a
    point where the tick may stop (its budget spent) and resume later, and
    names the stage the slice just before it belonged to (MapStreamer adds
    up the time per stage). The old structures keep serving until each
    stage's new one is complete."""
    w = world
    close_garage_roads((*w.ways, *getattr(w, "level_ways", ())))
    for _ in remove_trees_under_roads_steps(w.sceneries, w.ways):
        yield "trees_under_roads"
    w.spatial_grid.start_rebuild(w.ways)
    while not w.spatial_grid.advance_rebuild(MAP_SYNC_BUDGET_S):
        yield "road_grid"
    index = 0
    while index < len(w.buildings):
        index, _ = generate_detached_house_parking_chunk(w.buildings, w.ways, w.parking_spaces, w.spatial_grid,
                                                         index, MAP_SYNC_BUDGET_S)
        yield "house_parking"
    for name, grid, items in (("building_grid", w.building_grid, w.buildings), ("scenery_grid", w.scenery_grid, w.sceneries)):
        grid.start_rebuild(items)
        while not grid.advance_rebuild(MAP_SYNC_BUDGET_S):
            yield name
        yield name
    w.street_lamps[:] = [obj for obj in w.scenery_objects if obj.kind == "street_lamp"]
    for grid, items in ((w.street_lamp_grid, w.street_lamps), (w.water_grid, w.waters),
                        (w.crossing_grid, w.crossings), (w.curb_grid, w.curbs),
                        (w.railway_grid, w.railways), (w.railing_grid, w.railings),
                        (w.traffic_light_grid, w.traffic_lights)):
        grid.start_rebuild(items)
        while not grid.advance_rebuild(MAP_SYNC_BUDGET_S):
            yield "small_grids"
        yield "small_grids"
    # Everything the map chunks are built from is final now (trees under the
    # new roads gone, house bays added, the street-lamp grid the lights are
    # placed from): MapStreamer starts the chunk rebuild here, while the
    # gameplay graphs below are still being brought up to date.
    if getattr(w, "arena_crowds", None) is not None:
        w.arena_crowds.sync_buildings(w.buildings)
    w.traffic_mgr.start_map_sync(
        w.ways, traffic_lights=w.traffic_lights, stop_signs=w.stop_signs, yield_signs=w.yield_signs, crossings=w.crossings,
        buildings=w.buildings, sceneries=w.sceneries, parking_spaces=w.parking_spaces,
        logical_intersections=w.logical_intersections,
    )
    yield CHUNK_INPUTS_READY
    if getattr(w, "railway_mgr", None) is not None:
        for _ in w.railway_mgr.rebuild_steps(w.railways):
            yield "railways"
    if getattr(w, "tram_mgr", None) is not None:
        w.tram_mgr.rebuild(w.railways)  # (the tram network: small, one step)
    yield "railways"
    with w.auto_fetch_manager.lock:
        w.auto_fetch_manager._attempted_endpoints.clear()
    # The taxi's road network is a whole-map graph search (~0.1-0.5 s in one
    # go): a worker thread, the tick yielding meanwhile, so no tick waits for it.
    found = {}
    ways = list(w.ways)
    search = threading.Thread(target=lambda: found.setdefault("ways", connected_drivable_ways(ways)),
                              name="taxi-roads", daemon=True)
    search.start()
    while search.is_alive():
        yield "taxi"
    w.taxi_mgr.sync_map_data(w.ways, places=w.places, buildings=w.buildings, connected=found.get("ways"))
    yield "taxi"
    while not w.traffic_mgr.advance_map_sync(MAP_SYNC_BUDGET_S):
        yield "traffic"
    w.pedestrian_mgr.start_incremental_sync(
        w.ways, traffic_lights=w.traffic_lights, logical_intersections=w.logical_intersections,
        venue_buildings=w.buildings, scenery_features=(w.scenery_objects, w.sceneries, w.bus_stops),
    )
    while not w.pedestrian_mgr.advance_incremental_sync(MAP_SYNC_BUDGET_S):
        yield "pedestrians"
    rebuilt = _level_structures(w.ways, w.level_ways, w.level_connectors)
    w.level_roads = rebuilt["level_roads"]
    w.level_transitions.topologies = rebuilt["level_transitions"].topologies
    w.level_transitions.entrances = rebuilt["level_transitions"].entrances
    w.level_routes = rebuilt["level_routes"]
    yield "level_structures"


class MapStreamer:
    """Per tick: merge streamed tiles, ask for more near the edge, and run
    the map sync when a merge has settled. `on_synced(old_bounds,
    new_bounds, dirty_areas)` is called once per sync, as soon as the chunk
    inputs are synced (CHUNK_INPUTS_READY; the gameplay graphs follow): the
    bounds before and after, and the area its merges changed (None:
    nothing)."""

    def __init__(self, world, on_synced) -> None:
        self.world = world
        self.manager = world.auto_fetch_manager
        self.manager.soft_boundary_enabled = True
        self.on_synced = on_synced
        self._synced_revision = self.manager.get_map_revision()
        self._synced_bounds = self.manager.get_bounds()
        self._sync = None
        self._sync_revision = None
        self._sync_started = 0.0
        self._merged_since = None  # when an unsynced merge settled (SYNC_WAIT_FOR_FETCH_S)
        self._sync_ticks = 0
        self._sync_dirty = None
        self.sync_tiles: set = set()  # the tiles loaded when the running (or last) sync started: what it covers
        self.sync_stage_ms: dict[str, float] = {}  # busy time per stage of the running (or last) sync
        self.last_sync = None  # (wall s, busy ms, ticks) of the last completed sync
        self.hold = False  # the server rebuilds its chunks from the synced world: no merges meanwhile

    def _report_growth(self) -> None:
        old, new = self._synced_bounds, self.manager.get_bounds()
        self._synced_bounds = new
        self.on_synced(old, new, self._sync_dirty)

    @property
    def syncing(self) -> bool:
        return self._sync is not None

    def status(self) -> str:
        """What the map is doing, for the client's loading sign: "" settled,
        "fetching" (tiles downloading or built), "merging", "syncing" (the
        world catching up) or "building" (the server rebuilding its chunks:
        `hold`)."""
        if self.hold:
            return "building"
        if self._sync is not None:
            return "syncing"
        if self.manager.get_tile_merge_metrics()["tile_merge_active"]:
            return "merging"
        if self.manager.get_fetching():
            return "fetching"
        if self.manager.get_map_revision() != self._synced_revision:
            return "merging"  # merged, the sync starts on the next tick
        return ""

    def tick(self, x: float, y: float, vx: float, vy: float, budget_s: float = TILE_MERGE_BUDGET_S,
             urgent: bool = False) -> None:
        """`urgent`: the map under the player is missing (MAP_SYNC_URGENT_BUDGET_S
        for the merge and the sync instead of the 4 ms caps)."""
        manager = self.manager
        if self.hold and self._sync is None:
            return
        if not self.hold:  # while the chunks are rebuilt the world stays as synced: no merges, no new fetches
            manager.integrate_completed_tiles(budget_s=MAP_SYNC_URGENT_BUDGET_S if urgent else budget_s)
            if manager.start_tile_streaming(x, y, vx, vy):
                logger.info("Map streaming: tiles around (%.0f, %.0f), tile %s", x, y, manager.player_tile)
        if self._sync is None:
            busy = manager.get_tile_merge_metrics()["tile_merge_active"]
            if not busy and manager.get_map_revision() != self._synced_revision:
                if self._merged_since is None:
                    self._merged_since = time.perf_counter()
                waited = time.perf_counter() - self._merged_since
                if not urgent and waited < SYNC_WAIT_FOR_FETCH_S and (waited < SYNC_SETTLE_S or manager.get_fetching()):
                    return
                self._merged_since = None
                self._sync_revision = manager.get_map_revision()
                self._sync = map_sync_steps(self.world)
                self._sync_dirty = manager.take_dirty_areas()  # what this sync's merges changed
                self.sync_tiles = set(manager.loaded_tiles)  # a tile merged from here on waits for the next sync
                self._sync_started = time.perf_counter()
                self._sync_ticks = 0
                self.sync_stage_ms = {}
                logger.info("Map sync started: revision %d, %d ways", self._sync_revision, len(self.world.ways))
            return
        self._sync_ticks += 1
        started = time.perf_counter()
        deadline = started + (MAP_SYNC_URGENT_BUDGET_S if urgent else MAP_SYNC_BUDGET_S)
        for stage in self._sync:
            now = time.perf_counter()
            self.sync_stage_ms[stage] = self.sync_stage_ms.get(stage, 0.0) + (now - started) * 1000.0
            started = now
            if stage == CHUNK_INPUTS_READY:
                self._report_growth()
            if now >= deadline:
                return
        self._sync = None
        if CHUNK_INPUTS_READY not in self.sync_stage_ms:
            self._report_growth()  # a sync without the marker still rebuilds the chunks, at its end
        self.sync_stage_ms.pop(CHUNK_INPUTS_READY, None)
        busy_ms = sum(self.sync_stage_ms.values())
        self.last_sync = (time.perf_counter() - self._sync_started, busy_ms, self._sync_ticks)
        logger.info("Map sync stages: %.1f s wall, %.0f ms busy over %d ticks: %s", self.last_sync[0], busy_ms,
                    self._sync_ticks, ", ".join(f"{name} {ms:.0f}" for name, ms in
                                                sorted(self.sync_stage_ms.items(), key=lambda item: -item[1])))
        self._synced_revision = self._sync_revision
        logger.info("Map sync complete: revision %d, bounds %s", self._synced_revision, self._synced_bounds)
