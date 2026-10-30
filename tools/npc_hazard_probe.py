"""NPC hazard probe (docs/npc-hazards.md): load the real map around a point,
tick the simulation with the player standing there, and report

- every NPC crash with what the vehicles within 8 m were doing just before,
- every NPC standing still on a car road for 20 s or more (with its 3 nearest),
- vehicles parked beside a road at more than 15 degrees to it.

    PYTHONPATH=src .venv/bin/python tools/npc_hazard_probe.py --at 425213 7217320 \
        --city Oulu --start-time 2026-10-28T15:04 --seconds 600

Built on .claude/skills/repro-at/repro_at.py (same options); never imported by the game.
"""
import argparse
import datetime as dt
import json
import math
import sys
import time

if __name__ != "__main__":  # the server starts a helper process that re-imports this file
    raise SystemExit


def probe(server, car, report):
    import collections, types
    manager = server.world.npc_manager
    hist = collections.defaultdict(lambda: collections.deque(maxlen=4))
    crashes = []
    real = manager._trigger_vehicle_accident
    clock = [0.0]
    def spy(self, vehicle, *a, **k):
        near = [(v.vehicle_id, list(hist[v.vehicle_id])[-1:]) for v in manager.vehicles
                if v is not vehicle and math.hypot(v.x - vehicle.x, v.y - vehicle.y) < 8]
        crashes.append((round(clock[0]), vehicle.vehicle_id, list(hist[vehicle.vehicle_id])[-1:], near))
        return real(vehicle, *a, **k)
    manager._trigger_vehicle_accident = types.MethodType(spy, manager)
    ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
             "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
    still = collections.defaultdict(float)
    stops = {}
    for tick in range(int(ARGS.seconds * 30)):
        server.tick(1 / 30)
        clock[0] = tick / 30
        if tick % 15:
            continue
        for v in manager.vehicles:
            d = manager.drivers.get(v.vehicle_id)
            dec = getattr(d, "decision", None)
            row = (v.vehicle_type, getattr(v, "vehicle_kind", ""), v.state, round(v.car.speed, 1), getattr(dec, "reason", None), v.debug_waiting_for,
                   getattr(v.way, "highway", None), round(v.x), round(v.y), round(v.car.heading, 2), getattr(v.way, "name", None), getattr(v.way, "oneway", None))
            hist[v.vehicle_id].append(row)
            on_road = v.way is not None and getattr(v.way, "highway", "") in ROADS
            if v.state in ("PARKED", "CRASHED") or not on_road or abs(v.car.speed) > 0.3:
                still.pop(v.vehicle_id, None)
                continue
            still[v.vehicle_id] += 0.5
            if still[v.vehicle_id] >= 20.0 and v.vehicle_id not in stops:
                near = sorted(((math.hypot(o.x - v.x, o.y - v.y), o) for o in manager.vehicles if o is not v), key=lambda t: t[0])[:3]
                stops[v.vehicle_id] = row + (round(v.car.heading, 2), getattr(d, "passing", None) is not None, round(getattr(d, "pass_wait_s", 0), 1),
                    [(round(dist, 1), o.vehicle_type, o.state, round(o.car.heading, 2), round(o.car.speed, 1), o.debug_waiting_for) for dist, o in near])
    from theroadragetrip.physics import closest_point_and_dist_to_segment
    angled = []
    for v in manager.vehicles:
        if v.state != "PARKED" or v.way is None or getattr(v.way, "highway", "") not in ROADS:
            continue
        pts = v.way.points_m
        (ax, ay), (bx, by) = min(zip(pts, pts[1:]), key=lambda sg: closest_point_and_dist_to_segment(v.x, v.y, *sg[0], *sg[1])[3])
        dist = closest_point_and_dist_to_segment(v.x, v.y, ax, ay, bx, by)[3]
        diff = abs(math.sin(v.car.heading - math.atan2(by - ay, bx - ax)))
        if dist < 7.0 and diff > math.sin(math.radians(15)):
            angled.append((v.vehicle_type, getattr(v, "vehicle_kind", ""), round(math.degrees(math.asin(diff))), round(dist, 1), round(v.x), round(v.y)))
    print(f"ANGLED PARKED BY ROAD {len(angled)} {angled[:8]}")
    print(f"CRASHES {len(crashes)}")
    for t, vid, me, near in crashes:
        print(f"  t={t} {vid} {me} near {near}")
    print(f"STILL>=20s {len(stops)}")
    for row in stops.values():
        print("  ", row)


