"""rrt-018-shadows: the sun's azimuth from the same model as its altitude,
checked against an independent reference (NOAA's general solar position
equations: Julian centuries, true longitude, obliquity - not the game's
Spencer/Cooper formulas), and the map's grid azimuth against pyproj."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from theroadragetrip.calendar import finnish_utc, grid_azimuth, solar_position_on

OULU = (65.0121, 25.4651)
HELSINKI = (60.1699, 24.9384)
UTSJOKI = (69.9079, 27.0265)


def noaa_altitude_azimuth(moment_utc: datetime, latitude: float, longitude: float):
    """NOAA solar calculator (spreadsheet) equations, degrees."""
    jd = (moment_utc - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400.0 + 2451545.0
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(math.radians(m)) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(math.radians(2 * m)) * (0.019993 - 0.000101 * t) + math.sin(math.radians(3 * m)) * 0.000289)
    apparent = l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * t))
    obliquity = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliquity += 0.00256 * math.cos(math.radians(125.04 - 1934.136 * t))
    declination = math.asin(math.sin(math.radians(obliquity)) * math.sin(math.radians(apparent)))
    y = math.tan(math.radians(obliquity / 2)) ** 2
    eot = 4 * math.degrees(y * math.sin(2 * math.radians(l0)) - 2 * e * math.sin(math.radians(m))
                           + 4 * e * y * math.sin(math.radians(m)) * math.cos(2 * math.radians(l0))
                           - 0.5 * y * y * math.sin(4 * math.radians(l0)) - 1.25 * e * e * math.sin(2 * math.radians(m)))
    minutes = moment_utc.hour * 60 + moment_utc.minute + moment_utc.second / 60
    hour_angle = math.radians((minutes + eot + 4 * longitude) / 4 - 180)
    lat = math.radians(latitude)
    zenith = math.acos(math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(declination) * math.cos(hour_angle))
    azimuth = math.degrees(math.atan2(math.sin(hour_angle), math.cos(hour_angle) * math.sin(lat) - math.tan(declination) * math.cos(lat))) + 180
    return 90 - math.degrees(zenith), azimuth % 360


def game(local: datetime, place):
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return solar_position_on(local.date(), seconds, *place)


def azimuth_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


@pytest.mark.parametrize("local, place", [
    (datetime(2026, 6, 21, 7, 0), OULU),  # summer morning
    (datetime(2026, 6, 21, 13, 30), OULU),  # summer noon
    (datetime(2026, 6, 21, 21, 0), OULU),  # summer evening, north-west
    (datetime(2026, 6, 22, 1, 0), UTSJOKI),  # midnight sun, due north
    (datetime(2026, 12, 21, 12, 15), HELSINKI),  # winter noon, low
    (datetime(2026, 3, 20, 9, 0), HELSINKI),  # equinox morning
    (datetime(2026, 9, 23, 16, 0), OULU),  # equinox afternoon
    (datetime(2026, 10, 17, 2, 0), OULU),  # night: below the horizon
])
def test_the_sun_agrees_with_an_independent_solar_position_algorithm(local, place):
    altitude, azimuth = game(local, place)
    ref_altitude, ref_azimuth = noaa_altitude_azimuth(finnish_utc(local).replace(tzinfo=timezone.utc), *place)
    # The game's model (Cooper's declination, Spencer's equation of time)
    # is good to about 1.5 degrees; enough for shadows and daylight.
    assert altitude == pytest.approx(ref_altitude, abs=1.5)
    assert azimuth_gap(azimuth, ref_azimuth) < 1.5


def test_azimuth_quadrants_through_a_summer_day_in_oulu():
    def azimuth_at(hour):
        return game(datetime(2026, 6, 21, hour, 0), OULU)[1]

    assert 0 < azimuth_at(3) < 90  # north-east at sunrise
    assert 90 < azimuth_at(9) < 180  # south-east
    assert 180 < azimuth_at(17) < 270  # south-west
    assert 270 < azimuth_at(22) < 360  # north-west at sunset


def test_winter_noon_is_lower_than_summer_noon():
    winter = game(datetime(2026, 12, 21, 12, 15), HELSINKI)[0]
    summer = game(datetime(2026, 6, 21, 13, 25), HELSINKI)[0]
    assert 5 < winter < 8 and 52 < summer < 54


def test_the_sun_moves_continuously_minute_by_minute():
    start = datetime(2026, 6, 21, 0, 0)
    previous = game(start, OULU)
    for minute in range(1, 24 * 60):
        current = game(start + timedelta(minutes=minute), OULU)
        assert abs(current[0] - previous[0]) < 0.3
        assert azimuth_gap(current[1], previous[1]) < 0.6  # no jump, even through north
        previous = current


def test_below_the_horizon_and_near_zenith_stay_finite():
    for place in (OULU, HELSINKI, UTSJOKI, (0.0, 25.0), (23.44, 25.0)):
        for hour in range(24):
            altitude, azimuth = game(datetime(2026, 6, 21, hour, 0), place)
            assert math.isfinite(altitude) and -90 <= altitude <= 90 and 0 <= azimuth < 360


@pytest.mark.parametrize("place", [OULU, HELSINKI, (62.6, 29.76)])  # Joensuu: east of 27 E
def test_grid_azimuth_is_measured_from_the_map_s_north(place):
    """True north in map metres (EPSG:3067): a step north along the meridian
    lands at grid azimuth -convergence; pyproj, not the formula, decides."""
    from pyproj import Transformer

    to_map = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
    x0, y0 = to_map.transform(place[1], place[0])
    x1, y1 = to_map.transform(place[1], place[0] + 0.01)
    true_north_on_the_map = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360
    assert azimuth_gap(grid_azimuth(0.0, *place), true_north_on_the_map) < 0.05
