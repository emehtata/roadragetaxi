"""Tests for NPC-003: a real, persistent, configurable NPC vehicle
population (theroadragetrip.npc.NPCVehicleManager)."""
import math
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from theroadragetrip.npc import (
    NPCAvailability,
    NPC_MOVING_START_LIMIT_PER_TICK,
    NPCState,
    NPCVehicleManager,
    TripGroup,
    has_active_driver,
    place_parked_npc,
    spawn_npc,
    update_npc,
)
from theroadragetrip.osm import Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld

# A city block grid (mirrors test_npc.py's test_spawn_deterministic_npc_
# on_a_city_block_grid fixture) gives many independent roadside spots, so
# many vehicles can spawn without overlapping - unlike a single short
# straight chain. 10x10 blocks (vs. that test's 6x6) so populate_initial's
# bounded-attempts search (see its own docstring) reliably reaches the
# target counts used below without being flaky.
_BLOCK_COUNT = 10
_STEP_M = 40.0
_CENTER = ((_BLOCK_COUNT - 1) * _STEP_M / 2.0, (_BLOCK_COUNT - 1) * _STEP_M / 2.0)
_SPAWN_RADIUS_M = 250.0


def _city_block_grid():
    ways = []
    for row in range(_BLOCK_COUNT):
        for i in range(_BLOCK_COUNT - 1):
            ways.append(Way(points_m=[(i * _STEP_M, row * _STEP_M), ((i + 1) * _STEP_M, row * _STEP_M)], highway="residential", half_width_m=4.5))
    for col in range(_BLOCK_COUNT):
        for i in range(_BLOCK_COUNT - 1):
            ways.append(Way(points_m=[(col * _STEP_M, i * _STEP_M), (col * _STEP_M, (i + 1) * _STEP_M)], highway="residential", half_width_m=4.5))
    return ways


def _straight_chain(count: int = 16, step: float = 40.0):
    return [
        Way(points_m=[(i * step, 0.0), ((i + 1) * step, 0.0)], highway="residential", half_width_m=4.5)
        for i in range(count)
    ]


def test_populate_initial_reaches_target_count():
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    assert len(manager.vehicles) == 8


def test_populate_initial_gives_vehicles_a_variety_of_colors():
    """Reported: every NPC vehicle was the exact same flat gray."""
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    assert len(manager.vehicles) == 8
    assert len({vehicle.color for vehicle in manager.vehicles}) > 1


def test_place_one_rejects_a_point_another_vehicle_is_already_driving_toward():
    """Reported: a car returning to a yard found a brand-new car had, in
    the meantime, been spawned right into its spot. Population growth
    (_place_one) used to only check a candidate point against other
    vehicles' *current* positions - a vehicle mid-trip isn't physically at
    its destination yet, so that check alone saw the target spot as
    completely free and happily placed a new vehicle there."""
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=1, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})

    en_route = place_parked_npc(1, (1000.0, 1000.0), None, vehicle_type="car")
    en_route.state = NPCState.CRUISING
    en_route.destination = (0.0, 0.0)
    manager.vehicles.append(en_route)
    manager._next_vehicle_id = 2

    claimed_point = manager._place_one((0.0, 0.0), None, ways, None, None, None, None, None)
    assert claimed_point is None

    free_point = manager._place_one((500.0, 500.0), None, ways, None, None, None, None, None)
    assert free_point is not None


def test_populate_initial_reports_progress_gradually():
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    fractions = []
    manager.populate_initial(*_CENTER, ResidentManager(), ways, progress_callback=fractions.append)
    assert len(fractions) == len(manager.vehicles) == 8
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0


def test_populate_initial_respects_a_car_only_distribution_override():
    """NPC-003 v2 section 14: vehicle_distribution is an explicit override,
    not just a default-mix detail - pinning it to one plugin id must
    produce a population entirely of that type."""
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=6, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    assert manager.vehicles
    assert {vehicle.vehicle_type for vehicle in manager.vehicles} == {"car"}


def test_populate_initial_produces_a_vehicle_type_mix_from_the_distribution():
    """A distribution favoring a second type should actually produce some
    of that type over enough spawn attempts - not just accept the id and
    ignore it."""
    ways = _city_block_grid()
    manager = NPCVehicleManager(
        target_count=15, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 0.5, "motorcycle": 0.5},
    )
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    types = {vehicle.vehicle_type for vehicle in manager.vehicles}
    assert types <= {"car", "motorcycle"}
    assert "motorcycle" in types


def test_population_tick_tops_up_gradually_not_in_one_tick():
    """Section 19/23: a fresh population well below target must not fill
    to target_count in a single population tick - only NPC_POPULATION_
    SPAWN_LIMIT_PER_TICK new vehicles per tick."""
    from theroadragetrip.npc import NPC_POPULATION_SPAWN_LIMIT_PER_TICK, NPC_POPULATION_TICK_S

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=20, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.update(NPC_POPULATION_TICK_S, px, py, residents, traffic_world, ways)
    assert 0 < len(manager.vehicles) <= NPC_POPULATION_SPAWN_LIMIT_PER_TICK
    assert len(manager.vehicles) < manager.target_count


