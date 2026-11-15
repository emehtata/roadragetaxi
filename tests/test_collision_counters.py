"""Collision spec phase 7: collision counters (scenarios 2, 10, 11, 15)."""
import importlib.util
import math
import tracemalloc
from pathlib import Path
from types import SimpleNamespace as NS

from theroadragetrip.collision import Category as C, StaticObstacleIndex
from theroadragetrip.npc import NPCVehicleManager, place_parked_npc
from theroadragetrip.osm import Building, Way
from theroadragetrip.pedestrian import Pedestrian, PedestrianManager
from theroadragetrip.performance import COLLISION_COUNTERS as COUNTERS, HIT_PAIRS, HIT_SLOT
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.taxi import TaxiManager

_spec = importlib.util.spec_from_file_location(
    "bench_dense_city", Path(__file__).resolve().parents[1] / "tools" / "bench_dense_city.py")
dense = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dense)


def _counts(snapshot):
    return {k: v for k, v in snapshot.items() if not k.endswith("_ms")}  # times differ run to run


def test_counters_increment_on_placed_scenarios():
    # Scenario 2: two NPCs meet at a junction.
    COUNTERS.reset()
    residents, manager = ResidentManager(), NPCVehicleManager(target_count=2)
    a, b = place_parked_npc(1, (-8.0, 0.0), None), place_parked_npc(2, (0.0, -8.0), None)
    a.car.heading, b.car.heading = 0.0, math.pi / 2
    a.car.speed = b.car.speed = 12.0
    peds, dt = PedestrianManager([], target_count=0), 1.0 / 30.0
    for frame in range(60):
        prev = {id(v): (v.x, v.y, v.heading) for v in (a, b)}
        for v in (a, b):
            v.car.x += math.cos(v.heading) * v.car.speed * dt
            v.car.y += math.sin(v.heading) * v.car.speed * dt
        if manager._check_vehicle_collision(a, [b], residents, peds, frame * dt, prev[id(a)], prev):
            break
    snap = COUNTERS.snapshot()
    assert snap["collisions:broad_pairs"] > 0 and snap["collisions:narrow_checks"] > 0
    assert snap["collisions:hits:VEHICLE|VEHICLE"] == 1
    # Scenario 10: the taxi's long step reaches a bollard.
    COUNTERS.reset()
    post = NS(x=2.1, y=0.0, kind="bollard")
    car = Car(x=0.0, y=0.0, heading=0.0, speed=69.0)
    prev = (car.x, car.y, car.heading)
    car.x += 69.0 / 30.0
    taxi = TaxiManager(ways=[])
    previous = taxi.sweep_static(car, prev, [], [], [], [post])
    assert taxi.check_post_collision(car, [post], 0.0, previous_position=previous)
    snap = COUNTERS.snapshot()
    assert snap["collisions:broad_pairs"] > 0 and snap["collisions:narrow_checks"] > 0
    assert snap["collisions:hits:VEHICLE|POST"] == 1
    assert sum(COUNTERS.hits) == 1
    assert snap["collisions:index_update_ms"] > 0.0


def test_counters_deterministic_same_seed():
    _, first = dense.run(15, 300)
    _, second = dense.run(15, 300)
    assert list(map(_counts, first)) == list(map(_counts, second))
    _, other = dense.run(16, 300)
    assert sum(s["collisions:broad_pairs"] for s in other) != sum(s["collisions:broad_pairs"] for s in first)
    totals = {name: sum(s[name] for s in first) for name in first[0]}
    assert set(totals) == {"collisions:broad_pairs", "collisions:narrow_checks", "collisions:resolve_ms",
                           "collisions:index_update_ms", *("collisions:hits:" + p for p in HIT_PAIRS)}
    for name in ("broad_pairs", "narrow_checks", "hits:VEHICLE|VEHICLE", "hits:VEHICLE|BUILDING",
                 "hits:PEDESTRIAN|PEDESTRIAN", "resolve_ms", "index_update_ms"):
        assert totals["collisions:" + name] > 0, name


def _garage(level_b):
    """Taxi, NPC, pedestrian and pillar on level 0; the same set on level_b, moving into each other."""
    dt, residents = 1.0 / 30.0, ResidentManager()
    pillar = Building(points_m=[(9.5, -0.5), (10.5, -0.5), (10.5, 0.5), (9.5, 0.5)])
    pillar.map_level = level_b
    index = StaticObstacleIndex()
    index.sync("buildings", [pillar], C.BUILDING)
    npcs = NPCVehicleManager(target_count=1)
    npcs.static_index = index
    v = place_parked_npc(1, (0.0, 0.0), None)  # level 0, driving at the pillar
    v.car.speed = 8.0
    npcs.vehicles.append(v)
    npcs.drivers[1] = dense.Driver(resident_id=1, vehicle_id=1, path=[], destination=(0.0, 0.0))
    taxi = Car(x=20.0, y=0.0, heading=math.pi, speed=8.0)  # head-on at the NPC
    taxi.map_level = level_b
    way = Way(points_m=[(0.0, 0.0), (40.0, 0.0)], highway="footway", half_width_m=1.5)
    peds = PedestrianManager([way], target_count=0)
    ped = Pedestrian(19.5, 0.9, 0.0, 0.0, 0.0, way, 0, 1, (255, 0, 0))  # touching the taxi, level 0
    peds.pedestrians = [ped]
    COUNTERS.reset()
    for frame in range(60):
        prev = {id(v): (v.x, v.y, v.heading), id(taxi): (taxi.x, taxi.y, taxi.heading)}
        v.car.x += v.car.speed * dt
        taxi.x -= taxi.speed * dt
        npcs._static_collisions([v], prev, NS(sim_time=frame * dt, ways=[]), None)
        npcs._check_vehicle_collision(v, [taxi], residents, peds, frame * dt, prev[id(v)], prev)
        peds.check_player_avoidance(taxi, dt)
    return COUNTERS.snapshot()


def test_scenario11_garage_levels_no_cross_level_hits():
    cross = _garage(1)
    same = _garage(0)
    for pair in ("VEHICLE|VEHICLE", "VEHICLE|BUILDING", "VEHICLE|PEDESTRIAN"):
        assert cross["collisions:hits:" + pair] == 0, pair
        assert same["collisions:hits:" + pair] > 0, pair


def test_counters_reset_no_allocation():
    slot = HIT_SLOT["VEHICLE|POST"]
    COUNTERS.reset()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for tick in range(100):
            COUNTERS.reset()
            COUNTERS.broad_pairs += 3
            COUNTERS.narrow_checks += 2
            COUNTERS.hits[slot] += 1
            COUNTERS.resolve_ms += 0.01
            COUNTERS.index_update_ms += 0.02
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    assert after - before <= 0
