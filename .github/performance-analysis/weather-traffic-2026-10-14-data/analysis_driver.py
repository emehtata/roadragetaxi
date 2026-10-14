"""Temporary diagnostic harness; never modifies game source or player saves."""
import argparse
import cProfile
import json
import logging
import math
import os
import pstats
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--out', default='/tmp/rrt-performance-results')
parser.add_argument('--seconds', type=float, default=20.0)
parser.add_argument('--repeats', type=int, default=2)
parser.add_argument('--only', default='')
parser.add_argument('--headless', action='store_true')
parser.add_argument('--hide', default='')
parser.add_argument('--tracks', type=int, default=0)
parser.add_argument('--instrument-roads', action='store_true')
parser.add_argument('--zoom', default='1')
parser.add_argument('--ablations', action='store_true')
args = parser.parse_args()
out = Path(args.out)
out.mkdir(exist_ok=True)
logging.basicConfig(filename=str(out / 'server.log'), level=logging.INFO)
random.seed(20261014)
sys.argv = ['bench', '--preset', 'Oulu', '--no-auto-fetch', '--osm-source', 'pbf',
            '--osm-pbf-path', '/home/ubuntu/.local/share/godot/app_userdata/Road Rage Trip (Godot client)/maps/finland-latest.osm.pbf',
            '--no-historical-weather', '--no-train-timetable', '--npc-vehicle-count', '40',
            '--npc-vehicle-min', '20', '--pedestrian-count', '60', '--start-time', '2026-01-01T12:00']
from theroadragetrip.performance import tune_interpreter
from theroadragetrip.server import SimulationServer
from theroadragetrip.server.cli import parse_server_args
from theroadragetrip.weather import WeatherType

tune_interpreter()
server_args, config = parse_server_args()
started = time.perf_counter()
server = SimulationServer(server_args, config)
server._on_foot = False
server._home = None
server._update_outside = lambda: None
server.car.engine_on = True
start_pos = (server.car.x, server.car.y, server.car.heading)
server.start('127.0.0.1', 0)
print('LOADED', round(time.perf_counter() - started, 2), len(server.world.ways), len(server.world.buildings), server.port, flush=True)
if args.ablations:
    for _ in range(1200):
        server.tick(1/30)
    npc_update = server.world.npc_manager.update
    ped_update = server.world.pedestrian_mgr.update
    server.world.npc_manager.update = lambda *a, **k: None
    server.world.pedestrian_mgr.update = lambda *a, **k: None
    print('FROZEN_ACTORS', server.world.npc_manager.population_counts(), flush=True)

CASES = [
    ('day_clear', '2026-07-01T12:00', 'clear', 0.0, 0.0, False, False, 18.0),
    ('dawn_clear', '2026-09-01T06:00', 'clear', 0.0, 0.0, False, False, 8.0),
    ('dusk_rain', '2026-09-01T20:00', 'rain', 1.0, 0.0, False, False, 8.0),
    ('night_clear', '2026-01-01T23:00', 'clear', 0.0, 0.0, False, False, -10.0),
    ('night_thunder', '2026-09-01T23:00', 'rain', 1.0, 0.0, True, False, 8.0),
    ('day_slush', '2026-01-01T12:00', 'slush', 1.0, 0.0, False, False, 2.0),
    ('day_snow', '2026-01-01T12:00', 'snow', 0.0, 3.0, False, False, -10.0),
    ('night_snow', '2026-01-01T23:00', 'snow', 0.0, 3.0, False, False, -10.0),
    ('day_snow_plowed', '2026-01-01T12:00', 'snow', 0.0, 3.0, False, True, -10.0),
    ('day_snow_stopped', '2026-01-01T12:00', 'clear', 0.0, 3.0, False, True, -10.0),
]
if args.only:
    CASES = [c for c in CASES if c[0] in args.only.split(',')]
if args.ablations:
    base = {c[0]: c for c in CASES}
    variants = [('day_clear', '', 0), ('day_clear', 'buildings3d', 0),
                ('night_clear', '', 0), ('night_clear', 'pools', 0),
                ('night_clear', 'buildings3d', 0),
                ('dusk_rain', 'precipitation,ripples', 0),
                ('day_snow_plowed', '', 0), ('day_snow', '', 4000),
                ('day_snow_stopped', '', 4000)]
    CASES = [(f'{key}_hide_{hide or "none"}_tracks_{tracks}', *base[key][1:]) for key, hide, tracks in variants]
    case_variants = {c[0]: (hide, tracks) for c, (_, hide, tracks) in zip(CASES, variants)}