def test_population_tick_maintains_separate_moving_traffic_target():
    from theroadragetrip.npc import NPC_POPULATION_TICK_S

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=12, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)

    for _ in range(3):
        manager.update(NPC_POPULATION_TICK_S, px, py, residents, traffic_world, ways)

    counts = manager.population_counts()
    assert counts["parked"] > 0
    assert counts["moving"] >= 1
    assert counts["moving"] >= counts["moving_target"] - NPC_MOVING_START_LIMIT_PER_TICK


def test_parked_vehicles_do_not_satisfy_moving_target():
    from theroadragetrip.npc import NPC_POPULATION_TICK_S

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=10, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)

    counts_before = manager.population_counts()
    assert counts_before["moving"] == 0

    manager.update(NPC_POPULATION_TICK_S, px, py, residents, traffic_world, ways)

    counts_after = manager.population_counts()
    assert counts_after["moving"] > 0


def test_population_tick_can_spawn_direct_moving_traffic_when_no_parking_trip_starts_exist():
    from theroadragetrip.npc import NPC_POPULATION_TICK_S

    ways = _straight_chain()
    manager = NPCVehicleManager(
        target_count=2,
        max_count=4,
        spawn_radius_m=220.0,
        vehicle_distribution={"car": 1.0},
    )
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()

    manager.update(NPC_POPULATION_TICK_S, 240.0, 0.0, residents, traffic_world, ways)

    counts = manager.population_counts()
    assert counts["moving"] >= 1
    assert counts["drivers"] >= counts["moving"]
    assert all(has_active_driver(vehicle, residents) for vehicle in manager.vehicles if vehicle.state != NPCState.PARKED)


def test_no_duplicate_vehicle_ids_after_several_population_ticks():
    from theroadragetrip.npc import NPC_POPULATION_TICK_S

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=10, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    for _ in range(10):
        manager.update(NPC_POPULATION_TICK_S, px, py, residents, traffic_world, ways)
    ids = [vehicle.vehicle_id for vehicle in manager.vehicles]
    assert len(ids) == len(set(ids))


def test_despawn_never_drops_population_below_min_count():
    """Section 9's configured floor: despawning far, idle, parked
    vehicles must never take the population under min_count even if more
    than that are simultaneously idle and far away."""
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=10, min_count=6, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    assert len(manager.vehicles) == 10
    # Move every vehicle far outside despawn_radius_m without moving the
    # player - simulates the player having driven away.
    for vehicle in manager.vehicles:
        vehicle.car.x, vehicle.car.y = px + 10_000.0, py + 10_000.0
    manager._run_population_tick(px, py, residents, traffic_world, ways, None, None, None, None, None, None, None)
    assert len(manager.vehicles) >= manager.min_count


def test_despawn_never_removes_a_vehicle_currently_visible_in_the_viewport():
    """Reported: cars spawn/despawn visibly inside the viewport. Despawn
    radius alone doesn't guarantee this at every zoom level (a heavily
    zoomed-out viewport can exceed despawn_radius_m) - viewport_bounds
    must be an independent, always-checked guard, same as
    pedestrian.py's population culling."""
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=10, min_count=1, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    assert len(manager.vehicles) == 10
    original_ids = {vehicle.vehicle_id for vehicle in manager.vehicles}
    for vehicle in manager.vehicles:
        vehicle.car.x, vehicle.car.y = px + 10_000.0, py + 10_000.0
    # A viewport, however unrealistic relative to despawn_radius_m, that
    # happens to cover every vehicle's current (moved) position.
    viewport_bounds = (px + 9_000.0, py + 9_000.0, px + 11_000.0, py + 11_000.0)
    manager._run_population_tick(
        px, py, residents, traffic_world, ways, None, None, None, None, None, None, None,
        viewport_bounds=viewport_bounds,
    )
    assert original_ids <= {vehicle.vehicle_id for vehicle in manager.vehicles}


