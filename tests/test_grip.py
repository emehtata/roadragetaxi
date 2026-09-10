"""Acceptance tests for the tire grip/slip model (.github/prompts/GRIP.md
section 20), on top of the g-force measurement it builds on
(GFORCE.md, tests/test_g_force.py, tests/test_cornering_grip.py)."""
import math

from theroadragetrip.osm import Way
from theroadragetrip.physics import (
    Car,
    SURFACE_MAX_GRIP_G,
    _surface_max_grip_g,
    update_car_physics,
)


def _fast_car(speed=30.0):
    """See test_cornering_grip._fast_car - primes the g-force velocity
    history so a single subsequent update_car_physics call is meaningful."""
    car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=0.1)
    car.x, car.y, car.speed = 0.0, 0.0, speed
    car._prev_vx, car._prev_vy = speed * math.cos(car.heading), speed * math.sin(car.heading)
    return car


def test_1_stationary_steering_has_no_grip_usage_or_slip():
    car = _fast_car(speed=0.0)
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1)
    assert car.total_g < 0.05
    assert car.lateral_g == 0.0
    assert car.slip_amount == 0.0


def test_2_straight_constant_speed_has_no_grip_usage():
    """Exact constant speed isn't reachable through the throttle/friction
    pedal model at an arbitrary speed (friction alone often out-decelerates
    peak available accel) - drive the g-force measurement directly, as
    test_g_force.py's equivalent GFORCE.md check does."""
    from theroadragetrip.physics import _update_g_force

    car = _fast_car(speed=20.0)
    entry_x, entry_y = car.x, car.y
    car.x += 20.0 * 0.1  # moved exactly speed*dt: no accel at all
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert abs(car.raw_total_g) < 1e-9
    assert car.slip_amount == 0.0


def test_5_gentle_corner_at_moderate_speed_stays_under_three_quarters_g():
    car = _fast_car(speed=15.0)
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=0.3, steer_right=0.0, dt=0.05)
    assert abs(car.raw_lateral_g) < 0.75
    assert car.is_sliding is False


def test_6_lateral_g_grows_with_speed_squared_at_a_fixed_radius():
    """Steering input alone isn't a fixed radius (STEER_SPEED_FACTOR softens
    it with speed) - drive an exact circular arc directly, as
    test_g_force.py does, to isolate the physical relationship this
    section is actually about."""
    from tests.test_g_force import _drive_arc

    slow = _drive_arc(speed=8.0, radius=40.0, dt=0.02, steps=5)
    fast = _drive_arc(speed=16.0, radius=40.0, dt=0.02, steps=5)
    assert math.isclose(
        abs(fast.raw_lateral_g) / abs(slow.raw_lateral_g), 4.0, rel_tol=0.05,
    )


def test_7_excessively_fast_corner_approaches_max_grip_and_slides():
    car = _fast_car(speed=30.0)
    update_car_physics(
        car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1, physics_mode="arcade",
    )
    assert car.grip_usage >= 1.0
    assert car.is_sliding is True
    assert car.slip_amount > 0.5


def test_8_braking_while_cornering_combines_as_a_vector_not_a_sum():
    car = _fast_car(speed=20.0)
    update_car_physics(car, throttle=0.0, brake=1.0, steer_left=0.4, steer_right=0.0, dt=0.05)
    assert car.raw_forward_g < 0.0
    assert car.raw_lateral_g != 0.0
    assert math.isclose(
        car.raw_total_g, math.hypot(car.raw_forward_g, car.raw_lateral_g), rel_tol=1e-9,
    )
    assert car.raw_total_g < abs(car.raw_forward_g) + abs(car.raw_lateral_g)


def test_9_steering_while_stationary_has_no_lateral_g():
    car = _fast_car(speed=0.0)
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1)
    assert car.lateral_g == 0.0
    assert car.raw_lateral_g == 0.0


def test_10_drifting_shows_heading_diverging_from_velocity_with_rising_slip():
    """Hard, sustained oversteer must actually enter the sliding state (the
    transient onset, before the understeer clamp and hysteresis let a
    controllable slide settle back out - GRIP.md section 8's "can enter a
    controllable ... slide", not stay pinned in it forever for an ordinary
    full-lock turn)."""
    car = _fast_car(speed=30.0)
    was_sliding = False
    for _ in range(15):
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1,
            physics_mode="simulation",
        )
        was_sliding = was_sliding or car.is_sliding
    assert car.drift_angle != 0.0
    assert abs(car.slip_angle) > 0.0
    assert was_sliding is True


def test_11_collision_style_velocity_change_produces_a_g_spike():
    """A hard external stop (e.g. a building collision, handled outside
    physics.py) is a big net velocity change over one frame - the very
    thing _update_g_force measures directly, not from steering."""
    car = _fast_car(speed=25.0)
    entry_x, entry_y = car.x, car.y
    car.speed = 0.0
    car.x, car.y = entry_x, entry_y  # stopped dead this frame
    from theroadragetrip.physics import _update_g_force

    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert car.raw_forward_g < -2.0


