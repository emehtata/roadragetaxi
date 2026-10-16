#!/usr/bin/env python3
"""Diagnostic-only real-time Oulu traffic observation; never imported by the game.

PYTHONPATH=src .venv/bin/python tools/observe_npc_traffic.py --seconds 600 --out /tmp/rrt-traffic-observation
Records before/after collision evidence and sampled motion, without replacing
traffic decisions, collision response, routing or recovery.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter, deque
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import random
import subprocess
import sys
import time


def enum_value(value):
    return getattr(value, "value", value)


def low_progress(samples, minimum_s=30.0, distance_m=2.0):
    """A diagnostic flag, not permission to override a legal traffic wait."""
    return (len(samples) >= 2 and samples[-1][0] - samples[0][0] >= minimum_s
            and max(math.hypot(p[1] - samples[0][1], p[2] - samples[0][2])
                    for p in samples) < distance_m)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--out", type=Path, default=Path("/tmp/rrt-traffic-observation"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert low_progress([(0, 0, 0), (30, 1, 0)])
        assert not low_progress([(0, 0, 0), (29, 1, 0)])
        assert not low_progress([(0, 0, 0), (15, 10, 0), (30, 0, 0)])
        print("observation self-check passed")
        return
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(args.out / "server.log"), level=logging.INFO)
    seed = 20261015
    random.seed(seed)
    sys.argv = ["observe", "--preset", "Oulu", "--no-auto-fetch", "--osm-source", "pbf",
                "--osm-pbf-path", "/home/ubuntu/.local/share/godot/app_userdata/Road Rage Trip (Godot client)/maps/finland-latest.osm.pbf",
                "--no-historical-weather", "--no-train-timetable", "--npc-vehicle-count", "40",
                "--npc-vehicle-min", "20", "--pedestrian-count", "60", "--start-time", "2026-10-15T12:00"]
    from theroadragetrip.server import SimulationServer
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.performance import tune_interpreter
    from theroadragetrip.weather import WeatherType
    from theroadragetrip.geo import boxes_intersect

    tune_interpreter()
    server_args, config = parse_server_args()
    server = SimulationServer(server_args, config)
    # Test fixture: stay in the stationary taxi, without Home/outside UI work.
    server._on_foot = False
    server._home = None
    server._update_outside = lambda: None
    weather = server.world.weather
    weather._automatic = False
    weather.weather_type = WeatherType.CLEAR
    weather.wetness = weather.road_snow = 0.0
    weather._outside_temperature_c = weather.outside_temperature_c = 18.0
    weather.plowed_cells.clear()
    server.start("127.0.0.1", 0)
    world = server.world
    manager = world.npc_manager
    history = deque(maxlen=20)  # five seconds at 4 Hz, all nearby vehicle poses
    incidents = []
    recoveries = Counter()
    wait_seconds = Counter()
    seen = set()
    previous = {}
    windows = {}
    stalls = {}
    minutes = []
    tick_ms = []
    ped_states = Counter()
    trip_transitions = Counter()
    original_check = manager._check_vehicle_collision
    import theroadragetrip.npc as npc_module
    original_boundary_check = npc_module._npc_motion_stays_on_road
    boundary_events = []
    boundary_ids = set()
    began = time.monotonic()
    clock = [0.0]

    def pose(vehicle):
        identifier = getattr(vehicle, "vehicle_id", "player")
        driver = manager.drivers.get(identifier)
        way = getattr(driver, "current_way", None) or getattr(vehicle, "way", None)
        result = {"id": identifier, "x": vehicle.x, "y": vehicle.y,
                  "heading": vehicle.heading, "speed": vehicle.speed,
                  "length": vehicle.length_m, "width": vehicle.width_m,
                  "state": enum_value(getattr(vehicle, "state", "player")),
                  "wait": getattr(vehicle, "debug_waiting_for", ""),
                  "way": {key: getattr(way, key, None) for key in
                          ("highway", "name", "layer", "half_width_m", "priority_road", "oneway")}}
        if driver is not None:
            decision = driver.decision
            result.update({"path_index": driver.path_index, "path_length": len(driver.path),
                           "recovery": driver.recovery_stage, "stuck_s": driver.stuck_timer_s,
                           "target_speed": driver.target_speed_mps,
                           "decision": {"action": decision.action, "reason": decision.reason,
                                        "stop_position": decision.stop_position},
                           "route": [[p.x, p.y] for p in driver.path[max(0, driver.path_index - 2):driver.path_index + 6]],
                           "destination": driver.destination})
            group = getattr(vehicle, "trip_group", None)
            if group is not None:
                result["trip_group"] = {"id": group.group_id, "members": list(group.member_resident_ids),
                                        "boarded": sorted(group.boarded_resident_ids),
                                        "disembarked": sorted(group.disembarked_resident_ids),
                                        "all_aboard": group.all_aboard}
        return result

    def collision_check(vehicle, obstacles, *positional, **kwargs):
        before = pose(vehicle)
        nearby = [(other, pose(other)) for other in obstacles if other is not vehicle]
        result = original_check(vehicle, obstacles, *positional, **kwargs)
        new = [v.vehicle_id for v, p in [(vehicle, before)] + nearby
               if hasattr(v, "vehicle_id") and p["state"] != "CRASHED" and enum_value(v.state) == "CRASHED"]
        if result and new:
            contacts = [p["id"] for other, p in nearby if boxes_intersect(
                before["x"], before["y"], before["heading"], before["length"], before["width"],
                p["x"], p["y"], p["heading"], p["length"], p["width"])]
            ids = {before["id"], *new, *contacts}
            event = {"elapsed_s": round(clock[0], 3), "new_crashed": sorted(set(new)),
                     "vehicle": before, "obstacles": [p for _, p in nearby],
                     "endpoint_overlap_ids": contacts,
                     "previous_pose": kwargs.get("previous_vehicle_pose"),
                     "history": [{"t": t, "vehicles": [p for p in rows if p["id"] in ids]}
                                 for t, rows in history]}
            incidents.append(event)
            with (args.out / "incidents.jsonl").open("a") as handle:
                handle.write(json.dumps(event) + "\n")
            print("COLLISION", round(clock[0], 1), before["id"], "contacts", contacts, "new", new, flush=True)
        return result

    def boundary_check(vehicle, driver, previous, ways, spatial_grid=None):
        result = original_boundary_check(vehicle, driver, previous, ways, spatial_grid)
        if not result and vehicle.vehicle_id not in boundary_ids and len(boundary_events) < 50:
            boundary_ids.add(vehicle.vehicle_id)
            boundary_events.append({"elapsed_s": round(clock[0], 3), "previous_pose": previous,
                                    "proposed_pose": pose(vehicle)})
        return result

    manager._check_vehicle_collision = collision_check
    npc_module._npc_motion_stays_on_road = boundary_check
    runtime_patch = subprocess.check_output(["git", "diff", "HEAD", "--", "src/theroadragetrip"])
    metadata = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "runtime_patch_sha256": hashlib.sha256(runtime_patch).hexdigest() if runtime_patch else None,
                "started_utc": datetime.now(timezone.utc).isoformat(), "seed": seed,
                "requested_wall_s": args.seconds, "tick_rate": 30,
                "ways": len(world.ways), "buildings": len(world.buildings),
                "fixture": "stationary Oulu taxi; clear/dry 18 C; local PBF; no historical weather, train timetable or map growth",
                "player_start": [server.car.x, server.car.y, server.car.heading], "port": server.port}
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    next_history = next_sample = next_report = 0.0
    print("START", metadata, flush=True)
    try:
        while (elapsed := time.monotonic() - began) < args.seconds:
            clock[0] = elapsed
            start = time.perf_counter()
            server.tick(1 / 30)
            tick_ms.append((time.perf_counter() - start) * 1000)
            if elapsed >= next_history:
                history.append((round(elapsed, 3), [pose(v) for v in manager.vehicles] + [pose(server.car)]))
                next_history = elapsed + 0.25
            if elapsed >= next_sample:
                for vehicle in manager.vehicles:
                    identifier = vehicle.vehicle_id
                    seen.add(identifier)
                    driver = manager.drivers.get(identifier)
                    if driver is None:
                        windows.pop(identifier, None)
                        continue
                    row = pose(vehicle)
                    old = previous.get(identifier)
                    if old is not None and old["recovery"] != row["recovery"]:
                        recoveries[f'{old["recovery"]}->{row["recovery"]}'] += 1
                    if old is not None and old["state"] != row["state"]:
                        if row["state"] == "PARKED":
                            trip_transitions["arrivals"] += 1
                        elif old["state"] == "PARKED":
                            trip_transitions["departures"] += 1
                    previous[identifier] = row
                    if abs(vehicle.speed) < 0.5:
                        wait_seconds[vehicle.debug_waiting_for or "unlabelled active driver"] += 1
                    window = windows.setdefault(identifier, deque())
                    window.append((elapsed, vehicle.x, vehicle.y))
                    while len(window) > 1 and window[1][0] <= elapsed - 30:
                        window.popleft()
                    if low_progress(window):
                        record = stalls.setdefault(identifier, {"first_flag_s": elapsed, "samples_flagged": 0})
                        record.update({"last_flag_s": elapsed, "last_pose": row})
                        record["samples_flagged"] += 1
                for ped in world.pedestrian_mgr.pedestrians:
                    ped_states[str(enum_value(ped.state))] += 1
                next_sample = elapsed + 1.0
            if elapsed >= next_report:
                record = {"elapsed_s": round(elapsed, 2), "npcs": manager.population_counts(),
                          "pedestrians": len(world.pedestrian_mgr.pedestrians),
                          "incidents": len(incidents), "stalled_ids": sorted(stalls)}
                minutes.append(record)
                (args.out / "progress.json").write_text(json.dumps(record, indent=2))
                print("PROGRESS", json.dumps(record), flush=True)
                next_report = elapsed + 30.0
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - start)))
    finally:
        manager._check_vehicle_collision = original_check
        npc_module._npc_motion_stays_on_road = original_boundary_check
        server._running = False
        server._listener.close()
    ordered = sorted(tick_ms)
    summary = {**metadata, "finished_utc": datetime.now(timezone.utc).isoformat(),
               "actual_wall_s": time.monotonic() - began, "ticks": len(tick_ms),
               "simulated_physics_s": len(tick_ms) / 30, "unique_vehicles": len(seen),
               "collision_events": len(incidents),
               "road_boundary_blocks": manager.population_diagnostics.get("road_boundary_blocks", 0),
               "first_boundary_blocks": boundary_events,
               "unique_crashed_ids": sorted({i for e in incidents for i in e["new_crashed"]}),
               "recovery_transitions_sampled": dict(recoveries),
               "route_jobs": {
                   **{key: value for key, value in manager.route_job_stats.items() if key != "waits_frames"},
                   "waits_frames": list(manager.route_job_stats["waits_frames"]),
                   "pending": [{"kind": job["kind"],
                                "vehicle_id": getattr(job["vehicle"], "vehicle_id", None),
                                "age_frames": manager._route_job_frame - job["queued_frame"]}
                               for job in manager._route_jobs],
               },
               "trip_transitions_sampled": dict(trip_transitions),
               "stopped_driver_samples_by_reason": dict(wait_seconds),
               "pedestrian_state_samples": dict(ped_states),
               "low_progress_vehicles": stalls, "progress": minutes,
               "tick_ms": {"p50": ordered[len(ordered)//2], "p95": ordered[int(len(ordered)*.95)],
                           "p99": ordered[int(len(ordered)*.99)], "max": max(ordered)},
               "final_population": manager.population_counts()}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print("DONE", json.dumps({k: summary[k] for k in ("actual_wall_s", "ticks", "collision_events", "tick_ms")}), flush=True)


if __name__ == "__main__":
    main()
