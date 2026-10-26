import pytest

from theroadragetrip.weather import (
    DRY_DURATION_S,
    RAIN_WETTING_DURATION_S,
    WeatherSystem,
    WeatherType,
    AUTUMN_WINTER_PERIOD_RANGE,
    AUTUMN_WINTER_PRECIPITATION_CHANCE,
    SLUSH_MAX_TEMPERATURE_C,
    SNOW_MAX_TEMPERATURE_C,
    THUNDER_CHANCE_BY_SEASON,
)
from theroadragetrip.calendar import Season


def test_weather_rng_is_not_reseeded_identically_at_each_start(monkeypatch):
    import theroadragetrip.weather as weather_module

    calls = []
    real_random = weather_module.random.Random
    monkeypatch.setattr(weather_module.random, "Random", lambda *args: (calls.append(args), real_random(1))[1])

    WeatherSystem(season=Season.AUTUMN)

    assert calls == [()]


def test_weather_reports_time_left_in_current_period():
    weather = WeatherSystem(season=Season.AUTUMN)
    before = weather.seconds_until_weather_change

    weather.update(60.0, 0.0)

    assert weather.seconds_until_weather_change == before - 60.0
    weather.toggle_rain()
    assert weather.seconds_until_weather_change is None


def test_snow_accumulates_plows_clear_only_passed_cells_and_snow_returns():
    weather = WeatherSystem(WeatherType.SNOW, Season.WINTER)
    weather.update(1800.0, 0.0, outside_temperature_c=-5.0)
    assert weather.road_snow == pytest.approx(3.0)
    weather.plow_road((1.0, 1.0), (31.0, 1.0))
    assert set(weather.plowed_cells) == {(0, 0), (1, 0), (2, 0), (3, 0)}
    assert weather.road_snow - weather.plowed_cells[(1, 0)] == 0.0
    weather.update(600.0, 0.0, outside_temperature_c=-5.0)
    assert weather.road_snow - weather.plowed_cells[(1, 0)] == pytest.approx(1.0)


def test_road_snow_persists_in_cold_and_melts_above_freezing():
    weather = WeatherSystem(WeatherType.SNOW, Season.WINTER)
    weather.update(1800.0, 0.0, outside_temperature_c=-5.0)
    weather.plow_road((0.0, 0.0), (1.0, 0.0))
    weather.weather_type = WeatherType.CLEAR
    weather.update(1800.0, 0.0, outside_temperature_c=-5.0)
    assert weather.road_snow == pytest.approx(3.0)
    weather.update(5400.0, 0.0, outside_temperature_c=5.0)
    assert weather.road_snow == 0.0
    assert not weather.plowed_cells


def test_starts_clear_and_dry():
    weather = WeatherSystem()
    assert weather.weather_type == WeatherType.CLEAR
    assert weather.wetness == 0.0
    assert weather.is_precipitating is False


def test_thunderstorm_chances_are_seasonal():
    assert THUNDER_CHANCE_BY_SEASON == {
        Season.WINTER: 0.0,
        Season.SPRING: 0.1,
        Season.SUMMER: 0.5,
        Season.AUTUMN: 0.1,
    }


@pytest.mark.parametrize(
    ("season", "roll", "expected"),
    [
        (Season.SUMMER, 0.49, True),
        (Season.SUMMER, 0.51, False),
        (Season.SPRING, 0.09, True),
        (Season.AUTUMN, 0.09, True),
        (Season.WINTER, 0.0, False),
    ],
)
def test_thunder_is_chosen_once_for_rain_period(season, roll, expected):
    weather = WeatherSystem(WeatherType.CLEAR, season=season)
    weather.weather_type = WeatherType.RAIN
    weather._rng = type(
        "ThunderRoll",
        (),
        {"random": lambda self: roll, "uniform": lambda self, low, high: high},
    )()

    weather._roll_thunderstorm()

    assert weather.is_thunderstorm is expected


