"""The gig start time is clamped to the last calendar year."""
from datetime import date, datetime



from theroadragetrip.calendar import _one_calendar_year_ago, clamp_start_datetime


def test_calendar_picker_date_range_is_only_one_year_backwards():
    today = date(2026, 9, 23)
    assert _one_calendar_year_ago(today) == date(2025, 9, 23)
    assert clamp_start_datetime(datetime(2020, 1, 1, 12, 30), today) == datetime(2025, 9, 23, 12, 30)
    assert clamp_start_datetime(datetime(2027, 1, 1, 8, 15), today) == datetime(2026, 9, 23, 8, 15)


def test_calendar_picker_one_year_back_handles_leap_day():
    assert _one_calendar_year_ago(date(2024, 2, 29)) == date(2023, 2, 28)














