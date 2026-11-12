"""F3 (docs/specs/pr-findings-0.21.0b-0.md): drive the taxi along a real Oulu
motorway (VT4 past the city) through simulated map expansions, and check that
motorway through-traffic keeps spawning, never stands stuck beyond the F1 bound
and never vanishes in view without a retire reason.

Data: the bundled sample if it holds a motorway, else a cached OSM extract
covering OULU_MOTORWAY_BBOX, read (never written) from $RRT_OSM_CACHE_DIR or the
user's real OSM cache (conftest isolates XDG_CACHE_HOME). Without either the
test skips with the reason; it never passes silently."""
import gzip
import json
import math
import os
import random
import time
from pathlib import Path

import pytest

import theroadragetrip.npc as npc
from theroadragetrip.npc import NPCVehicleManager
from theroadragetrip.osm import build_ways
from theroadragetrip.osm.cache import load_local_sample
from theroadragetrip.physics import Car, SpatialWayGrid
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps

OULU_MOTORWAY_BBOX = (64.96, 25.42, 65.04, 25.62)  # south, west, north, east: VT4 (Pohjantie) past Oulu
SEED = 21
DT = 1.0 / 30.0
SPEED_MPS = 25.0  # 90 km/h, above MOTORWAY_SPAWN_MIN_SPEED_MPS
LOADED_HALF_M = 1500.0  # a streamed map area around the taxi
EXPANSIONS = 3
EXPANSION_EVERY_S = 35.0
DRIVE_S = EXPANSION_EVERY_S * (EXPANSIONS + 1)
DRIVE_M = SPEED_MPS * DRIVE_S + 200.0
ACTIVE_HALF_M, NEAR_HALF_M, VIEW_HALF = 700.0, 300.0, (160.0, 90.0)
# F1: stuck timeout, then NPC_THROUGH_STUCK_MAX_TICKS population ticks, then one more tick of slack.
STUCK_BOUND_S = npc.NPC_STUCK_TIMEOUT_S + (npc.NPC_THROUGH_STUCK_MAX_TICKS + 2) * npc.NPC_POPULATION_TICK_S


def _box(x, y, half_x, half_y=None):
    return (x - half_x, y - (half_x if half_y is None else half_y), x + half_x, y + (half_x if half_y is None else half_y))


def _inside(box, x, y):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _roads_only(elements):
    roads = [e for e in elements if e.get("type") == "way" and "highway" in e.get("tags", {})]
    needed = {node for way in roads for node in way.get("nodes", ())}
    return [e for e in elements if e.get("type") == "node" and e.get("id") in needed] + roads


def _real_osm_cache_dir():
    """The player's OSM cache under the real home (conftest points HOME/XDG at a temp dir)."""
    try:
        import pwd
        home = pwd.getpwuid(os.getuid()).pw_dir
    except (ImportError, KeyError):
        return Path(os.devnull)
    return Path(home) / ".cache" / "RoadRageTrip" / "osm_cache"


def _oulu_ways():
    sample = load_local_sample() or []
    if any(e.get("tags", {}).get("highway") == "motorway" for e in sample):
        return build_ways(_roads_only(sample)).ways, "bundled sample"
    cache_dir = Path(os.environ.get("RRT_OSM_CACHE_DIR") or _real_osm_cache_dir())
    for path in sorted(cache_dir.glob("bbox_*.json*")):
        try:
            south, west, north, east = (float(part.replace("m", "-").replace("p", "."))
                                        for part in path.name.split(".")[0].removeprefix("bbox_").split("_"))
        except ValueError:
            continue
        want = OULU_MOTORWAY_BBOX
        if south <= want[0] and west <= want[1] and north >= want[2] and east >= want[3]:
            with (gzip.open if path.suffix == ".gz" else open)(path, "rt", encoding="utf-8") as file:
                return build_ways(_roads_only(json.load(file)["elements"])).ways, f"cached extract {path.name}"
    pytest.skip(f"no Oulu motorway OSM data: the bundled sample has no highway=motorway and no cached "
                f"extract in {cache_dir} covers {OULU_MOTORWAY_BBOX} (set RRT_OSM_CACHE_DIR, or fetch it "
                f"once with theroadragetrip.osm.pbf_source.fetch_osm_ways_from_pbf(bbox) or Overpass)")


def _ways_in(ways, box):
    return [w for w in ways if w.points_m and any(_inside(box, x, y) for x, y in w.points_m)]


