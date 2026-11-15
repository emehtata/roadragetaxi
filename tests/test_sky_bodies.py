"""docs/specs/sun-moon-in-sky.md: the Sun and Moon positions the sky discs are drawn at."""
from datetime import date, datetime

from theroadragetrip.calendar import solar_position_on
from theroadragetrip.moon import moon_position_at

OULU = (65.01, 25.47)


def test_oulu_sun_position_reference():
    # NOAA solar calculator algorithm (Meeus), cross-checked with PyEphem's airless Sun.
    altitude, azimuth = solar_position_on(date(2026, 6, 21), 13 * 3600, *OULU)
    assert abs(altitude - 48.30) < 0.5 and abs(azimuth - 173.12) < 1.0
    altitude, azimuth = solar_position_on(date(2026, 12, 21), 12.5 * 3600, *OULU)
    assert abs(altitude - 1.51) < 0.5 and abs(azimuth - 183.17) < 1.0


def test_oulu_moon_position_matches_ephem_reference():
    # JPL Horizons (airless, geodetic 25.47 E 65.01 N): 2026-10-21 18:00 UTC az 170.87, alt 13.72.
    altitude, azimuth, illumination = moon_position_at(datetime(2026, 10, 21, 21, 0), *OULU)
    assert abs(altitude - 13.72) < 0.5 and abs(azimuth - 170.87) < 0.5
    assert abs(illumination - 0.78) < 0.02


def test_state_calendar_carries_sky_bodies(tmp_path, monkeypatch):
    from theroadragetrip import protocol
    from tests.test_server_headless import _build_server

    server = _build_server(tmp_path, monkeypatch)
    message = protocol.build_state_message(
        tick=1, world=server.world, car=server.car, on_foot=True, player_pedestrian=server.world.player_pedestrian,
        game_time_seconds=server._game_time_seconds, camx=0.0, camy=0.0, rage_power=0.0, water_elapsed=0.0,
        calendar=server.calendar_state())
    calendar = protocol.decode(protocol.encode(message))["state"]["calendar"]
    for field in ("sun_altitude_deg", "sun_azimuth_deg", "moon_altitude_deg", "moon_azimuth_deg", "moon_illumination"):
        assert isinstance(calendar[field], (int, float)), field
