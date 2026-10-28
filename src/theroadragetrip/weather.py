"""Dynamic weather state: precipitation type and road wetness.

Kept separate from rendering (render/*.py reads this, doesn't own it) -
same relationship render/ already has with TaxiManager/PedestrianManager -
so wet-road tint and puddles read one shared WeatherSystem instead of each
tracking their own notion of "is it raining". Rain, snowflakes and splashes
are drawn by the client alone; nothing visual-only is simulated here.
"""
import copy
import math
import random
from enum import Enum
from typing import Optional
from .calendar import Season
from .weather_history import gradual_weather, precipitation_from_observation


class WeatherType(str, Enum):
    CLEAR = "clear"
    RAIN = "rain"
    SLUSH = "slush"
    SNOW = "snow"


SNOW_MAX_TEMPERATURE_C = 1.0
SLUSH_MAX_TEMPERATURE_C = 5.0
# A station's present-weather sensor misreads fine snow as drizzle in the
# cold: reported rain this cold falls as snow (and reported snow this warm as slush).
OBSERVED_RAIN_MIN_TEMPERATURE_C = -2.0


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
# (time_scale is 1x with a passenger, 60x without). Rain wets faster than drying dries:
# a road visibly darkens within minutes of rain starting but takes longer
# to fully dry once it stops.
RAIN_WETTING_DURATION_S = 10.0 * 60.0  # 0 -> 1 wetness over 10 game-minutes of rain
DRY_DURATION_S = 60.0 * 60.0  # 1 -> 0 wetness over 1 game-hour (WEATHER_RAIN.md #7)

# Wind: mean speed/direction follow an observation (historical weather) or
# a generated random walk in game time; gusts ride on top in real time so
# they look the same at any time_scale. Direction is meteorological: the
# compass bearing the wind blows FROM (0 = north, 90 = east).
WIND_WEIBULL_SCALE_MPS = 5.0  # generated mean speeds: typical ~4 m/s, storms rare
WIND_WEIBULL_SHAPE = 2.0
WIND_CHANGE_INTERVAL_S = (60.0 * 60.0, 3.0 * 60.0 * 60.0)  # new generated target every 1-3 game hours
WIND_DIRECTION_WANDER_DEG = 40.0
WIND_SETTLE_S = 20.0 * 60.0  # game-time constant towards a new mean
# Cloud cover, 0 clear .. 1 overcast (rrt-018-shadows): it dims the direct
# sunlight and the building shadows. Observed (FMI n_man / forecast cloud %)
# when the weather follows history; generated otherwise: a new target every
# 1-4 game hours from a seasonal mix of clear / partly cloudy / overcast skies
# (ESTIMATES of Finnish climate - autumn and winter mostly overcast), eased
# towards over CLOUD_SETTLE_S. Rain, slush or snow need clouds: generated
# cover is then at least PRECIPITATION_MIN_CLOUD (not 1 - showers have breaks).
CLOUD_CHANGE_INTERVAL_S = (60.0 * 60.0, 4.0 * 60.0 * 60.0)
CLOUD_SETTLE_S = 15.0 * 60.0
PRECIPITATION_MIN_CLOUD = 0.85
CLOUD_REGIMES = ((0.0, 0.25), (0.3, 0.7), (0.8, 1.0))  # clear, partly cloudy, overcast
CLOUD_REGIME_WEIGHTS = {
    Season.SPRING: (0.35, 0.35, 0.30), Season.SUMMER: (0.35, 0.40, 0.25),
    Season.AUTUMN: (0.15, 0.30, 0.55), Season.WINTER: (0.15, 0.25, 0.60),
}
WIND_GUST_AMPLITUDE = 0.35  # +-35% of the mean speed
TREE_LEAN_PER_WIND_SQ = 0.004  # crown shift m per (m/s)^2: 10 m/s -> 0.4 m, 20 m/s -> 1.6 m
TREE_MAX_LEAN_M = 2.0


def weather_type_for_observation(kind: str, temperature_c: Optional[float]) -> WeatherType:
    """Map precipitation_from_observation()'s kind to a WeatherType; an
    untyped "precipitation" falls as snow/slush/rain by temperature."""
    if kind == "":
        return WeatherType.CLEAR
    if kind != "precipitation":
        if temperature_c is not None and kind in ("rain", "slush") and temperature_c <= OBSERVED_RAIN_MIN_TEMPERATURE_C:
            return WeatherType.SNOW
        if temperature_c is not None and kind == "snow" and temperature_c >= SLUSH_MAX_TEMPERATURE_C:
            return WeatherType.SLUSH
        return WeatherType(kind)
    if temperature_c is None or temperature_c <= SNOW_MAX_TEMPERATURE_C:
        return WeatherType.SNOW
    return WeatherType.SLUSH if temperature_c < SLUSH_MAX_TEMPERATURE_C else WeatherType.RAIN