def test_thunderstorm_emits_and_fades_lightning_flash():
    weather = WeatherSystem(WeatherType.RAIN, season=Season.SUMMER)
    weather.is_thunderstorm = True
    weather._lightning_timer = 0.01

    weather.update(0.0, 0.02)
    event_id = weather.lightning_event_id
    assert event_id == 1
    assert weather.lightning_intensity == 1.0

    weather.update(0.0, 0.3)
    assert weather.lightning_intensity == 0.0


def test_forecast_samples_temperature_without_advancing_live_weather():
    weather = WeatherSystem(WeatherType.RAIN, season=Season.SPRING)

    forecast = weather.forecast([0.0, 3.0, 8.0], interval_s=6.0 * 60.0 * 60.0)

    assert [condition for condition, _ in forecast] == [
        WeatherType.SNOW, WeatherType.SLUSH, WeatherType.RAIN,
    ]
    assert weather.weather_type == WeatherType.RAIN
    assert weather._outside_temperature_c is None


def test_winter_forecast_continues_after_current_fmi_observation():
    weather = WeatherSystem(season=Season.WINTER)
    weather._follow_observation("", False)

    forecast = weather.forecast([-5.0, -4.0, -3.0], interval_s=6.0 * 60.0 * 60.0)

    assert len(forecast) == 3
    assert weather._following_observation is True


def test_toggle_rain_flips_clear_and_rain():
    weather = WeatherSystem()
    weather.toggle_rain()
    assert weather.weather_type == WeatherType.RAIN
    assert weather.is_precipitating is True
    weather.toggle_rain()
    assert weather.weather_type == WeatherType.CLEAR


def test_automatic_autumn_weather_changes_from_clear_to_rain():
    weather = WeatherSystem(season=Season.AUTUMN)
    weather._rng = type("RainRoll", (), {"random": lambda self: 0.1, "uniform": lambda self, low, high: 3600.0})()
    weather._start_autumn_or_winter_period()
    assert weather.weather_type == WeatherType.RAIN
    assert weather._weather_timer == 3600.0


def test_automatic_winter_weather_has_fifty_percent_snow_periods_up_to_one_day():
    assert AUTUMN_WINTER_PRECIPITATION_CHANCE == 0.5
    assert AUTUMN_WINTER_PERIOD_RANGE == (0.0, 24.0 * 60.0 * 60.0)
    weather = WeatherSystem(season=Season.WINTER)
    weather._rng = type("SnowRoll", (), {"random": lambda self: 0.1, "uniform": lambda self, low, high: high})()
    weather._start_autumn_or_winter_period()
    assert weather.weather_type == WeatherType.SNOW
    assert weather._weather_timer == 24.0 * 60.0 * 60.0
    weather._rng = type("ClearRoll", (), {"random": lambda self: 0.9, "uniform": lambda self, low, high: 7200.0})()
    weather._start_autumn_or_winter_period()
    assert weather.weather_type == WeatherType.CLEAR


def test_cold_rain_becomes_snow_or_slush_without_winter_ground_cover():
    assert SNOW_MAX_TEMPERATURE_C == 1.0
    assert SLUSH_MAX_TEMPERATURE_C == 5.0
    weather = WeatherSystem(WeatherType.RAIN, season=Season.SPRING)

    weather.update(1.0, 0.0, outside_temperature_c=0.0)
    assert weather.weather_type == WeatherType.SNOW
    assert weather.season == Season.SPRING

    weather.update(1.0, 0.0, outside_temperature_c=3.0)
    assert weather.weather_type == WeatherType.SLUSH

    weather.update(1.0, 0.0, outside_temperature_c=5.0)
    assert weather.weather_type == WeatherType.RAIN


def test_slush_wets_the_road_like_rain():
    weather = WeatherSystem(WeatherType.RAIN, season=Season.AUTUMN)
    weather.update(
        RAIN_WETTING_DURATION_S / 2.0,
        0.0,
        outside_temperature_c=3.0,
    )
    assert weather.weather_type == WeatherType.SLUSH
    assert 0.49 < weather.wetness < 0.51


