"""Live map expansion on the server (main()'s auto-fetch + map sync).

As the taxi nears the loaded map's edge the AutoFetchManager streams the
neighbouring tiles in the background and merges them into the world's lists
(budgeted per tick). Once a merge settles, the world's derived structures
are brought up to date in main()'s order - grids, taxi, traffic and
pedestrian graphs, level structures - each stage resumable and budgeted
like Pygame's, so a tick never stalls for long. Then the street lights of
the new area are placed and the map chunks rebuilt; the server resends the
chunks that changed.
"""

from __future__ import annotations

import logging
import time

from ..main import _level_structures
from ..osm import TILE_MERGE_BUDGET_S, remove_trees_under_roads_steps
from ..performance import MAP_SYNC_BUDGET_S
from ..render import generate_detached_house_parking_chunk

logger = logging.getLogger(__name__)


def map_sync_steps(world):
    """main()'s map_sync_stage 1..14 as one generator: each `yield` is a
    point where the tick may stop (its budget spent) and resume later. The
    old structures keep serving until each stage's new one is complete."""
    w = world
    for _ in remove_trees_under_roads_steps(w.sceneries, w.ways):
        yield
    w.taxi_mgr.invalidate_tree_collision_index()
    w.spatial_grid.start_rebuild(w.ways)
    while not w.spatial_grid.advance_rebuild(MAP_SYNC_BUDGET_S):
        yield
    index = 0
    while index < len(w.buildings):
        index, _ = generate_detached_house_parking_chunk(w.buildings, w.ways, w.parking_spaces, w.spatial_grid,
                                                         index, MAP_SYNC_BUDGET_S)
        yield
    w.building_grid.rebuild(w.buildings)
    yield
    w.scenery_grid.rebuild(w.sceneries)
    w.street_lamps[:] = [obj for obj in w.scenery_objects if obj.kind == "street_lamp"]
    w.street_lamp_grid.rebuild(w.street_lamps)
    yield
    for grid, items in ((w.water_grid, w.waters), (w.crossing_grid, w.crossings), (w.curb_grid, w.curbs),
                        (w.railway_grid, w.railways), (w.railing_grid, w.railings),
                        (w.traffic_light_grid, w.traffic_lights)):
        grid.rebuild(items)
        yield
    if getattr(w, "railway_mgr", None) is not None:
        w.railway_mgr.rebuild(w.railways)
    with w.auto_fetch_manager.lock:
        w.auto_fetch_manager._attempted_endpoints.clear()
    w.taxi_mgr.sync_map_data(w.ways, places=w.places, buildings=w.buildings)
    yield
    w.traffic_mgr.start_map_sync(
        w.ways, traffic_lights=w.traffic_lights, stop_signs=w.stop_signs, crossings=w.crossings,
        buildings=w.buildings, sceneries=w.sceneries, parking_spaces=w.parking_spaces,
        logical_intersections=w.logical_intersections,
    )
    while not w.traffic_mgr.advance_map_sync(MAP_SYNC_BUDGET_S):
        yield
    w.pedestrian_mgr.start_incremental_sync(
        w.ways, traffic_lights=w.traffic_lights, logical_intersections=w.logical_intersections,
        venue_buildings=w.buildings, scenery_features=(w.scenery_objects, w.sceneries, w.bus_stops),
    )
    while not w.pedestrian_mgr.advance_incremental_sync(MAP_SYNC_BUDGET_S):
        yield
    rebuilt = _level_structures(w.ways, w.level_ways, w.level_connectors)
    w.level_roads = rebuilt["level_roads"]
    w.level_transitions.topologies = rebuilt["level_transitions"].topologies
    w.level_routes = rebuilt["level_routes"]


class MapStreamer:
    """Per tick: merge streamed tiles, ask for more near the edge, and run
    the map sync when a merge has settled. `on_synced(new_bounds)` is
    called once a sync completes, with the area that grew."""

    def __init__(self, world, on_synced) -> None:
        self.world = world
        self.manager = world.auto_fetch_manager
        self.manager.soft_boundary_enabled = True
        self.on_synced = on_synced
        self._synced_revision = self.manager.get_map_revision()
        self._synced_bounds = self.manager.get_bounds()
        self._sync = None
        self._sync_revision = None
        self.hold = False  # the server rebuilds its chunks from the synced world: no merges meanwhile

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

    def tick(self, x: float, y: float, vx: float, vy: float, budget_s: float = TILE_MERGE_BUDGET_S) -> None:
        manager = self.manager
        if self.hold:
            return
        manager.integrate_completed_tiles(budget_s=budget_s)
        if manager.start_tile_streaming(x, y, vx, vy):
            logger.info("Map streaming: tiles around (%.0f, %.0f), tile %s", x, y, manager.player_tile)
        if self._sync is None:
            busy = manager.get_tile_merge_metrics()["tile_merge_active"]
            if not busy and manager.get_map_revision() != self._synced_revision:
                self._sync_revision = manager.get_map_revision()
                self._sync = map_sync_steps(self.world)
                logger.info("Map sync started: revision %d, %d ways", self._sync_revision, len(self.world.ways))
            return
        deadline = time.perf_counter() + MAP_SYNC_BUDGET_S
        for _ in self._sync:
            if time.perf_counter() >= deadline:
                return
        self._sync = None
        self._synced_revision = self._sync_revision
        old, new = self._synced_bounds, manager.get_bounds()
        self._synced_bounds = new
        logger.info("Map sync complete: revision %d, bounds %s -> %s", self._synced_revision, old, new)
        self.on_synced(old, new)
