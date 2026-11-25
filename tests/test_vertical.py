"""docs/specs/terrain-following-bodies.md part 3: the server decides when the car is airborne, and nothing steers it then.

Terrain: TerrainFlight leaves where v^2 times the crest curvature, at the DEM's own spacing, reaches g. Mapped speed bumps:
BumpFlight takes the hop from the bump's profile, the speed and the wheelbase alone, so it is the same at any frame rate.
"""
import math
import random
from types import SimpleNamespace

from theroadragetrip.osm import elevation
from theroadragetrip.osm.elevation import Dem
from theroadragetrip.physics import AIR_DRAG, Car, update_car_physics
from theroadragetrip.vertical import BUMP_DECAY_S, BUMP_PROFILES, BumpField, BumpFlight, TerrainFlight, axle_hops, bump_hops, bump_profile

HZ = (30, 45, 60, 75, 90, 120, 144, 240, 360, 720)


def hump_field(kind="hump", x=100.0, angle=0.0):
    return BumpField([SimpleNamespace(x=x, y=0.0, direction_angle=angle, kind=kind, width_m=6.0)])


WHEELBASE = 2.4


def drive_bump(kind, v, dts, direction=1.0, wheelbase=WHEELBASE):
    """Drive along the road over a `kind` bump at constant speed with the frame times `dts(i)`: (seconds with an axle off the
    road, hopped, peak body lift, landing jolt)."""
    field = hump_field(kind)
    flight = BumpFlight()
    x, i, air, peak, jolt = 100.0 - direction * 12.0, 0, 0.0, 0.0, 0.0
    while (x - 100.0) * direction < 14.0:
        dt = dts(i)
        i += 1
        nx = x + direction * v * dt
        flight.step((x, 0.0), (nx, 0.0), direction * v, dt, field, 0, wheelbase)
        x = nx
        air, peak, jolt = air + flight.air_s, max(peak, flight.air_height), max(jolt, flight.land_bump)
    return air, air > 0.0, peak, jolt


def test_a_bump_is_a_short_hop_with_a_small_lift():
    """Criterion 3 (7 cm bump at 50 km/h): each axle's tyre is off the road 0.05-0.12 s and lifts under half the bump's height
    (the suspension absorbs the rest); the whole car has an axle off for twice that, the rear one a wheelbase after the front."""
    hops = axle_hops("bump", 50 / 3.6)
    assert hops and 0.05 <= sum(h[5] for h in hops) <= 0.12 and max(h[2] for h in hops) < 0.035, hops
    air, hopped, peak, jolt = drive_bump("bump", 50 / 3.6, lambda i: 1 / 60)
    assert hopped and 0.1 < air < 0.26 and 0.0 < peak < 0.035 and jolt > 0.2, (air, peak, jolt)
    assert abs(air - bump_hops("bump", 50 / 3.6, WHEELBASE)["seconds"]) < 0.002


def test_a_hump_hops_more_the_faster_it_is_taken_and_not_at_20_kmh():
    """Criterion 2 (10 cm hump): no hop at 20 or 40 km/h; at 50 km/h a hop of at most 0.12 s lifting under 4 cm; faster, longer and
    higher, but the body never rises past the hump's own height at 70 km/h (the peak is the mean of two axles)."""
    assert not axle_hops("hump", 20 / 3.6) and not axle_hops("hump", 40 / 3.6)
    secs = [sum(h[5] for h in axle_hops("hump", kmh / 3.6)) for kmh in (50, 60, 70, 100)]
    lifts = [max(h[2] for h in axle_hops("hump", kmh / 3.6)) for kmh in (50, 60, 70, 100)]
    assert 0.05 <= secs[0] <= 0.12 and lifts[0] < 0.04, (secs, lifts)
    assert secs == sorted(secs) and lifts == sorted(lifts) and secs[1] > secs[0] and lifts[1] > lifts[0] and lifts[2] < 0.10, (secs, lifts)
    air, _, peak, _ = drive_bump("hump", 50 / 3.6, lambda i: 1 / 60)
    assert 0.05 <= air <= 0.3 and peak <= 0.25


def test_the_hop_scales_with_the_height_and_the_wheelbase():
    """A bump of half the height hops less (and at 50 km/h not at all, under MIN_LIFT_M), a double one more; a longer wheelbase
    keeps the two axles' hops further apart in time (and in position), so the car is off the road for longer in total."""
    lift = lambda scale, kmh=70: max([h[2] for h in axle_hops("bump", kmh / 3.6, scale)], default=0.0)
    assert lift(0.5) < lift(1.0) < lift(2.0) and not axle_hops("bump", 50 / 3.6, 0.5)
    short, long = bump_hops("bump", 70 / 3.6, 2.0), bump_hops("bump", 70 / 3.6, 4.5)
    assert short["seconds"] < long["seconds"]
    assert len(short["air"]) == 1 and len(long["air"]) == 2  # the axles' hops overlap on a short wheelbase, separate on a long one
    front, rear = long["front"][0], long["rear"][0]
    assert abs((rear[0] - front[0]) - 4.5) < 1e-9