def wetness_after(raining: list, step_s: float, start: float = 0.0) -> float:
    """Road wetness after a run of equal steps, oldest first, with the
    game's own wetting and drying (RAIN_WETTING_DURATION_S, DRY_DURATION_S):
    True raining (rain or slush), False dry, None unknown (unchanged)."""
    wetness = start
    for wet in raining:
        if wet is True:
            wetness = min(1.0, wetness + step_s / RAIN_WETTING_DURATION_S)
        elif wet is False:
            wetness = max(0.0, wetness - step_s / DRY_DURATION_S)
    return wetness


def raining_last_hour(history, now, typical_temperature, key="") -> list:
    """WeatherHistory's weather every 5 minutes over the hour before `now`
    (and the step before it), oldest first: True rain or slush, False dry,
    None unknown; [] when nothing is known. `typical_temperature(moment)`
    types precipitation without an observed temperature."""
    from datetime import timedelta

    steps = []
    for minutes in range(65, -1, -5):
        moment = now - timedelta(minutes=minutes)
        seen = gradual_weather(history, moment, key)
        kind = precipitation_from_observation(seen)[0] if seen is not None else None
        if kind is None:
            steps.append(None)
            continue
        temperature = seen.temperature_c if seen.temperature_c is not None else typical_temperature(moment)
        steps.append(weather_type_for_observation(kind, temperature) in (WeatherType.RAIN, WeatherType.SLUSH))
    return steps if any(step is not None for step in steps) else []