def test_rain_wets_over_its_full_duration_and_clamps():
    weather = WeatherSystem(WeatherType.RAIN)
    weather.update(RAIN_WETTING_DURATION_S / 2.0, 0.0)
    assert 0.49 < weather.wetness < 0.51
    weather.update(RAIN_WETTING_DURATION_S, 0.0)  # well past full wetting
    assert weather.wetness == 1.0


def test_clear_dries_over_one_in_game_hour_and_clamps():
    """WEATHER_RAIN.md #7: drying must take ~1 in-game hour, tracked via
    game-seconds (dt * time_scale), not wall-clock time."""
    weather = WeatherSystem(WeatherType.CLEAR)
    weather.wetness = 1.0
    weather.update(DRY_DURATION_S / 2.0, 0.0)
    assert 0.49 < weather.wetness < 0.51
    weather.update(DRY_DURATION_S, 0.0)  # well past fully dry
    assert weather.wetness == 0.0


def test_wet_road_freezes_below_zero_and_does_not_dry_until_thawed():
    weather = WeatherSystem(WeatherType.CLEAR, season=Season.AUTUMN)
    weather.wetness = 0.8

    weather.update(DRY_DURATION_S, 0.0, outside_temperature_c=-0.1)
    assert weather.road_ice_fraction == 0.8
    assert weather.wetness == 0.8

    weather.update(DRY_DURATION_S / 2.0, 0.0, outside_temperature_c=1.0)
    assert weather.road_ice_fraction == 0.0
    assert 0.29 < weather.wetness < 0.31


def test_wetness_persists_independently_of_weather_type():
    """WEATHER_RAIN.md #9: CLEAR does not imply dry."""
    weather = WeatherSystem(WeatherType.RAIN)
    weather.update(RAIN_WETTING_DURATION_S, 0.0)
    assert weather.wetness == 1.0
    weather.toggle_rain()
    assert weather.weather_type == WeatherType.CLEAR
    assert weather.wetness == 1.0  # unchanged until update() ticks drying


def test_rain_resumes_wetting_from_current_level_not_from_zero():
    """WEATHER_RAIN.md acceptance test #7: toggling rain back on before
    fully dry must keep increasing wetness, not reset it."""
    weather = WeatherSystem(WeatherType.RAIN)
    weather.update(RAIN_WETTING_DURATION_S / 2.0, 0.0)
    partial = weather.wetness
    weather.toggle_rain()  # CLEAR: starts drying
    weather.update(1.0, 0.0)
    assert weather.wetness < partial
    dried_a_bit = weather.wetness
    weather.toggle_rain()  # RAIN again
    weather.update(1.0, 0.0)
    assert weather.wetness > dried_a_bit


def test_the_road_starts_as_the_last_hours_weather_left_it():
    """The initial wetness from the last hour (5-minute steps, oldest first,
    the first one deciding whether the hour began wet), with the game's own
    wetting (10 min) and drying (1 h)."""
    from theroadragetrip.weather import WeatherSystem, WeatherType, wetness_after

    assert wetness_after([True] * 2, 300.0) == 1.0  # 10 minutes of rain: soaked
    assert abs(wetness_after([False] * 6, 300.0, 1.0) - 0.5) < 1e-9  # half an hour dry after rain
    assert wetness_after([None, None], 300.0, 0.4) == 0.4  # nothing known: as it was

    weather = WeatherSystem(weather_type=WeatherType.CLEAR)
    weather.settle_initial_wetness([True] + [True] * 6 + [False] * 6)  # rained, stopped half an hour ago
    assert abs(weather.wetness - 0.5) < 1e-9
    weather.settle_initial_wetness([False] * 13)  # a dry hour
    assert weather.wetness == 0.0
    raining = WeatherSystem(weather_type=WeatherType.RAIN)
    raining.settle_initial_wetness([])  # no history: raining now means it has rained a while
    assert raining.wetness == 1.0