def test_population_tick_treats_an_en_route_vehicles_destination_as_claimed(monkeypatch):
    """Reported: a car seen driving toward the exact spot another car
    (already sent there in an earlier tick, still en route - not yet
    parked) was already heading to. _run_population_tick used to only
    treat currently-PARKED vehicles' own positions as "claimed" when
    searching for a new destination - a vehicle mid-trip, with a
    committed .destination it hasn't reached yet, was invisible to that
    search entirely."""
    import theroadragetrip.npc as npc_module

    ways = _city_block_grid()
    # target_count=6, not 2: populate_initial's bounded-attempts search
    # (see its own docstring, and test_household_vehicle_ownership_
    # persists_through_a_full_trip_cycle's identical note) can occasionally
    # place fewer than a very small target on the first try - headroom
    # keeps this test about the claimed-destination behavior, not that
    # unrelated budget.
    manager = NPCVehicleManager(
        target_count=6, household_fraction=0.0, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0},
    )
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    assert len(manager.vehicles) >= 2

    en_route, idle = manager.vehicles[0], manager.vehicles[1]
    en_route.state = NPCState.CRUISING
    en_route.destination = (999.0, 999.0)
    manager.drivers[en_route.vehicle_id] = object()

    idle.state = NPCState.PARKED
    idle.availability = NPCAvailability.AVAILABLE
    manager.drivers.pop(idle.vehicle_id, None)

    captured = {}

    def fake_find_and_start_npc_trip(vehicle, *args, other_vehicle_positions=None, **kwargs):
        captured["other_vehicle_positions"] = other_vehicle_positions
        return None

    monkeypatch.setattr(npc_module, "find_and_start_npc_trip", fake_find_and_start_npc_trip)
    monkeypatch.setattr(random, "random", lambda: 0.0)  # force the trip-start roll to pass

    manager._run_population_tick(px, py, residents, traffic_world, ways, None, None, None, None, None, None, None)

    assert "other_vehicle_positions" in captured, "the idle vehicle's trip-start search never ran"
    assert (999.0, 999.0) in captured["other_vehicle_positions"]


def test_population_tick_never_spawns_a_vehicle_inside_the_viewport():
    """Reported: cars spawn visibly inside the viewport in a parking
    area. A candidate spawn point inside viewport_bounds must be
    rejected and retried, same as pedestrian.py's spawn_pedestrian.

    Regression: seed 691 previously reproduced a vehicle spawned a hair
    outside the viewport that then got rolled to start a trip in the very
    same tick - _begin_trip_on_vehicle's snap to the route's actual road-
    graph start point moved it a couple of meters, just inside the
    viewport. Fixed by giving the spawn-time rejection a margin
    (NPC_PARKING_ACCESS_TOLERANCE_M) instead of checking the raw
    viewport - seeded here so this specific case is always exercised."""
    random.seed(691)
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=10, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    # A realistically-sized viewport (roughly what a default zoom level
    # shows) centered on the player - most of the much larger spawn
    # circle still lies outside it, so spawning has plenty of room.
    viewport_bounds = (px - 70.0, py - 40.0, px + 70.0, py + 40.0)
    # A single tick's spawn attempts are capped (NPC_POPULATION_SPAWN_
    # LIMIT_PER_TICK * 6) and every found candidate this run happening to
    # land inside the small viewport is possible, if unlikely - several
    # ticks make that combined chance negligible without weakening what's
    # actually being asserted (no vehicle ever *spawned* inside the
    # viewport). Later ticks also roll idle vehicles to start a real trip
    # (step 3/4) - a vehicle actually *driving* into view is completely
    # normal (that's the whole point of visible traffic) and not what
    # this test is about, so each vehicle's position is checked the first
    # tick it appears in, before any later tick's trip-start step could
    # legitimately move it.
    checked_ids = set()
    newly_spawned_positions = []
    for _ in range(10):
        manager._run_population_tick(
            px, py, residents, traffic_world, ways, None, None, None, None, None, None, None,
            viewport_bounds=viewport_bounds,
        )
        for vehicle in manager.vehicles:
            if vehicle.vehicle_id in checked_ids:
                continue
            checked_ids.add(vehicle.vehicle_id)
            newly_spawned_positions.append((vehicle.x, vehicle.y))
    assert newly_spawned_positions
    for x, y in newly_spawned_positions:
        assert not (
            viewport_bounds[0] <= x <= viewport_bounds[2]
            and viewport_bounds[1] <= y <= viewport_bounds[3]
        )


def test_household_vehicle_has_a_home_position_and_kind():
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, household_fraction=1.0, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    assert manager.vehicles
    for vehicle in manager.vehicles:
        assert vehicle.vehicle_kind == "household"
        assert vehicle.household_id is not None
        assert vehicle.home_position == (vehicle.x, vehicle.y)


def test_autonomous_vehicle_has_no_household():
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, household_fraction=0.0, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    assert manager.vehicles
    for vehicle in manager.vehicles:
        assert vehicle.vehicle_kind == "traffic"
        assert vehicle.household_id is None


def test_two_households_stay_independent():
    """A household can own up to NPC_MAX_VEHICLES_PER_HOUSEHOLD vehicles
    (NPC-003 v2 section 9), but two *different* households' vehicles and
    members must never mix."""
    from theroadragetrip.npc import NPC_MAX_VEHICLES_PER_HOUSEHOLD

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, household_fraction=1.0, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    manager.populate_initial(*_CENTER, ResidentManager(), ways)
    household_ids = {vehicle.household_id for vehicle in manager.vehicles}
    assert 1 <= len(household_ids) <= len(manager.vehicles)
    for vehicle in manager.vehicles:
        household = manager.household_manager.get(vehicle.household_id)
        assert vehicle.vehicle_id in household.vehicle_ids
        assert 1 <= len(household.vehicle_ids) <= NPC_MAX_VEHICLES_PER_HOUSEHOLD
        same_household_vehicles = {
            other_vehicle.vehicle_id for other_vehicle in manager.vehicles
            if other_vehicle.household_id == vehicle.household_id
        }
        assert same_household_vehicles == household.vehicle_ids
        assert all(
            other_vehicle.household_id != vehicle.household_id
            for other_vehicle in manager.vehicles
            if other_vehicle.vehicle_id not in household.vehicle_ids
        )


