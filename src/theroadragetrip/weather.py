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
import copy
import math
import random
from enum import Enum
from typing import Optional
from .calendar import Season
from .weather_history import precipitation_from_observation


class WeatherType(str, Enum):
    CLEAR = "clear"
    RAIN = "rain"
    SLUSH = "slush"
    SNOW = "snow"


SNOW_MAX_TEMPERATURE_C = 1.0
SLUSH_MAX_TEMPERATURE_C = 5.0


# Automatic weather durations in game-seconds. Autumn and winter use
# separate 50%-precipitation periods lasting up to one game-day.
SEASON_CLEAR_DURATION_RANGES = {
    Season.SPRING: (60.0 * 60.0, 3.0 * 60.0 * 60.0),
    Season.SUMMER: (2.0 * 60.0 * 60.0, 5.0 * 60.0 * 60.0),
    Season.AUTUMN: (30.0 * 60.0, 90.0 * 60.0),
}
RAIN_DURATION_RANGE = (20.0 * 60.0, 50.0 * 60.0)
AUTUMN_WINTER_PRECIPITATION_CHANCE = 0.5
AUTUMN_WINTER_PERIOD_RANGE = (0.0, 24.0 * 60.0 * 60.0)
THUNDER_CHANCE_BY_SEASON = {
    Season.WINTER: 0.0,
    Season.SPRING: 0.1,
    Season.SUMMER: 0.5,
    Season.AUTUMN: 0.1,
}
LIGHTNING_INTERVAL_RANGE_S = (4.0, 18.0)
LIGHTNING_FLASH_DURATION_S = 0.22


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

# Wind: mean speed/direction follow an observation (historical weather) or
# a generated random walk in game time; gusts ride on top in real time so
# they look the same at any time_scale. Direction is meteorological: the
# compass bearing the wind blows FROM (0 = north, 90 = east).
WIND_WEIBULL_SCALE_MPS = 5.0  # generated mean speeds: typical ~4 m/s, storms rare
WIND_WEIBULL_SHAPE = 2.0
WIND_CHANGE_INTERVAL_S = (60.0 * 60.0, 3.0 * 60.0 * 60.0)  # new generated target every 1-3 game hours
WIND_DIRECTION_WANDER_DEG = 40.0
WIND_SETTLE_S = 20.0 * 60.0  # game-time constant towards a new mean
WIND_GUST_AMPLITUDE = 0.35  # +-35% of the mean speed
TREE_LEAN_PER_WIND_SQ = 0.004  # crown shift m per (m/s)^2: 10 m/s -> 0.4 m, 20 m/s -> 1.6 m
TREE_MAX_LEAN_M = 2.0


def weather_type_for_observation(kind: str, temperature_c: Optional[float]) -> WeatherType:
    """Map precipitation_from_observation()'s kind to a WeatherType; an
    untyped "precipitation" falls as snow/slush/rain by temperature."""
    if kind == "":
        return WeatherType.CLEAR
    if kind != "precipitation":
        return WeatherType(kind)
    if temperature_c is None or temperature_c <= SNOW_MAX_TEMPERATURE_C:
        return WeatherType.SNOW
    return WeatherType.SLUSH if temperature_c < SLUSH_MAX_TEMPERATURE_C else WeatherType.RAIN


