"""Tests for pedestrian simulation, movement, traffic light compliance, and dodging."""
import math
import pytest
from types import SimpleNamespace
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.osm import Building, TrafficLight, Way
from theroadragetrip.osm import TaxiStop
from theroadragetrip.pedestrian import (
    CyclistManager,
    Pedestrian,
    PedestrianAppearance,
    PedestrianManager,
    PedestrianNetwork,
    PedestrianState,
)
from theroadragetrip.npc import NPCState, spawn_npc, update_npc
from theroadragetrip.physics import Car
from theroadragetrip.render import draw_pedestrians
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


def test_pedestrian_network_routes_across_connected_ways():
    network = PedestrianNetwork([
        Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=2.0),
        Way(points_m=[(10.0, 0.0), (10.0, 10.0)], highway="footway", half_width_m=2.0),
    ])

    route = network.route((0.0, 0.0), (10.0, 10.0))

    assert (10.0, 0.0) in route
    assert network.nearest_point((8.0, 2.0)) == (8.0, 0.0)


def test_sync_map_data_adds_streamed_footway():
    initial_way = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=2.0,
    )
    streamed_way = Way(
        points_m=[(20.0, 0.0), (30.0, 0.0)], highway="footway", half_width_m=2.0,
    )
    manager = PedestrianManager([initial_way], target_count=0)

    manager.sync_map_data([initial_way, streamed_way])

    assert streamed_way in manager.ped_ways
    assert streamed_way in manager._spawn_ways


def _grid_pedestrian_ways(count: int) -> list:
    return [
        Way(
            points_m=[(float(i * 20), 0.0), (float(i * 20 + 15), 0.0)],
            highway="footway", half_width_m=1.5,
            bbox=(float(i * 20), -1.5, float(i * 20 + 15), 1.5),
        )
        for i in range(count)
    ]


def test_incremental_sync_serves_old_result_until_finished():
    """bin-loader-v3.md: start_incremental_sync()/advance_incremental_sync()
    must not touch ped_ways/route graph/junction grid until the whole job
    commits - live queries mid-rebuild must see the OLD complete result."""
    old_ways = _grid_pedestrian_ways(3)
    manager = PedestrianManager(old_ways, target_count=0)
    old_ped_ways_count = len(manager.ped_ways)

    new_ways = _grid_pedestrian_ways(60)
    manager.start_incremental_sync(new_ways)
    assert len(manager.ped_ways) == old_ped_ways_count, "old result must still be live right after start"
    assert not manager.advance_incremental_sync(0.0), "a job this size must not finish in one zero-budget call"
    assert len(manager.ped_ways) == old_ped_ways_count, "old result must still be live mid-rebuild"
    assert manager._sync_stage not in (None, "done")


def test_incremental_sync_can_pause_and_resume_across_many_calls():
    ways = _grid_pedestrian_ways(60)
    manager = PedestrianManager([], target_count=0)
    manager.start_incremental_sync(ways)
    finished = False
    steps = 0
    while not finished:
        finished = manager.advance_incremental_sync(0.0)
        steps += 1
        assert steps < 5000, "incremental sync never finished"
    assert steps > 1, "a zero budget must force multiple advance_incremental_sync() calls"
    assert manager._sync_stage == "done"
    assert len(manager.ped_ways) == len(ways)


def test_incremental_sync_matches_synchronous_sync_map_data_exactly():
    ways = _grid_pedestrian_ways(60)
    building = SimpleNamespace(
        points_m=[(100.0, -5.0), (110.0, -5.0), (110.0, 5.0), (100.0, 5.0)],
        bbox=(100.0, -5.0, 110.0, 5.0),
        entrances=[],
        venue_type=None,
    )

    sync_mgr = PedestrianManager([], target_count=0, venue_buildings=[building])
    sync_mgr.sync_map_data(ways)

    inc_mgr = PedestrianManager([], target_count=0, venue_buildings=[building])
    inc_mgr.start_incremental_sync(ways)
    finished = False
    while not finished:
        finished = inc_mgr.advance_incremental_sync(0.0)

    sync_points = sorted(tuple(w.points_m) for w in sync_mgr.ped_ways)
    inc_points = sorted(tuple(w.points_m) for w in inc_mgr.ped_ways)
    assert sync_points == inc_points
    assert sync_mgr.network.nodes == inc_mgr.network.nodes
    assert sync_mgr.network.edges == inc_mgr.network.edges
    assert sync_mgr._junction_grid.keys() == inc_mgr._junction_grid.keys()
    assert len(sync_mgr._spawn_ways) == len(inc_mgr._spawn_ways)
    assert sync_mgr._way_grid.keys() == inc_mgr._way_grid.keys()


def test_incremental_sync_handles_repeated_batches_without_duplicates():
    """Multiple tile-streaming batches arriving one after another (start_
    incremental_sync called again once a previous job finished) must not
    accumulate stale or duplicate ways - each sync fully replaces the
    previous result, matching sync_map_data()'s own behavior."""
    first_batch = _grid_pedestrian_ways(10)
    manager = PedestrianManager([], target_count=0)
    manager.start_incremental_sync(first_batch)
    finished = False
    while not finished:
        finished = manager.advance_incremental_sync(0.0)
    assert len(manager.ped_ways) == 10

    second_batch = _grid_pedestrian_ways(25)  # a larger, overlapping-range batch
    manager.start_incremental_sync(second_batch)
    finished = False
    while not finished:
        finished = manager.advance_incremental_sync(0.0)
    assert len(manager.ped_ways) == 25
    assert len(set(id(w) for w in manager.ped_ways)) == 25


def test_building_free_ways_skips_far_way_but_still_splits_one_near_a_building():
    """_building_free_ways' bbox pre-check must skip the expensive
    per-segment building scan for a way nowhere near any building (fast
    path, returned unchanged), while a way that genuinely runs through a
    building still gets split around it exactly as before (slow path)."""
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        bbox=(18.0, -2.0, 22.0, 2.0),
        entrances=[],
        venue_type=None,
    )
    crossing_way = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0), (30.0, 0.0), (40.0, 0.0)],
        highway="footway", half_width_m=1.5,
        bbox=(0.0, 0.0, 40.0, 0.0),
    )
    far_way = Way(
        points_m=[(5000.0, 5000.0), (5010.0, 5000.0)],
        highway="footway", half_width_m=1.5,
        bbox=(5000.0, 5000.0, 5010.0, 5000.0),
    )
    manager = PedestrianManager([crossing_way, far_way], target_count=0, venue_buildings=[building])

    assert any(way.points_m == far_way.points_m for way in manager.ped_ways)
    assert all(
        not point_in_polygon(point[0], point[1], building.points_m)
        for way in manager.ped_ways
        for point in way.points_m
    )