def test_household_can_own_two_vehicles():
    """NPC-003 v2 section 9's explicit acceptance criterion: a household
    can own zero, one, or two vehicles - forced deterministic here since
    NPC_SECOND_HOUSEHOLD_VEHICLE_PROBABILITY is a low-probability roll."""
    manager = NPCVehicleManager(target_count=2, household_fraction=1.0)
    residents = ResidentManager()
    first = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    second = place_parked_npc(2, (10.0, 0.0), None, vehicle_type="car")
    manager.vehicles.extend([first, second])
    manager._make_household(first, residents)
    household = manager.household_manager.get(first.household_id)
    assert len(household.vehicle_ids) == 1

    import random as random_module
    original_random = random_module.random
    original_choice = random_module.choice
    random_module.random = lambda: 0.0  # always take the "join existing" branch
    random_module.choice = lambda seq: household
    try:
        manager._make_household(second, residents)
    finally:
        random_module.random = original_random
        random_module.choice = original_choice

    assert second.household_id == first.household_id
    assert household.vehicle_ids == {first.vehicle_id, second.vehicle_id}


def test_household_owned_second_vehicle_never_exceeds_max():
    """A household already at NPC_MAX_VEHICLES_PER_HOUSEHOLD must not
    accept a third vehicle even when the join roll succeeds."""
    from theroadragetrip.npc import NPC_MAX_VEHICLES_PER_HOUSEHOLD

    manager = NPCVehicleManager(target_count=1, household_fraction=1.0)
    residents = ResidentManager()
    vehicles = [place_parked_npc(i, (float(i) * 10.0, 0.0), None, vehicle_type="car") for i in range(1, 4)]
    manager.vehicles.extend(vehicles)
    for vehicle in vehicles:
        manager._make_household(vehicle, residents)
    household_ids = {vehicle.household_id for vehicle in vehicles}
    for household_id in household_ids:
        household = manager.household_manager.get(household_id)
        assert len(household.vehicle_ids) <= NPC_MAX_VEHICLES_PER_HOUSEHOLD


def test_non_household_eligible_plugin_never_becomes_household_kind():
    """NPC-003 v2 section 14: a truck/bus rolled into the household
    fraction stays a plain traffic vehicle - not every plugin is eligible
    for household ownership."""
    manager = NPCVehicleManager(target_count=1, household_fraction=1.0)
    residents = ResidentManager()
    truck = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="truck")
    manager.vehicles.append(truck)
    manager._make_household(truck, residents)
    assert truck.vehicle_kind == "traffic"
    assert truck.household_id is None


def test_continue_npc_trip_is_deferred_to_the_population_tick_not_every_frame():
    """Perf-critical: continue_npc_trip's BFS-walk-then-plan_route search
    costs well over a second per call against real dense OSM data
    (measured). It must never fire from update()'s per-frame hot loop the
    instant a vehicle parks with all_aboard True - only from the
    throttled, budget-capped population tick, exactly like a brand-new
    trip start already is."""
    from theroadragetrip.npc import NPC_POPULATION_TICK_S, spawn_npc

    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    spawned = spawn_npc(1, residents, traffic_world, ways, (20.0, 0.0), (60.0, 0.0))
    assert spawned is not None
    _, driver, vehicle = spawned
    vehicle.state = NPCState.PARKED
    vehicle.car.x, vehicle.car.y = 20.0, 0.0
    for member_id in list(vehicle.trip_group.member_resident_ids):
        vehicle.trip_group.boarded_resident_ids.add(member_id)
    assert vehicle.trip_group.all_aboard
    original_destination = vehicle.destination

    manager = NPCVehicleManager(target_count=1)
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    manager._population_elapsed = 0.0  # don't let the first update() call fire a tick

    for _ in range(5):
        manager.update(0.1, 20.0, 0.0, residents, traffic_world, ways)
    assert vehicle.state == NPCState.PARKED
    assert vehicle.destination == original_destination

    manager._population_elapsed = NPC_POPULATION_TICK_S
    manager.update(0.0, 20.0, 0.0, residents, traffic_world, ways)
    assert vehicle.destination != original_destination or vehicle.state != NPCState.PARKED