def run(server, car, seconds, speed, report=None, every_s=5.0):
    """Tick `seconds` of simulation, moving the car straight at `speed`."""
    ticks = []
    for i in range(int(seconds * 30)):
        car.x += math.cos(car.heading) * speed / 30
        car.y += math.sin(car.heading) * speed / 30
        car.speed = speed
        started = time.perf_counter()
        server.tick(1 / 30)
        ticks.append(time.perf_counter() - started)
        if report is not None and i and i % int(every_s * 30) == 0:
            report(f"t={i / 30:.0f}s")
    if ticks:
        ticks.sort()
        print(f"  tick avg {1000 * sum(ticks) / len(ticks):.1f} ms, p95 {1000 * ticks[int(len(ticks) * .95)]:.1f} ms")


parser = argparse.ArgumentParser()
parser.add_argument("--json", help="an F12 screenshot JSON: position, heading, city and time of day")
parser.add_argument("--at", nargs=2, type=float, metavar=("X", "Y"), help="world metres (EPSG:3067)")
parser.add_argument("--heading", type=float)
parser.add_argument("--city")
parser.add_argument("--start-time")
parser.add_argument("--speed", type=float, default=0.0)
parser.add_argument("--seconds", type=float, default=0.0)
parser.add_argument("--box-km", type=float, default=3.0)
parser.add_argument("--view", nargs=2, type=float, default=(142.0, 80.0), metavar=("W", "H"))
ARGS = parser.parse_args()

x = y = None
heading, city, start = 0.0, "Oulu", None
if ARGS.json:
    dump = json.load(open(ARGS.json, encoding="utf-8"))
    x, y, heading = dump["car"]["x"], dump["car"]["y"], dump["car"]["heading"]
    city = dump["world"].get("city") or city
    seconds = dump["taxi"]["scalar_properties"].get("game_time_seconds")
    if seconds is not None:  # the dump has the time of day, not the game date: the dump's own date
        day = dt.datetime.fromtimestamp(dump["timestamp_ns"] / 1e9).date()
        start = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=int(seconds) % 86400)
if ARGS.at:
    x, y = ARGS.at
if x is None:
    parser.error("give --json or --at")
heading = ARGS.heading if ARGS.heading is not None else heading
city = ARGS.city or city
start_text = ARGS.start_time or (start.strftime("%Y-%m-%dT%H:%M") if start else None)

from theroadragetrip.geo import meters_to_latlon  # noqa: E402

lat, lon = meters_to_latlon(x, y)
half = ARGS.box_km / 2 / 111.0
half_lon = half / math.cos(math.radians(lat))
sys.argv = ["prog", "--preset", city, "--bbox", f"{lat - half},{lon - half_lon},{lat + half},{lon + half_lon}",
            "--no-historical-weather", "--no-intercity-fares", "--osm-source", "overpass"]
if start_text:
    sys.argv += ["--start-time", start_text]

from theroadragetrip.server import SimulationServer  # noqa: E402
from theroadragetrip.server.cli import parse_server_args  # noqa: E402

args, config = parse_server_args()
server = SimulationServer(args, config)
server._fares_opened = True
server._set_fares_open(True)  # as when the game client has connected
car = server.car
car.x, car.y, car.heading, car.speed = x, y, heading, 0.0
view_w, view_h = ARGS.view
server._visible_bounds = lambda: (car.x - view_w / 2, car.y - view_h / 2, car.x + view_w / 2, car.y + view_h / 2)
print(f"at {x:.1f} {y:.1f} heading {heading:.2f} ({lat:.5f}, {lon:.5f}) city {city} time {start_text}")


def report(label):
    world = server.world
    npcs = world.npc_manager.vehicles
    moving = sum(1 for v in npcs if abs(v.car.speed) > 0.5)
    taxi = world.taxi_mgr
    print(f"[{label}] car {car.x:.1f} {car.y:.1f} | npcs {len(npcs)} (moving {moving}) | "
          f"people {len(world.pedestrian_mgr.pedestrians)} | taxi {taxi.state} score {taxi.total_score} "
          f"| note {taxi.notification_msg!r}")


probe(server, car, report)