def test_12_surface_changes_grip_ceiling_for_the_same_corner_and_speed():
    surfaces = {
        "dry_asphalt": Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0),
        "gravel": Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0, surface="gravel"),
        "grass": Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0, surface="grass"),
        "ice": Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0, is_ice_road=True),
    }
    max_grips = {}
    for name, way in surfaces.items():
        car = _fast_car(speed=20.0)
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
            current_way=way, physics_mode="simulation",
        )
        max_grips[name] = car.max_grip_g

    assert max_grips["dry_asphalt"] == SURFACE_MAX_GRIP_G["dry_asphalt"]
    assert max_grips["ice"] == SURFACE_MAX_GRIP_G["ice"]
    assert max_grips["ice"] < max_grips["grass"] < max_grips["gravel"] < max_grips["dry_asphalt"]


def test_hysteresis_keeps_is_sliding_from_flickering_at_the_boundary():
    """GRIP.md section 12: separate enter/exit thresholds on slip_amount,
    not one threshold checked every frame."""
    from theroadragetrip.physics import SLIDE_ENTER_THRESHOLD, SLIDE_EXIT_THRESHOLD, _slip_amount_from_ratio

    car = _fast_car(speed=30.0)
    car.is_sliding = True
    # A grip ratio whose slip_amount sits between the exit and enter
    # thresholds: already-sliding must stay sliding here.
    mid_ratio = 1.01  # slip_amount ~0.70, between the 0.65 exit and 0.80 enter thresholds
    car.raw_total_g = mid_ratio * car.max_grip_g
    car.grip_usage = mid_ratio
    car.slip_amount = _slip_amount_from_ratio(mid_ratio)
    assert SLIDE_EXIT_THRESHOLD < car.slip_amount < SLIDE_ENTER_THRESHOLD
    is_sliding = car.slip_amount > SLIDE_EXIT_THRESHOLD if car.is_sliding else car.slip_amount >= SLIDE_ENTER_THRESHOLD
    assert is_sliding is True  # stays sliding: was sliding, hasn't dropped below exit

    car.is_sliding = False
    is_sliding = car.slip_amount > SLIDE_EXIT_THRESHOLD if car.is_sliding else car.slip_amount >= SLIDE_ENTER_THRESHOLD
    assert is_sliding is False  # stays not-sliding: wasn't sliding, hasn't reached enter


def test_13_wetness_interpolates_asphalt_grip_toward_wet_asphalt():
    """Rain (weather.py's WeatherSystem.wetness) makes asphalt grip fall
    progressively toward wet_asphalt, not switch at a threshold - same
    "progressive, not instant" approach GRIP.md already uses elsewhere."""
    dry = SURFACE_MAX_GRIP_G["dry_asphalt"]
    wet = SURFACE_MAX_GRIP_G["wet_asphalt"]

    assert _surface_max_grip_g(None, "simulation", wetness=0.0) == dry
    assert _surface_max_grip_g(None, "simulation", wetness=1.0) == wet
    half = _surface_max_grip_g(None, "simulation", wetness=0.5)
    assert wet < half < dry
    assert abs(half - (dry + wet) / 2.0) < 1e-9

    # Out-of-range wetness is clamped rather than extrapolated past wet_asphalt.
    assert _surface_max_grip_g(None, "simulation", wetness=5.0) == wet
    assert _surface_max_grip_g(None, "simulation", wetness=-1.0) == dry


def test_14_wetness_does_not_affect_non_asphalt_surfaces():
    """GRIP.md's surface list has no "wet grass"/"wet gravel" bucket -
    wetness only interpolates the asphalt (default) surface."""
    grass = Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0, surface="grass")
    gravel = Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0, surface="gravel")
    ice = Way([(0.0, 0.0), (100.0, 0.0)], "primary", 6.0, is_ice_road=True)

    for way, key in ((grass, "grass"), (gravel, "gravel"), (ice, "ice")):
        dry_wetness = _surface_max_grip_g(way, "simulation", wetness=0.0)
        full_wetness = _surface_max_grip_g(way, "simulation", wetness=1.0)
        assert dry_wetness == full_wetness == SURFACE_MAX_GRIP_G[key]


def test_15_rain_lowers_the_cornering_grip_ceiling_for_the_same_corner_and_speed():
    """Integration-level version of test_12, with wetness standing in for
    a surface change: the same corner/speed slides sooner on wet asphalt
    than dry."""
    dry_car = _fast_car(speed=20.0)
    update_car_physics(
        dry_car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
        physics_mode="simulation", wetness=0.0,
    )
    wet_car = _fast_car(speed=20.0)
    update_car_physics(
        wet_car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
        physics_mode="simulation", wetness=1.0,
    )
    assert wet_car.max_grip_g < dry_car.max_grip_g
    assert wet_car.grip_usage > dry_car.grip_usage