def test_reserved_vehicle_is_excluded_from_idle_trip_start_candidates():
    """Section 7: a RESERVED household vehicle must not be among the
    idle-parked vehicles the population tick rolls for a new,
    unrelated trip."""
    from theroadragetrip.npc import NPC_POPULATION_TICK_S, reserve_household_vehicle

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, household_fraction=1.0, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    vehicle = manager.vehicles[0]
    assert vehicle.availability == NPCAvailability.AVAILABLE
    reserve_household_vehicle(vehicle)
    assert vehicle.availability == NPCAvailability.RESERVED
    for _ in range(5):
        manager.update(NPC_POPULATION_TICK_S, px, py, residents, traffic_world, ways)
    # Still parked, idle, and untouched by the population tick's own trip
    # rolls - reservation is respected, not overridden by unrelated logic.
    assert vehicle.state == NPCState.PARKED
    assert manager.drivers.get(vehicle.vehicle_id) is None


def test_vehicle_outside_simulation_radius_is_not_ticked():
    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, spawn_radius_m=_SPAWN_RADIUS_M, simulation_radius_m=100.0, vehicle_distribution={"car": 1.0})
    residents = ResidentManager()
    traffic_world = TrafficWorld(ways)
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    vehicle = manager.vehicles[0]
    from theroadragetrip.npc import start_npc_trip

    # A handful of fixed grid corners rather than the probabilistic BFS
    # search (find_and_start_npc_trip) - this test only needs *a* valid
    # driver to exist, deterministically, not to exercise trip discovery.
    driver = None
    corner = (_BLOCK_COUNT - 1) * _STEP_M
    for destination in [(0.0, 0.0), (corner, 0.0), (0.0, corner), (corner, corner), (corner / 2.0, corner)]:
        driver = start_npc_trip(vehicle, residents, traffic_world, ways, destination)
        if driver is not None:
            break
    assert driver is not None
    manager.drivers[vehicle.vehicle_id] = driver
    original_state = vehicle.state
    vehicle.car.x, vehicle.car.y = px + 10_000.0, py + 10_000.0
    manager.update(1.0, px, py, residents, traffic_world, ways)
    # Untouched except for our own manual move above - update() must have
    # skipped it entirely (no physics/state change from update_npc).
    assert vehicle.state == original_state


def test_no_duplicate_spawn_when_population_already_at_target():
    from theroadragetrip.npc import NPC_POPULATION_TICK_S

    ways = _city_block_grid()
    manager = NPCVehicleManager(target_count=8, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    assert len(manager.vehicles) == 8
    for _ in range(5):
        manager.update(NPC_POPULATION_TICK_S, px, py, residents, traffic_world, ways)
    assert len(manager.vehicles) == 8


def test_population_counts_by_type_matches_actual_vehicles():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    truck = place_parked_npc(2, (10.0, 0.0), None, vehicle_type="truck")
    manager.vehicles.extend([car, truck])
    counts = manager.population_counts_by_type()
    assert counts == {"car": 1, "truck": 1}


def test_request_vehicle_reserves_an_eligible_household_vehicle():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(car)
    manager._make_household(car, residents)
    household = manager.household_manager.get(car.household_id)

    won = manager.request_vehicle(household, passengers=2)
    assert won is car
    assert car.availability == NPCAvailability.RESERVED


def test_request_vehicle_excludes_a_reserved_vehicle():
    from theroadragetrip.npc import reserve_household_vehicle

    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(car)
    manager._make_household(car, residents)
    household = manager.household_manager.get(car.household_id)
    reserve_household_vehicle(car)

    assert manager.request_vehicle(household, passengers=1) is None


def test_request_vehicle_excludes_a_vehicle_without_enough_capacity():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    motorcycle = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="motorcycle")
    manager.vehicles.append(motorcycle)
    manager._make_household(motorcycle, residents)
    household = manager.household_manager.get(motorcycle.household_id)

    assert manager.request_vehicle(household, passengers=3) is None
    assert motorcycle.availability == NPCAvailability.AVAILABLE


def test_request_vehicle_ignores_a_vehicle_the_household_does_not_own():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    own_car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    other_car = place_parked_npc(2, (50.0, 0.0), None, vehicle_type="car")
    manager.vehicles.extend([own_car, other_car])
    manager._make_household(own_car, residents)
    manager._make_household(other_car, residents)
    household = manager.household_manager.get(own_car.household_id)

    won = manager.request_vehicle(household, passengers=1)
    assert won is own_car


def test_reserve_household_vehicle_claims_an_available_vehicle():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(car)
    manager._make_household(car, residents)

    from theroadragetrip.npc import reserve_household_vehicle

    assert car.availability == NPCAvailability.AVAILABLE
    assert reserve_household_vehicle(car) is True
    assert car.availability == NPCAvailability.RESERVED


def test_reserve_household_vehicle_prevents_a_duplicate_reservation():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(car)
    manager._make_household(car, residents)

    from theroadragetrip.npc import reserve_household_vehicle

    assert reserve_household_vehicle(car) is True
    # Already RESERVED - a second, unrelated claim must not succeed.
    assert reserve_household_vehicle(car) is False
    assert car.availability == NPCAvailability.RESERVED


