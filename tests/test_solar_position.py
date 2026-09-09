"""Tests for the real-time-throttled sun position cache."""
from theroadragetrip.render import common as render_common


def test_solar_position_is_throttled_by_real_time_not_game_time(monkeypatch):
    """Regression: caching this by game-time bucket alone could refresh as
    often as every ~15 real seconds while driving without a passenger
    (time_scale runs game time at 60x - see main()'s time_scale), since
    900 game-seconds / 60 = 15 real seconds. Every lighting effect derived
    from this (day/night tint, street light brightness, headlight glow)
    rebuilds along with it. Real-time-based throttling keeps a predictable
    ~20s cadence regardless of how fast game time is running."""
    render_common._solar_position_cache.clear()
    fake_now = [1000.0]
    monkeypatch.setattr(render_common.time, "monotonic", lambda: fake_now[0])

    first = render_common.solar_altitude_and_events(0.0, 65.0, 25.0)
    # A wildly different game_time_seconds within the same real-time
    # window must still return the cached value, not recompute.
    second = render_common.solar_altitude_and_events(12345.0, 65.0, 25.0)
    assert second == first

    # Still short of the throttle interval: still cached.
    fake_now[0] += render_common.SOLAR_UPDATE_INTERVAL_SECONDS - 0.1
    assert render_common.solar_altitude_and_events(12345.0, 65.0, 25.0) == first

    # Real time advances past the throttle interval: now it recomputes.
    fake_now[0] += 0.2
    third = render_common.solar_altitude_and_events(12345.0, 65.0, 25.0)
    assert third != first
