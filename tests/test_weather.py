from theroadragetrip.weather import (
    DRY_DURATION_S,
    RAIN_WETTING_DURATION_S,
    WeatherSystem,
    WeatherType,
)


def test_starts_clear_and_dry():
    weather = WeatherSystem()
    assert weather.weather_type == WeatherType.CLEAR
    assert weather.wetness == 0.0
    assert weather.is_precipitating is False


def test_toggle_rain_flips_clear_and_rain():
    weather = WeatherSystem()
    weather.toggle_rain()
    assert weather.weather_type == WeatherType.RAIN
    assert weather.is_precipitating is True
    weather.toggle_rain()
    assert weather.weather_type == WeatherType.CLEAR


def test_rain_wets_over_its_full_duration_and_clamps():
    weather = WeatherSystem(WeatherType.RAIN)
    weather.update(RAIN_WETTING_DURATION_S / 2.0)
    assert 0.49 < weather.wetness < 0.51
    weather.update(RAIN_WETTING_DURATION_S)  # well past full wetting
    assert weather.wetness == 1.0


def test_clear_dries_over_one_in_game_hour_and_clamps():
    """WEATHER_RAIN.md #7: drying must take ~1 in-game hour, tracked via
    game-seconds (dt * time_scale), not wall-clock time."""
    weather = WeatherSystem(WeatherType.CLEAR)
    weather.wetness = 1.0
    weather.update(DRY_DURATION_S / 2.0)
    assert 0.49 < weather.wetness < 0.51
    weather.update(DRY_DURATION_S)  # well past fully dry
    assert weather.wetness == 0.0


def test_wetness_persists_independently_of_weather_type():
    """WEATHER_RAIN.md #9: CLEAR does not imply dry."""
    weather = WeatherSystem(WeatherType.RAIN)
    weather.update(RAIN_WETTING_DURATION_S)
    assert weather.wetness == 1.0
    weather.toggle_rain()
    assert weather.weather_type == WeatherType.CLEAR
    assert weather.wetness == 1.0  # unchanged until update() ticks drying


def test_rain_resumes_wetting_from_current_level_not_from_zero():
    """WEATHER_RAIN.md acceptance test #7: toggling rain back on before
    fully dry must keep increasing wetness, not reset it."""
    weather = WeatherSystem(WeatherType.RAIN)
    weather.update(RAIN_WETTING_DURATION_S / 2.0)
    partial = weather.wetness
    weather.toggle_rain()  # CLEAR: starts drying
    weather.update(1.0)
    assert weather.wetness < partial
    dried_a_bit = weather.wetness
    weather.toggle_rain()  # RAIN again
    weather.update(1.0)
    assert weather.wetness > dried_a_bit