def test_the_decision_is_the_same_for_every_bump_type_at_every_frame_rate():
    """Yes or no and the airtime depend on the bump, the speed and the wheelbase only: any rate 30-720 Hz, jittered frames,
    both directions."""
    rnd = random.Random(3)
    for kind in BUMP_PROFILES:
        for kmh in (20, 30, 50, 70, 100):
            v = kmh / 3.6
            planned = bump_hops(kind, v, WHEELBASE)["seconds"]
            for direction in (1.0, -1.0):
                for hz in HZ:
                    air, hopped, _, _ = drive_bump(kind, v, lambda i, hz=hz: 1 / hz, direction)
                    assert abs(air - planned) < 0.002 and hopped == (planned > 0), (kind, kmh, hz, air, planned)
                for base in (30, 60, 144, 360):
                    air, hopped, _, _ = drive_bump(kind, v, lambda i, base=base: rnd.uniform(0.5, 1.8) / base, direction)
                    assert abs(air - planned) < 0.002 and hopped == (planned > 0), (kind, kmh, base, air, planned)
    # the decisions at 50 km/h: the three smooth bumps hop, a table's gentle corners do not; at 20 km/h none does
    assert [bool(axle_hops(k, 50 / 3.6)) for k in ("bump", "hump", "cushion", "table")] == [True, True, True, False]
    assert not any(axle_hops(k, 20 / 3.6) for k in BUMP_PROFILES) and axle_hops("table", 70 / 3.6)


def test_a_fast_move_cannot_step_over_a_bump():
    """Continuous detection: a move of 5.5 m in one tick (0.2 s at 100 km/h) over any bump still hops, by the plan."""
    for kind in BUMP_PROFILES:
        planned = bump_hops(kind, 100 / 3.6, WHEELBASE)["seconds"]
        air, hopped, _, _ = drive_bump(kind, 100 / 3.6, lambda i: 0.2)
        assert hopped and abs(air - planned) < 0.002, (kind, air, planned)


def test_the_landing_jolt_is_bounded_and_dies_away():
    """A hop's landing sets land_bump in (0, 1] and it is gone within BUMP_DECAY_S, for a bump and for a terrain hop alike."""
    field, flight = hump_field("bump"), BumpFlight()
    x, jolts = 88.0, []
    for _ in range(120):
        flight.step((x, 0.0), (x + 14.0 / 60, 0.0), 14.0, 1 / 60, field, 0, WHEELBASE)
        x += 14.0 / 60
        jolts.append(flight.land_bump)
    assert 0.0 < max(jolts) <= 1.0 and jolts[-1] == 0.0
    peak = len(jolts) - 1 - jolts[::-1].index(max(jolts))
    assert all(a >= b for a, b in zip(jolts[peak:], jolts[peak + 1:])) and jolts[min(peak + int(BUMP_DECAY_S * 60) + 1, 119)] == 0.0


def test_a_bridge_deck_or_garage_never_hops():
    field = hump_field()
    flight = BumpFlight()
    for layer in (1, -1):
        for i in range(60):
            flight.step((90.0 + i * 0.3, 0.0), (90.3 + i * 0.3, 0.0), 14.0, 1 / 46, field, layer)
            assert not flight.airborne and flight.air_s == 0.0


def synthetic_dem(seed, embankments=True, step=80.0, cells=70):
    """A raster of grade kinks of 2-6 % (grades up to 12 %) and, where asked, 3-6 m embankment steps inside a single cell."""
    rnd = random.Random(seed)
    grade, heights = 0.0, [0.0]
    for _ in range(cells):
        grade = max(-0.12, min(0.12, grade + rnd.choice([-1, 1]) * rnd.uniform(0.02, 0.06)))
        heights.append(heights[-1] + grade * step)
        if embankments and rnd.random() < 0.08:
            heights[-1] += rnd.choice([-1, 1]) * rnd.uniform(3.0, 6.0)
    return Dem((0.0, -step * 1.5), step, len(heights), [h for _ in range(3) for h in heights])


def terrain_launches(dem, speed, hz, length=5000.0, step_m=80.0):
    ground_at = lambda x, y: dem.height_m(x, y) or 0.0
    flight, x, launches, was = TerrainFlight(), 100.0, 0, False
    while x < length:
        x += speed / hz
        flight.step(ground_at, step_m, x, 0.0, 0.0, speed, 0, 1 / hz)
        launches += flight.airborne and not was
        was = flight.airborne
    return launches