class WeatherSystem:
    """Owns the current weather type and road wetness.

    Everything else (wet-road tint, puddles)
    reads .weather_type / .wetness from this rather than tracking their
    own state or reacting directly to keyboard input.
    """

    def __init__(self, weather_type: Optional[WeatherType] = None, season: Season = Season.SUMMER) -> None:
        self._automatic = weather_type is None
        self._season = season
        self._outside_temperature_c: Optional[float] = None
        self.weather_type = weather_type or WeatherType.CLEAR
        self._following_observation = False
        self.road_ice_override: Optional[float] = None  # live station road ice; None: from the air temperature
        self.wetness = 0.0  # 0.0 dry .. 1.0 fully wet; independent of weather_type -
        self.road_snow = 0.0  # centimetres; fully white at three centimetres
        self.plowed_cells = {}  # 10 m road cells -> snow level when last cleared
        # CLEAR does not imply dry, e.g. right after rain stops (see #9).
        self._rng = random.Random()
        self.is_thunderstorm = False
        self.lightning_intensity = 0.0
        self.lightning_event_id = 0
        self._lightning_timer = self._rng.uniform(*LIGHTNING_INTERVAL_RANGE_S)
        if not self._automatic:
            self._weather_timer = float("inf")
        elif season in (Season.AUTUMN, Season.WINTER):
            self._start_autumn_or_winter_period()
        else:
            self._weather_timer = self._next_weather_duration()
        self.wind_speed_mps = self._rng.weibullvariate(WIND_WEIBULL_SCALE_MPS, WIND_WEIBULL_SHAPE)
        self.wind_from_deg = self._rng.uniform(0.0, 360.0)
        self._wind_target = (self.wind_speed_mps, self.wind_from_deg)
        self._wind_timer = self._rng.uniform(*WIND_CHANGE_INTERVAL_S)
        self._gust_time = self._rng.uniform(0.0, 100.0)
        self._cloud_target = self._generated_cloud()
        self.cloud_cover = self._cloud_target
        self._cloud_timer = self._rng.uniform(*CLOUD_CHANGE_INTERVAL_S)
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
        """Fraction of wet road frozen into black ice below 0 C, or what a
        live road weather station reports (road_ice_override, digitraffic_mqtt.py)."""
        if self.road_ice_override is not None:
            return self.road_ice_override
        if self._outside_temperature_c is None or self._outside_temperature_c >= 0.0:
            return 0.0
        return self.wetness

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

    def _generated_cloud(self) -> float:
        low, high = self._rng.choices(CLOUD_REGIMES, weights=CLOUD_REGIME_WEIGHTS[self._season])[0]
        return self._rng.uniform(low, high)

    def _advance_clouds(self, game_dt: float, observed) -> None:
        observed_cloud = getattr(observed, "cloud_cover", None)
        if observed_cloud is not None:
            self._cloud_target = float(observed_cloud)
        else:
            self._cloud_timer -= game_dt
            if self._cloud_timer <= 0.0:
                self._cloud_timer = self._rng.uniform(*CLOUD_CHANGE_INTERVAL_S)
                self._cloud_target = self._generated_cloud()
            if self.is_precipitating:
                self._cloud_target = max(self._cloud_target, PRECIPITATION_MIN_CLOUD)
        blend = 1.0 - math.exp(-game_dt / CLOUD_SETTLE_S)
        self.cloud_cover += (self._cloud_target - self.cloud_cover) * blend

    def _follow_observation(self, kind: str, thunder: bool) -> None:
        self._following_observation = True
        weather_type = weather_type_for_observation(kind, self._outside_temperature_c)
        thunder = thunder and weather_type == WeatherType.RAIN
        if weather_type != self.weather_type or thunder != self.is_thunderstorm:
            self.weather_type = weather_type
            self.is_thunderstorm = thunder
            self.lightning_intensity = 0.0
            self._lightning_timer = self._rng.uniform(*LIGHTNING_INTERVAL_RANGE_S)

    def settle_initial_wetness(self, raining_last_hour: Optional[list] = None, step_s: float = 300.0) -> None:
        """The road at the start: as the last hour's observed weather left it
        (`raining_last_hour`, oldest first, see wetness_after; the step
        before it decides whether the hour began wet), else - no history -
        wet if it is raining now (it has rained a while), dry otherwise."""
        if raining_last_hour:
            start = 1.0 if raining_last_hour[0] else 0.0
            self.wetness = wetness_after(raining_last_hour[1:], step_s, start)
        else:
            self.wetness = 1.0 if self.weather_type in (WeatherType.RAIN, WeatherType.SLUSH) else 0.0

    def toggle_rain(self) -> None:
        """Debug toggle (F8), disabling automatic changes for this session."""
        self._automatic = False
        precipitation = self._precipitation_type_for_conditions()
        self.weather_type = WeatherType.CLEAR if self.is_precipitating else precipitation
        if self.weather_type == WeatherType.RAIN:
            self._roll_thunderstorm()
        else:
            self.is_thunderstorm = False

    def road_snow_at(self, x: float, y: float) -> float:
        cell = (math.floor(x / 10.0), math.floor(y / 10.0))
        return max(0.0, self.road_snow - self.plowed_cells.get(cell, 0.0))

    def plow_road(self, start, end) -> None:
        if self.road_snow <= 0.0:
            return
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(1, math.ceil(distance / 2.0))
        for step in range(steps + 1):
            t = step / steps
            cell = (math.floor((start[0] + (end[0] - start[0]) * t) / 10.0),
                    math.floor((start[1] + (end[1] - start[1]) * t) / 10.0))
            self.plowed_cells[cell] = self.road_snow
        # Keep streaming trips from retaining an unlimited history of cleared roads.
        while len(self.plowed_cells) > 4096:
            del self.plowed_cells[next(iter(self.plowed_cells))]

    def update(
        self,
        game_dt: float,
        real_dt: float,
        outside_temperature_c: Optional[float] = None,
        observed=None,
    ) -> None:
        """Advance wetness (game time) and lightning (real time).

        `observed` (weather_history.HourlyWeather, historical-weather mode):
        when it tells whether it is precipitating, that replaces the
        generated weather for this hour; otherwise the generator runs,
        continuing from whatever was last observed.

        `game_dt` is dt * time_scale - the same delta the server uses to
        advance game_time_seconds - so drying/wetting tracks the game
        clock, not wall-clock time. `real_dt` is the plain per-frame dt:
        lightning flashes at a consistent speed regardless of how fast
        game time is currently running (time_scale up to 60x).
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
                    if self._season in (Season.AUTUMN, Season.WINTER):
                        self._start_autumn_or_winter_period()
                    else:
                        self._weather_timer = self._next_weather_duration()
                self._advance_automatic_weather(game_dt)
                self._apply_precipitation_temperature()
            self._advance_clouds(game_dt, observed)
            if self.weather_type == WeatherType.SNOW:
                self.road_snow += game_dt / 600.0
            elif self._outside_temperature_c is not None and self._outside_temperature_c > 0.0:
                self.road_snow = max(0.0, self.road_snow - game_dt / 1800.0)
                for cell, cleared_at in self.plowed_cells.items():
                    self.plowed_cells[cell] = min(cleared_at, self.road_snow)
            if self.road_snow == 0.0:
                self.plowed_cells.clear()
            if self.weather_type in (WeatherType.RAIN, WeatherType.SLUSH):
                self.wetness = min(1.0, self.wetness + game_dt / RAIN_WETTING_DURATION_S)
            elif self.road_ice_fraction > 0.0:
                # Frozen water cannot evaporate/dry until it thaws.
                pass
            else:
                self.wetness = max(0.0, self.wetness - game_dt / DRY_DURATION_S)

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
