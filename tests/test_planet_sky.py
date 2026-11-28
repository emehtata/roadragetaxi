"""docs/planet-sky.md: Mercury..Uranus positions, cache/lifecycle, offline provider and the named scenarios."""
from __future__ import annotations

import json
import math
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from theroadragetrip import planets
from theroadragetrip.calendar import grid_azimuth

ROOT = Path(__file__).resolve().parents[1]
BODIES = ["mercury", "venus", "mars", "jupiter", "saturn", "uranus"]
MAG_TOLERANCE = {"mercury": 0.6, "venus": 0.55, "mars": 0.25, "jupiter": 0.2, "saturn": 0.1, "uranus": 0.05}  # PyEphem vs Skyfield/Mallama 2018


def direction(alt: float, true_az: float, lat: float, lon: float) -> tuple:
    """Godot axes (+X east, +Y up, -Z grid north) of a true alt/az, through the EPSG:3067 convergence."""
    a, z = math.radians(alt), math.radians(grid_azimuth(true_az, lat, lon))
    return math.sin(z) * math.cos(a), math.sin(a), -math.cos(z) * math.cos(a)


def angle(u, v) -> float:
    """Angle between directions (cross/dot form: exact for tiny angles, and the state's 6-decimal unit vectors are not exactly unit)."""
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return math.degrees(math.atan2(math.sqrt(sum(c * c for c in cross)), sum(x * y for x, y in zip(u, v))))


def test_positions_against_independent_reference():
    reference = json.loads((ROOT / "tests/data/planet_sky_reference.json").read_text())
    assert "DE421" in reference["source"] and len(reference["rows"]) >= 50
    crossings = worst = 0.0
    for row in reference["rows"]:
        local = datetime.fromisoformat(row["local"]).replace(fold=row["fold"])
        state = planets.planet_sky_state(local, row["lat"], row["lon"], row["elevation"])
        assert state["supported"] and state["utc"] == row["utc"], row["local"]
        assert [b["id"] for b in state["bodies"]] == BODIES
        for body in state["bodies"]:
            expected = row["bodies"][body["id"]]
            # direction vectors: a mirrored axis, a city-centre observer, a clock error or a second precession all break this
            error = angle(body["dir"], direction(expected["alt"], expected["true_az"], row["lat"], row["lon"]))
            assert error <= 0.1, (row["local"], row["site"], body["id"], error)
            assert body["alt"] == pytest.approx(expected["alt"], abs=0.1)
            assert abs(body["mag"] - expected["mag"]) <= MAG_TOLERANCE[body["id"]], (row["local"], body["id"])
            crossings += -2 < expected["alt"] < 10
            worst = max(worst, error)
    assert crossings >= 10, "horizon crossings are covered"
    # the cache's 10 s bucket costs at most 10 s of Earth rotation (0.042 degrees)
    row = reference["rows"][0]
    late = planets.planet_sky_state(datetime.fromisoformat(row["local"]) + timedelta(seconds=9), row["lat"], row["lon"], row["elevation"])
    assert angle(late["bodies"][0]["dir"], direction(row["bodies"]["mercury"]["alt"], row["bodies"]["mercury"]["true_az"], row["lat"], row["lon"])) < 0.1


def test_east_is_plus_x_and_north_is_minus_z():
    state = planets.planet_sky_state(datetime(2026, 11, 15, 8, 0), 64.0, 26.0, 0)
    venus = {b["id"]: b for b in state["bodies"]}["venus"]  # morning star in the south-east
    assert venus["dir"][0] > 0 and venus["dir"][2] > 0 and venus["dir"][1] > 0  # east (+X), south (+Z), up
    assert math.hypot(*venus["dir"]) == pytest.approx(1.0, abs=1e-5)


