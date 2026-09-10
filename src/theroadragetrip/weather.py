"""Dynamic weather state: precipitation type and road wetness.

Kept separate from rendering (render/*.py reads this, doesn't own it) -
same relationship render/ already has with TaxiManager/PedestrianManager -
so rain particles, wet-road tint, puddles and splashes all read one shared
WeatherSystem instead of each tracking their own notion of "is it raining".
"""
from enum import Enum


class WeatherType(str, Enum):
    CLEAR = "clear"
    RAIN = "rain"
    SNOW = "snow"  # placeholder - not implemented yet (see WEATHER_RAIN.md #10)


# Wetness dynamics, in game-seconds - matches the game clock's own hour/
# minute units regardless of how fast time_scale is currently running it
# (main()'s time_scale is 1x with a passenger, 60x without - see
# main()'s game_time_seconds update). Rain wets faster than drying dries:
# a road visibly darkens within minutes of rain starting but takes longer
# to fully dry once it stops.
RAIN_WETTING_DURATION_S = 10.0 * 60.0  # 0 -> 1 wetness over 10 game-minutes of rain
DRY_DURATION_S = 60.0 * 60.0  # 1 -> 0 wetness over 1 game-hour (WEATHER_RAIN.md #7)


class WeatherSystem:
    """Owns the current weather type and road wetness.

    Everything else (rain particles, wet-road tint, puddles, splashes)
    reads .weather_type / .wetness from this rather than tracking their
    own state or reacting directly to keyboard input.
    """

    def __init__(self, weather_type: WeatherType = WeatherType.CLEAR) -> None:
        self.weather_type = weather_type
        self.wetness = 0.0  # 0.0 dry .. 1.0 fully wet; independent of weather_type -
        # CLEAR does not imply dry, e.g. right after rain stops (see #9).

    @property
    def is_precipitating(self) -> bool:
        return self.weather_type in (WeatherType.RAIN, WeatherType.SNOW)

    def toggle_rain(self) -> None:
        """Debug toggle (F8): CLEAR <-> RAIN."""
        self.weather_type = WeatherType.CLEAR if self.weather_type == WeatherType.RAIN else WeatherType.RAIN

    def update(self, game_dt: float) -> None:
        """Advance wetness by one frame's worth of game time.

        `game_dt` is dt * time_scale - the same delta main() uses to
        advance game_time_seconds - so drying/wetting tracks the game
        clock, not wall-clock time.
        """
        if game_dt <= 0.0:
            return
        if self.weather_type == WeatherType.RAIN:
            self.wetness = min(1.0, self.wetness + game_dt / RAIN_WETTING_DURATION_S)
        else:
            self.wetness = max(0.0, self.wetness - game_dt / DRY_DURATION_S)