def _route_length_outside(route, box):
    return sum(math.dist(a, b) for a, b in zip(route, route[1:]) if not (_inside(box, *a) and _inside(box, *b)))


def _demand(world, x, y, heading, view):
    """Motorway nodes a spawn could use: ahead of the taxi, in the active area, out of view."""
    ahead = (math.cos(heading), math.sin(heading))
    active = _box(x, y, ACTIVE_HALF_M)
    return sum(1 for nx, ny, _ in world.motorway_graph.nodes
               if _inside(active, nx, ny) and not _inside(view, nx, ny)
               and (nx - x) * ahead[0] + (ny - y) * ahead[1] > npc.NPC_TRANSIT_SPAWN_CLEARANCE_M)


def select_motorway_segment(ways):
    """The first motorway way (by OSM id) meeting the fixed criteria: highway=motorway,
    connected in the loaded area's motorway_graph, a motorway route from it that runs at least
    MOTORWAY_TRIP_MAX_M beyond the loaded bounds, and demand (motorway nodes ahead).
    (start, route, loaded bounds, report); fails as a setup error when none qualifies."""
    full = TrafficWorld(ways)
    graph = full.motorway_graph
    report = {"candidates": 0, "not_connected": 0, "no_extension": 0, "no_demand": 0}
    for way in sorted((w for w in ways if w.highway == "motorway"), key=lambda w: (w.osm_id or 0)):
        report["candidates"] += 1
        points = list(reversed(way.points_m)) if way.oneway == -1 else list(way.points_m)
        start = points[0]
        loaded_box = _box(start[0], start[1], LOADED_HALF_M)
        loaded = TrafficWorld(_ways_in(ways, loaded_box))
        near = [i for i, node in enumerate(loaded.motorway_graph.nodes) if math.dist(node[:2], start) < 3.0]
        if not near or not loaded.motorway_graph.edges.get(near[0]):
            report["not_connected"] += 1
            continue
        heading = math.atan2(points[1][1] - start[1], points[1][0] - start[0])
        ahead = (math.cos(heading), math.sin(heading))
        targets = sorted((node for node in graph.nodes
                          if DRIVE_M <= math.dist(node[:2], start) <= DRIVE_M + 1500.0
                          and (node[0] - start[0]) * ahead[0] + (node[1] - start[1]) * ahead[1] > 0.7 * math.dist(node[:2], start)),
                         key=lambda node: (round(node[0]), round(node[1])))
        route = None
        for target in targets[:5]:
            route = run_route_steps(full.plan_motorway_route_steps(start, target[:2]))
            if route and _route_length_outside(route, loaded_box) >= npc.MOTORWAY_TRIP_MAX_M:
                break
            route = None
        if route is None:
            report["no_extension"] += 1
            continue
        view = _box(start[0], start[1], *VIEW_HALF)
        if not _demand(loaded, start[0], start[1], heading, view):
            report["no_demand"] += 1  # not a spawn failure: nothing to spawn on here
            continue
        assert way.highway == "motorway"
        assert _route_length_outside(route, loaded_box) >= npc.MOTORWAY_TRIP_MAX_M
        return start, route, loaded_box, report
    pytest.fail(f"setup error: no Oulu motorway segment qualifies {report}")


def _along(route, distance):
    """(x, y, heading) `distance` metres along the route polyline."""
    for a, b in zip(route, route[1:]):
        length = math.dist(a, b)
        if length > 0 and distance <= length:
            t = distance / length
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, math.atan2(b[1] - a[1], b[0] - a[0])
        distance -= length
    a, b = route[-2], route[-1]
    return b[0], b[1], math.atan2(b[1] - a[1], b[0] - a[0])