def test_reserve_household_vehicle_rejects_a_non_household_vehicle():
    from theroadragetrip.npc import reserve_household_vehicle

    truck = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="truck")
    assert truck.vehicle_kind == "traffic"
    assert reserve_household_vehicle(truck) is False
    assert truck.availability == NPCAvailability.AVAILABLE


def test_reserve_household_vehicle_rejects_a_vehicle_mid_trip():
    """A vehicle already out on a trip (has a trip_group) must not be
    claimed by an unrelated reservation, even if its availability field
    hasn't been separately marked RESERVED/IN_USE."""
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(car)
    manager._make_household(car, residents)
    car.trip_group = TripGroup(
        group_id=1, vehicle_id=car.vehicle_id, member_resident_ids=[car.owner_id or 1], boarded_resident_ids=set(),
    )

    from theroadragetrip.npc import reserve_household_vehicle

    assert reserve_household_vehicle(car) is False
    assert car.availability == NPCAvailability.AVAILABLE


def test_release_household_vehicle_makes_a_reserved_vehicle_available_again():
    manager = NPCVehicleManager(target_count=1)
    residents = ResidentManager()
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(car)
    manager._make_household(car, residents)

    from theroadragetrip.npc import release_household_vehicle, reserve_household_vehicle

    reserve_household_vehicle(car)
    assert car.availability == NPCAvailability.RESERVED
    release_household_vehicle(car)
    assert car.availability == NPCAvailability.AVAILABLE


def test_release_household_vehicle_is_idempotent():
    """Safe to call even if the vehicle was never reserved."""
    car = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="car")
    from theroadragetrip.npc import release_household_vehicle

    assert car.availability == NPCAvailability.AVAILABLE
    release_household_vehicle(car)
    release_household_vehicle(car)
    assert car.availability == NPCAvailability.AVAILABLE


def test_household_vehicle_ownership_persists_through_a_full_trip_cycle():
    """NPC-003 v2 acceptance criterion ("vehicle ownership persists") and
    this project's own testing checklist ("household association
    survives a full drive-park-drive-home cycle") - not just the single
    leg most other tests exercise."""
    from theroadragetrip.npc import find_and_start_npc_trip

    ways = _city_block_grid()
    # target_count=3, not 1: populate_initial's bounded-attempts search
    # (see its own docstring) can occasionally place fewer than a very
    # small target on the first try - a little headroom keeps this test
    # about the ownership-persists behavior, not that unrelated budget.
    manager = NPCVehicleManager(
        target_count=3, household_fraction=1.0, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0},
    )
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    px, py = _CENTER
    manager.populate_initial(px, py, residents, ways)
    assert manager.vehicles
    vehicle = manager.vehicles[0]
    assert vehicle.vehicle_kind == "household"
    household_id = vehicle.household_id
    assert household_id is not None
    home_position = vehicle.home_position

    driver = find_and_start_npc_trip(vehicle, residents, traffic_world, ways)
    assert driver is not None
    manager.drivers[vehicle.vehicle_id] = driver

    # A real dt (matching every other driving test in this file/module) -
    # a huge dt starves the steering/corner logic of the small, frequent
    # updates it expects and the vehicle oscillates in place forever
    # instead of actually completing turns.
    #
    # NPC-004: this synthetic map has no traffic lights/right-of-way logic
    # at its many unsignalized intersections, so - now that real vehicle-
    # vehicle collision detection exists - an occasional crash during a
    # long, continuous, multi-minute drive is a legitimate, intentional
    # outcome (spec section 25: "robust rather than perfect... NPCs should
    # make mistakes occasionally"), not a bug. Household ownership must
    # survive either ending: a normal retirement, or an accident cleanly
    # severing the driver.
    retired = False
    crashed = False
    for _ in range(12000):
        manager.update(1.0 / 30.0, px, py, residents, traffic_world, ways)
        # Ownership must survive every leg of the trip - departure,
        # arrival/waiting, and the drive home - not just the first one.
        assert vehicle.vehicle_kind == "household"
        assert vehicle.household_id == household_id
        if manager.drivers.get(vehicle.vehicle_id) is None and vehicle.state == NPCState.PARKED:
            retired = True
            break
        if vehicle.state == NPCState.CRASHED:
            crashed = True
            break
    assert retired or crashed, "vehicle neither made it home nor had a well-formed accident"
    if crashed:
        assert vehicle.driver_departed is True
        assert vehicle.car.speed == 0.0
        return
    distance_from_home = math.hypot(vehicle.x - home_position[0], vehicle.y - home_position[1])
    assert distance_from_home < 100.0


def test_experimental_vehicles_excluded_from_default_distribution():
    """Motorcycle is marked experimental (vehicles/plugins/motorcycle.py) -
    off by default, matching config's [experimental] enable_two_wheelers
    default of false."""
    manager = NPCVehicleManager(target_count=1)
    assert "motorcycle" not in manager.vehicle_distribution
    assert "car" in manager.vehicle_distribution


