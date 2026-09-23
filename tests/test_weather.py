import pytest

from theroadragetrip.weather import (
    DRY_DURATION_S,
    RAIN_PARTICLE_COUNT,
    RAIN_WETTING_DURATION_S,
    SPLASH_LIFETIME_S,
    SPLASH_POOL_MAX,
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


def test_rain_particle_pool_is_fixed_size_and_stays_in_bounds():
    weather = WeatherSystem(WeatherType.RAIN)
    assert len(weather.rain_particles) == RAIN_PARTICLE_COUNT
    for _ in range(500):  # many frames, including several full wrap-arounds
        weather.update(0.0, 1.0 / 60.0)
    assert len(weather.rain_particles) == RAIN_PARTICLE_COUNT  # never reallocated
    for x, y, factor in weather.rain_particles:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
        assert factor > 0.0


def test_rain_particles_move_downward_each_frame():
    weather = WeatherSystem(WeatherType.RAIN)
    before = [y for _, y, _ in weather.rain_particles]
    weather.update(0.0, 1.0 / 60.0)
    after = [y for _, y, _ in weather.rain_particles]
    # A wrapped-around particle wouldn't necessarily be "after > before", so
    # just confirm motion happened (positions changed) rather than assert
    # strict monotonic increase for every particle.
    assert before != after


def test_rain_particles_freeze_when_weather_is_clear():
    """Regression target: particles must not keep animating (or be updated
    at all) while it isn't raining - matches "stop spawning new rain"."""
    weather = WeatherSystem(WeatherType.CLEAR)
    before = [tuple(p) for p in weather.rain_particles]
    weather.update(0.0, 1.0 / 60.0)
    after = [tuple(p) for p in weather.rain_particles]
    assert before == after


def test_spawn_splash_clamps_strength_and_starts_at_zero_age():
    weather = WeatherSystem()
    weather.spawn_splash(10.0, 20.0, strength=5.0)  # out-of-range, must clamp to 1.0
    x, y, age, strength = weather.splashes[0]
    assert (x, y, age, strength) == (10.0, 20.0, 0.0, 1.0)


def test_splash_pool_is_capped():
    """WEATHER_RAIN.md #5: pooled, not unbounded object creation."""
    weather = WeatherSystem()
    for i in range(SPLASH_POOL_MAX + 20):
        weather.spawn_splash(float(i), 0.0, 1.0)
    assert len(weather.splashes) == SPLASH_POOL_MAX


def test_splash_expires_after_its_lifetime():
    weather = WeatherSystem()
    weather.spawn_splash(0.0, 0.0, 1.0)
    weather.update(0.0, SPLASH_LIFETIME_S - 0.01)
    assert len(weather.splashes) == 1
    weather.update(0.0, 0.02)  # crosses the lifetime threshold
    assert weather.splashes == []