def test_pedestrian_routes_and_spawns_stay_outside_buildings():
    ways = [Way(
        points_m=[(0.0, 0.0), (10.0, 0.0), (30.0, 0.0), (40.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )]
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        bbox=(18.0, -2.0, 22.0, 2.0),
        entrances=[(20.0, 0.0)],
        venue_type=None,
    )
    manager = PedestrianManager(ways, target_count=0, venue_buildings=[building])

    assert manager.spawn_pedestrian_at(20.0, 0.0) is None
    assert all(
        not point_in_polygon(point[0], point[1], building.points_m)
        for way in manager.ped_ways
        for point in way.points_m
    )
    assert manager.spawn_pedestrian_at_door(20.0, 0.0) is not None


def test_spawn_at_door_does_not_snap_onto_a_way_reachable_only_through_the_building():
    """Regression: spawn_pedestrian_at_door's nearest-way search picked
    the geometrically closest ped_way regardless of whether reaching it
    from the door required cutting through the building itself - a way
    just behind the building can be closer as the crow flies than the
    real street out front across an open lot/plaza (reported: pedestrians
    spawn at the door then walk straight through the building). The
    nearer-but-blocked way must be skipped in favor of the farther,
    actually-reachable one."""
    front_street = Way(points_m=[(-10.0, -30.0), (30.0, -30.0)], highway="footway", half_width_m=1.5)
    back_alley = Way(points_m=[(-10.0, 21.0), (30.0, 21.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(
        points_m=[(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        bbox=(0.0, 0.0, 20.0, 20.0),
        entrances=[(10.0, 0.0)],
        venue_type=None,
    )
    manager = PedestrianManager([front_street, back_alley], target_count=0, venue_buildings=[building])

    pedestrian = manager.spawn_pedestrian_at_door(10.0, 0.0)

    assert pedestrian is not None
    assert pedestrian.way.points_m == front_street.points_m


def test_pedestrian_state_and_appearance_support_interactions():
    assert PedestrianState.APPROACHING_CROSSING.value == "approaching_crossing"
    appearance = PedestrianAppearance(body=(10, 20, 30))
    assert appearance.body == (10, 20, 30)
    assert appearance.head == (238, 185, 145)


def test_drunk_promille_changes_walking_and_can_cause_a_fall(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)
    pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.is_drunk = True
    pedestrian.blood_alcohol_promille = 3.0
    pedestrian.fall_cooldown = 100.0
    pedestrian.drunk_vomit_cooldown = 100.0
    manager.pedestrians = [pedestrian]

    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 1.0)
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert 0.5 <= pedestrian.blood_alcohol_promille <= 3.0
    assert pedestrian.speed < pedestrian.base_speed

    pedestrian.fall_cooldown = 0.0
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian.state == "fallen"
    assert pedestrian.animation_state == "fallen"


def test_vehicle_exit_can_use_explicit_transition_state():
    way = Way(points_m=[(0.0, 0.0), (30.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(x=10.0, y=0.0, heading=0.0, width_m=1.8, state="occupied", current_driver_id=None)
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    vehicle.current_driver_id = id(pedestrian)
    assert manager.exit_vehicle(pedestrian, vehicle, animate=True)
    assert pedestrian.state == PedestrianState.EXITING_VEHICLE.value


def test_crashed_driver_pedestrian_keeps_resident_identity():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=2.0)
    residents = ResidentManager()
    resident = residents.create("driving")
    manager = PedestrianManager([way], target_count=0, residents=residents)

    pedestrian = manager.spawn_pedestrian_at(20.0, 0.0, resident_id=resident.resident_id)

    assert pedestrian is not None
    assert pedestrian.resident_id == resident.resident_id
    assert list(residents.residents).count(resident.resident_id) == 1


def test_pedestrian_target_count_keeps_nearest_characters():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=3)
    manager.pedestrians = [
        Pedestrian(1.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1)),
        Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1)),
        Pedestrian(30.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1)),
    ]

    manager.set_target_count(2, Car(x=0.0, y=0.0, heading=0.0, speed=0.0))

    assert [ped.x for ped in manager.pedestrians] == [1.0, 10.0]


def test_repeated_target_count_updates_do_not_delay_population_check():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=1)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)
    manager._population_update_elapsed = 4.9

    manager.set_target_count(1, player)
    manager.update(player, dt=0.1)

    assert len(manager.pedestrians) == 1


def test_population_spawn_does_not_fallback_into_viewport(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=1)
    calls = []

    def blocked_spawn(*args, **kwargs):
        calls.append(kwargs.get("viewport_bounds"))
        return None

    monkeypatch.setattr(manager, "spawn_pedestrian", blocked_spawn)
    manager._population_update_elapsed = 5.0
    manager.update(
        Car(x=50.0, y=0.0, heading=0.0, speed=0.0),
        dt=0.1,
        viewport_bounds=(0.0, -10.0, 100.0, 10.0),
    )

    assert calls
    assert all(call == (0.0, -10.0, 100.0, 10.0) for call in calls)
    assert len(calls) > 1
    assert manager.pedestrians == []


def test_pedestrian_can_reserve_any_nearby_parked_vehicle():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))

    assert manager.find_available_parked_vehicle(pedestrian.x, pedestrian.y, 10.0) is vehicle
    assert manager.reserve_parked_vehicle(pedestrian, vehicle)
    assert not manager.reserve_parked_vehicle(pedestrian, vehicle)
    assert vehicle.state == "reserved"
    manager.cancel_vehicle_reservation(pedestrian)
    assert vehicle.state == "parked"


def test_pedestrian_cannot_reserve_vehicle_over_100_meters_away():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=100.1,
        y=0.0,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))

    assert manager.reserve_parked_vehicle(pedestrian, vehicle) is False
    assert vehicle.reserved_by_pedestrian_id is None
    assert vehicle.state == "parked"


def test_pedestrian_can_reserve_vehicle_at_100_meters():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=100.0,
        y=0.0,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))

    assert manager.reserve_parked_vehicle(pedestrian, vehicle) is True


def test_reserved_pedestrian_walks_to_vehicle_and_enters():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        heading=0.0,
        width_m=1.8,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 2.0, 2.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians = [pedestrian]

    assert manager.reserve_parked_vehicle(pedestrian, vehicle)
    assert pedestrian.route is not None
    assert pedestrian.route[0] == (0.0, 0.0)
    assert pedestrian.route[-1] == manager._vehicle_entry_position(vehicle)
    for _ in range(15):
        manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.5)

    assert pedestrian.current_vehicle_id == id(vehicle)
    assert pedestrian.state == "in_vehicle"
    assert vehicle.state == "occupied"


def test_pedestrian_with_vehicle_goal_starts_nearby_vehicle_reservation():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        heading=0.0,
        width_m=1.8,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 2.0, 2.0, way, 0, 1, (1, 1, 1), wants_vehicle=True)
    manager.pedestrians = [pedestrian]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian.state == "approaching_vehicle"
    assert pedestrian.reserved_vehicle_id == id(vehicle)
    assert vehicle.state == "reserved"


