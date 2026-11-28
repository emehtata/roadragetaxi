"""docs/specs/solar-eclipse-sky.md: topocentric solar eclipse state (PyEphem), offline."""
from __future__ import annotations

import math
import socket
from datetime import datetime

import pytest

from theroadragetrip import eclipse

SITE_A = (63.77, 29.63)  # three fixed test sites, none a city centre: partial 2026, total 2026, partial 2025
SITE_B = (40.97, -2.47)
SITE_C = (61.91, 27.63)


def at(utc: str, place: tuple, **kwargs) -> dict:
    """The state for a UTC time (the API takes Finnish local time: summer +3, March 29 2025 +2)."""
    moment = datetime.fromisoformat(utc)
    local = moment.replace(hour=moment.hour + (3 if moment.month > 4 else 2))
    return eclipse.solar_eclipse_state(local, *place, **kwargs)


def test_oulu_2026_partial():
    state = at("2026-08-12T17:45:00", SITE_A)
    assert state["active"] and state["phase"] == "partial"
    assert state["magnitude"] == pytest.approx(0.831, abs=0.01)
    assert state["sun_alt"] == pytest.approx(2.9, abs=0.5)


def test_zaragoza_2026_total():
    state = at("2026-08-12T18:31:00", SITE_B)
    assert state["phase"] == "total" and state["magnitude"] >= 1.0 and state["obscuration"] == 1.0


def test_helsinki_2025_partial():
    state = at("2025-03-29T11:38:00", SITE_C)
    assert state["phase"] == "partial" and state["magnitude"] == pytest.approx(0.29, abs=0.02)


def test_no_eclipse_next_day():
    state = at("2026-08-13T17:45:00", SITE_A)
    assert not state["active"] and state["phase"] == "none" and state["obscuration"] == 0


def test_obscuration_matches_integration():
    r_sun, r_moon, n = 0.2631, 0.2721, 20000
    for step in range(0, 106, 5):
        separation = abs(r_sun + r_moon - step / 100 * 2 * r_sun)  # beyond the centred Moon (1.017) it mirrors
        covered = 0.0  # per vertical strip across the Sun: the overlap of the two discs' chords
        for i in range(n):
            x = -r_sun + (i + 0.5) / n * 2 * r_sun
            sun_half = math.sqrt(max(0.0, r_sun ** 2 - x * x))
            moon_half = math.sqrt(max(0.0, r_moon ** 2 - (x - separation) ** 2))
            covered += max(0.0, 2 * min(sun_half, moon_half)) * (2 * r_sun / n) if moon_half > 0 else 0.0
        assert eclipse.obscuration(separation, r_sun, r_moon) == pytest.approx(covered / (math.pi * r_sun ** 2), abs=0.005), step


def test_offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    eclipse._solar_eclipse_state.cache_clear()
    assert at("2026-08-12T17:45:00", SITE_A)["active"]
