from datetime import datetime

from theroadragetrip.fare import calculate_fare_cents, format_euros, starting_fee_cents, tip_cents_from_happiness


def test_starting_fee_weekday_daytime_is_eight_euros():
    assert starting_fee_cents(datetime(2026, 9, 21, 6, 0)) == 800
    assert starting_fee_cents(datetime(2026, 9, 21, 19, 59)) == 800


def test_starting_fee_saturday_daytime_is_eight_euros():
    assert starting_fee_cents(datetime(2026, 9, 26, 6, 0)) == 800
    assert starting_fee_cents(datetime(2026, 9, 26, 15, 59)) == 800


def test_starting_fee_is_twelve_fifty_at_other_times():
    assert starting_fee_cents(datetime(2026, 9, 21, 20, 0)) == 1250
    assert starting_fee_cents(datetime(2026, 9, 26, 16, 0)) == 1250
    assert starting_fee_cents(datetime(2026, 9, 27, 12, 0)) == 1250


def test_fare_adds_distance_and_time_charges():
    # €8.00 start + 1 km * €1.50 + 10 min * €0.92 = €18.70.
    assert calculate_fare_cents(1000.0, 600.0, datetime(2026, 9, 21, 12, 0)) == 1870


def test_fare_is_always_rounded_up_to_next_ten_cents():
    # €8.00 + €0.15 distance + €0.92 time = €9.07 -> €9.10.
    assert calculate_fare_cents(100.0, 60.0, datetime(2026, 9, 21, 12, 0)) == 910


def test_money_format_uses_local_decimal_separator():
    assert format_euros(1870, "fi") == "18,70 €"
    assert format_euros(1870, "en") == "18.70 €"


def test_tip_ranges_from_zero_to_ten_euros_with_happiness():
    assert tip_cents_from_happiness(-50.0) == 0
    assert tip_cents_from_happiness(0.0) == 0
    assert tip_cents_from_happiness(50.0) == 500
    assert tip_cents_from_happiness(100.0) == 1000
    assert tip_cents_from_happiness(150.0) == 1000
