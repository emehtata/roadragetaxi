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