def test_cache_time_travel_and_unavailable_state(monkeypatch, caplog):
    planets._planet_sky_state.cache_clear()
    moment = datetime(2026, 11, 15, 1, 0)
    first = planets.planet_sky_state(moment, 64.0, 26.0, 10)
    assert planets.planet_sky_state(moment + timedelta(seconds=9), 64.0, 26.0, 12) is first  # same bucket, observer, 10 m of height
    assert planets._planet_sky_state.cache_info().hits == 1 and planets._planet_sky_state.cache_info().misses == 1
    for changed in (planets.planet_sky_state(moment + timedelta(seconds=10), 64.0, 26.0, 10),  # next bucket
                    planets.planet_sky_state(moment, 64.0002, 26.0, 10), planets.planet_sky_state(moment, 64.0, 26.0004, 10),  # travel
                    planets.planet_sky_state(moment, 64.0, 26.0, 40)):  # a hill
        assert changed is not first
    assert planets._planet_sky_state.cache_info().misses == 5
    # save loads and time jumps replace the state, they are never served stale; the DST fold is two different hours
    assert planets.planet_sky_state(datetime(2026, 6, 1, 1, 0), 64.0, 26.0, 10)["utc"] == "2026-05-31T22:00:00Z"
    folds = [planets.planet_sky_state(datetime(2026, 10, 25, 3, 30, fold=f), 64.0, 26.0, 10) for f in (0, 1)]
    assert [f["utc"] for f in folds] == ["2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"] and folds[0]["bodies"] != folds[1]["bodies"]
    # the work is bounded
    for i in range(planets.CACHE_SIZE * 2):
        planets.planet_sky_state(moment + timedelta(seconds=10 * i), 64.0, 26.0, 10)
    assert planets._planet_sky_state.cache_info().currsize == planets.CACHE_SIZE
    # unsupported years, invalid coordinates: explicit reason, no bodies, no invented positions, one diagnostic
    for state in (planets.planet_sky_state(datetime(2019, 12, 31, 23, 0), 64.0, 26.0), planets.planet_sky_state(datetime(2041, 1, 2), 64.0, 26.0),
                  planets.planet_sky_state(moment, float("nan"), 26.0), planets.planet_sky_state(moment, 91.0, 26.0),
                  planets.planet_sky_state(moment, 64.0, None)):
        assert state["supported"] is False and state["bodies"] == [] and state["reason"]
    assert "outside 2020-2040" in caplog.text and "invalid observer" in caplog.text
    # a failing or non-finite body is hidden by itself and the other five stay
    planets._planet_sky_state.cache_clear()
    monkeypatch.setattr(planets.ephem, "Mars", lambda observer: (_ for _ in ()).throw(RuntimeError("corrupt")))
    state = planets.planet_sky_state(moment, 64.0, 26.0)
    by_id = {b["id"]: b for b in state["bodies"]}
    assert state["supported"] and list(by_id["mars"]) == ["id", "unavailable"] and all("dir" in by_id[n] for n in BODIES if n != "mars")
    planets._planet_sky_state.cache_clear()


def test_server_state_follows_the_observer(tmp_path, monkeypatch):
    from tests.test_server_headless import _build_server
    from theroadragetrip.geo import meters_to_latlon
    server = _build_server(tmp_path, monkeypatch)
    sky = server.calendar_state()["planet_sky"]
    assert sky["supported"] and [b["id"] for b in sky["bodies"]] == BODIES and sky["utc"].endswith("Z")
    player = server.world.player_pedestrian if server._on_foot else server.car
    assert sky["observer"][:2] == pytest.approx(list(meters_to_latlon(player.x, player.y)), abs=0.0001)
    assert server.calendar_state()["planet_sky"] == sky
    other = server.car if server._on_foot else server.world.player_pedestrian
    other.x += 5000  # the car and the walker stand at different points: switching changes the observer
    server._on_foot = not server._on_foot
    assert server.calendar_state()["planet_sky"] != sky
    server._on_foot = not server._on_foot
    player.x += 20000
    moved = server.calendar_state()["planet_sky"]
    assert moved["observer"] != sky["observer"] and moved["bodies"] != sky["bodies"]
    server.world.dem = type("Hill", (), {"height_m": lambda self, x, y: 321.0})()  # validated terrain height reaches the provider
    assert server.calendar_state()["planet_sky"]["observer"][2] == 320.0


