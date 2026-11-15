#!/usr/bin/env python3
"""Collision spec phase 7: the scenario 15 dense city, headless (no map load, no Godot).

    PYTHONPATH=src python tools/bench_dense_city.py [--seed 15] [--ticks 1800] [--json out.json]

A 300 x 300 m street grid with buildings, 150 drifting NPCs, 200 bollards and fences
along the kerbs, 60 pedestrians and a taxi driving the grid at 20 m/s (the phase 6
scenario 15 harness), plus a two-level garage (level 0 and 1 stacked). Each tick runs
the collision work the server does (taxi sweep and checks, NPC static and vehicle pairs,
pedestrian contact and separation). Prints p50/p99/max (ms) of the collisions section
(the taxi's, as simulation.py times it), the NPC collision work and the pedestrian contact,
and every collision counter (p50/p99/max per tick, run total).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from theroadragetrip.collision import Category as C, StaticObstacleIndex  # noqa: E402
from theroadragetrip.npc import Driver, NPCVehicleManager, place_parked_npc, update_knocked  # noqa: E402
from theroadragetrip.osm import Building, Way  # noqa: E402
from theroadragetrip.osm.models import Railing  # noqa: E402
from theroadragetrip.pedestrian import Pedestrian, PedestrianManager  # noqa: E402
from theroadragetrip.performance import COLLISION_COUNTERS  # noqa: E402
from theroadragetrip.physics import Car  # noqa: E402
from theroadragetrip.residents import ResidentManager  # noqa: E402
from theroadragetrip.taxi import TaxiManager  # noqa: E402

DT = 1.0 / 30.0
STREETS = [i * 60.0 for i in range(6)]  # streets every 60 m, 10 m wide
GARAGE = (330.0, 30.0)  # beside the grid: pillars and cars on level 0 and level 1


def _square(cx, cy, h):
    return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]


def _npc(vid, x, y, heading, speed, level=0):
    v = place_parked_npc(vid, (x, y), None)
    v.car.x, v.car.y, v.car.heading, v.car.speed = x, y, heading, speed
    v.car.map_level = level
    return v, Driver(resident_id=vid, vehicle_id=vid, path=[], destination=(x, y))


def build_world(seed: int = 15):
    """The scenario 15 world (phase 6 harness layout) and the garage; deterministic per seed."""
    rng = random.Random(seed)
    buildings = [Building(points_m=_square(sx + 30.0, sy + 30.0, 22.0)) for sx in STREETS[:-1] for sy in STREETS[:-1]]
    for level in (0, 1):  # garage pillars, one set per floor
        for i in range(4):
            pillar = Building(points_m=_square(GARAGE[0] + 4.0 + i * 8.0, GARAGE[1], 0.5))
            pillar.map_level = level
            buildings.append(pillar)
    posts, railings = [], []
    while len(posts) < 200:
        s, t = rng.choice(STREETS), rng.uniform(5.0, 295.0)
        if min(abs(t - u) for u in STREETS) < 8.0:
            continue  # kerbs only, not across a junction
        side = rng.choice((-1, 1)) * 4.6
        posts.append(NS(x=t, y=s + side, kind="bollard") if rng.random() < 0.5 else NS(x=s + side, y=t, kind="bollard"))
    for s in STREETS:
        for t in range(15, 290, 60):
            railings.append(Railing(points_m=[(t, s + 5.2), (t + 20.0, s + 5.2)], bbox=(t, s + 5.2, t + 20.0, s + 5.2)))
    index = StaticObstacleIndex()
    index.sync("buildings", buildings, C.BUILDING)
    index.sync("scenery_objects", posts, C.POST)
    index.sync("railings", railings, C.BARRIER)
    manager = NPCVehicleManager(target_count=160)
    manager.static_index = index
    lanes = []
    for vid in range(150):
        along_x, s = rng.random() < 0.5, rng.choice(STREETS)
        heading = rng.choice((0.0, math.pi)) + (0.0 if along_x else math.pi / 2)
        t = rng.uniform(0.0, 300.0)
        s += rng.choice((-2.0, 2.0))  # in a lane
        v, driver = _npc(vid, t if along_x else s, s if along_x else t, heading, rng.uniform(8.0, 14.0))
        manager.vehicles.append(v)
        manager.drivers[vid] = driver
        lanes.append([rng.uniform(1.0, 2.0), rng.uniform(0.0, 6.0), 0.0, s])  # drift m/s, phase, waiting s, lane
    for level in (0, 1):  # one car per floor, the same lane, stacked
        vid = 150 + level
        v, driver = _npc(vid, GARAGE[0], GARAGE[1], 0.0, 5.0, level)
        manager.vehicles.append(v)
        manager.drivers[vid] = driver
        lanes.append([1.5, 0.0, 0.0, GARAGE[1]])
    way = Way(points_m=[(0.0, 0.0), (300.0, 0.0)], highway="footway", half_width_m=1.5)
    peds = PedestrianManager([way], target_count=0)
    peds.static_index = index
    for i in range(60):  # on the pavements, a third along building walls, ten crossing the taxi's street
        s, t = rng.choice(STREETS), rng.uniform(0.0, 300.0)
        y = STREETS[1] + 2.0 if i < 10 else s + (8.3 if i < 30 else rng.choice((-6.0, 6.0)))
        ped = Pedestrian(t, y, rng.choice((0.0, math.pi)), 1.4, 1.4, way, 0, 1, (255, 0, 0))
        peds.pedestrians.append(ped)
    taxi = TaxiManager(ways=[])
    car = Car(x=0.0, y=STREETS[1] + 2.0, heading=0.0, speed=20.0)
    return NS(rng=rng, buildings=buildings, posts=posts, railings=railings, index=index, npcs=manager, lanes=lanes,
              peds=peds, taxi=taxi, car=car, residents=ResidentManager(), world=NS(sim_time=0.0, ways=[]))


def step(w, frame: int) -> tuple:
    """One tick: move everything, then the collision work. Returns ms of the server's `collisions`
    section (the taxi's sweep and checks, as simulation.py times it), the NPC collision work
    (static sweeps, grid, vehicle pairs: inside the `npc` section) and the pedestrian contact."""
    COLLISION_COUNTERS.reset()
    manager, car, world = w.npcs, w.car, w.world
    world.sim_time = frame * DT
    prev = {id(v): (v.x, v.y, v.heading) for v in manager.vehicles}
    for v, lane in zip(manager.vehicles, w.lanes):
        if v.knock_vx or v.knock_vy:
            update_knocked(v, DT, static_index=w.index)
            continue
        if lane[2] > 0.0:
            lane[2] -= DT
            continue
        fx, fy = math.cos(v.heading), math.sin(v.heading)
        drift = lane[0] * math.sin(world.sim_time * 0.7 + lane[1])  # wanders toward a kerb and back
        base, span = (0.0, 300.0) if v.car.x < 300.0 else (GARAGE[0] - 4.0, 40.0)  # the garage cars loop in it
        v.car.x = base + (v.car.x - base + (fx * 11.0 - fy * drift) * DT) % span
        v.car.y = (v.car.y + (fy * 11.0 + fx * drift) * DT) % 300.0
        prev[id(v)] = (v.x - (fx * 11.0 - fy * drift) * DT, v.y - (fy * 11.0 + fx * drift) * DT, v.heading)
    car_prev = (car.x, car.y, car.heading)
    car.speed = car.speed or 20.0  # a stop: drive on next tick
    car.x = (car.x + car.speed * DT) % 300.0
    car.y = car_prev[1] + 0.8 * math.sin(world.sim_time * 0.5)  # weaving toward the kerbs
    if car.x < car_prev[0]:  # wrapped: next street
        car_prev = (car.x, car.y, car.heading)
    for ped in w.peds.pedestrians:
        ped.x = (ped.x + math.cos(ped.heading) * 1.4 * DT) % 300.0

    started = time.perf_counter()
    taxi = w.taxi
    previous = taxi.sweep_static(car, car_prev, w.buildings, [], w.railings, w.posts)
    taxi.check_building_collision(car, w.buildings, world.sim_time, previous)
    taxi.check_barrier_collision(car, w.railings, world.sim_time, previous)
    taxi.check_post_collision(car, w.posts, world.sim_time, previous)
    taxi_ms, started = (time.perf_counter() - started) * 1000.0, time.perf_counter()
    manager._static_collisions(manager.vehicles, prev, world, None)
    manager.rebuild_spatial_grid()
    prev[id(car)] = car_prev
    for v in manager.vehicles:
        p = prev[id(v)]
        candidates = list(manager.nearby_vehicles_at(v.x, v.y, math.hypot(v.x - p[0], v.y - p[1]) + v.length_m + 3.0))
        candidates.append(car)
        if manager._check_vehicle_collision(v, candidates, w.residents, w.peds, world.sim_time, p, prev):
            COLLISION_COUNTERS.resolve_ms += (time.perf_counter() - COLLISION_COUNTERS._t0) * 1000.0
    npc_ms, started = (time.perf_counter() - started) * 1000.0, time.perf_counter()
    w.peds.rebuild_spatial_grid()
    w.peds.check_player_avoidance(car, DT, rebuild=False)
    w.peds._separate_pedestrians(DT)
    ped_ms = (time.perf_counter() - started) * 1000.0

    for v, lane in zip(manager.vehicles, w.lanes):  # a stopped NPC is rerouted back into its lane
        if v.car.speed == 0.0 and lane[2] <= 0.0 and not (v.knock_vx or v.knock_vy):
            lane[0], lane[2], v.car.speed = 0.0, 1.0, 11.0
            if abs(math.sin(v.heading)) < 0.5:
                v.car.y = lane[3]
            else:
                v.car.x = lane[3]
    return taxi_ms, npc_ms, ped_ms


def run(seed: int = 15, ticks: int = 1800):
    """((collisions, npc, pedestrian) ms per tick, counter snapshot per tick)."""
    random.seed(seed)  # curses pick a symbol from the global generator
    w = build_world(seed)
    times, snaps = [], []
    for frame in range(ticks):
        times.append(step(w, frame))
        snaps.append(COLLISION_COUNTERS.snapshot())
    return times, snaps


def pct(values, p, digits=3):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))], digits) if values else 0.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=15)
    parser.add_argument("--ticks", type=int, default=1800)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    times, snaps = run(args.seed, args.ticks)
    result = {
        "seed": args.seed, "ticks": args.ticks,
        **{name + "_ms": {"p50": pct(v, .5), "p99": pct(v, .99), "max": round(max(v), 3)}
           for i, name in enumerate(("collisions_section", "npc_collisions", "pedestrian_contact"))
           for v in [[t[i] for t in times]]},
        "collision_counters": {name: {"p50": pct(v, .5), "p99": pct(v, .99), "max": round(max(v), 3), "total": round(sum(v), 3)}
                               for name in snaps[0] for v in [[s[name] for s in snaps]]},
    }
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