def test_include_experimental_restores_motorcycle_in_default_distribution():
    manager = NPCVehicleManager(target_count=1, include_experimental=True)
    assert manager.vehicle_distribution.get("motorcycle", 0.0) > 0.0


def test_explicit_vehicle_distribution_override_bypasses_experimental_gate():
    """An explicit override is always respected, even for an experimental
    plugin - only the *default* distribution is gated."""
    manager = NPCVehicleManager(target_count=1, vehicle_distribution={"motorcycle": 1.0})
    assert manager.vehicle_distribution == {"motorcycle": 1.0}


def _driving_vehicle(residents, x, y, heading=0.0, vehicle_id=1):
    """A parked NPCVehicle wired up with a real active driver (owner_id +
    resident.active_vehicle_id both matching) - place_parked_npc alone
    creates an empty, driverless vehicle, so NPC-004's accident response
    (which reads has_active_driver) needs this extra wiring in tests."""
    vehicle = place_parked_npc(vehicle_id, (x, y), None, vehicle_type="car")
    vehicle.car.heading = heading
    resident = residents.create(mode="driving")
    vehicle.owner_id = resident.resident_id
    resident.active_vehicle_id = vehicle.vehicle_id
    return vehicle, resident


def test_trigger_vehicle_accident_stops_the_vehicle_and_ejects_the_driver():
    """NPC-004 sections 10-17: collision -> stopped CRASHED vehicle,
    driver permanently severed, and (since someone was actually driving)
    a new annoyed pedestrian checking their phone nearby."""
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    vehicle, resident = _driving_vehicle(residents, 5.0, 0.0)
    manager.vehicles.append(vehicle)
    sidewalk = Way(points_m=[(0.0, 3.0), (20.0, 3.0)], highway="footway", half_width_m=2.0)
    pedestrian_mgr = PedestrianManager([sidewalk], target_count=0)

    manager._trigger_vehicle_accident(vehicle, residents, pedestrian_mgr, sim_time=100.0)

    assert vehicle.state == NPCState.CRASHED
    assert vehicle.driver_departed is True
    assert vehicle.car.speed == 0.0
    assert manager.drivers.get(vehicle.vehicle_id) is None
    assert resident.active_vehicle_id is None
    assert not has_active_driver(vehicle, residents)

    matching = [ped for ped in pedestrian_mgr.pedestrians if ped.resident_id == resident.resident_id]
    assert len(matching) == 1
    pedestrian = matching[0]
    assert pedestrian.mood == "annoyed"
    assert pedestrian.activity is not None
    assert pedestrian.activity.plugin_id == "phone_usage"


def test_trigger_vehicle_accident_never_retriggers():
    """Section 18: the accident must not repeatedly trigger - a second
    call on an already-CRASHED vehicle must be a pure no-op, never
    ejecting a second pedestrian for the same driver."""
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    vehicle, resident = _driving_vehicle(residents, 5.0, 0.0)
    manager.vehicles.append(vehicle)
    sidewalk = Way(points_m=[(0.0, 3.0), (20.0, 3.0)], highway="footway", half_width_m=2.0)
    pedestrian_mgr = PedestrianManager([sidewalk], target_count=0)

    manager._trigger_vehicle_accident(vehicle, residents, pedestrian_mgr, sim_time=100.0)
    manager._trigger_vehicle_accident(vehicle, residents, pedestrian_mgr, sim_time=101.0)

    assert len(pedestrian_mgr.pedestrians) == 1


def test_trigger_vehicle_accident_with_no_driver_still_becomes_an_obstacle():
    """A vehicle that gets hit while genuinely idle (no active driver) has
    nobody to eject - it must still become a stopped CRASHED obstacle."""
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    vehicle = place_parked_npc(1, (5.0, 0.0), None, vehicle_type="car")
    manager.vehicles.append(vehicle)
    pedestrian_mgr = PedestrianManager([], target_count=0)

    manager._trigger_vehicle_accident(vehicle, residents, pedestrian_mgr, sim_time=100.0)

    assert vehicle.state == NPCState.CRASHED
    assert vehicle.driver_departed is True
    assert pedestrian_mgr.pedestrians == []


def test_check_vehicle_collision_crashes_both_overlapping_npc_vehicles():
    """NPC-004 section 10: an actual NPC-NPC overlap must crash *both*
    vehicles, each getting its own independent accident."""
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    vehicle_a, resident_a = _driving_vehicle(residents, 0.0, 0.0, vehicle_id=1)
    vehicle_b, resident_b = _driving_vehicle(residents, 1.0, 0.0, vehicle_id=2)  # well within each other's footprint
    manager.vehicles.extend([vehicle_a, vehicle_b])
    pedestrian_mgr = PedestrianManager([], target_count=0)

    manager._check_vehicle_collision(vehicle_a, [vehicle_b], residents, pedestrian_mgr, sim_time=50.0)

    assert vehicle_a.state == NPCState.CRASHED
    assert vehicle_b.state == NPCState.CRASHED