def test_vehicle_approach_uses_connected_pedestrian_waypoints():
    first_way = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.5)
    second_way = Way(points_m=[(10.0, 0.0), (10.0, 10.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([first_way, second_way], target_count=0)
    vehicle = SimpleNamespace(x=10.0, y=10.0, heading=0.0, width_m=1.8)
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, first_way, 0, 1, (1, 1, 1))

    route = manager._footway_route_to(pedestrian, manager._vehicle_entry_position(vehicle))

    assert (10.0, 0.0) in route


def test_footway_route_to_does_not_snap_onto_a_way_reachable_only_through_the_building():
    """Regression: _footway_route_to's final-approach hop picked the
    raw-distance-nearest mapped footway point to the target regardless of
    whether the straight line from it to the target crossed the building
    the target belongs to - the same bug as spawn_pedestrian_at's
    nearest-way search, but for the "walking to a building entrance/
    vehicle door" approach leg every activity plugin and the multi-
    passenger trip-group flow shares."""
    front_street = Way(points_m=[(-10.0, -30.0), (30.0, -30.0)], highway="footway", half_width_m=1.5)
    back_alley = Way(points_m=[(-10.0, 21.0), (30.0, 21.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([front_street, back_alley], target_count=0)
    # Standing far off to the side, walking toward a building entrance at
    # (10, 0) - the building itself spans x:0-20, y:0-20 (not passed to
    # the manager; _footway_route_to only cares about the footway network
    # here, so the "is this point inside a building" check is exercised
    # via a monkeypatched _point_inside_building below instead of a real
    # Building object, keeping the test focused on the routing logic).
    pedestrian = Pedestrian(-50.0, -30.0, 0.0, 1.3, 1.3, front_street, 0, 1, (1, 1, 1))

    def fake_point_inside_building(x, y):
        return 0.0 <= x <= 20.0 and 0.0 <= y <= 20.0

    manager._point_inside_building = fake_point_inside_building

    route = manager._footway_route_to(pedestrian, (10.0, 0.0))

    assert (10.0, -30.0) in route  # routed via the reachable front street
    assert (10.0, 21.0) not in route  # not the closer-but-blocked back alley


def test_pedestrian_in_vehicle_follows_vehicle_position():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        state="occupied",
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(8.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    vehicle.current_driver_id = id(pedestrian)
    pedestrian.current_vehicle_id = id(vehicle)
    pedestrian.state = "in_vehicle"
    manager.pedestrians = [pedestrian]

    vehicle.x = 30.0
    vehicle.y = 4.0
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert (pedestrian.x, pedestrian.y) == (30.0, 4.0)


def test_pedestrian_exits_vehicle_at_vehicle_destination():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    road_way = Way(points_m=[(0.0, 0.0), (30.0, 0.0)], highway="residential", half_width_m=4.0)
    vehicle = SimpleNamespace(
        x=30.0,
        y=0.0,
        heading=0.0,
        width_m=1.8,
        state="occupied",
        current_driver_id=None,
        way=road_way,
        direction=1,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(30.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    pedestrian.vehicle_destination = (30.0, 0.0)
    pedestrian.state = "in_vehicle"
    vehicle.current_driver_id = id(pedestrian)
    manager.pedestrians = [pedestrian]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian.state == "walking"
    assert pedestrian.current_vehicle_id is None
    assert vehicle.state == "driving"


def test_pedestrian_in_vehicle_is_not_despawned_while_vehicle_is_active():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=200.0,
        y=0.0,
        state="occupied",
        current_driver_id=None,
    )
    manager = PedestrianManager(
        [way], target_count=0, despawn_radius_m=20.0, traffic_vehicles=[vehicle]
    )
    pedestrian = Pedestrian(200.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    pedestrian.state = "in_vehicle"
    vehicle.current_driver_id = id(pedestrian)
    manager.pedestrians = [pedestrian]
    manager._population_update_elapsed = 5.0

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert manager.pedestrians == [pedestrian]


def test_pedestrian_can_exit_occupied_vehicle():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=20.0,
        y=5.0,
        heading=0.0,
        width_m=1.8,
        state="occupied",
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(20.0, 5.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    vehicle.current_driver_id = id(pedestrian)
    pedestrian.state = "in_vehicle"

    assert manager.exit_vehicle(pedestrian, vehicle)
    assert pedestrian.state == "walking"
    assert pedestrian.current_vehicle_id is None
    assert (pedestrian.x, pedestrian.y) == (20.0, 6.9)
    assert vehicle.state == "driving"
    assert vehicle.current_driver_id is None


def test_pedestrian_can_spawn_at_and_leave_through_building_entrance():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        entrances=[(20.0, 0.0)],
        venue_type="school",
    )
    manager = PedestrianManager([way], target_count=0, venue_buildings=[building])

    pedestrian = manager.spawn_pedestrian_at_door(20.0, 0.0)
    assert pedestrian is not None
    assert (pedestrian.x, pedestrian.y) == (20.0, 0.0)
    manager.pedestrians.append(pedestrian)
    pedestrian.door_grace_timer = 0.0
    pedestrian.spawned_at_door = False
    manager._population_update_elapsed = 5.0

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian not in manager.pedestrians


def test_amenity_door_spawns_pedestrian_every_ten_evening_seconds(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        entrances=[(20.0, 0.0)],
        venue_type="school",
    )
    manager = PedestrianManager([way], target_count=1, venue_buildings=[building])
    monkeypatch.setattr(manager, "spawn_pedestrian", lambda *args, **kwargs: None)
    random_values = iter((1.0, 1.0, 0.0))
    monkeypatch.setattr(
        "theroadragetrip.pedestrian.random.random",
        lambda: next(random_values),
    )
    player = Car(x=10.0, y=0.0, heading=0.0, speed=0.0)
    manager._amenity_spawn_elapsed = 0.0
    manager._population_update_elapsed = 5.0

    manager.update(player, dt=5.0, game_time_seconds=18.0 * 3600.0)
    assert manager.pedestrians == []

    manager.update(player, dt=5.0, game_time_seconds=18.0 * 3600.0)
    assert len(manager.pedestrians) == 1
    assert manager.pedestrians[0].spawned_at_door is True
    assert manager.pedestrians[0].x > 20.0


def test_pedestrian_despawns_after_remaining_offscreen():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, despawn_radius_m=200.0)
    pedestrian = Pedestrian(80.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(pedestrian)
    viewport = (0.0, -10.0, 50.0, 10.0)

    for _ in range(10):
        manager._population_update_elapsed = 5.0
        manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1, viewport_bounds=viewport)

    assert pedestrian not in manager.pedestrians


def test_taxi_stop_gets_waiting_customer():
    way = Way(points_m=[(0.0, -3.0), (100.0, -3.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    player = Car(x=10.0, y=0.0, heading=0.0, speed=0.0)

    manager.ensure_taxi_stop_waiter([TaxiStop(20.0, 0.0)], player)

    assert len(manager.pedestrians) == 1
    assert manager.pedestrians[0].is_taxi_stop_waiter is True
    assert (manager.pedestrians[0].x, manager.pedestrians[0].y) == (20.0, -3.0)


def test_taxi_stop_waiter_spawns_when_stop_enters_view(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    player = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    stop = TaxiStop(20.0, 0.0, id=1)
    existing_pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(existing_pedestrian)

    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)

    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(-10.0, -10.0, 30.0, 10.0))
    assert not existing_pedestrian.is_walking_to_taxi_stop

    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(40.0, -10.0, 80.0, 10.0))
    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(-10.0, -10.0, 30.0, 10.0))

    assert len(manager.pedestrians) == 1
    assert existing_pedestrian.is_walking_to_taxi_stop is True

    for _ in range(500):
        manager.update(player, dt=0.1)
        if existing_pedestrian.is_taxi_stop_waiter:
            break
    assert existing_pedestrian.is_taxi_stop_waiter is True


def test_customer_walks_to_taxi_stop_edge(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, -3.0), (100.0, -3.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    customer = Pedestrian(10.0, -3.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(customer)
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    stop = TaxiStop(20.0, 0.0)
    player = Car(10.0, 0.0, 0.0, 0.0)
    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(40.0, -10.0, 60.0, 10.0))
    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(-10.0, -10.0, 30.0, 10.0))

    assert customer.is_walking_to_taxi_stop is True
    assert customer.taxi_stop_target == (20.0, -3.0)

    for _ in range(150):
        manager.update(Car(10.0, 0.0, 0.0, 0.0), dt=0.1)
        if customer.is_taxi_stop_waiter:
            break

    assert customer.is_taxi_stop_waiter is True
    assert (customer.x, customer.y) == (20.0, -3.0)


def test_pedestrian_spawning_and_movement():
    footway1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
        name="Walkway 1",
    )
    footway2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="path",
        half_width_m=1.5,
        name="Walkway 2",
    )
    ways = [footway1, footway2]

    ped_mgr = PedestrianManager(ways, target_count=5, spawn_radius_m=150.0, despawn_radius_m=250.0)
    player = Car(x=50.0, y=10.0, heading=0.0, speed=0.0)

    # Initial update spawns pedestrians
    ped_mgr.update(player, dt=0.1)
    assert len(ped_mgr.pedestrians) == 5

    for ped in ped_mgr.pedestrians:
        assert isinstance(ped, Pedestrian)
        assert 0.0 <= ped.x <= 200.0
        assert len(ped.color) == 3
        # A pedestrian can legitimately roll straight into a no-location
        # ambient activity (e.g. phone_usage) on its very first update and
        # stand still - only a pedestrian with no activity must be moving.
        if ped.activity is None:
            assert ped.speed > 0.0

    # Step simulation frames
    initial_positions = [(p.x, p.y) for p in ped_mgr.pedestrians]
    for _ in range(10):
        ped_mgr.update(player, dt=0.1)

    # At least some pedestrians moved
    moved = sum(
        1 for i, p in enumerate(ped_mgr.pedestrians)
        if (p.x, p.y) != initial_positions[i]
    )
    assert moved > 0


def test_pedestrians_spawn_near_hospitality_venues(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="footway", half_width_m=1.5)
    venue = SimpleNamespace(
        venue_type="restaurant",
        points_m=[(48.0, -4.0), (52.0, -4.0), (52.0, 4.0), (48.0, 4.0)],
    )
    manager = PedestrianManager([way], target_count=3, venue_buildings=[venue])
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    monkeypatch.setattr("theroadragetrip.pedestrian.random.choice", lambda values: values[0])

    manager.update(Car(x=50.0, y=0.0, heading=0.0, speed=0.0), dt=0.1)

    assert len(manager.venue_locations) == 1
    assert all(math.hypot(ped.x - 50.0, ped.y) <= 45.0 for ped in manager.pedestrians)


def test_pedestrian_spawn_area_is_limited_to_building_radius():
    way = Way(points_m=[(0.0, 0.0), (500.0, 0.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(bbox=(100.0, 100.0, 110.0, 110.0))
    manager = PedestrianManager([way], target_count=0, venue_buildings=[building])

    assert manager._point_near_building(0.0, 105.0)
    assert not manager._point_near_building(400.0, 0.0)


def test_drunk_pedestrian_walks_unevenly_and_may_vomit(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)
    drunk = Pedestrian(20.0, 0.0, 0.0, 1.3, 1.3, way, 0, 1, (230, 80, 80), is_drunk=True)
    drunk.drunk_vomit_cooldown = 0.0
    manager.pedestrians = [drunk]
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert drunk.y != 0.0
    assert manager.vomit_puddles == [(20.0, 0.0)]


def test_cyclist_spawn_assigns_body_color():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)

    cyclist = manager.spawn_pedestrian(50.0, 0.0)

    assert cyclist is not None
    assert cyclist.is_cyclist is True
    assert cyclist.color != (230, 80, 80)


def test_cyclist_spawn_uses_synced_ways_outside_local_grid():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=10.0)

    cyclist = manager.spawn_pedestrian(500.0, 500.0)

    assert cyclist is not None


def test_cyclists_use_right_edge_for_both_directions(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)

    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    forward = manager.spawn_pedestrian(50.0, 0.0)
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 1.0)
    reverse = manager.spawn_pedestrian(50.0, 0.0)

    assert forward is not None and reverse is not None
    assert forward.direction == 1
    assert reverse.direction == -1
    assert forward.lateral_offset_m == pytest.approx(3.0)
    assert reverse.lateral_offset_m == pytest.approx(3.0)


def test_all_cyclists_continue_moving():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)
    cyclists = [manager.spawn_pedestrian(50.0, 0.0) for _ in range(2)]
    manager.pedestrians = [cyclist for cyclist in cyclists if cyclist is not None]
    initial_positions = [(cyclist.x, cyclist.y) for cyclist in manager.pedestrians]

    manager.update(Car(x=-100.0, y=50.0, heading=0.0, speed=0.0), dt=0.1)

    assert all((cyclist.x, cyclist.y) != initial for cyclist, initial in zip(manager.pedestrians, initial_positions))


def test_spawn_pedestrian_at_creates_walking_passenger():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)

    passenger = manager.spawn_pedestrian_at(20.0, 1.0, heading=0.0)

    assert passenger is not None
    assert passenger.speed == passenger.base_speed == 1.3
    assert passenger.way is way


def test_pedestrian_speed_and_natural_distribution():
    footway = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="footway",
        half_width_m=2.0,
    )
    ped_mgr = PedestrianManager([footway], target_count=30, spawn_radius_m=300.0)
    player = Car(x=150.0, y=0.0, heading=0.0, speed=0.0)
    ped_mgr.update(player, dt=0.1)

    assert len(ped_mgr.pedestrians) == 30
    speeds = [p.base_speed for p in ped_mgr.pedestrians]
    # Check speed variety across profiles (from ~0.8m/s to ~3.0m/s)
    assert min(speeds) < 1.3
    assert max(speeds) > 1.3
    # Check natural lateral offset distribution across sidewalk width
    lat_offsets = [p.lateral_offset_m for p in ped_mgr.pedestrians]
    assert any(lat > 0.1 for lat in lat_offsets)
    assert any(lat < -0.1 for lat in lat_offsets)


def test_pedestrian_dodging_and_cursing_when_car_approaches():
    footway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )
    ped_mgr = PedestrianManager([footway], target_count=1)
    ped = Pedestrian(
        x=20.0,
        y=0.0,
        heading=0.0,
        speed=1.4,
        base_speed=1.4,
        way=footway,
        segment_idx=0,
        direction=1,
        color=(255, 0, 0),
    )
    ped_mgr.pedestrians = [ped]

    # Car moving directly towards pedestrian (at x=17.0, heading east towards x=20.0, long_dist=3.0m)
    player = Car(x=17.0, y=0.0, heading=0.0, speed=10.0)
    ped_mgr.check_player_avoidance(player, dt=0.05)

    assert ped.curse_timer > 0.0
    assert ped.curse_text in ["@#*!%", "#$@&!", "!%#&*", "%$!#@", "@!*#$"]
    assert ped.dodge_timer > 0.0
    assert (ped.dodge_vx != 0.0 or ped.dodge_vy != 0.0)


def test_pedestrian_does_not_dodge_when_car_drives_parallel_or_away():
    footway = Way(
        points_m=[(0.0, 5.0), (100.0, 5.0)],
        highway="footway",
        half_width_m=1.5,
    )
    ped_mgr = PedestrianManager([footway], target_count=1)
    ped = Pedestrian(
        x=20.0,
        y=5.0,
        heading=0.0,
        speed=1.4,
        base_speed=1.4,
        way=footway,
        segment_idx=0,
        direction=1,
        color=(255, 0, 0),
    )
    ped_mgr.pedestrians = [ped]

    # Car driving on road at y=0.0 (lateral offset 5.0m > 1.8m corridor)
    player = Car(x=18.0, y=0.0, heading=0.0, speed=10.0)
    ped_mgr.check_player_avoidance(player, dt=0.05)

    # Should not trigger dodge
    assert ped.curse_timer == 0.0
    assert ped.dodge_timer == 0.0


def test_pedestrian_does_not_dodge_until_car_is_close():
    footway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )
    ped_mgr = PedestrianManager([footway], target_count=1)
    ped = Pedestrian(20.0, 0.0, 0.0, 1.4, 1.4, footway, 0, 1, (255, 0, 0))
    ped_mgr.pedestrians = [ped]

    player = Car(x=16.0, y=0.0, heading=0.0, speed=10.0)
    ped_mgr.check_player_avoidance(player, dt=0.05)

    assert ped.curse_timer == 0.0
    assert ped.dodge_timer == 0.0