def test_offline_assets_and_scenario_contract(monkeypatch):
    import re
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import collect_licenses
    # no kernel, timescale file or download: the provider is the bundled, already shipped PyEphem
    source = (ROOT / "src/theroadragetrip/planets.py").read_text()
    assert not re.search(r"^\s*(import|from)\s+(urllib|requests|skyfield|http|socket)", source, re.M)
    assert re.search(r'^\s+"ephem[<>=,0-9.]*"', (ROOT / "pyproject.toml").read_text(), re.M) and "ephem" in collect_licenses.RUNTIME
    assert "skyfield" not in (ROOT / "pyproject.toml").read_text().lower() and "skyfield" not in (ROOT / "requirements.txt").read_text().lower()
    inventory = json.loads((ROOT / "tools/license_inventory.json").read_text())
    assert inventory["python_packages"]["ephem"]["status"] == "verified" and "credit" in inventory["python_packages"]["ephem"]["obligations"]

    def blocked(*args, **kwargs):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    planets._planet_sky_state.cache_clear()
    assert planets.planet_sky_state(datetime(2026, 11, 15, 1, 0), 64.0, 26.0)["supported"]
    assert tuple(planets.BODIES) == tuple(BODIES) and "neptune" not in source.lower().replace("neptune is excluded", "")
    # the release smoke: the same entry point the packaged exe runs (windows-release.yml), no data files
    assert "--planet-sky-smoke" in (ROOT / ".github/workflows/windows-release.yml").read_text()
    import subprocess
    out = subprocess.run([sys.executable, "-m", "theroadragetrip.server", "--planet-sky-smoke"], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert [b["id"] for b in json.loads(out.splitlines()[-1])["bodies"]] == BODIES
    # the displayed credit exists in all three languages
    i18n = (ROOT / "godot/i18n.gd").read_text()
    assert len(re.findall(r'"credits_planet_sky": "[^"]*PyEphem[^"]*DE421[^"]*Skyfield', i18n)) == 3
    assert "credits_planet_sky" in (ROOT / "godot/startup.gd").read_text()
    notes = (ROOT / "docs/planet-sky.md").read_text()
    for needed in ("10ad0a3", "PyEphem", "DE421", "MIT", "refraction", "0.1", "Mallama", "B-V"):
        assert needed in notes, needed

    # real scenarios chosen from computed ephemerides, covering all six bodies and the controls
    import visual_test  # the harness merges `extends`, as a run does
    registry = visual_test.scenarios()
    found = {i: s for i, s in registry.items() if i.startswith("planets_") and "planets" in s.get("requires", {})}
    assert {"planets_dark_rural_uranus", "planets_dark_rural_outer", "planets_twilight_inner", "planets_urban_faint", "planets_urban_bright",
            "planets_below_horizon_control", "planets_day_control", "planets_overcast_control", "planets_time_shift", "planets_rotated_view"} <= set(found)
    from theroadragetrip.geo import meters_to_latlon
    covered = set()
    for scenario_id, scenario in found.items():
        request = scenario["requires"]["planets"]
        assert scenario.get("weather") == "clear" and scenario["start_time"] < "2027" and scenario["start_time"] >= "2025-11"
        lat, lon = meters_to_latlon(*scenario["pose"][:2])
        state = planets.planet_sky_state(datetime.fromisoformat(scenario["start_time"]), lat, lon, 0)
        bodies = {b["id"]: b for b in state["bodies"]}
        assert state["supported"] and list(bodies) == BODIES, scenario_id
        for name in request.get("visible", []):
            assert bodies[name]["alt"] >= request.get("min_alt", 8.0), (scenario_id, name)
            covered.add(name)
        for name in request.get("below_horizon", []):
            assert bodies[name]["alt"] < 0, (scenario_id, name)
        assert request.get("visible") or request.get("hidden_all"), scenario_id  # an empty sky must not pass
        assert not (set(request.get("visible", [])) & set(request.get("hidden", []))), scenario_id
    assert covered == set(BODIES)
    assert all(s["engine_args"] == ["--rendering-method", "forward_plus", "--rendering-driver", "vulkan"] for s in found.values())
    outer, rotated, shifted = (registry[i] for i in ("planets_dark_rural_outer", "planets_rotated_view", "planets_time_shift"))
    assert rotated["start_time"] == outer["start_time"] and rotated["pose"] == outer["pose"] and rotated["eye"]["yaw"] != outer["eye"]["yaw"]
    assert shifted["pose"] == outer["pose"] and shifted["eye"] == outer["eye"] and shifted["start_time"] > outer["start_time"]
    lat, lon = meters_to_latlon(*outer["pose"][:2])
    mars = [next(b for b in planets.planet_sky_state(datetime.fromisoformat(t["start_time"]), lat, lon)["bodies"] if b["id"] == "mars") for t in (outer, shifted)]
    assert abs(mars[1]["az"] - mars[0]["az"]) > 10 and mars[1]["alt"] - mars[0]["alt"] > 4, "the time shift moves Mars on the sky"


def _channel(x: float, mu: float, low: float, high: float) -> float:
    t = (x - mu) / (low if x < mu else high)
    return math.exp(-0.5 * t * t)


def _linear_rgb(kelvin: float) -> list:
    """Blackbody to linear sRGB through the Wyman, Sloan and Shirley analytic CIE 1931 fit."""
    x = y = z = 0.0
    for nm in range(360, 831, 2):
        weight = 1.0 / (nm ** 5 * (math.exp(1.4388e7 / (nm * kelvin)) - 1.0))
        x += weight * (1.056 * _channel(nm, 599.8, 37.9, 31.0) + 0.362 * _channel(nm, 442.0, 16.0, 26.7) - 0.065 * _channel(nm, 501.1, 20.4, 26.2))
        y += weight * (0.821 * _channel(nm, 568.8, 46.9, 40.5) + 0.286 * _channel(nm, 530.9, 16.3, 31.1))
        z += weight * (1.217 * _channel(nm, 437.0, 11.8, 36.0) + 0.681 * _channel(nm, 459.0, 26.0, 13.8))
    return [3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z, 0.0557 * x - 0.2040 * y + 1.0570 * z]


def test_colours_follow_published_b_minus_v():
    """Mallama, Krobusek and Pavlov 2017 (Icarus 282, Table 3: B minus V of the reference magnitudes; the Sun is
    B 26.10 - V 26.75 = 0.65) -> Ballesteros 2012 temperature -> blackbody chromaticity, Sun balanced to white."""
    import re
    published = {"mercury": (0.28, -0.69), "venus": (-3.68, -4.38), "mars": (-0.24, -1.60), "jupiter": (-8.54, -9.40), "saturn": (-7.84, -8.91), "uranus": (-6.61, -7.11)}
    text = (ROOT / "godot/planet_sky.gd").read_text()
    in_game_bv = [float(v) for v in re.search(r"B_MINUS_V := \[([^\]]*)\]", text)[1].split(",")]
    colours = re.findall(r"Color\(([\d.]+), ([\d.]+), ([\d.]+)\)", re.search(r"const COLORS := \[(.*?)\]\n", text, re.S)[1])
    assert len(colours) == 6
    sun_bv = -26.10 - -26.75
    temperature = lambda bv: 4600 * (1 / (0.92 * bv + 1.7) + 1 / (0.92 * bv + 0.62))
    sun = _linear_rgb(temperature(sun_bv))
    for (name, (b, v)), bv, rgb in zip(published.items(), in_game_bv, colours):
        assert bv == pytest.approx(b - v, abs=0.006), name
        balanced = [c / s for c, s in zip(_linear_rgb(temperature(bv)), sun)]
        expected = [c / max(balanced) for c in balanced]
        assert [float(c) for c in rgb] == pytest.approx(expected, abs=0.01), name
    reddest = {n: float(c[2]) / float(c[0]) for n, c in zip(published, colours)}
    assert reddest["mars"] < reddest["saturn"] < reddest["mercury"] < reddest["jupiter"] < reddest["venus"] and float(colours[5][2]) > float(colours[5][0])
    assert all(float(c[2]) > 0.4 for c in colours), "subtle, not a saturated tint"
