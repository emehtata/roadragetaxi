from datetime import date, datetime

from theroadragetrip.moon import moon_info_on, moon_position_at


def _minutes(moment):
    return moment.hour * 60 + moment.minute


def test_oulu_moon_events_and_phase_match_reference_day():
    info = moon_info_on(date(2026, 10, 21), 65.0121, 25.4651)

    assert abs(_minutes(info.rise) - (17 * 60 + 8)) <= 15
    assert abs(_minutes(info.transit) - (21 * 60 + 36)) <= 15
    assert abs(_minutes(info.set) - 43) <= 15
    assert info.phase == "waxing gibbous"
    assert abs(info.illumination - 0.786) < 0.05


def test_high_latitude_day_can_have_no_rise_or_set():
    info = moon_info_on(date(2026, 10, 16), 65.0121, 25.4651)

    assert info.rise is None and info.set is None
    assert info.transit.date() == date(2026, 10, 16)


def test_moon_position_has_physical_ranges():
    altitude, azimuth, illumination = moon_position_at(datetime(2026, 10, 21, 20), 65.0121, 25.4651)
    assert -90.0 <= altitude <= 90.0
    assert 0.0 <= azimuth < 360.0
    assert 0.0 <= illumination <= 1.0
