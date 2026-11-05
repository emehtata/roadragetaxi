#!/usr/bin/env python3
"""Deterministic visual tests (docs/visual-testing.md).

    .venv/bin/python tools/visual_test.py list
    .venv/bin/python tools/visual_test.py run SCENARIO [SCENARIO...] [--out DIR]
    .venv/bin/python tools/visual_test.py compare RESULT_DIR_A RESULT_DIR_B [--out diff.png]
    PYTHONPATH=src .venv/bin/python tools/visual_test.py find --city Helsinki --near X Y [--radius 800]

`run` starts the simulation server with the scenario's fixed conditions
(--test-pose, --test-weather, --test-cloud, --test-seed, --test-time-scale 0)
and the Godot client with --visual-test, which waits for its readiness
checks (godot/visual_test.gd), measures, and writes screenshot.png and
result.json under visual-test-results/SCENARIO/TIME_COMMIT/. A scenario with
several start times runs once per time. Exit status 1 if any run failed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "tools" / "visual_scenarios.json"
RESULTS = REPO / "visual-test-results"
WINDOWS_GODOT = Path("/mnt/c/Godot/Godot_v4.7.2-stable_win64_console.exe")


def scenarios() -> dict:
    return {s["id"]: s for s in json.loads(REGISTRY.read_text(encoding="utf-8"))["scenarios"]}


def _godot() -> Path:
    if os.environ.get("GODOT"):
        return Path(os.environ["GODOT"])
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists() and WINDOWS_GODOT.exists():
        return WINDOWS_GODOT  # WSL: native Windows rendering (AGENTS.md), not Mesa
    found = sorted(Path.home().glob("tools/godot/Godot_v*-stable_linux.x86_64"))
    if not found:
        sys.exit("Godot binary not found (set GODOT=/path/to/godot)")
    return found[-1]


def _host_path(path: Path, godot: Path) -> str:
    """A path as the Godot binary sees it (wslpath -w for the Windows one)."""
    if godot.suffix == ".exe":
        return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return str(path)


def _commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return head + ("-dirty" if dirty else "")


def _bbox(x: float, y: float, box_km: float) -> str:
    sys.path.insert(0, str(REPO / "src"))
    from theroadragetrip.geo import meters_to_latlon

    lat, lon = meters_to_latlon(x, y)
    half = box_km / 2 / 111.0
    half_lon = half / math.cos(math.radians(lat))
    return f"{lat - half},{lon - half_lon},{lat + half},{lon + half_lon}"


def run_one(scenario: dict, start_time: str, out_root: Path) -> dict:
    commit = _commit()
    out = out_root / scenario["id"] / f"{start_time.replace(':', '')}_{dt.datetime.now():%Y%m%d-%H%M%S}_{commit}"
    out.mkdir(parents=True, exist_ok=True)
    spec = dict(scenario, start_time=start_time, commit=commit)
    if scenario.get("lineup"):  # the 2D lineup at the simulation's own sizes (godot/visual_test.gd)
        sys.path.insert(0, str(REPO / "src"))
        from theroadragetrip.trams import DEFAULT_TRAM, TRAM_WIDTH_M
        from theroadragetrip.vehicles.base import vehicle_definition

        kinds = ("car", "van", "truck", "bus", "tractor", "camper_van", "car_caravan", "motorcycle", "bicycle", "e_scooter")
        spec["lineup_rows"] = [[kind, vehicle_definition(kind).length_m, vehicle_definition(kind).width_m] for kind in scenario.get("lineup_kinds", kinds)]
        trailer = vehicle_definition("car_caravan").trailer
        spec["lineup_trailer"] = [trailer.length_m, trailer.width_m, trailer.drawbar_m]
        spec["lineup_tram"] = [DEFAULT_TRAM[0], list(DEFAULT_TRAM[1]), TRAM_WIDTH_M]
        if scenario.get("view", "3d") == "3d":  # the 3D view draws a train coach too (lineup "coach": only it, close)
            from theroadragetrip.train_compositions import DEFAULT_WAGON_LENGTH_M
            from theroadragetrip.trains import TRAIN_WIDTH_M

            spec["lineup_coach"] = ["standard", DEFAULT_WAGON_LENGTH_M, TRAIN_WIDTH_M]
    (out / "scenario.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    x, y, heading = scenario["pose"]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server_args = [
        "--port", str(port), "--preset", scenario["city"], "--bbox", _bbox(x, y, scenario.get("box_km", 2.0)),
        "--start-time", start_time, "--test-pose", f"{x},{y},{heading}", "--test-weather", scenario["weather"],
        "--test-cloud", str(scenario["cloud"]), "--test-seed", str(scenario.get("seed", 1)), "--test-time-scale", "0",
        "--no-historical-weather", "--no-intercity-fares", *scenario.get("server_args", []),
    ]
    log = open(out / "server.log", "w", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH="src")
    server = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "theroadragetrip.server", *server_args], cwd=REPO,
                              stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        ready = subprocess.run([str(REPO / ".venv/bin/python"), "tools/wait_for_port.py", "127.0.0.1", str(port), "600"], cwd=REPO)
        if ready.returncode != 0:
            result = {"scenario": scenario["id"], "status": "failed", "errors": ["the server did not start (server.log)"]}
            (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result | {"dir": str(out)}
        godot = _godot()
        project = _host_path(REPO / "godot", godot)
        engine = [] if godot.suffix == ".exe" else ["--display-driver", "x11", "--rendering-driver", "opengl3"]
        client = ["--port", str(port), "--zoom", str(scenario.get("zoom", 1.0)),
                  "--visual-test", _host_path(out / "scenario.json", godot), *scenario.get("godot_args", [])]
        if scenario.get("view", "3d") == "3d":
            client.append("--outdoor-3d")
        with open(out / "godot.log", "w", encoding="utf-8") as godot_log:
            subprocess.run([str(godot), "--path", project, *engine, "--", *client], cwd=REPO, stdout=godot_log,
                           stderr=subprocess.STDOUT, timeout=600)
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
    path = out / "result.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "scenario": scenario["id"], "status": "failed", "errors": ["the client wrote no result (godot.log)"]}
    return result | {"dir": str(out)}


def compare(a: Path, b: Path, out: Path) -> None:
    """Side by side (A | B | difference x4) and the mean absolute difference."""
    from PIL import Image, ImageChops

    first, second = (Image.open(p / "screenshot.png").convert("RGB") for p in (a, b))
    diff = ImageChops.difference(first, second)
    mean = sum(sum(px) for px in diff.getdata()) / (3 * diff.width * diff.height)
    amplified = diff.point(lambda v: min(255, v * 4))
    sheet = Image.new("RGB", (first.width * 3, first.height))
    for i, image in enumerate((first, second, amplified)):
        sheet.paste(image, (i * first.width, 0))
    sheet.save(out)
    print(f"{out}: mean absolute difference {mean:.2f} / 255")
    for label, path in (("A", a), ("B", b)):
        result = json.loads((path / "result.json").read_text(encoding="utf-8"))
        frames = result.get("frames", {})
        print(f"  {label} {result.get('commit')} {result.get('status')} avg {frames.get('avg_fps', 0):.1f} fps, "
              f"p99 {frames.get('p99_ms', 0):.1f} ms, render {result.get('render', {})}")


def find(city: str, near: tuple, radius: float) -> None:
    """Rank drivable road points near `near` by street lamps and buildings
    around them (and how many building colours): candidate scenario poses
    from the real map, with the heading along the road."""
    sys.path.insert(0, str(REPO / "src"))
    sys.argv = ["find", "--preset", city, "--bbox", _bbox(near[0], near[1], radius * 2 / 1000 + 0.6),
                "--no-historical-weather", "--no-intercity-fares", "--test-seed", "1"]
    from theroadragetrip.server import SimulationServer, place_street_lights
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.static_world import building_style

    args, config = parse_server_args()
    world = SimulationServer(args, config).world
    lamps = [(x, y) for x, y, *_ in place_street_lights(world)]
    centres = [((min(p[0] for p in b.points_m) + max(p[0] for p in b.points_m)) / 2,
                (min(p[1] for p in b.points_m) + max(p[1] for p in b.points_m)) / 2, tuple(building_style(b)[0]), b)
               for b in world.buildings]
    rows = []
    for way in world.ways:
        if not way.is_drivable or way.is_bridge or way.is_tunnel or way.layer != 0:
            continue
        for (ax, ay), (bx, by) in zip(way.points_m, way.points_m[1:]):
            x, y = (ax + bx) / 2, (ay + by) / 2
            if math.hypot(x - near[0], y - near[1]) > radius:
                continue
            near_lamps = sum(1 for lx, ly in lamps if abs(lx - x) < 40 and abs(ly - y) < 25)
            around = [c for c in centres if abs(c[0] - x) < 70 and abs(c[1] - y) < 40]
            commercial = sum(1 for c in around if (c[3].building_type or "") in ("commercial", "retail", "office"))
            rows.append((near_lamps, len(around), len({c[2] for c in around}), commercial, round(x, 1), round(y, 1),
                         round(math.atan2(by - ay, bx - ax), 3), way.name or way.highway))
    rows.sort(key=lambda r: (-(min(r[0], 8) * 3 + min(r[1], 20) + 2 * min(r[2], 8)), r[4]))
    print("lamps buildings colours commercial  x y heading  street")
    for row in rows[:25]:
        print(*row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("ids", nargs="+")
    run.add_argument("--out", type=Path, default=RESULTS)
    cmp = sub.add_parser("compare")
    cmp.add_argument("a", type=Path)
    cmp.add_argument("b", type=Path)
    cmp.add_argument("--out", type=Path, default=Path("visual-test-compare.png"))
    fnd = sub.add_parser("find")
    fnd.add_argument("--city", required=True)
    fnd.add_argument("--near", nargs=2, type=float, required=True, metavar=("X", "Y"))
    fnd.add_argument("--radius", type=float, default=800.0)
    args = parser.parse_args()
    if args.command == "list":
        for s in scenarios().values():
            print(f"{s['id']:32} {s['description']}")
    elif args.command == "compare":
        compare(args.a, args.b, args.out)
    elif args.command == "find":
        find(args.city, tuple(args.near), args.radius)
    else:
        known = scenarios()
        failed = 0
        for scenario_id in args.ids:
            if scenario_id not in known:
                sys.exit(f"unknown scenario {scenario_id}: see `list`")
            scenario = known[scenario_id]
            times = scenario["start_time"] if isinstance(scenario["start_time"], list) else [scenario["start_time"]]
            for start_time in times:
                result = run_one(scenario, start_time, args.out)
                failed += result["status"] != "passed"
                frames = result.get("frames", {})
                print(f"{scenario_id} {start_time}: {result['status']} {result['dir']}"
                      + (f" avg {frames['avg_fps']:.1f} fps p99 {frames['p99_ms']:.1f} ms" if frames else ""))
                for error in result.get("errors", []):
                    print(f"  - {error}")
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
