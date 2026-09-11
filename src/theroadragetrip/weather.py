"""Dynamic weather state: precipitation type and road wetness.

Kept separate from rendering (render/*.py reads this, doesn't own it) -
same relationship render/ already has with TaxiManager/PedestrianManager -
so rain particles, wet-road tint, puddles and splashes all read one shared
WeatherSystem instead of each tracking their own notion of "is it raining".

Rain particle positions are stored as screen-fraction coordinates (0..1
on each axis) rather than pixels, so this module never needs to import
SCREEN_W/SCREEN_H from render/ (render/ imports from game-state modules
like this one, not the other way around) - render/weather.py converts to
pixels at draw time using whatever screen size it's actually given.
"""
import random
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

# Rain particles animate in real time (wall-clock dt), not game time - at
# time_scale=60 (no passenger), game-time-driven rain would streak down the
# screen 60x too fast. A fixed-size pool, recycled in place (never
# resized/reallocated) rather than spawned/destroyed per frame.
RAIN_PARTICLE_COUNT = 220
RAIN_FALL_FRACTION_PER_S = 0.9  # base screen-heights/second fall speed
RAIN_DRIFT_FRACTION_PER_S = 0.05  # constant screen-widths/second wind drift
RAIN_SPEED_VARIATION = (0.75, 1.3)  # per-particle multiplier, assigned once at spawn

# Splashes: visual only (WEATHER_RAIN.md #5 - vehicle physics are never
# touched here), real-time lifetime like rain particles. Edge-triggered by
# the caller (main() only spawns one when the car *enters* a puddle, not
# every frame it spends inside one) so continuously driving through a
# puddle doesn't flood the pool.
SPLASH_LIFETIME_S = 0.5
SPLASH_MIN_SPEED_MPS = 1.0  # below this, "driving through" doesn't splash
SPLASH_POOL_MAX = 40  # defensive cap; splashes expire well before this matters


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
        self._rng = random.Random(1729)
        # Each entry: [x_fraction, y_fraction, speed_factor]. Recycled in
        # place (wrap to a fresh random x/y when a streak falls off the
        # bottom) rather than reallocated - render/weather.py maps these
        # to actual screen pixels.
        self.rain_particles = [self._spawn_rain_particle() for _ in range(RAIN_PARTICLE_COUNT)]
        # Each entry: [x, y, age_s, strength]. Short-lived (SPLASH_LIFETIME_S)
        # and pruned in update() - never grows large enough to need the
        # rain-particle pool's recycle-in-place treatment.
        self.splashes: list = []

    def spawn_splash(self, x: float, y: float, strength: float) -> None:
        """Trigger a splash effect (world position, 0..1 strength - see
        WEATHER_RAIN.md #5: stronger/larger at higher vehicle speed)."""
        self.splashes.append([x, y, 0.0, max(0.0, min(1.0, strength))])
        if len(self.splashes) > SPLASH_POOL_MAX:
            del self.splashes[: len(self.splashes) - SPLASH_POOL_MAX]

    def _spawn_rain_particle(self) -> list:
        return [
            self._rng.random(),
            self._rng.random(),
            self._rng.uniform(*RAIN_SPEED_VARIATION),
        ]

    @property
    def is_precipitating(self) -> bool:
        return self.weather_type in (WeatherType.RAIN, WeatherType.SNOW)

    def toggle_rain(self) -> None:
        """Debug toggle (F8): CLEAR <-> RAIN."""
        self.weather_type = WeatherType.CLEAR if self.weather_type == WeatherType.RAIN else WeatherType.RAIN

    def update(self, game_dt: float, real_dt: float) -> None:
        """Advance wetness (game time) and rain particles (real time).

        `game_dt` is dt * time_scale - the same delta main() uses to
        advance game_time_seconds - so drying/wetting tracks the game
        clock, not wall-clock time. `real_dt` is the plain per-frame dt:
        rain must fall at a consistent visual speed regardless of how
        fast game time is currently running (time_scale up to 60x).
        """
        if game_dt > 0.0:
            if self.weather_type == WeatherType.RAIN:
                self.wetness = min(1.0, self.wetness + game_dt / RAIN_WETTING_DURATION_S)
            else:
                self.wetness = max(0.0, self.wetness - game_dt / DRY_DURATION_S)

        if self.is_precipitating and real_dt > 0.0:
            for particle in self.rain_particles:
                x, y, factor = particle
                y += RAIN_FALL_FRACTION_PER_S * factor * real_dt
                x += RAIN_DRIFT_FRACTION_PER_S * factor * real_dt
                if y > 1.0:
                    y -= 1.0
                    x = self._rng.random()
                elif x > 1.0:
                    x -= 1.0
                particle[0] = x
                particle[1] = y

        if self.splashes and real_dt > 0.0:
            for splash in self.splashes:
                splash[2] += real_dt
            self.splashes = [s for s in self.splashes if s[2] < SPLASH_LIFETIME_S]