def test_check_vehicle_collision_ignores_vehicles_that_do_not_overlap():
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    vehicle_a, _ = _driving_vehicle(residents, 0.0, 0.0, vehicle_id=1)
    vehicle_b, _ = _driving_vehicle(residents, 100.0, 0.0, vehicle_id=2)
    manager.vehicles.extend([vehicle_a, vehicle_b])
    pedestrian_mgr = PedestrianManager([], target_count=0)

    manager._check_vehicle_collision(vehicle_a, [vehicle_b], residents, pedestrian_mgr, sim_time=50.0)

    assert vehicle_a.state != NPCState.CRASHED
    assert vehicle_b.state != NPCState.CRASHED


def test_check_vehicle_collision_with_the_player_car_only_crashes_the_npc():
    """Section 11: an NPC-taxi collision must trigger the NPC's own
    accident response without touching the player's car at all."""
    from theroadragetrip.physics import Car

    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    vehicle, _ = _driving_vehicle(residents, 0.0, 0.0)
    manager.vehicles.append(vehicle)
    player_car = Car(x=1.0, y=0.0, heading=0.0, speed=15.0)
    pedestrian_mgr = PedestrianManager([], target_count=0)

    manager._check_vehicle_collision(vehicle, [player_car], residents, pedestrian_mgr, sim_time=50.0)

    assert vehicle.state == NPCState.CRASHED
    assert player_car.speed == 15.0  # untouched - taxi physics/scoring stays taxi.py's own business


def test_population_tick_reroutes_a_stuck_vehicle_when_a_valid_route_exists():
    """NPC-004 section 3/6/8's recovery step: a vehicle update_npc flagged
    STUCK gets a fresh route from wherever it currently sits, planned off
    the throttled population tick (never per-frame - see that function's
    own comment on why), and resumes normal driving."""
    from theroadragetrip.npc import spawn_npc

    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    result = spawn_npc(1, residents, traffic_world, ways, _CENTER, (_CENTER[0] + 80.0, _CENTER[1]))
    assert result is not None
    _, driver, vehicle = result
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    driver.recovery_stage = "STUCK"
    old_path = driver.path

    manager._run_population_tick(
        _CENTER[0], _CENTER[1], residents, traffic_world, ways, None, None, None, None, None, None, None,
    )

    assert driver.recovery_stage == "NORMAL"
    assert vehicle.state == NPCState.CRUISING
    assert driver.path is not old_path
    assert driver.path_index == 1


def test_population_tick_falls_back_to_reversing_when_no_route_exists():
    """When no valid route can be found from the vehicle's current
    position (e.g. genuinely boxed in), recovery must fall back to a
    controlled reverse rather than leaving the vehicle marked STUCK
    forever with nothing ever retrying it differently."""
    from theroadragetrip.npc import spawn_npc

    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    result = spawn_npc(1, residents, traffic_world, ways, _CENTER, (_CENTER[0] + 80.0, _CENTER[1]))
    assert result is not None
    _, driver, vehicle = result
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    driver.recovery_stage = "STUCK"
    # An unreachable destination, far outside any mapped road - no route
    # can ever validate to it.
    driver.destination = (1_000_000.0, 1_000_000.0)

    manager._run_population_tick(
        _CENTER[0], _CENTER[1], residents, traffic_world, ways, None, None, None, None, None, None, None,
    )

    assert driver.recovery_stage == "REVERSING"
    assert vehicle.state == NPCState.REVERSING


def test_manager_update_avoidance_still_works_without_a_player_car():
    """Regression: nearby_vehicles_at (its own spatial-grid query) yields,
    it doesn't return a list. update() used to only materialize it into a
    real list inside the `if player_car is not None` branch
    (list(nearby_obstacles) + [player_car]) - without a player_car, that
    same one-shot generator got consumed twice (once for collision
    detection, once again for avoidance inside update_npc), so the second
    consumer silently saw nothing at all and avoidance never engaged.
    Reproduced as a real rear-end collision in a full drive-cycle stress
    test purely because player_car was omitted."""
    ways = [
        Way(points_m=[(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], highway="residential", half_width_m=4.5)
        for i in range(20)
    ]
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=2)
    result = spawn_npc(1, residents, traffic_world, ways, (0.0, 0.0), (200.0, 0.0))
    assert result is not None
    _, driver, vehicle = result
    vehicle.car.speed = 10.0
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    blocker = place_parked_npc(2, (vehicle.car.x + 8.0, vehicle.car.y), None, vehicle_type="car")
    manager.vehicles.append(blocker)

    for _ in range(30):
        manager.update(1.0 / 30.0, 0.0, 0.0, residents, traffic_world, ways)

    assert driver.target_speed_mps < 5.0