def test_dem_kinks_and_embankments_never_launch_at_motorway_speed():
    """Criterion (tester): a raster with grade kinks of 2-6 % and embankments, driven at 50-58 m/s at 30-144 Hz: no take-off."""
    for seed in range(3):
        dem = synthetic_dem(seed)
        for speed in (50.0, 58.0):
            for hz in (30, 60, 144):
                assert terrain_launches(dem, speed, hz) == 0, (seed, speed, hz)


def test_a_fine_hill_does_launch_and_slowly_does_not():
    hill = elevation.test_hill(0.0, 0.0, 12.0, 30.0)
    dem = Dem(hill["origin"], hill["step"], hill["cols"], hill["heights"])
    ground_at = lambda x, y: dem.height_m(x, y) or 0.0

    def run(speed):
        flight, x, air = TerrainFlight(), -100.0, 0.0
        while x < 100.0:
            x += speed / 60
            flight.step(ground_at, hill["step"], x, 0.0, 0.0, speed, 0, 1 / 60)
            air += flight.airborne / 60
        return air

    assert run(30.0) > 0.15 and run(8.0) == 0.0 and run(11.0) == 0.0


def test_a_terrain_hop_lasts_the_same_at_any_frame_rate():
    """Swept take-off, fixed sub-steps in the air: the hop of a 30 m/s car over a fine hill is 2.2 s within 0.06 s at 30-720 Hz and jittered."""
    hill = elevation.test_hill(0.0, 0.0, 12.0, 30.0)
    dem = Dem(hill["origin"], hill["step"], hill["cols"], hill["heights"])
    ground_at = lambda x, y: dem.height_m(x, y) or 0.0
    rnd = random.Random(2)

    def hop(dts):
        flight, x, i = TerrainFlight(), -100.0, 0
        while x < 150.0:
            dt, i = dts(i), i + 1
            x += 30.0 * dt
            flight.step(ground_at, hill["step"], x, 0.0, 0.0, 30.0, 0, dt)
        return flight.last_hop_s, flight.land_bump

    results = [hop(lambda i, hz=hz: 1 / hz) for hz in HZ] + [hop(lambda i, b=b: rnd.uniform(0.5, 1.8) / b) for b in (30, 60, 144) for _ in range(4)]
    hops = [h for h, _ in results]
    assert min(hops) > 1.5 and max(hops) - min(hops) < 0.06, hops
    assert all(0.0 <= j <= 1.0 for _, j in results)


def drive_over_hump(steer=0.0, throttle=0.0, brake=0.0):
    """update_car_physics over a hump along +x; the controls are applied from the first airborne tick."""
    car = Car(x=-10.0, y=0.0, heading=0.0, speed=50 / 3.6)  # the speed is held on the ground: the driver keeps up 50 km/h
    field = hump_field(x=0.0)
    log = []
    for _ in range(240):
        air = car.airborne
        if not air:
            car.speed = 50 / 3.6
        controls = (steer, throttle, brake) if air else (0.0, 0.0, 0.0)
        before = (car.x, car.y, car.heading, car.speed)
        update_car_physics(car, controls[1], controls[2], controls[0], 0.0, 1 / 60, ways=[], block_offroad=False, bump_field=field)
        log.append((air, before, (car.x, car.y, car.heading, car.speed)))
    return log


def test_no_air_steer():
    """Criterion 11: full steer, throttle or brake held in the air change neither heading nor speed (beyond drag)."""
    for kwargs in ({"steer": 1.0}, {"throttle": 1.0, "steer": 1.0}, {"brake": 1.0}):
        flights = [(b, a) for air, b, a in drive_over_hump(**kwargs) if air]
        assert flights, "the hump hop never happened"
        for before, after in flights:
            assert after[2] == before[2], "heading changed in the air"
            assert before[3] - after[3] <= AIR_DRAG / 60 + 1e-9 and after[3] <= before[3], "controls changed the speed in the air"


def test_landing_follows_arc():
    """Criterion 12: the landing is within 0.2 m of the straight line from the take-off at the take-off velocity."""
    log = drive_over_hump(steer=1.0, throttle=1.0)
    start = next(i for i, (air, _, _) in enumerate(log) if air)
    end = next(i for i in range(start, len(log)) if not log[i][0])
    x0, y0, h0, v0 = log[start][1]
    x1, y1, _, _ = log[end][2]
    seconds = (end - start + 1) / 60
    assert math.hypot(x1 - (x0 + math.cos(h0) * v0 * seconds), y1 - (y0 + math.sin(h0) * v0 * seconds)) < 0.2


def test_only_layer_zero_launches():
    car = Car(x=-10.0, y=0.0, heading=0.0, speed=50 / 3.6, layer=0, map_level=-1)
    for _ in range(120):
        update_car_physics(car, 0, 0, 0, 0, 1 / 60, ways=[], block_offroad=False, bump_field=hump_field(x=0.0))
        assert not car.airborne