class WeatherSystem:
    """Owns the current weather type and road wetness.

    Everything else (rain particles, wet-road tint, puddles, splashes)
    reads .weather_type / .wetness from this rather than tracking their
    own state or reacting directly to keyboard input.
    """

    def __init__(self, weather_type: Optional[WeatherType] = None, season: Season = Season.SUMMER) -> None:
        self._automatic = weather_type is None
        self._season = season
        self._outside_temperature_c: Optional[float] = None
        self.weather_type = weather_type or WeatherType.CLEAR
        self._following_observation = False
        self.wetness = 0.0  # 0.0 dry .. 1.0 fully wet; independent of weather_type -
        # CLEAR does not imply dry, e.g. right after rain stops (see #9).
        self._rng = random.Random()
        self.is_thunderstorm = False
        self.lightning_intensity = 0.0
        self.lightning_event_id = 0
        self._lightning_timer = self._rng.uniform(*LIGHTNING_INTERVAL_RANGE_S)
        # Each entry: [x_fraction, y_fraction, speed_factor]. Recycled in
        # place (wrap to a fresh random x/y when a streak falls off the
        # bottom) rather than reallocated - render/weather.py maps these
        # to actual screen pixels.
        self.rain_particles = [self._spawn_rain_particle() for _ in range(RAIN_PARTICLE_COUNT)]
        if not self._automatic:
            self._weather_timer = float("inf")
        elif season in (Season.AUTUMN, Season.WINTER):
            self._start_autumn_or_winter_period()
        else:
            self._weather_timer = self._next_weather_duration()
        # Each entry: [x, y, age_s, strength]. Short-lived (SPLASH_LIFETIME_S)
        # and pruned in update() - never grows large enough to need the
        # rain-particle pool's recycle-in-place treatment.
        self.splashes: list = []
        self.wind_speed_mps = self._rng.weibullvariate(WIND_WEIBULL_SCALE_MPS, WIND_WEIBULL_SHAPE)
        self.wind_from_deg = self._rng.uniform(0.0, 360.0)
        self._wind_target = (self.wind_speed_mps, self.wind_from_deg)
        self._wind_timer = self._rng.uniform(*WIND_CHANGE_INTERVAL_S)
        self._gust_time = self._rng.uniform(0.0, 100.0)
        if not self._automatic and self.weather_type == WeatherType.RAIN:
            self._roll_thunderstorm()

    @property
    def season(self) -> Season:
        return self._season

    @season.setter
    def season(self, value: Season) -> None:
        if value == self._season:
            return
        self._season = value
        if not self._automatic:
            return
        self.weather_type = WeatherType.CLEAR
        self.is_thunderstorm = False
        if value in (Season.AUTUMN, Season.WINTER):
            self._start_autumn_or_winter_period()
        else:
            self._weather_timer = self._next_weather_duration()

    def _start_autumn_or_winter_period(self) -> None:
        """Roll a new 0-24h period with a 50% precipitation chance."""
        precipitation = self._precipitation_type_for_conditions()
        self.weather_type = (
            precipitation
            if self._rng.random() < AUTUMN_WINTER_PRECIPITATION_CHANCE
            else WeatherType.CLEAR
        )
        self._roll_thunderstorm()
        # Avoid a zero-duration loop while retaining the requested range.
        self._weather_timer = max(1.0, self._rng.uniform(*AUTUMN_WINTER_PERIOD_RANGE))

    def _next_weather_duration(self) -> float:
        duration_range = (
            RAIN_DURATION_RANGE
            if self.is_precipitating
            else SEASON_CLEAR_DURATION_RANGES[self._season]
        )
        return self._rng.uniform(*duration_range)

    def _precipitation_type_for_conditions(self) -> WeatherType:
        """Choose falling precipitation from air temperature, not ground cover."""
        if self._outside_temperature_c is None:
            return WeatherType.SNOW if self._season == Season.WINTER else WeatherType.RAIN
        if self._outside_temperature_c <= SNOW_MAX_TEMPERATURE_C:
            return WeatherType.SNOW
        if self._outside_temperature_c < SLUSH_MAX_TEMPERATURE_C:
            return WeatherType.SLUSH
        return WeatherType.RAIN

    def _apply_precipitation_temperature(self) -> None:
        if self.is_precipitating:
            self.weather_type = self._precipitation_type_for_conditions()
            if self.weather_type != WeatherType.RAIN:
                self.is_thunderstorm = False

    def _roll_thunderstorm(self) -> None:
        """Choose thunder once for the current rain period."""
        self.is_thunderstorm = (
            self.weather_type == WeatherType.RAIN
            and self._rng.random() < THUNDER_CHANCE_BY_SEASON[self._season]
        )
        self.lightning_intensity = 0.0
        self._lightning_timer = self._rng.uniform(*LIGHTNING_INTERVAL_RANGE_S)

    def _advance_automatic_weather(self, game_dt: float) -> None:
        if not self._automatic or game_dt <= 0.0:
            return
        remaining = game_dt
        while remaining >= self._weather_timer:
            remaining -= self._weather_timer
            if self._season in (Season.AUTUMN, Season.WINTER):
                self._start_autumn_or_winter_period()
            else:
                self.weather_type = (
                    WeatherType.CLEAR
                    if self.is_precipitating
                    else self._precipitation_type_for_conditions()
                )
                if self.is_precipitating:
                    self._roll_thunderstorm()
                else:
                    self.is_thunderstorm = False
                self._weather_timer = self._next_weather_duration()
        self._weather_timer -= remaining

    def forecast(self, temperatures_c: list[float], interval_s: float) -> list[tuple[WeatherType, bool]]:
        """Predict sampled conditions without advancing the live weather."""
        predicted = copy.deepcopy(self)
        result = []
        for index, temperature_c in enumerate(temperatures_c):
            if index:
                predicted.update(interval_s, 0.0, outside_temperature_c=temperature_c)
            else:
                predicted._outside_temperature_c = temperature_c
                predicted._apply_precipitation_temperature()
            result.append((predicted.weather_type, predicted.is_thunderstorm))
        return result

    @property
    def road_grip_wetness(self) -> float:
        """Effective asphalt slipperiness; winter roads stay slick when clear."""
        return max(self.wetness, 1.0 if self.season == Season.WINTER else 0.0)

    @property
    def road_ice_fraction(self) -> float:
        """Fraction of wet road frozen into black ice below 0 C."""
        if self._outside_temperature_c is None or self._outside_temperature_c >= 0.0:
            return 0.0
        return self.wetness

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
        return self.weather_type in (WeatherType.RAIN, WeatherType.SLUSH, WeatherType.SNOW)

    @property
    def seconds_until_weather_change(self) -> Optional[float]:
        """Game seconds left in the current automatic weather period."""
        return max(0.0, self._weather_timer) if self._automatic else None

    @property
    def gust_factor(self) -> float:
        """Real-time gust multiplier on wind_speed_mps (two incommensurate
        sines: irregular, smooth, no per-frame randomness)."""
        t = self._gust_time
        return 1.0 + WIND_GUST_AMPLITUDE * (0.6 * math.sin(t * 0.9) + 0.4 * math.sin(t * 2.3 + 1.7))

    @property
    def wind_vector_mps(self) -> tuple:
        """Gusty wind velocity in world metres (east, north): where the air
        moves TO, i.e. opposite wind_from_deg."""
        speed = self.wind_speed_mps * self.gust_factor
        bearing = math.radians(self.wind_from_deg)
        return (-math.sin(bearing) * speed, -math.cos(bearing) * speed)

    @property
    def tree_lean_m(self) -> tuple:
        """Downwind crown displacement (east, north) seen from above; grows
        with wind pressure (speed squared) and sways with the gusts."""
        east, north = self.wind_vector_mps
        speed = math.hypot(east, north)
        if speed < 1e-6:
            return (0.0, 0.0)
        lean = min(TREE_MAX_LEAN_M, TREE_LEAN_PER_WIND_SQ * speed * speed)
        return (east / speed * lean, north / speed * lean)

    def _advance_wind(self, game_dt: float, observed) -> None:
        observed_speed = getattr(observed, "wind_speed_mps", None)
        if observed_speed is not None:
            observed_from = getattr(observed, "wind_from_deg", None)
            self._wind_target = (observed_speed, self._wind_target[1] if observed_from is None else observed_from)
        else:
            self._wind_timer -= game_dt
            if self._wind_timer <= 0.0:
                self._wind_timer = self._rng.uniform(*WIND_CHANGE_INTERVAL_S)
                self._wind_target = (
                    self._rng.weibullvariate(WIND_WEIBULL_SCALE_MPS, WIND_WEIBULL_SHAPE),
                    (self._wind_target[1] + self._rng.gauss(0.0, WIND_DIRECTION_WANDER_DEG)) % 360.0,
                )
        blend = 1.0 - math.exp(-game_dt / WIND_SETTLE_S)
        target_speed, target_from = self._wind_target
        self.wind_speed_mps += (target_speed - self.wind_speed_mps) * blend
        turn = (target_from - self.wind_from_deg + 180.0) % 360.0 - 180.0  # shortest way round
        self.wind_from_deg = (self.wind_from_deg + turn * blend) % 360.0

    def _follow_observation(self, kind: str, thunder: bool) -> None:
        self._following_observation = True
        weather_type = weather_type_for_observation(kind, self._outside_temperature_c)
        thunder = thunder and weather_type == WeatherType.RAIN
        if weather_type != self.weather_type or thunder != self.is_thunderstorm:
            self.weather_type = weather_type
            self.is_thunderstorm = thunder
            self.lightning_intensity = 0.0
            self._lightning_timer = self._rng.uniform(*LIGHTNING_INTERVAL_RANGE_S)

    def toggle_rain(self) -> None:
        """Debug toggle (F8), disabling automatic changes for this session."""
        self._automatic = False
        precipitation = self._precipitation_type_for_conditions()
        self.weather_type = WeatherType.CLEAR if self.is_precipitating else precipitation
        if self.weather_type == WeatherType.RAIN:
            self._roll_thunderstorm()
        else:
            self.is_thunderstorm = False

    def update(
        self,
        game_dt: float,
        real_dt: float,
        outside_temperature_c: Optional[float] = None,
        observed=None,
    ) -> None:
        """Advance wetness (game time) and rain particles (real time).

        `observed` (weather_history.HourlyWeather, historical-weather mode):
        when it tells whether it is precipitating, that replaces the
        generated weather for this hour; otherwise the generator runs,
        continuing from whatever was last observed.

        `game_dt` is dt * time_scale - the same delta main() uses to
        advance game_time_seconds - so drying/wetting tracks the game
        clock, not wall-clock time. `real_dt` is the plain per-frame dt:
        rain must fall at a consistent visual speed regardless of how
        fast game time is currently running (time_scale up to 60x).
        """
        if outside_temperature_c is not None:
            self._outside_temperature_c = float(outside_temperature_c)
        if real_dt > 0.0:
            self._gust_time += real_dt
        if game_dt > 0.0:
            self._advance_wind(game_dt, observed)
            observed_kind, observed_thunder = (
                precipitation_from_observation(observed) if observed is not None else (None, False)
            )
            if self._automatic and observed_kind is not None:
                self._follow_observation(observed_kind, observed_thunder)
            else:
                if self._following_observation:
                    # Observations ended (e.g. game time passed "now"): the
                    # generator takes over from the last observed state.
                    self._following_observation = False
                    self._weather_timer = self._next_weather_duration()
                self._advance_automatic_weather(game_dt)
                self._apply_precipitation_temperature()
            if self.weather_type in (WeatherType.RAIN, WeatherType.SLUSH):
                self.wetness = min(1.0, self.wetness + game_dt / RAIN_WETTING_DURATION_S)
            elif self.road_ice_fraction > 0.0:
                # Frozen water cannot evaporate/dry until it thaws.
                pass
            else:
                self.wetness = max(0.0, self.wetness - game_dt / DRY_DURATION_S)

        if self.is_precipitating and real_dt > 0.0:
            for particle in self.rain_particles:
                x, y, factor = particle
                if self.weather_type == WeatherType.SNOW:
                    fall_factor, drift_factor = 0.22, 1.8
                elif self.weather_type == WeatherType.SLUSH:
                    fall_factor, drift_factor = 0.55, 1.35
                else:
                    fall_factor, drift_factor = 1.0, 1.0
                fall_rate = RAIN_FALL_FRACTION_PER_S * fall_factor
                drift_rate = RAIN_DRIFT_FRACTION_PER_S * drift_factor
                y += fall_rate * factor * real_dt
                x += drift_rate * factor * real_dt
                if y > 1.0:
                    y -= 1.0
                    x = self._rng.random()
                elif x > 1.0:
                    x -= 1.0
                particle[0] = x
                particle[1] = y

        if self.is_thunderstorm and self.weather_type == WeatherType.RAIN and real_dt > 0.0:
            self._lightning_timer -= real_dt
            if self._lightning_timer <= 0.0:
                self.lightning_intensity = 1.0
                self.lightning_event_id += 1
                self._lightning_timer = self._rng.uniform(*LIGHTNING_INTERVAL_RANGE_S)
            elif self.lightning_intensity > 0.0:
                self.lightning_intensity = max(
                    0.0,
                    self.lightning_intensity - real_dt / LIGHTNING_FLASH_DURATION_S,
                )
        else:
            self.lightning_intensity = 0.0

        if self.splashes and real_dt > 0.0:
            for splash in self.splashes:
                splash[2] += real_dt
            self.splashes = [s for s in self.splashes if s[2] < SPLASH_LIFETIME_S]