def test_oulu_motorway_drive(tmp_path):
    ways, source = _oulu_ways()
    start, route, loaded_box, selection = select_motorway_segment(ways)
    random.seed(SEED)
    loaded_ways = _ways_in(ways, loaded_box)
    world, residents = TrafficWorld(loaded_ways), ResidentManager()
    grid = SpatialWayGrid(loaded_ways)
    manager = NPCVehicleManager(target_count=40)
    manager.target_moving_count = 12
    player = Car(x=start[0], y=start[1], heading=0.0, speed=SPEED_MPS)

    spawned, in_view, stationary_s = {}, set(), {}
    entered = left = 0
    unexplained, expansions, tick_ms = [], [], []
    seen_retired = 0
    last = {}
    steps = int(DRIVE_S / DT)
    for step in range(steps):
        t = step * DT
        x, y, heading = _along(route, SPEED_MPS * t)
        player.x, player.y, player.heading, player.speed = x, y, heading, SPEED_MPS
        if len(expansions) < EXPANSIONS and t >= EXPANSION_EVERY_S * (len(expansions) + 1):
            box = _box(x, y, LOADED_HALF_M)
            loaded_box = (min(loaded_box[0], box[0]), min(loaded_box[1], box[1]),
                          max(loaded_box[2], box[2]), max(loaded_box[3], box[3]))
            loaded_ways = _ways_in(ways, loaded_box)
            revision = world.route_graph_revision
            world.sync_map_data(loaded_ways)
            grid = SpatialWayGrid(loaded_ways)
            assert world.route_graph_revision != revision
            expansions.append(t)
        view = _box(x, y, *VIEW_HALF)
        started = time.perf_counter()
        manager.update(DT, x, y, residents, world, loaded_ways, spatial_grid=grid, viewport_bounds=view,
                       player_car=player, active_bounds=_box(x, y, ACTIVE_HALF_M), near_bounds=_box(x, y, NEAR_HALF_M))
        tick_ms.append((time.perf_counter() - started) * 1000.0)
        world.advance_time(DT)
        retired = manager.spawn_flow["through_dead_end"] + manager.spawn_flow["through_stuck_retired"]
        current = {v.vehicle_id: v for v in manager.vehicles if v.fast_through}
        for vehicle_id, vehicle in current.items():
            spawned.setdefault(vehicle_id, t)
            visible = _inside(view, vehicle.x, vehicle.y)
            if visible and vehicle_id not in in_view:
                in_view.add(vehicle_id)
                entered += 1
            elif not visible and vehicle_id in in_view:
                in_view.discard(vehicle_id)
                left += 1
            stationary_s[vehicle_id] = stationary_s.get(vehicle_id, 0.0) + DT if abs(vehicle.car.speed) < 0.05 else 0.0
        explained = retired - seen_retired
        for vehicle_id in [vid for vid in last if vid not in current]:
            in_view.discard(vehicle_id)
            vehicle, driver = last[vehicle_id]
            if not _inside(view, vehicle.x, vehicle.y):  # (where it was removed, in this frame's view)
                continue
            if explained > 0:
                explained -= 1
            elif vehicle.state != npc.NPCState.CRASHED and not (
                    driver is not None and driver.recovery_stage == "HOLD"
                    and driver.hold_failures >= npc.NPC_HOLD_GIVE_UP_ATTEMPTS):
                unexplained.append((round(t, 2), vehicle_id, vehicle.state.name,
                                    getattr(driver, "recovery_stage", None), round(vehicle.x), round(vehicle.y)))
        seen_retired = retired
        last = {vid: (v, manager.drivers.get(vid)) for vid, v in current.items()}

    waits = [frames * DT for frames in manager.route_job_stats["waits_frames"]]
    metrics = {
        "source": source, "selection": selection, "start": start, "expansions_s": expansions,
        "spawned": len(spawned), "routed": manager.spawn_stats["routes_searched"],
        "entered_view": entered, "left_view": left,
        "failed_spawns": manager.route_job_stats["failed"],
        "discard_reasons": manager.route_job_stats.get("discard_reasons", {}),
        "stuck_retired": manager.spawn_flow["through_stuck_retired"],
        "dead_end_retired": manager.spawn_flow["through_dead_end"],
        "out_of_view_retired": manager.spawn_flow["through_retired"],
        "spawn_delay_mean_s": sum(waits) / len(waits) if waits else None,
        "spawn_delay_max_s": max(waits) if waits else None,
        "tick_ms_mean": sum(tick_ms) / len(tick_ms), "tick_ms_max": max(tick_ms),
        "max_stationary_s": max(stationary_s.values(), default=0.0),
        "unexplained_in_view": unexplained,
    }
    out = tmp_path / "oulu_motorway_drive.json"
    out.write_text(json.dumps(metrics, indent=2))
    print(f"oulu motorway metrics: {out}\n{json.dumps(metrics)}")

    assert len(expansions) >= 2
    windows = expansions + [DRIVE_S]
    for begin, end in zip(windows, windows[1:]):
        assert any(begin < at <= end for at in spawned.values()), f"no motorway spawn in {begin:.0f}-{end:.0f} s: {metrics}"
    assert metrics["max_stationary_s"] < STUCK_BOUND_S, metrics
    assert not unexplained, metrics