def test_cyclist_avoidance_is_reported_but_parallel_traffic_is_not():
    cycleway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="cycleway",
        half_width_m=1.5,
    )
    manager = CyclistManager([cycleway], target_count=0)
    cyclist = Pedestrian(20.0, 0.0, 0.0, 4.0, 4.0, cycleway, 0, 1, (50, 120, 220))
    cyclist.is_cyclist = True
    manager.pedestrians = [cyclist]

    assert manager.check_player_avoidance(Car(x=17.0, y=0.0, heading=0.0, speed=10.0), 0.05) is True
    assert manager.check_player_avoidance(Car(x=17.0, y=0.0, heading=0.0, speed=10.0), 0.05) is False

    cyclist.x = 20.0
    cyclist.y = 2.0
    cyclist.dodge_timer = 0.0
    assert manager.check_player_avoidance(Car(x=17.0, y=0.0, heading=0.0, speed=10.0), 0.05) is False


def test_pedestrian_traffic_light_crossing_stop():
    crossing = Way(
        points_m=[(0.0, 0.0), (20.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )
    tl = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=0.0)
    # At sim_time=0.0: state is 'green' for vehicular road -> pedestrian crossing is red (must stop)
    ped_mgr = PedestrianManager([crossing], target_count=1, traffic_lights=[tl])
    ped = Pedestrian(
        x=8.0,
        y=0.0,
        heading=0.0,
        speed=1.4,
        base_speed=1.4,
        way=crossing,
        segment_idx=0,
        direction=1,
        color=(255, 0, 0),
    )
    ped_mgr.pedestrians = [ped]
    player = Car(x=100.0, y=100.0, heading=0.0, speed=0.0)

    ped_mgr.update(player, dt=0.1)
    # Pedestrian stopped at red light
    assert ped.speed == 0.0


def _grid_of_ways(count: int) -> list:
    """`count` short, disconnected footway segments spread over a wide
    area - enough distinct ways in ped_ways to make an O(len(ped_ways))
    per-call cost show up, while still landing plenty of them within any
    given spawn_radius_m so spawn_pedestrian can actually succeed."""
    ways = []
    for i in range(count):
        x = float(i % 100) * 40.0
        y = float(i // 100) * 40.0
        ways.append(Way(points_m=[(x, y), (x + 20.0, y)], highway="footway", half_width_m=1.5))
    return ways


def test_sync_map_data_keeps_ped_way_ids_cache_in_sync():
    """Regression: spawn_pedestrian() reads self._ped_way_ids (see its
    docstring) instead of rebuilding {id(way) for way in self.ped_ways}
    itself - sync_map_data() (both PedestrianManager's and
    CyclistManager's, which overrides it) must keep that cache exactly
    in sync with ped_ways, on every call, not just the first."""
    way_a = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.5)
    way_b = Way(points_m=[(20.0, 0.0), (30.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way_a], target_count=0)
    assert manager._ped_way_ids == {id(w) for w in manager.ped_ways}

    manager.sync_map_data([way_a, way_b])
    assert manager._ped_way_ids == {id(w) for w in manager.ped_ways}
    assert manager._ped_way_ids  # non-empty: actually exercised, not just equal-by-emptiness

    cyclists = CyclistManager([way_a], target_count=0)
    assert cyclists._ped_way_ids == {id(w) for w in cyclists.ped_ways}
    cyclists.sync_map_data([way_a, way_b])
    assert cyclists._ped_way_ids == {id(w) for w in cyclists.ped_ways}


def test_spawn_pedestrian_does_not_rescan_ped_ways_per_attempt():
    """Regression: spawn_pedestrian() used to rebuild
    {id(way) for way in self.ped_ways} from scratch on *every single
    call* - every spawn attempt, not just successful ones, and update()
    can make up to max(50, target_count * 5) attempts per 5-second
    population pass (most of them failing, e.g. at low zoom where the
    whole spawn_radius_m search area already sits inside the viewport -
    see the other regression test below). Against a real city-scale
    ped_ways (tens of thousands of ways after autofetch grows the map)
    this one line dominated the whole pass: ~900ms in a single frame,
    confirmed via profiling against real Oulu OSM data (30949 ways).

    Reproduces that shape directly: a large ped_ways and many calls that
    all fail to place anyone (max_distance_m=0.001 - effectively zero -
    rejects every candidate point, the same "burn the whole retry budget
    with nothing to show for it" shape a real doomed-to-fail attempt has),
    asserting on wall time. A successful placement's own cost would
    otherwise dwarf and hide the one line this covers, so this isolates
    it: fixed, 300 calls against 15000 ped_ways measured ~0.21s;
    unfixed (rebuilding the id() set from scratch each call) measured
    ~0.58s. The threshold is set well clear of both."""
    import time

    ways = _grid_of_ways(15000)
    manager = PedestrianManager(ways, target_count=0)
    assert len(manager.ped_ways) >= 12000

    start = time.perf_counter()
    for _ in range(300):
        result = manager.spawn_pedestrian(20.0, 0.0, max_distance_m=0.001)
        assert result is None  # every candidate point must fail the distance check
    elapsed = time.perf_counter() - start
    assert elapsed < 0.35, (
        f"300 always-failing spawn_pedestrian calls against {len(manager.ped_ways)} "
        f"ped_ways took {elapsed:.2f}s - looks like the per-call ped-way-id-set rebuild regressed"
    )


def test_spawn_pedestrian_gives_up_immediately_when_search_area_is_fully_onscreen(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: at low zoom, the viewport can be wider than
    2 * spawn_radius_m - every candidate point spawn_pedestrian's retry
    loop could generate near `near_x, near_y` is then guaranteed to land
    inside the viewport (and get rejected), yet the old code still ran
    the full retry budget (up to 30 candidate ways x every segment x 8
    points) on every one of the up to max(50, target_count * 5) attempts
    update() makes - confirmed via profiling: ~900ms in a single frame
    against real OSM data (340800 wasted random.uniform() calls alone).
    Must recognize a fully-onscreen search area and return None
    immediately instead of exhausting the retry budget on attempts that
    can never succeed.

    Verified by call count rather than wall time - real Oulu ways carry
    many points each, so the retry loop's cost scales with segments per
    way; this repo's small synthetic ways don't reproduce that volume,
    which makes a timing threshold here either too loose to catch a
    regression or too tight to be reliable. random.shuffle() is called
    exactly once per candidate way inside that retry loop (to randomize
    which segment is tried first) - zero calls is a direct, robust
    signal that the loop never started."""
    ways = _grid_of_ways(6000)
    manager = PedestrianManager(ways, target_count=0)
    near_x, near_y = 20.0, 0.0
    r = manager.spawn_radius_m
    huge_viewport = (near_x - r - 50.0, near_y - r - 50.0, near_x + r + 50.0, near_y + r + 50.0)

    shuffle_calls = []
    real_shuffle = __import__("random").shuffle
    monkeypatch.setattr(
        "theroadragetrip.pedestrian.random.shuffle",
        lambda seq: (shuffle_calls.append(len(seq)), real_shuffle(seq))[-1],
    )

    result = manager.spawn_pedestrian(near_x, near_y, viewport_bounds=huge_viewport)
    assert result is None  # every candidate would be onscreen - never a valid spot
    assert shuffle_calls == [], (
        f"spawn_pedestrian shuffled candidates {len(shuffle_calls)} time(s) despite a "
        f"fully-onscreen search area - looks like the early-exit shortcut regressed"
    )

    # Sanity: a normal, screen-sized viewport (smaller than the search
    # area) must still let a real spawn succeed - the shortcut above must
    # not be so broad it breaks ordinary spawning.
    tight_viewport = (near_x - 10.0, near_y - 10.0, near_x + 10.0, near_y + 10.0)
    assert manager.spawn_pedestrian(near_x, near_y, viewport_bounds=tight_viewport) is not None


def test_spawn_pedestrian_at_does_not_scan_every_ped_way():
    """Regression: spawn_pedestrian_at() (used for every door/amenity
    spawn - see spawn_pedestrian_at_door) scanned the *entire* self.ped_ways
    list, every segment, to find the single nearest one to one point -
    unlike spawn_pedestrian() (the other spawn path), which was already
    scoped to self._way_grid. Confirmed via profiling a real drive (real
    Oulu cache data, autofetch on): one call to spawn_pedestrian_at() cost
    ~20000 closest_point_and_dist_to_segment calls, dominating the periodic
    population-update pass whenever a door spawn was attempted. Must use
    _nearby_ped_ways() (the same grid spawn_pedestrian() already relies on)
    instead of the full list.

    300 calls against 15000 ped_ways: fixed measures well under a second;
    unfixed (O(len(ped_ways)) per call) takes several seconds - the
    threshold is set well clear of both."""
    import time

    ways = _grid_of_ways(15000)
    manager = PedestrianManager(ways, target_count=0)
    assert len(manager.ped_ways) >= 12000

    start = time.perf_counter()
    for _ in range(300):
        result = manager.spawn_pedestrian_at(20.0, 0.0)
        assert result is not None
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, (
        f"300 spawn_pedestrian_at calls against {len(manager.ped_ways)} ped_ways "
        f"took {elapsed:.2f}s - looks like the full-ped_ways scan regressed"
    )


def test_nearby_ped_ways_falls_back_to_every_way_when_grid_is_empty():
    """_nearby_ped_ways()'s expanding-radius search must still find
    something (spawn_pedestrian_at's whole-map fallback, restored) when a
    point sits farther from every ped_way than the grid search ever
    expands to - correctness over the common-case speed path."""
    ways = [Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.5)]
    manager = PedestrianManager(ways, target_count=0, spawn_radius_m=50.0)
    far_away = manager._nearby_ped_ways(1_000_000.0, 1_000_000.0)
    assert far_away == manager._spawn_ways


def _dense_buildings(count: int) -> list:
    """`count` small building footprints packed into one 500x500m area -
    enough distinct buildings landing in the same _point_near_building
    cell window to make an uncached per-call rescan show up."""
    buildings = []
    per_row = 50
    for i in range(count):
        x = (i % per_row) * 10.0
        y = (i // per_row) * 10.0
        buildings.append(Building(
            points_m=[(x, y), (x + 6.0, y), (x + 6.0, y + 6.0), (x, y + 6.0)],
            bbox=(x, y, x + 6.0, y + 6.0),
        ))
    return buildings


def test_point_near_building_caches_the_per_window_building_list():
    """Regression: spawn_pedestrian()'s retry loop calls _point_near_building
    for every candidate point tried along a segment (up to 8 per segment,
    for up to 30 candidate ways per spawn attempt) - nearby points along
    the same short segment overwhelmingly land in the same cell window,
    but the old code re-scanned and re-deduplicated (via id() + a set)
    every mapped building in that window from scratch on every single
    call. Confirmed via profiling a real drive: ~1M id() calls across 2100
    calls to this method in one slow population-update pass.

    300 calls at slightly different points, all within the same 100m
    building-grid cell window, against 2000 densely packed buildings:
    fixed (cached per-window) measures well under the unfixed cost."""
    import time

    ways = [Way(points_m=[(0.0, 0.0), (500.0, 0.0)], highway="footway", half_width_m=1.5)]
    manager = PedestrianManager(ways, target_count=0, venue_buildings=_dense_buildings(2000))
    assert manager._building_grid

    start = time.perf_counter()
    for i in range(300):
        manager._point_near_building(10.0 + i * 0.01, 10.0 + i * 0.01)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, (
        f"300 _point_near_building calls in the same window took {elapsed:.2f}s - "
        f"looks like the per-call window cache regressed"
    )
    assert len(manager._near_building_window_cache) == 1, (
        "all 300 calls landed in the same cell window - expected exactly one cached entry"
    )


def test_point_near_building_window_cache_is_cleared_when_buildings_change():
    """set_venue_buildings() (called whenever the buildings list itself
    changes, e.g. autofetch loading a new tile) must clear the per-window
    cache - otherwise a window could keep returning a building list from
    before new buildings were added to (or removed from) that same area."""
    ways = [Way(points_m=[(0.0, 0.0), (500.0, 0.0)], highway="footway", half_width_m=1.5)]
    manager = PedestrianManager(ways, target_count=0, venue_buildings=_dense_buildings(50))
    manager._point_near_building(10.0, 10.0)
    assert manager._near_building_window_cache

    manager.set_venue_buildings(_dense_buildings(50))
    assert manager._near_building_window_cache == {}


def _park_a_trip_group_vehicle(capacity_monkeypatch=None):
    """Drive a real spawn_npc'd vehicle to NPCState.PARKED - shared setup
    for the multi-passenger-car.md tests below, so each test exercises the
    real npc.py/pedestrian.py integration rather than a hand-built mock."""
    ways = [
        Way(points_m=[(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], highway="residential", half_width_m=4.5)
        for i in range(10)
    ]
    building = Building(
        points_m=[(190.0, 10.0), (210.0, 10.0), (210.0, 30.0), (190.0, 30.0)],
        bbox=(190.0, 10.0, 210.0, 30.0),
        entrances=[(195.0, 10.0)],
    )
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    spawned = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (180.0, 0.0))
    assert spawned is not None
    _, driver, vehicle = spawned
    for _ in range(3000):
        update_npc(vehicle, driver, 1.0 / 30.0, tw, residents)
        tw.advance_time(1.0 / 30.0)
        if vehicle.state == NPCState.PARKED:
            break
    assert vehicle.state == NPCState.PARKED
    return ways, building, tw, residents, driver, vehicle


def test_materialize_parked_drivers_spawns_one_pedestrian_per_trip_group_member():
    ways, building, tw, residents, driver, vehicle = _park_a_trip_group_vehicle()
    tw.npcs = [vehicle]
    manager = PedestrianManager(ways, target_count=0, traffic_manager=tw, residents=residents, venue_buildings=[building])

    manager.update(Car(x=5000.0, y=5000.0, heading=0.0, speed=0.0), dt=1.0 / 30.0)

    member_ids = set(vehicle.trip_group.member_resident_ids)
    spawned_ids = {ped.resident_id for ped in manager.pedestrians}
    assert spawned_ids == member_ids
    assert vehicle.trip_group.boarded_resident_ids == set()
    for ped in manager.pedestrians:
        assert ped.linked_vehicle_id == id(vehicle)
        assert ped.state == "walking_to_building"


def test_materialize_parked_drivers_shares_one_building_entrance_across_the_group():
    ways, building, tw, residents, driver, vehicle = _park_a_trip_group_vehicle()
    tw.npcs = [vehicle]
    manager = PedestrianManager(ways, target_count=0, traffic_manager=tw, residents=residents, venue_buildings=[building])

    # Check spawn positions directly, before any walking - once en route,
    # members legitimately funnel through the same shared footway nodes.
    manager._materialize_parked_drivers()

    entrances = {ped.linked_building_entrance for ped in manager.pedestrians}
    assert len(entrances) == 1
    assert vehicle.trip_group.destination_entrance in entrances
    # A group of >1 spawns at distinct positions - not stacked on one point.
    if len(manager.pedestrians) > 1:
        positions = {(round(p.x, 3), round(p.y, 3)) for p in manager.pedestrians}
        assert len(positions) == len(manager.pedestrians)


def test_walking_to_building_follows_the_footway_network_not_a_straight_line():
    """Regression: trip-group members used to walk in a straight line from
    the car to the building entrance, cutting through the car and the
    building itself ("people get out of car and walk thru the car/
    building"). The walk must be built through the sidewalk network's
    shared nodes instead of a direct 2-point hop."""
    ways, building, tw, residents, driver, vehicle = _park_a_trip_group_vehicle()
    tw.npcs = [vehicle]
    manager = PedestrianManager(ways, target_count=0, traffic_manager=tw, residents=residents, venue_buildings=[building])
    manager._materialize_parked_drivers()

    pedestrian = manager.pedestrians[0]
    entrance = pedestrian.linked_building_entrance
    manager._update_linked_driver(pedestrian, 1.0 / 30.0)

    assert pedestrian.route is not None
    assert len(pedestrian.route) > 2
    assert entrance in pedestrian.route


def test_full_trip_group_lifecycle_reboards_and_frees_the_vehicle():
    """The complete section 7-21 loop: disembark, walk to the shared
    building, wait, walk back, reboard as a group, all_aboard becomes
    true again - using the real npc.py/pedestrian.py wiring, not mocks.

    Drives _materialize_parked_drivers/_update_linked_driver directly
    (not through PedestrianManager.update()'s full population-management
    pass) - that pass's LOD throttling and offscreen/at-door despawn
    rules are pre-existing, general-purpose pedestrian bookkeeping
    unrelated to this feature, and calibrated around a real game's
    frame rate/city scale, not a synthetic 10-way test map. This still
    exercises the exact same trip-group code this feature adds - just
    without also depending on those unrelated systems behaving a
    particular way on a tiny fixture.
    """
    ways, building, tw, residents, driver, vehicle = _park_a_trip_group_vehicle()
    tw.npcs = [vehicle]
    manager = PedestrianManager(ways, target_count=0, traffic_manager=tw, residents=residents, venue_buildings=[building])
    member_ids = set(vehicle.trip_group.member_resident_ids)

    manager._materialize_parked_drivers()
    assert {ped.resident_id for ped in manager.pedestrians} == member_ids
    assert not vehicle.trip_group.all_aboard

    for _ in range(100_000):
        for ped in manager.pedestrians:
            manager._update_linked_driver(ped, 0.2)
        update_npc(vehicle, driver, 0.2, tw, residents)
        tw.advance_time(0.2)
        if vehicle.trip_group.all_aboard:
            break

    assert vehicle.trip_group.all_aboard
    assert set(vehicle.trip_group.member_resident_ids) == member_ids  # nobody stranded
    # Every member ended up DESPAWNING (about to be removed), never stuck
    # mid-walk or still "in" the building.
    for ped in manager.pedestrians:
        if ped.resident_id in member_ids:
            assert ped.state == PedestrianState.DESPAWNING.value


def test_find_available_parked_vehicle_ignores_trip_group_vehicles():
    """multi-passenger-car.md section 16: the generic 'grab any nearby
    idle vehicle' mechanic must never claim a vehicle that belongs to a
    trip group, even though its state string technically matches."""
    ways, building, tw, residents, driver, vehicle = _park_a_trip_group_vehicle()
    vehicle.state = "parked"  # what the generic mechanic actually checks for
    manager = PedestrianManager(ways, target_count=0, traffic_manager=None, residents=residents, traffic_vehicles=[vehicle])

    found = manager.find_available_parked_vehicle(vehicle.x, vehicle.y, radius_m=50.0)
    assert found is None

    vehicle.trip_group = None
    found = manager.find_available_parked_vehicle(vehicle.x, vehicle.y, radius_m=50.0)
    assert found is vehicle


def test_two_trip_group_vehicles_materialize_independently():
    """multi-passenger-car.md Test 10: two parked trip-group vehicles at
    once must not mix up which pedestrians belong to which vehicle."""
    ways, building, tw, residents, driver_a, vehicle_a = _park_a_trip_group_vehicle()
    spawned_b = spawn_npc(2, residents, tw, ways, (20.0, 0.0), (160.0, 0.0))
    assert spawned_b is not None
    _, driver_b, vehicle_b = spawned_b
    for _ in range(3000):
        update_npc(vehicle_b, driver_b, 1.0 / 30.0, tw, residents)
        tw.advance_time(1.0 / 30.0)
        if vehicle_b.state == NPCState.PARKED:
            break
    assert vehicle_b.state == NPCState.PARKED

    tw.npcs = [vehicle_a, vehicle_b]
    manager = PedestrianManager(ways, target_count=0, traffic_manager=tw, residents=residents, venue_buildings=[building])
    manager.update(Car(x=5000.0, y=5000.0, heading=0.0, speed=0.0), dt=1.0 / 30.0)

    members_a = set(vehicle_a.trip_group.member_resident_ids)
    members_b = set(vehicle_b.trip_group.member_resident_ids)
    assert members_a.isdisjoint(members_b)
    for ped in manager.pedestrians:
        if ped.resident_id in members_a:
            assert ped.linked_vehicle_id == id(vehicle_a)
        elif ped.resident_id in members_b:
            assert ped.linked_vehicle_id == id(vehicle_b)


def test_trip_group_pedestrians_survive_population_culling_far_from_player():
    """Regression: a trip-group member walking to/from the building used
    to be culled by the ordinary distance-based population sweep the
    instant the player was more than despawn_radius_m away (their state
    - "walking_to_building"/IN_BUILDING/"returning_to_vehicle" - wasn't
    in the sweep's protected state set, only current_vehicle_id-based
    states were). _materialize_parked_drivers runs every frame, so the
    despawned member was immediately re-spawned right back at the car
    next frame - "walks a bit, thrown back to the car, walks again"
    forever, and exactly the "passenger spawned twice" case section 6
    says must never happen."""
    ways, building, tw, residents, driver, vehicle = _park_a_trip_group_vehicle()
    tw.npcs = [vehicle]
    manager = PedestrianManager(ways, target_count=0, traffic_manager=tw, residents=residents, venue_buildings=[building])
    member_count = len(vehicle.trip_group.member_resident_ids)

    far_away_player = Car(x=5000.0, y=5000.0, heading=0.0, speed=0.0)
    counts = []
    for _ in range(60):
        manager.update(far_away_player, dt=0.2)
        counts.append(len(manager.pedestrians))

    assert all(count == member_count for count in counts[3:]), (
        f"pedestrian count fluctuated away from {member_count}: {counts}"
    )


def test_fanned_out_spawn_positions_never_land_inside_the_vehicle():
    """Regression: fanning members out in a full circle around the
    already-cleared entry point pushed roughly half of them back across
    that clearance and into the vehicle's own footprint (reported:
    "people get out of car and walk thru the car"). Spread must stay
    beside the car regardless of its heading/length."""
    from theroadragetrip.pedestrian import _fanned_out_position

    vehicle_width_m = 1.8
    clearance = vehicle_width_m * 0.5 + 1.0  # _vehicle_entry_position's own offset formula
    for heading in (0.0, math.pi / 2.0, math.pi / 4.0, 2.3):
        # _vehicle_entry_position's exact perpendicular-offset formula,
        # vehicle at the world origin.
        entry_x = -math.sin(heading) * clearance
        entry_y = math.cos(heading) * clearance
        for total in (1, 2, 5):
            for index in range(total):
                x, y = _fanned_out_position(entry_x, entry_y, index, total, heading=heading)
                # Rotate the point into the vehicle's own frame (undo its
                # heading) - the lateral (local y) coordinate must clear
                # the car's half-width no matter how far along its length
                # (local x) a member is spread.
                local_y = -x * math.sin(heading) + y * math.cos(heading)
                assert abs(local_y) >= vehicle_width_m * 0.5, (
                    f"heading={heading} total={total} index={index} landed inside the car's width"
                )


def _v9_world(dedicated=True):
    from theroadragetrip.osm import SceneryObject
    from theroadragetrip.pedestrian import VENUE_TYPES

    highway = "footway" if dedicated else "residential"
    ways = [Way(points_m=[(float(x), -40.0), (float(x), 0.0), (float(x), 40.0)], highway=highway,
                half_width_m=1.5, bbox=(float(x), -40.0, float(x), 40.0)) for x in range(0, 200, 20)]
    ways.append(Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway=highway, half_width_m=1.5,
                    bbox=(0.0, 0.0, 200.0, 0.0)))
    ways.append(Way(points_m=[(0.0, 10.0), (50.0, 10.0)], highway="primary", half_width_m=4.0,
                    bbox=(0.0, 10.0, 50.0, 10.0)))
    buildings = [SimpleNamespace(points_m=[(x, 3.0), (x + 12.0, 3.0), (x + 12.0, 15.0), (x, 15.0)],
                                 bbox=(x, 3.0, x + 12.0, 15.0), entrances=[(x + 6.0, 3.0)],
                                 venue_type=next(iter(VENUE_TYPES)) if x < 60 else None)
                 for x in (15.0, 55.0, 95.0, 135.0)]
    features = ([SceneryObject(x=float(x), y=5.0, kind="bench") for x in range(5, 200, 30)],
                [SimpleNamespace(bbox=(10.0, 20.0, 90.0, 60.0))], [])
    return ways, buildings, features


def _v9_state(manager):
    def way_key(w):
        return tuple(w.points_m)
    return {
        "ped_ways": [way_key(w) for w in manager.ped_ways],
        "spawn_ways": [way_key(w) for w in manager._spawn_ways],
        "way_grid": {k: [way_key(w) for w in v] for k, v in manager._way_grid.items()},
        "junction_grid": {k: [(way_key(e[0]),) + e[1:] for e in v] for k, v in manager._junction_grid.items()},
        "nodes": manager.network.nodes, "edges": manager.network.edges,
        "route_nodes": manager._route_nodes, "route_edges": manager._route_edges,
        "building_grid": {k: [id(b) for b in v] for k, v in manager._building_grid.items()},
        "venues": manager.venue_locations, "entrances": manager.entrance_locations,
        "amenity_entrances": manager.amenity_entrance_locations, "entrance_grid": manager._entrance_grid,
        "scenery_object_grid": {k: [id(o) for o in v] for k, v in manager._scenery_object_grid.items()},
        "scenery_grid": {k: [id(o) for o in v] for k, v in manager._scenery_grid.items()},
    }


@pytest.mark.parametrize("dedicated", [True, False])
def test_v9_budgeted_sync_matches_full_sync_and_snapshots_inputs(dedicated):
    ways, buildings, features = _v9_world(dedicated)

    full = PedestrianManager([], target_count=0)
    full.set_venue_buildings(buildings, resync=False)
    full.set_scenery_features(*features)
    full.sync_map_data(ways)
    expected = _v9_state(full)
    assert expected["ped_ways"] and expected["junction_grid"] and expected["venues"]

    manager = PedestrianManager([], target_count=0)
    old = _v9_state(manager)
    raw_ways, raw_buildings = list(ways), list(buildings)
    manager.start_incremental_sync(raw_ways, venue_buildings=raw_buildings, scenery_features=features)
    # Raw list growth after the snapshot never leaks into this job.
    raw_ways.append(Way(points_m=[(500.0, 0.0), (520.0, 0.0)], highway="footway", half_width_m=1.5))
    raw_buildings.clear()
    frames = 0
    while not manager.advance_incremental_sync(0.0):
        frames += 1
        assert frames < 10_000
        if manager._sync_stage in ("venue", "building_free", "junction_grid", "spawn_grid"):
            # The old walkable result stays live until the atomic commit.
            assert [tuple(w.points_m) for w in manager.ped_ways] == old["ped_ways"]
    assert frames > 10, "zero budget must spread the job over many frames"
    assert _v9_state(manager) == expected
    assert manager.sync_stats["jobs"] == manager.sync_stats["completed"] == 1

    # Unchanged inputs a second time: identical, no duplicates.
    manager.start_incremental_sync(ways, venue_buildings=buildings, scenery_features=features)
    while not manager.advance_incremental_sync(0.0):
        pass
    assert _v9_state(manager) == expected


def test_v9_budgeted_sync_handles_an_empty_world():
    manager = PedestrianManager([], target_count=0)
    manager.start_incremental_sync([], venue_buildings=[], scenery_features=([], [], []))
    while not manager.advance_incremental_sync(0.0):
        pass
    assert manager.ped_ways == [] and manager._way_grid == {} and manager._building_grid == {}


def test_v9_indexed_network_lookups_match_brute_force():
    """nearest_point()/route() endpoint lookups use grids now; answers
    (including ties, rejects and far-away queries) match the old scans."""
    import heapq
    import random
    from theroadragetrip.geo import closest_point_and_dist_to_segment

    def brute_nearest(network, point, reject=None):
        best, best_distance = None, float("inf")
        for way in network.ways:
            for first, second in zip(way.points_m, way.points_m[1:]):
                x, y, _, distance = closest_point_and_dist_to_segment(point[0], point[1], *first, *second)
                if distance < best_distance and not (reject and reject(x, y)):
                    best, best_distance = (x, y), distance
        return best

    def brute_route(network, start, target):
        nodes, edges = network.nodes, network.edges
        start_id = min(edges, key=lambda i: (nodes[i][0] - start[0]) ** 2 + (nodes[i][1] - start[1]) ** 2)
        target_id = min(edges, key=lambda i: (nodes[i][0] - target[0]) ** 2 + (nodes[i][1] - target[1]) ** 2)
        distances, previous, queue = {start_id: 0.0}, {}, [(0.0, start_id)]
        while queue:
            distance, current = heapq.heappop(queue)
            if distance != distances.get(current):
                continue
            if current == target_id:
                break
            for neighbor, edge_distance in edges[current]:
                if distance + edge_distance < distances.get(neighbor, math.inf):
                    distances[neighbor], previous[neighbor] = distance + edge_distance, current
                    heapq.heappush(queue, (distance + edge_distance, neighbor))
        if target_id not in distances:
            return [start, target]
        path = [target_id]
        while path[-1] != start_id:
            path.append(previous[path[-1]])
        return [start] + [nodes[i] for i in reversed(path)] + [target]

    rnd = random.Random(9)
    ways = [Way(points_m=[(round(rnd.uniform(-400, 400) / 10) * 10.0, round(rnd.uniform(-400, 400) / 10) * 10.0)
                          for _ in range(rnd.randint(2, 4))], highway="footway", half_width_m=1.5)
            for _ in range(120)]
    incremental = PedestrianNetwork()
    incremental.start_rebuild(ways)
    while not incremental.advance_rebuild(0.0):
        pass
    for network in (PedestrianNetwork(ways), incremental):
        for _ in range(150):
            point = (rnd.uniform(-2000, 2000), rnd.uniform(-2000, 2000))
            assert network.nearest_point(point) == brute_nearest(network, point)
            reject = lambda x, y: x < point[0]  # noqa: E731 - rejects roughly half the candidates
            assert network.nearest_point(point, reject) == brute_nearest(network, point, reject)
            target = (rnd.uniform(-500, 500), rnd.uniform(-500, 500))
            assert network.route(point, target) == brute_route(network, point, target)
        # Exact ties on shared nodes resolve to the first scanned segment/node.
        for way in ways[:20]:
            assert network.nearest_point(way.points_m[0]) == brute_nearest(network, way.points_m[0])
    assert PedestrianNetwork().nearest_point((0.0, 0.0)) is None
    assert PedestrianNetwork([ways[0]]).nearest_point((0.0, 0.0), lambda x, y: True) is None


def test_v11_route_rejects_other_component_without_searching():
    """bin-loader-v11: A-B-C routes; a separate C-D island is rejected
    before Dijkstra expands anything (same straight fallback as before)."""
    abc = [Way(points_m=[(0.0, 0.0), (50.0, 0.0)], highway="footway", half_width_m=1.0),
           Way(points_m=[(50.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.0)]
    island = [Way(points_m=[(0.0, 500.0), (50.0, 500.0)], highway="footway", half_width_m=1.0)]
    network = PedestrianNetwork(abc + island)

    route = network.route((0.0, 0.0), (100.0, 0.0))
    assert route[1:-1] == [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
    assert network.last_route_expanded > 0

    assert network.route((0.0, 0.0), (50.0, 500.0)) == [(0.0, 0.0), (50.0, 500.0)]
    assert network.last_route_expanded == 0


def test_v11_components_match_brute_force_and_follow_graph_rebuilds():
    import random
    from theroadragetrip.pedestrian import _component_root

    rnd = random.Random(11)
    ways = [Way(points_m=[(round(rnd.uniform(0, 600) / 20) * 20.0, round(rnd.uniform(0, 600) / 20) * 20.0)
                          for _ in range(rnd.randint(2, 3))], highway="footway", half_width_m=1.0)
            for _ in range(80)]

    def brute_components(network):
        seen, label = {}, 0
        for node in range(len(network.nodes)):
            if node in seen:
                continue
            stack = [node]
            seen[node] = label
            while stack:
                for neighbor, _ in network.edges[stack.pop()]:
                    if neighbor not in seen:
                        seen[neighbor] = label
                        stack.append(neighbor)
            label += 1
        return seen

    def same(network, a, b):
        return _component_root(network._component_parent, a) == _component_root(network._component_parent, b)

    incremental = PedestrianNetwork()
    incremental.start_rebuild(ways[:40])
    while not incremental.advance_rebuild(0.0):
        pass
    for network in (PedestrianNetwork(ways[:40]), incremental):
        labels = brute_components(network)
        for a in range(len(network.nodes)):
            for b in range(0, len(network.nodes), 7):
                assert same(network, a, b) == (labels[a] == labels[b])

    # Generation N+1: joining two former islands. Until the rebuild commits,
    # the live graph (nodes, edges and components together) is still N.
    old_nodes, old_parent = incremental.nodes, incremental._component_parent
    incremental.start_rebuild(ways)
    assert incremental.nodes is old_nodes and incremental._component_parent is old_parent
    while not incremental.advance_rebuild(0.0):
        pass
    assert incremental._component_parent is not old_parent
    labels = brute_components(incremental)
    for a in range(len(incremental.nodes)):
        for b in range(0, len(incremental.nodes), 5):
            assert same(incremental, a, b) == (labels[a] == labels[b])
    # Ways dropped by a later sync (e.g. an unloaded tile) leave no stale
    # nodes or component entries behind: the next build starts from scratch.
    incremental.set_ways(ways[:10])
    assert len(incremental._component_parent) == len(incremental.nodes)


def test_only_a_phone_user_draws_a_phone_next_to_the_head():
    import pygame
    from types import SimpleNamespace

    pygame.init()
    ground = Way(points_m=[(-50.0, 0.0), (50.0, 0.0)], highway="footway", half_width_m=5.0)

    def draw(activity):
        pedestrian = Pedestrian(0.0, 0.0, 0.0, 0.0, 1.0, ground, 0, 1, (200, 50, 50))
        pedestrian.mood = "annoyed"
        pedestrian.activity = activity
        screen = pygame.Surface((400, 400))
        draw_pedestrians(screen, [pedestrian], camx=0.0, camy=0.0, px_per_m=8.0, ways=[ground], screen_w=400, screen_h=400)
        return screen

    passenger = draw(None)
    caller = draw(SimpleNamespace(plugin_id="phone_usage", data={}))
    lit = [
        (x, y) for x in range(400) for y in range(400)
        if caller.get_at((x, y))[:3] == (120, 200, 255)
    ]
    assert lit and not any(passenger.get_at(p)[:3] == (120, 200, 255) for p in lit)
    # Held at the head (screen centre 200,200), not floating off to one side.
    assert all(abs(x - 200) <= 8 and abs(y - 200) <= 8 for x, y in lit)


def test_residents_wanting_a_taxi_raise_a_yellow_hand():
    import pygame
    from theroadragetrip.render.pedestrians import TAXI_HAIL_COLOR

    pygame.init()
    ground = Way(points_m=[(-50.0, 0.0), (50.0, 0.0)], highway="footway", half_width_m=5.0)

    def yellow_pixels(**flags):
        pedestrian = Pedestrian(0.0, 0.0, 0.0, 0.0, 1.0, ground, 0, 1, (200, 50, 50))
        for name, value in flags.items():
            setattr(pedestrian, name, value)
        screen = pygame.Surface((200, 200))
        draw_pedestrians(screen, [pedestrian], camx=0.0, camy=0.0, px_per_m=8.0, ways=[ground], screen_w=200, screen_h=200)
        return [(x, y) for x in range(200) for y in range(200) if screen.get_at((x, y))[:3] == TAXI_HAIL_COLOR]

    assert yellow_pixels() == []
    for flag in ("wants_taxi", "is_walking_to_taxi_stop", "is_taxi_stop_waiter"):
        hand = yellow_pixels(**{flag: True})
        assert hand and all(abs(x - 100) <= 20 and abs(y - 100) <= 20 for x, y in hand), flag  # at the body