def pct(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*p)-1)] if values else 0

def configure(case):
    name, moment, kind, wetness, depth, thunder, plowed, temperature = case
    weather = server.world.weather
    server.calendar.current = datetime.fromisoformat(moment)
    weather._automatic = False
    weather._outside_temperature_c = temperature
    weather.outside_temperature_c = temperature
    weather.weather_type = WeatherType(kind)
    weather.wetness = wetness
    weather.road_snow = depth
    weather.is_thunderstorm = thunder
    weather.plowed_cells.clear()
    if plowed:
        x, y, _ = start_pos
        for cx in range(math.floor(x/10)-20, math.floor(x/10)+21):
            for cy in range(math.floor(y/10)-20, math.floor(y/10)+21):
                if (cx + cy) % 3 == 0:
                    weather.plowed_cells[(cx,cy)] = depth
    return datetime.fromisoformat(moment)

results=[]
godot='/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64'
for rep in range(args.repeats):
    for case in CASES:
        fixed_time = configure(case)
        name = f'{case[0]}_{rep}'
        log = open(out / f'{name}.log', 'w')
        command = [godot, '--path', '/home/ubuntu/work/roadragetaxi/godot', '--script', '/tmp/rrt_perf_client.gd',
                   '--audio-driver', 'Dummy', '--resolution', '1280x720', '--disable-vsync', '--',
                   '--port', str(server.port), '--bench', str(args.seconds)]
        if args.headless:
            command.insert(1, '--headless')
        command += ['--zoom', args.zoom]
        hide, tracks = case_variants[case[0]] if args.ablations else (args.hide, args.tracks)
        if hide:
            command += ['--bench-hide', hide]
        if tracks:
            command += ['--diagnostic-tracks', str(tracks)]
        if args.instrument_roads:
            command += ['--diagnostic-roads']
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        tick_times=[]
        began=time.perf_counter()
        try:
            while child.poll() is None and time.perf_counter()-began < args.seconds+45:
                t=time.perf_counter()
                server.calendar.current=fixed_time
                server.car.x, server.car.y, server.car.heading = start_pos
                server.car.speed=0.0
                server.tick(1/30)
                tick_times.append((time.perf_counter()-t)*1000)
                time.sleep(max(0, 1/30-(time.perf_counter()-t)))
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            log.close()
        lines=(out / f'{name}.log').read_text().splitlines()
        bench=[json.loads(line[6:]) for line in lines if line.startswith('BENCH ')]
        record={'case':case[0], 'repeat':rep, 'client':bench[-1] if bench else None,
                'tick_ms':{'avg':sum(tick_times)/max(1,len(tick_times)), 'p95':pct(tick_times,.95),
                           'p99':pct(tick_times,.99), 'max':max(tick_times,default=0)},
                'npcs':server.world.npc_manager.population_counts(), 'exit':child.returncode,
                'plowed_cells':len(server.world.weather.plowed_cells)}
        record['actual_weather'] = server.world.weather.weather_type.value
        record['temperature_c'] = server.world.weather._outside_temperature_c
        record['road_snow_cm'] = server.world.weather.road_snow
        results.append(record)
        (out / 'results.json').write_text(json.dumps(results,indent=2))
        print('CASE',name,record['tick_ms'],record['client']['frames'] if bench else 'NO_BENCH',flush=True)

# Profiling runs are separate from FPS measurement: cProfile adds significant cost.
if args.ablations:
    server.world.npc_manager.update = npc_update
    server.world.pedestrian_mgr.update = ped_update
for case in CASES:
    fixed_time=configure(case)
    profiler=cProfile.Profile()
    profiler.enable()
    for _ in range(180):
        server.calendar.current=fixed_time
        server.car.x, server.car.y, server.car.heading=start_pos
        server.car.speed=0.0
        server.tick(1/30)
    profiler.disable()
    profiler.dump_stats(str(out / f'{case[0]}.prof'))
    with open(out / f'{case[0]}-profile.txt','w') as f:
        pstats.Stats(profiler,stream=f).sort_stats('cumulative').print_stats(35)
print('DONE',out,flush=True)
