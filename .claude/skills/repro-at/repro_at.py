"""Headless reproduction at a map position: a template - copy it to the
scratchpad and replace probe() with what the bug needs.

    PYTHONPATH=src .venv/bin/python repro_at.py --json screenshots/screenshot_X.json [options]
    PYTHONPATH=src .venv/bin/python repro_at.py --at 427400 7210900 --city Oulu [options]

Options: --heading RAD, --speed M_S (driven straight along the heading for
--seconds of simulation), --seconds S, --start-time YYYY-MM-DDTHH:MM,
--box-km K (map loaded around the point, default 3), --view W H (the
client's view in metres, default 142 x 80: 1280x720 at the default zoom).

The first run in an area after a world-cache format change rebuilds it
(minutes): run it in the background.
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
    """Replace with the investigation. `report(label)` prints the default
    counters; the world is server.world (ways, buildings, railings, waters,
    npc_manager, pedestrian_mgr, taxi_mgr, traffic_mgr ...)."""
    report("start")
    run(server, car, ARGS.seconds, ARGS.speed, report)
    report("end")


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
