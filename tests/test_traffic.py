"""Tests for autonomous NPC traffic manager."""
import math
import random
from types import SimpleNamespace
from theroadragetrip.osm import Building, ParkingSpace, Scenery, StopSign, Way
from theroadragetrip.osm import TrafficLight
from theroadragetrip.physics import Car
from theroadragetrip.traffic import (
    IntersectionManager,
    NPCCar,
    TrafficManager,
    calculate_npc_turning_geometry,
    compute_turn_lane_offset,
    traffic_count_for_zoom,
)
from theroadragetrip.osm import IntersectionApproach, LogicalIntersection
from theroadragetrip.geo import boxes_intersect


def test_npc_turning_geometry_is_individual_and_bicycle_based():
    short_car = calculate_npc_turning_geometry(3.5, "car")
    long_car = calculate_npc_turning_geometry(5.0, "car")
    motorcycle = calculate_npc_turning_geometry(2.2, "motorcycle")

    assert short_car[0] < long_car[0]
    assert motorcycle[1] > short_car[1]


def test_turn_lane_offset_uses_left_and_right_edges():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=6.0)

    assert compute_turn_lane_offset(way, "left") == -5.0
    assert compute_turn_lane_offset(way, "right") == 5.0


def test_traffic_manager_nearby_parking_spaces_uses_osm_spaces():
    near_space = ParkingSpace([(0.0, 0.0), (2.0, 0.0), (2.0, 4.0), (0.0, 4.0)], (0.0, 0.0, 2.0, 4.0), osm_id=101)
    far_space = ParkingSpace([(500.0, 0.0), (502.0, 0.0), (502.0, 4.0), (500.0, 4.0)], (500.0, 0.0, 502.0, 4.0), osm_id=102)
    manager = TrafficManager([], target_count=0, parking_spaces=[near_space, far_space])

    assert manager.nearby_parking_spaces(0.0, 0.0, 100.0) == [near_space]
    assert manager.nearby_parking_spaces(250.0, 0.0, 300.0) == [near_space, far_space]
    assert near_space.occupied is False
    near_space.reserved = True
    near_space.reserved_by_pedestrian_id = 7
    assert near_space.reserved_by_pedestrian_id == 7


def test_npc_occupies_and_releases_existing_parking_space():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    parking_space = ParkingSpace([(0.0, 0.0), (2.0, 0.0), (2.0, 4.0), (0.0, 4.0)], (0.0, 0.0, 2.0, 4.0), osm_id=9)
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])
    npc = NPCCar(1.0, 2.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20))

    assert manager.occupy_parking_space(npc, parking_space)
    assert npc.state == "parked"
    assert parking_space.occupied is True
    assert parking_space.vehicle_id == id(npc)
    assert manager.activate_occupied_vehicle(npc)
    assert npc.state == "driving"
    assert parking_space.occupied is False


def test_npc_vehicle_has_assigned_driver_identity():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    npc = NPCCar(10.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20))

    assert npc.assigned_driver_id == id(npc)
    assert npc.driver is not None
    assert npc.driver.driver_id == npc.assigned_driver_id
    npc.set_driver_present(False)
    assert npc.has_driver() is False
    assert npc.driver.present is False


def test_npc_without_driver_association_does_not_move():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    npc = NPCCar(10.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20), assigned_driver_id=None)
    npc.assigned_driver_id = None
    manager.npcs = [npc]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=1.0)

    assert npc.x == 10.0
    assert npc.speed == 0.0
    assert npc.state == "waiting"


def test_npc_with_absent_assigned_driver_does_not_move():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    npc = NPCCar(10.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20), driver_present=False)
    manager.npcs = [npc]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=1.0)

    assert npc.x == 10.0
    assert npc.speed == 0.0
    assert npc.state == "waiting"


def test_roundabout_way_flag_and_counter_clockwise_direction():
    roundabout = Way(
        [(10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0), (10.0, 0.0)],
        "secondary",
        4.0,
        oneway=1,
        is_roundabout=True,
    )
    manager = TrafficManager([roundabout], target_count=0)

    assert roundabout.is_roundabout
    assert manager._roundabout_direction(roundabout) == 1


def test_roundabout_entry_yields_to_circulating_npc():
    approach = Way([(40.0, 0.0), (10.0, 0.0)], "secondary", 4.0)
    roundabout = Way(
        [(10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0), (10.0, 0.0)],
        "secondary",
        4.0,
        oneway=1,
        is_roundabout=True,
    )
    manager = TrafficManager([approach, roundabout], target_count=0)
    entering = NPCCar(25.0, 0.0, math.pi, 4.0, approach, 0, -1, 10.0, (20, 20, 20))
    circulating = NPCCar(10.0, 6.0, math.pi / 2, 4.0, roundabout, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [entering, circulating]

    assert manager._roundabout_entry_blocked(entering, roundabout, (10.0, 0.0))


def test_planned_route_does_not_reselect_current_way_at_junction():
    approach = Way([(10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0), (10.0, 0.0)], "secondary", 4.0, oneway=1, is_roundabout=True)
    exit_way = Way([(10.0, 0.0), (10.0, 30.0)], "secondary", 4.0)
    manager = TrafficManager([approach, exit_way], target_count=0)

    route = manager._find_next_way_and_segment(
        approach,
        (10.0, 0.0),
        incoming_heading=0.0,
        preferred_point=(20.0, 0.0),
    )

    assert route is not None
    assert route[0] is exit_way


def test_npc_stops_before_stop_sign():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0, stop_signs=[StopSign(20.0, 0.0, id=4)])
    npc = NPCCar(10.0, 0.0, 0.0, 8.0, way, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [npc]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=1.0)
    assert npc.x <= 18.0
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=1.0)
    assert npc.speed == 0.0
    assert npc.x <= 18.0


def test_activating_occupied_npc_clears_driver_and_parking_state():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Departure Street",
    )
    parking_space = ParkingSpace(
        [(0.0, -2.0), (2.0, -2.0), (2.0, 2.0), (0.0, 2.0)],
        (0.0, -2.0, 2.0, 2.0),
        osm_id=10,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])
    npc = manager.spawn_npc(20.0, 0.0)
    assert npc is not None
    assert manager.occupy_parking_space(npc, parking_space)
    npc.current_driver_id = 123
    npc.state = "occupied"

    assert manager.activate_occupied_vehicle(npc)
    assert npc.state == "parking_departure"
    assert npc.current_driver_id is None
    assert npc.parking_space_id == manager.parking_space_id(parking_space)
    assert parking_space.occupied is True
    assert npc.parking_route is not None
    npc.x = 20.0
    manager.update(Car(x=20.0, y=0.0, heading=0.0, speed=0.0), dt=0.0)
    assert npc.parking_space_id is None
    assert parking_space.occupied is False


def test_departing_occupied_npc_is_not_despawned_before_leaving_space():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Departure Street",
    )
    parking_space = ParkingSpace(
        [(0.0, -2.0), (2.0, -2.0), (2.0, 2.0), (0.0, 2.0)],
        (0.0, -2.0, 2.0, 2.0),
        osm_id=14,
    )
    manager = TrafficManager([way], target_count=0, despawn_radius_m=10.0, parking_spaces=[parking_space])
    npc = NPCCar(1.0, 0.0, 0.0, 0.0, way, 0, 1, 0.0, (20, 20, 20), state="occupied")
    assert manager.occupy_parking_space(npc, parking_space)
    npc.state = "occupied"
    npc.current_driver_id = 123
    manager.npcs = [npc]

    assert manager.activate_occupied_vehicle(npc)
    manager.update(Car(x=100.0, y=0.0, heading=0.0, speed=0.0), dt=0.0)

    assert manager.npcs == [npc]
    assert parking_space.occupied is True


def test_traffic_update_populates_half_target_with_parked_npcs():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.0)
    spaces = [
        ParkingSpace([(x - 1.0, -2.0), (x + 1.0, -2.0), (x + 1.0, 2.0), (x - 1.0, 2.0)], (x - 1.0, -2.0, x + 1.0, 2.0), orientation=0.0, osm_id=x)
        for x in (20.0, 40.0, 60.0, 80.0)
    ]
    manager = TrafficManager(ways=[way], target_count=4, parking_spaces=spaces, parking_density=0.5)

    manager.update(Car(x=100.0, y=0.0, heading=0.0, speed=0.0), dt=1.0)

    assert sum(npc.state == "parked" for npc in manager.npcs) == 2
    assert sum(space.occupied for space in spaces) == 2


def test_despawning_parked_npc_releases_osm_space():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.0)
    parking_space = ParkingSpace([(0.0, -2.0), (2.0, -2.0), (2.0, 2.0), (0.0, 2.0)], (0.0, -2.0, 2.0, 2.0), osm_id=11)
    manager = TrafficManager([way], target_count=0, despawn_radius_m=50.0, parking_spaces=[parking_space])
    npc = NPCCar(1.0, 0.0, 0.0, 0.0, way, 0, 1, 0.0, (20, 20, 20))
    manager.npcs = [npc]
    assert manager.occupy_parking_space(npc, parking_space)

    manager.update(Car(x=100.0, y=0.0, heading=0.0, speed=0.0), dt=0.1)

    assert manager.npcs == []
    assert parking_space.occupied is False


def test_parked_npc_does_not_spawn_directly_inside_viewport():
    way = Way(
        points_m=[(-100.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Parking Street",
    )
    parking_space = ParkingSpace(
        [(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)],
        (-2.0, -2.0, 2.0, 2.0),
        osm_id=12,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])

    npc = manager.spawn_parked_npc(
        0.0,
        0.0,
        viewport_bounds=(-25.0, -25.0, 25.0, 25.0),
    )

    assert npc is None
    assert parking_space.occupied is False


def test_parked_npc_can_spawn_directly_outside_viewport():
    way = Way(
        points_m=[(-100.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Parking Street",
    )
    parking_space = ParkingSpace(
        [(60.0, -2.0), (64.0, -2.0), (64.0, 2.0), (60.0, 2.0)],
        (60.0, -2.0, 64.0, 2.0),
            orientation=0.0,
        osm_id=13,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])

    npc = manager.spawn_parked_npc(
        0.0,
        0.0,
        viewport_bounds=(-25.0, -25.0, 25.0, 25.0),
    )

    assert npc is not None
    assert npc.state == "parked"
    assert parking_space.occupied is True


def test_parking_without_orientation_is_not_used():
    way = Way(
        points_m=[(-100.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    parking_space = ParkingSpace(
        [(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        (18.0, -2.0, 22.0, 2.0),
        osm_id=14,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])

    assert manager.spawn_parked_npc(0.0, 0.0, viewport_bounds=(-25.0, -25.0, 25.0, 25.0)) is None


def test_visible_parking_space_uses_driving_spawn_before_occupying_space():
    random.seed(7)
    way = Way(
        points_m=[(-100.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Parking Approach",
    )
    parking_space = ParkingSpace(
        [(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        (18.0, -2.0, 22.0, 2.0),
            orientation=0.0,
        osm_id=15,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])
    viewport = (-25.0, -25.0, 25.0, 25.0)

    npc = manager.spawn_parking_npc(0.0, 0.0, viewport)

    assert npc is not None
    assert npc.state == "parking"
    assert not (viewport[0] <= npc.x <= viewport[2] and viewport[1] <= npc.y <= viewport[3])
    assert parking_space.occupied is False
    assert parking_space.reserved is True

    for _ in range(300):
        manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.5, viewport_bounds=viewport)
        if npc.state == "parked":
            break

    assert npc.state == "parked"
    assert parking_space.occupied is True


def test_destination_parking_starts_from_a_road_end():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    parking_space = ParkingSpace(
        [(78.0, -2.0), (82.0, -2.0), (82.0, 2.0), (78.0, 2.0)],
        (78.0, -2.0, 82.0, 2.0),
            orientation=0.0,
        osm_id=16,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])
    npc = NPCCar(100.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20))

    assert manager._start_destination_parking(npc)
    assert npc.state == "parking"
    assert npc.parking_route is not None
    assert parking_space.reserved is True
    assert parking_space.vehicle_id == id(npc)


def test_destination_parking_rejects_space_far_from_road():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    parking_space = ParkingSpace(
        [(78.0, 30.0), (82.0, 30.0), (82.0, 34.0), (78.0, 34.0)],
        (78.0, 30.0, 82.0, 34.0),
        osm_id=17,
    )
    manager = TrafficManager([way], target_count=0, parking_spaces=[parking_space])
    npc = NPCCar(100.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20))

    assert not manager._start_destination_parking(npc)
    assert parking_space.reserved is False


def test_plan_route_starts_at_car_and_ends_at_destination():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    manager = TrafficManager([way], target_count=0)

    route = manager.plan_route((25.0, 2.0), (175.0, -3.0))

    assert route is not None
    assert route[0] == (25.0, 2.0)
    assert route[-1] == (175.0, -3.0)
    assert (100.0, 0.0) in route


def test_intersection_manager_reserves_and_releases_conflicting_approaches():
    way = Way(points_m=[(-100.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    first_approach = IntersectionApproach("east", [way], (1.0, 0.0), ((10.0, -4.0), (10.0, 4.0)))
    second_approach = IntersectionApproach("north", [way], (0.0, 1.0), ((-4.0, 10.0), (4.0, 10.0)))
    intersection = LogicalIntersection("junction", (0.0, 0.0), 20.0, approaches=[first_approach, second_approach])
    manager = IntersectionManager([intersection])
    first = NPCCar(8.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20))
    second = NPCCar(0.0, 8.0, math.pi / 2, 4.0, way, 0, 1, 10.0, (30, 30, 30))

    assert manager.request_enter(first, first_approach)
    assert not manager.request_enter(second, second_approach)
    manager.release(first)
    assert manager.request_enter(second, second_approach)


def test_sync_map_data_rebuilds_navigation_graph():
    initial_way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    extended_way = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    manager = TrafficManager([initial_way], target_count=0)

    manager.sync_map_data([initial_way, extended_way])

    route = manager.plan_route((25.0, 0.0), (175.0, 0.0))

    assert route is not None
    assert (100.0, 0.0) in route


def test_traffic_count_scales_down_when_zoomed_in():
    assert traffic_count_for_zoom(50, px_per_m=9.0) == 17
    assert traffic_count_for_zoom(50, px_per_m=18.0) == 8
    assert traffic_count_for_zoom(50, px_per_m=1.0) == 50


def test_traffic_count_is_capped_at_fifty():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=500)

    assert manager.target_count == 50
    manager.set_target_count(500)
    assert manager.target_count == 50


def test_npc_lod_assigns_distance_bands_and_schedules_updates():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    near = NPCCar(100.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (20, 20, 20))
    medium = NPCCar(600.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (30, 30, 30))
    distant = NPCCar(1600.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (40, 40, 40))
    manager.npcs = [near, medium, distant]

    manager.update_lod(Car(0.0, 0.0, 0.0, 0.0), 0.1)

    assert [npc.lod_level for npc in manager.npcs] == [0, 1, 2]
    assert [npc.lod_update_due for npc in manager.npcs] == [True, False, False]

    manager.update_lod(Car(0.0, 0.0, 0.0, 0.0), 0.1)

    assert [npc.lod_update_due for npc in manager.npcs] == [True, True, False]


def test_traffic_manager_assigns_resident_owner_to_existing_npc():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    npc = NPCCar(20.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [npc]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), 0.01)

    assert npc.owner_id is not None
    owner = manager.residents.get(npc.owner_id)
    assert owner is not None
    assert id(npc) in owner.vehicle_ids
    assert npc.current_driver_id == owner.resident_id


def test_active_route_less_npc_gets_a_new_travel_route():
    way = Way(points_m=[(0.0, 0.0), (300.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    npc = NPCCar(10.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [npc]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), 0.01)

    assert npc.travel_route is not None
    assert npc.destination is not None


def test_npc_spatial_grid_refreshes_after_movement():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    npc = NPCCar(31.0, 0.0, 0.0, 10.0, way, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [npc]
    manager._build_npc_spatial_grid()

    manager.update(Car(0.0, 0.0, 0.0, 0.0), 0.2)

    new_cell = (int(npc.x // manager._npc_grid_cell_size), int(npc.y // manager._npc_grid_cell_size))
    assert npc in manager._npc_grid[new_cell]


def test_distant_npc_movement_is_scheduled_by_lod():
    way = Way(points_m=[(0.0, 0.0), (5000.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    npc = NPCCar(2000.0, 0.0, 0.0, 10.0, way, 0, 1, 10.0, (20, 20, 20), lod_level=2)
    npc.lod_update_due = False
    manager.npcs = [npc]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), 0.01)

    assert npc.x == 2000.0


def test_rival_taxi_picks_up_taxi_stand_waiter():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    taxi = NPCCar(0.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (245, 205, 35), is_taxi=True)
    manager.npcs = [taxi]
    waiter = SimpleNamespace(x=1.0, y=0.0, is_taxi_stop_waiter=True)
    pedestrians = [waiter]

    manager.let_taxi_pick_up_waiter([SimpleNamespace(x=0.0, y=0.0)], pedestrians, dt=0.1)

    assert pedestrians == [waiter]
    assert waiter.rival_taxi is taxi
    assert waiter.is_walking_to_car is True
    assert taxi.speed == 0.0
    assert taxi.taxi_pickup_timer == 1.5

    waiter.x = 0.5
    manager.let_taxi_pick_up_waiter([SimpleNamespace(x=0.0, y=0.0)], pedestrians)
    assert pedestrians == []


def test_nearby_offscreen_taxi_stop_spawns_taxis_once(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    spawned = []

    def spawn_npc(*args, **kwargs):
        taxi = NPCCar(100.0, 0.0, 0.0, 0.0, way, 0, 1, 0.0, (245, 205, 35))
        manager.npcs.append(taxi)
        spawned.append(taxi)
        return taxi

    monkeypatch.setattr(manager, "spawn_npc", spawn_npc)
    monkeypatch.setattr("theroadragetrip.traffic.random.randint", lambda low, high: high)
    stop = SimpleNamespace(x=100.0, y=0.0, id=1)
    player = Car(50.0, 0.0, 0.0, 0.0)
    viewport = (-10.0, -10.0, 80.0, 10.0)

    assert manager.spawn_taxis_at_nearby_stops([stop], player, viewport) == 1
    assert all(taxi.is_taxi and taxi.waiting_at_taxi_stop for taxi in spawned)
    assert manager.spawn_taxis_at_nearby_stops([stop], player, viewport) == 0


def test_visible_taxi_stop_does_not_spawn_taxis(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    monkeypatch.setattr("theroadragetrip.traffic.random.randint", lambda low, high: high)

    assert manager.spawn_taxis_at_nearby_stops(
        [SimpleNamespace(x=50.0, y=0.0, id=1)],
        Car(50.0, 0.0, 0.0, 0.0),
        (-10.0, -10.0, 80.0, 10.0),
    ) == 0


def test_npc_traffic_spawning_and_movement():
    # Two connected way segments
    way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main St 1",
    )
    way2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main St 2",
    )
    ways = [way1, way2]

    traffic_mgr = TrafficManager(ways, target_count=5, spawn_radius_m=300.0, despawn_radius_m=500.0)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)

    # Initial update spawns NPCs
    traffic_mgr.update(player, dt=0.1)
    assert len(traffic_mgr.npcs) == 5

    # Check each NPC has valid position and color
    for npc in traffic_mgr.npcs:
        assert isinstance(npc, NPCCar)
        assert 0.0 <= npc.x <= 200.0
        assert -5.0 <= npc.y <= 5.0
        assert len(npc.color) == 3

    # Step simulation multiple frames and verify movement
    initial_positions = [(npc.x, npc.y) for npc in traffic_mgr.npcs]
    for _ in range(10):
        traffic_mgr.update(player, dt=0.1)

    # At least some NPCs have moved
    moved_count = sum(
        1 for i, npc in enumerate(traffic_mgr.npcs)
        if (npc.x, npc.y) != initial_positions[i]
    )
    assert moved_count > 0


def test_spawned_driving_npc_starts_at_target_speed_and_follows_road_direction():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        speed_limit_kmh=50,
    )
    traffic_mgr = TrafficManager([way], target_count=0, spawn_radius_m=300.0)

    npc = traffic_mgr.spawn_npc(50.0, 50.0)

    assert npc is not None
    assert npc.speed == npc.target_speed
    assert npc.speed > 0.0
    assert abs(npc.heading) in (0.0, math.pi)


def test_two_wheelers_are_experimental_only(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)

    class FixedRandom:
        calls = 0

        def random(self):
            self.calls += 1
            return 1.0 if self.calls in (1, 4) else 0.0

        def uniform(self, low, high):
            return low

        def shuffle(self, values):
            return None

        def choice(self, values):
            return values[0]

    fixed_random = FixedRandom()
    monkeypatch.setattr("theroadragetrip.traffic.random", fixed_random)

    default_manager = TrafficManager([way], target_count=0, spawn_radius_m=100.0)
    default_npc = default_manager.spawn_npc(player.x, player.y)
    fixed_random.calls = 0
    experimental_manager = TrafficManager(
        [way], target_count=0, spawn_radius_m=100.0, enable_two_wheelers=True
    )
    experimental_npc = experimental_manager.spawn_npc(player.x, player.y)

    assert default_npc is not None and default_npc.vehicle_type == "car"
    assert experimental_npc is not None and experimental_npc.vehicle_type == "motorcycle"


def test_overlapping_npcs_are_separated():
    way = Way(
        points_m=[(0.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Collision Street",
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    first = NPCCar(50.0, 0.0, 0.0, 4.0, way, 0, 1, 10.0, (20, 20, 20))
    second = NPCCar(50.0, 0.0, math.pi, 4.0, way, 0, -1, 10.0, (30, 30, 30))
    traffic_mgr.npcs = [first, second]

    traffic_mgr.update(Car(x=50.0, y=100.0, heading=0.0, speed=0.0), dt=0.0)

    assert not boxes_intersect(
        first.x, first.y, first.heading, first.length_m, first.width_m,
        second.x, second.y, second.heading, second.length_m, second.width_m,
    )
    assert first.speed == 0.0
    assert second.speed == 0.0


def test_npc_static_collision_stops_at_building():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=2.0)
    building = Building(points_m=[(20.0, -10.0), (30.0, -10.0), (30.0, 10.0), (20.0, 10.0)])
    manager = TrafficManager([way], target_count=0, buildings=[building])
    npc = NPCCar(22.0, 4.0, 0.0, 8.0, way, 0, 1, 8.0, (20, 20, 20))

    crashed = manager._npc_hits_static_obstacle(npc, (15.0, 4.0))

    assert crashed is True
    assert (npc.x, npc.y) == (15.0, 4.0)
    assert npc.speed == 0.0
    assert npc.crashed_timer == 3.0


def test_npc_static_collision_stops_at_tree():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=2.0)
    scenery = Scenery([(0.0, -10.0), (100.0, -10.0), (100.0, 10.0)], "park", trees=[(20.0, 0.0)])
    manager = TrafficManager([way], target_count=0, sceneries=[scenery])
    npc = NPCCar(20.0, 0.0, 0.0, 8.0, way, 0, 1, 8.0, (20, 20, 20))

    crashed = manager._npc_hits_static_obstacle(npc, (15.0, 0.0))

    assert crashed is True
    assert math.hypot(npc.x - 20.0, npc.y) > 3.0
    assert npc.speed == 0.0


def test_parking_npc_does_not_drive_through_another_vehicle():
    way = Way(
        points_m=[(0.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Parking Collision Street",
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    parked = NPCCar(50.0, 0.0, 0.0, 0.0, way, 0, 1, 0.0, (20, 20, 20), state="parking")
    active = NPCCar(50.0, 0.0, math.pi, 0.0, way, 0, -1, 0.0, (30, 30, 30))
    parked.parking_route = [(parked.x, parked.y), (100.0, 0.0)]
    parked.parking_route_index = 1
    traffic_mgr.npcs = [parked, active]

    traffic_mgr.update(Car(x=50.0, y=100.0, heading=0.0, speed=0.0), dt=0.1)

    assert parked.x == 50.0
    assert parked.speed == 0.0


def test_moving_npc_avoids_parked_npc_without_moving_it():
    way = Way(
        points_m=[(0.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Parked Obstacle Street",
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    parked = NPCCar(50.0, 0.0, 0.0, 0.0, way, 0, 1, 0.0, (20, 20, 20), state="parked")
    moving = NPCCar(50.0, 0.0, math.pi, 4.0, way, 0, -1, 10.0, (30, 30, 30))
    traffic_mgr.npcs = [parked, moving]
    parked_position = (parked.x, parked.y)

    traffic_mgr._resolve_npc_collisions()

    assert (parked.x, parked.y) == parked_position
    assert (moving.x, moving.y) != parked_position


def test_waiting_npc_records_blocking_npc_for_debug_overlay():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="primary", half_width_m=6.0)
    traffic_mgr = TrafficManager([way], target_count=0)
    waiting = NPCCar(50.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (20, 20, 20))
    blocker = NPCCar(53.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (30, 30, 30))
    traffic_mgr.npcs = [waiting, blocker]

    traffic_mgr.update(Car(x=-100.0, y=100.0, heading=0.0, speed=0.0), dt=0.1)

    assert waiting.debug_waiting_for == f"NPC {id(blocker) % 1000}"


def test_rage_shout_moves_cars_ahead_to_road_edge():
    way = Way(
        points_m=[(0.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        oneway=1,
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    ahead = NPCCar(
        x=30.0, y=0.0, heading=0.0, speed=8.0, way=way,
        segment_idx=0, direction=1, target_speed=12.0, color=(100, 100, 100),
    )
    behind = NPCCar(
        x=-30.0, y=0.0, heading=0.0, speed=8.0, way=way,
        segment_idx=0, direction=1, target_speed=12.0, color=(100, 100, 100),
    )
    traffic_mgr.npcs = [ahead, behind]

    moved = traffic_mgr.rage_shout(Car(x=0.0, y=0.0, heading=0.0, speed=0.0))

    assert moved == 1
    assert ahead.y == -7.35
    assert ahead.rage_timer > 0.0
    assert behind.y == 0.0


def test_npc_uses_only_first_traffic_light_ahead():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    near_green = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=0.0, direction_angle=0.0)
    far_red = TrafficLight(x=20.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    traffic_mgr = TrafficManager([way], target_count=0, traffic_lights=[far_red, near_green])
    npc = NPCCar(
        x=0.0, y=0.0, heading=0.0, speed=10.0, way=way,
        segment_idx=0, direction=1, target_speed=20.0, color=(100, 100, 100),
    )
    traffic_mgr.npcs = [npc]

    traffic_mgr.update(Car(x=-200.0, y=200.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.speed > 10.0


def test_npc_right_side_and_overtaking():
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Two-way Road",
        oneway=0,
    )
    ways = [way]
    traffic_mgr = TrafficManager(ways, target_count=2, spawn_radius_m=300.0, despawn_radius_m=500.0)

    # Spawn NPC
    npc = traffic_mgr.spawn_npc(100.0, 0.0)
    assert npc is not None
    assert npc.lane_offset > 0.0
    assert npc.y * npc.direction < 0.0  # opposite directions use opposite world-side lanes

    # Test overtaking offset
    from theroadragetrip.traffic import compute_desired_lane_offset
    normal_offset = compute_desired_lane_offset(way, is_overtaking=False)
    overtake_offset = compute_desired_lane_offset(way, is_overtaking=True)
    assert normal_offset > 0
    assert overtake_offset < 0  # shifts left to overtake


def test_npc_reverse_direction_uses_opposite_lane():
    from theroadragetrip.traffic import compute_desired_lane_offset

    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Two-way Road",
        oneway=0,
    )

    assert compute_desired_lane_offset(way, travel_direction=1) > 0.0
    assert compute_desired_lane_offset(way, travel_direction=-1) > 0.0


def test_npc_does_not_overtake_into_opposing_lane():
    way = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        oneway=0,
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    lead = NPCCar(
        x=50.0, y=-2.7, heading=0.0, speed=0.0, way=way,
        segment_idx=0, direction=1, target_speed=12.0, color=(100, 100, 100),
        lane_offset=2.7, target_lane_offset=2.7,
    )
    follower = NPCCar(
        x=40.0, y=-2.7, heading=0.0, speed=12.0, way=way,
        segment_idx=0, direction=1, target_speed=12.0, color=(200, 50, 50),
        lane_offset=2.7, target_lane_offset=2.7,
    )
    traffic_mgr.npcs = [lead, follower]

    traffic_mgr.update(Car(x=200.0, y=200.0, heading=0.0, speed=0.0), dt=0.1)

    assert follower.target_lane_offset > 0.0


def test_npc_immediately_returns_to_right_lane():
    way = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        oneway=0,
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    npc = NPCCar(
        x=100.0, y=-2.7, heading=3.1415926535, speed=8.0, way=way,
        segment_idx=0, direction=-1, target_speed=12.0, color=(200, 50, 50),
        lane_offset=2.7, target_lane_offset=2.7,
    )
    traffic_mgr.npcs = [npc]

    traffic_mgr.update(Car(x=-200.0, y=200.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.lane_offset > 0.0
    assert npc.y < 0.0


def test_npc_spawning_avoids_junction_conflict_zone():
    ew_way = Way(
        points_m=[(-100.0, 0.0), (0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="EW Street",
    )
    ns_way = Way(
        points_m=[(0.0, -100.0), (0.0, 0.0), (0.0, 100.0)],
        highway="primary",
        half_width_m=4.0,
        name="NS Street",
    )
    traffic_mgr = TrafficManager([ew_way, ns_way], target_count=6, spawn_radius_m=100.0)
    player = Car(x=200.0, y=200.0, heading=0.0, speed=0.0)

    traffic_mgr.update(player, dt=0.1)

    assert all(math.hypot(npc.x, npc.y) >= 18.0 for npc in traffic_mgr.npcs)


def test_npc_despawning_when_far():
    way = Way(
        points_m=[(0.0, 0.0), (1000.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Long Highway",
    )
    ways = [way]
    traffic_mgr = TrafficManager(ways, target_count=3, spawn_radius_m=200.0, despawn_radius_m=300.0)

    player = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    traffic_mgr.update(player, dt=0.1)
    assert len(traffic_mgr.npcs) == 3

    # Move player far away
    player.x = 5000.0
    traffic_mgr.update(player, dt=0.1)
    # Old NPCs despawned and new ones spawned around the player's new position
    for npc in traffic_mgr.npcs:
        assert math.hypot(npc.x - player.x, npc.y - player.y) <= 400.0


def test_npc_behind_player_despawns_outside_viewport():
    way = Way(
        points_m=[(-200.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Viewport Street",
    )
    traffic_mgr = TrafficManager([way], target_count=0, despawn_radius_m=300.0)
    behind = NPCCar(-100.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (20, 20, 20))
    ahead = NPCCar(100.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (30, 30, 30))
    traffic_mgr.npcs = [behind, ahead]

    traffic_mgr.update(
        Car(x=0.0, y=0.0, heading=0.0, speed=0.0),
        dt=0.0,
        viewport_bounds=(-25.0, -25.0, 25.0, 25.0),
    )

    assert traffic_mgr.npcs == [ahead]


def test_npc_does_not_fallback_to_spawning_inside_viewport():
    way = Way(
        points_m=[(-10.0, 0.0), (10.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Visible Street",
    )
    traffic_mgr = TrafficManager([way], target_count=1, spawn_radius_m=50.0)

    traffic_mgr.update(
        Car(x=0.0, y=0.0, heading=0.0, speed=0.0),
        dt=0.0,
        viewport_bounds=(-25.0, -25.0, 25.0, 25.0),
    )

    assert traffic_mgr.npcs == []


def test_npc_avoids_180_degree_u_turns_at_junction():
    # + shape intersection:
    # East-West road: (-100, 0) to (100, 0)
    # North-South road: (0, -100) to (0, 100)
    ew_way = Way(
        points_m=[(-100.0, 0.0), (0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="EW Street",
        oneway=0,
    )
    ns_way = Way(
        points_m=[(0.0, -100.0), (0.0, 0.0), (0.0, 100.0)],
        highway="primary",
        half_width_m=4.0,
        name="NS Street",
        oneway=0,
    )
    ways = [ew_way, ns_way]
    traffic_mgr = TrafficManager(ways)

    # Car approaching junction (0, 0) from west moving east (heading = 0.0)
    # Incoming heading is 0.0 (east)
    chosen_routes = []
    for _ in range(50):
        next_route = traffic_mgr._find_next_way_and_segment(
            ew_way, (0.0, 0.0), incoming_heading=0.0
        )
        assert next_route is not None
        cand_way, cand_seg_idx, cand_dir = next_route
        # Check angle
        cand_pts = cand_way.points_m
        if cand_dir == 1:
            p1, p2 = cand_pts[cand_seg_idx], cand_pts[cand_seg_idx + 1]
        else:
            p1, p2 = cand_pts[cand_seg_idx + 1], cand_pts[cand_seg_idx]
        out_heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        angle_diff = abs((out_heading - 0.0 + math.pi) % (2 * math.pi) - math.pi)
        # Must not turn ~180 degrees back west
        assert angle_diff < math.radians(135)
        chosen_routes.append(next_route)

    # Single isolated road: 180 turn is the ONLY option, so it should allow it
    dead_end_way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=3.0,
        name="Dead End",
        oneway=0,
    )
    traffic_mgr_single = TrafficManager([dead_end_way])
    rev_route = traffic_mgr_single._find_next_way_and_segment(
        dead_end_way, (100.0, 0.0), incoming_heading=0.0
    )
    # When at (100, 0), the only way to go is backward (dir=-1, segment 0)
    assert rev_route is not None
    assert rev_route[0] is dead_end_way
    assert rev_route[2] == -1


def test_uncontrolled_left_turn_yields_to_oncoming_traffic():
    approach = Way(points_m=[(-30.0, 0.0), (0.0, 0.0)], highway="secondary", half_width_m=4.0)
    exit_way = Way(points_m=[(0.0, 0.0), (0.0, 30.0)], highway="secondary", half_width_m=4.0)
    opposing_way = Way(points_m=[(30.0, 0.0), (0.0, 0.0)], highway="secondary", half_width_m=4.0)
    turning = NPCCar(-10.0, 0.0, 0.0, 4.0, approach, 0, 1, 10.0, (0, 0, 0), next_route=(exit_way, 0, 1))
    opposing = NPCCar(10.0, 0.0, math.pi, 4.0, opposing_way, 0, -1, 10.0, (0, 0, 0))
    manager = TrafficManager([approach, exit_way, opposing_way])
    manager.npcs = [turning, opposing]

    assert manager._junction_is_clear_for(turning, (0.0, 0.0)) is False


def test_stop_line_queue_does_not_occupy_junction():
    way = Way(points_m=[(-100.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    manager = TrafficManager([way], target_count=0)
    waiting = NPCCar(-10.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (0, 0, 0), state="waiting")
    approaching = NPCCar(10.0, 0.0, math.pi, 0.0, way, 1, -1, 10.0, (0, 0, 0), state="waiting")
    manager.npcs = [waiting, approaching]

    assert manager._junction_is_occupied((0.0, 0.0), waiting) is False


def test_parked_npc_does_not_block_uncontrolled_junction():
    approach = Way(points_m=[(-30.0, 0.0), (0.0, 0.0)], highway="secondary", half_width_m=4.0)
    parked_way = Way(points_m=[(0.0, -30.0), (0.0, 0.0)], highway="service", half_width_m=4.0)
    approaching = NPCCar(-10.0, 0.0, 0.0, 4.0, approach, 0, 1, 10.0, (0, 0, 0))
    parked = NPCCar(0.0, -8.0, math.pi / 2.0, 0.0, parked_way, 0, 1, 0.0, (0, 0, 0), state="parked")
    manager = TrafficManager([approach, parked_way])
    manager.npcs = [approaching, parked]

    assert manager._junction_is_clear_for(approaching, (0.0, 0.0)) is True
    assert manager._junction_is_occupied((0.0, 0.0), approaching) is False


def test_stopped_junction_queue_has_deterministic_deadlock_breaker():
    horizontal = Way(points_m=[(-30.0, 0.0), (0.0, 0.0)], highway="secondary", half_width_m=4.0)
    vertical = Way(points_m=[(0.0, -30.0), (0.0, 0.0)], highway="secondary", half_width_m=4.0)
    first = NPCCar(-10.0, 0.0, 0.0, 0.0, horizontal, 0, 1, 10.0, (0, 0, 0), junction_wait_timer=2.5)
    second = NPCCar(0.0, -8.0, math.pi / 2.0, 0.0, vertical, 0, 1, 10.0, (0, 0, 0), junction_wait_timer=1.0)
    manager = TrafficManager([horizontal, vertical])
    manager.npcs = [first, second]

    assert manager._junction_deadlock_can_proceed(second, (0.0, 0.0)) is True
    assert manager._junction_deadlock_can_proceed(first, (0.0, 0.0)) is False


def test_priority_road_has_right_of_way_over_uncontrolled_approach():
    priority = Way(points_m=[(30.0, 0.0), (0.0, 0.0)], highway="primary", half_width_m=4.0, priority_road=True)
    side = Way(points_m=[(0.0, -30.0), (0.0, 0.0)], highway="residential", half_width_m=4.0)
    priority_car = NPCCar(10.0, 0.0, math.pi, 4.0, priority, 0, -1, 10.0, (0, 0, 0))
    side_car = NPCCar(0.0, -10.0, math.pi / 2.0, 4.0, side, 0, 1, 10.0, (0, 0, 0))
    manager = TrafficManager([priority, side])
    manager.npcs = [priority_car, side_car]

    assert manager._junction_is_clear_for(side_car, (0.0, 0.0)) is False
    assert manager._junction_is_clear_for(priority_car, (0.0, 0.0)) is True


def test_npc_can_leave_bridge_at_layer_transition():
    approach = Way(
        points_m=[(0.0, 0.0), (50.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        layer=0,
    )
    bridge = Way(
        points_m=[(50.0, 0.0), (50.0, 100.0)],
        highway="primary",
        half_width_m=4.0,
        layer=1,
        is_bridge=True,
    )
    exit_road = Way(
        points_m=[(50.0, 100.0), (100.0, 100.0)],
        highway="primary",
        half_width_m=4.0,
        layer=0,
    )
    traffic_mgr = TrafficManager([approach, bridge, exit_road])

    route = traffic_mgr._find_next_way_and_segment(bridge, (50.0, 100.0))

    assert route is not None
    assert route[0] is exit_road
    assert route[2] == 1


def test_npc_waits_for_occupied_junction_to_clear():
    approach = Way(
        points_m=[(-50.0, 0.0), (0.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    crossing = Way(
        points_m=[(0.0, -50.0), (0.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    crossing_exit = Way(
        points_m=[(0.0, 0.0), (0.0, 50.0)],
        highway="primary",
        half_width_m=4.0,
    )
    traffic_mgr = TrafficManager([approach, crossing, crossing_exit], target_count=0)
    waiting = NPCCar(
        x=-15.0,
        y=0.0,
        heading=0.0,
        speed=8.0,
        way=approach,
        segment_idx=0,
        direction=1,
        target_speed=12.0,
        color=(200, 50, 50),
    )
    occupying = NPCCar(
        x=0.0,
        y=0.0,
        heading=1.570796,
        speed=0.0,
        way=crossing,
        segment_idx=0,
        direction=1,
        target_speed=12.0,
        color=(50, 50, 200),
    )
    traffic_mgr.npcs = [waiting, occupying]
    player = Car(x=200.0, y=200.0, heading=0.0, speed=0.0)

    traffic_mgr.update(player, dt=0.1)

    assert waiting.speed < 8.0
    assert waiting.x < -7.0


def test_npc_prepares_next_route_before_junction():
    approach = Way(
        points_m=[(-50.0, 0.0), (0.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    crossing = Way(
        points_m=[(0.0, -50.0), (0.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    crossing_exit = Way(
        points_m=[(0.0, 0.0), (0.0, 50.0)],
        highway="primary",
        half_width_m=4.0,
    )
    traffic_mgr = TrafficManager([approach, crossing, crossing_exit], target_count=0)
    npc = NPCCar(
        x=-20.0,
        y=0.0,
        heading=0.0,
        speed=8.0,
        way=approach,
        segment_idx=0,
        direction=1,
        target_speed=12.0,
        color=(200, 50, 50),
    )
    traffic_mgr.npcs = [npc]

    traffic_mgr.update(Car(x=200.0, y=200.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.next_route is not None


def test_npc_turn_uses_bounded_steering_and_continuous_body_heading():
    approach = Way(
        points_m=[(-30.0, 0.0), (0.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    exit_way = Way(
        points_m=[(0.0, 0.0), (0.0, 30.0)],
        highway="residential",
        half_width_m=4.0,
    )
    manager = TrafficManager([approach, exit_way], target_count=0)
    npc = NPCCar(
        x=-1.0,
        y=0.0,
        heading=0.0,
        speed=8.0,
        way=approach,
        segment_idx=0,
        direction=1,
        target_speed=8.0,
        color=(20, 20, 20),
        next_route=(exit_way, 0, 1),
    )
    manager.npcs = [npc]

    manager.update(Car(x=-100.0, y=-100.0, heading=0.0, speed=0.0), dt=0.1)

    assert abs(npc.steering_angle) <= math.radians(32.0)
    assert abs(npc.heading) < math.pi / 2.0
    assert npc.x < 0.0
    assert abs(npc.y) < 1.0


def test_npc_advances_route_when_turn_node_is_already_behind_it():
    approach = Way(
        points_m=[(-30.0, 0.0), (0.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    exit_way = Way(
        points_m=[(0.0, 0.0), (0.0, 30.0)],
        highway="residential",
        half_width_m=4.0,
    )
    manager = TrafficManager([approach, exit_way], target_count=0)
    npc = NPCCar(
        x=2.0,
        y=0.0,
        heading=0.0,
        speed=8.0,
        way=approach,
        segment_idx=0,
        direction=1,
        target_speed=8.0,
        color=(20, 20, 20),
        next_route=(exit_way, 0, 1),
    )
    manager.npcs = [npc]

    manager.update(Car(x=-100.0, y=-100.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.way is exit_way


def test_npc_right_turn_joins_exit_way_right_lane():
    approach = Way(
        points_m=[(-30.0, 0.0), (0.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
    )
    exit_way = Way(
        points_m=[(0.0, 0.0), (0.0, -40.0)],
        highway="residential",
        half_width_m=4.0,
    )
    manager = TrafficManager([approach, exit_way], target_count=0)
    npc = NPCCar(
        x=-8.0,
        y=0.0,
        heading=0.0,
        speed=5.0,
        way=approach,
        segment_idx=0,
        direction=1,
        target_speed=5.0,
        color=(20, 20, 20),
        next_route=(exit_way, 0, 1),
    )
    manager.npcs = [npc]

    for _ in range(60):
        manager.update(Car(x=-100.0, y=100.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.way is exit_way
    assert npc.x < 0.0


def test_npc_signals_prepared_turn_before_junction():
    approach = Way(points_m=[(-50.0, 0.0), (0.0, 0.0)], highway="primary", half_width_m=4.0)
    turn = Way(points_m=[(0.0, 0.0), (0.0, 50.0)], highway="primary", half_width_m=4.0)
    npc = NPCCar(
        x=-20.0, y=0.0, heading=0.0, speed=8.0, way=approach,
        segment_idx=0, direction=1, target_speed=12.0, color=(200, 50, 50),
        next_route=(turn, 0, 1),
    )

    assert TrafficManager._turn_signal_for_next_route(npc) == "left"


def test_npc_does_not_stop_for_next_light_inside_junction():
    approach = Way(points_m=[(-50.0, 0.0), (0.0, 0.0), (50.0, 0.0)], highway="primary", half_width_m=4.0)
    crossing = Way(points_m=[(0.0, -50.0), (0.0, 50.0)], highway="primary", half_width_m=4.0)
    near_green = TrafficLight(x=5.0, y=0.0, cycle_time=16.0, offset=0.0, direction_angle=0.0)
    next_red = TrafficLight(x=15.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    traffic_mgr = TrafficManager([approach, crossing], target_count=0, traffic_lights=[next_red, near_green])
    npc = NPCCar(
        x=8.0, y=0.0, heading=0.0, speed=8.0, way=approach,
        segment_idx=1, direction=1, target_speed=12.0, color=(200, 50, 50),
    )
    traffic_mgr.npcs = [npc]

    traffic_mgr.update(Car(x=200.0, y=200.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.speed > 0.0


def test_npc_brakes_near_red_light_stop_line():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    red_light = TrafficLight(x=30.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    traffic_mgr = TrafficManager([way], target_count=0, traffic_lights=[red_light])
    npc = NPCCar(
        x=0.0, y=0.0, heading=0.0, speed=10.0, way=way,
        segment_idx=0, direction=1, target_speed=20.0, color=(200, 50, 50),
    )
    traffic_mgr.npcs = [npc]

    for _ in range(30):
        traffic_mgr.update(Car(x=200.0, y=200.0, heading=0.0, speed=0.0), dt=0.1)

    assert 25.0 <= npc.x <= 32.0
    assert npc.speed == 0.0


def test_player_and_npc_car_crash_and_penalty():
    from theroadragetrip.taxi import TaxiManager

    taxi_mgr = TaxiManager(ways=[])
    taxi_mgr.total_score = 500

    player = Car(x=10.0, y=0.0, heading=0.0, speed=10.0, length_m=4.0, width_m=1.8)
    # NPC right at (12.0, 0.0) -> overlaps with 4m player car
    npc = NPCCar(
        x=12.0,
        y=0.0,
        heading=0.0,
        speed=5.0,
        way=Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0),
        segment_idx=0,
        direction=1,
        target_speed=10.0,
        color=(100, 100, 100),
        length_m=4.0,
        width_m=1.8,
    )

    crashed = taxi_mgr.check_car_collision(player, [npc], sim_time=1.0, penalty=150)
    assert crashed is True
    assert taxi_mgr.total_score == 350
    assert "Kolari!" in taxi_mgr.notification_msg
    assert taxi_mgr.taxi_smoke_timer == 5.0

    # Cooldown prevents repeated penalties in rapid succession
    crashed2 = taxi_mgr.check_car_collision(player, [npc], sim_time=1.2, penalty=150)
    assert taxi_mgr.total_score == 350


def test_motorcycle_crash_falls_and_moves_to_roadside():
    from theroadragetrip.taxi import TaxiManager

    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    player = Car(x=10.0, y=0.0, heading=0.0, speed=10.0)
    motorcycle = NPCCar(
        x=12.0,
        y=0.0,
        heading=0.0,
        speed=5.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=10.0,
        color=(220, 40, 40),
        length_m=2.2,
        width_m=0.8,
        vehicle_type="motorcycle",
    )

    assert TaxiManager(ways=[]).check_car_collision(player, [motorcycle], sim_time=1.0)
    assert motorcycle.fallen is True
    assert abs(motorcycle.y) > way.half_width_m
    assert motorcycle.speed == 0.0


def test_npc_does_not_spawn_on_orphaned_road_segment():
    # Main connected road network
    main_way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main Road 1",
    )
    main_way2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main Road 2",
    )
    # Orphaned disconnected road segment far away
    orphan_way = Way(
        points_m=[(50.0, 50.0), (70.0, 50.0)],
        highway="residential",
        half_width_m=4.0,
        name="Orphan Road",
    )
    ways = [main_way1, main_way2, orphan_way]

    traffic_mgr = TrafficManager(ways, target_count=5, spawn_radius_m=300.0, despawn_radius_m=500.0)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)

    traffic_mgr.update(player, dt=0.1)

    # NPCs must only be on the main connected road network, none on the orphaned segment
    assert len(traffic_mgr.npcs) == 5
    for npc in traffic_mgr.npcs:
        assert npc.way is not orphan_way
        assert npc.way in (main_way1, main_way2)


def test_npc_avoids_colliding_with_leading_npc():
    way = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Straight Road",
    )
    traffic_mgr = TrafficManager([way], target_count=2)

    # Lead car (slow or stopped) at x=50.0
    lead_npc = NPCCar(
        x=50.0,
        y=0.0,
        heading=0.0,
        speed=0.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=0.0,
        color=(100, 100, 100),
        length_m=4.0,
        width_m=1.8,
    )
    # Following car approaching from x=40.0 with speed 12.0 m/s
    following_npc = NPCCar(
        x=40.0,
        y=0.0,
        heading=0.0,
        speed=12.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=12.0,
        color=(200, 50, 50),
        length_m=4.0,
        width_m=1.8,
    )

    traffic_mgr.npcs = [lead_npc, following_npc]
    player = Car(x=200.0, y=200.0, heading=0.0, speed=0.0)

    # Update simulation
    traffic_mgr.update(player, dt=0.1)

    # Following car should brake hard to avoid collision
    assert following_npc.speed < 12.0
    # Run multiple steps to ensure distance is maintained
    for _ in range(15):
        traffic_mgr.update(player, dt=0.1)

    # Following car stopped or maintained safe distance behind lead car
    assert following_npc.x < lead_npc.x
    assert math.hypot(lead_npc.x - following_npc.x, lead_npc.y - following_npc.y) >= 3.5


def test_npc_escapes_after_being_blocked():
    way = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Blocked Road",
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    lead_npc = NPCCar(
        x=50.0,
        y=0.0,
        heading=0.0,
        speed=0.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=0.0,
        color=(100, 100, 100),
    )
    following_npc = NPCCar(
        x=45.0,
        y=0.0,
        heading=0.0,
        speed=4.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=12.0,
        color=(200, 50, 50),
    )
    traffic_mgr.npcs = [lead_npc, following_npc]

    player = Car(x=-100.0, y=100.0, heading=0.0, speed=0.0)
    for _ in range(25):
        traffic_mgr.update(player, dt=0.1)

    assert following_npc.escape_timer > 0.0
    assert following_npc.speed > 0.0


def test_npc_is_removed_at_one_way_route_end():
    way = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0)],
        highway="motorway",
        half_width_m=6.0,
        oneway=1,
    )
    traffic_mgr = TrafficManager([way], target_count=0)
    npc = NPCCar(
        x=9.0,
        y=0.0,
        heading=0.0,
        speed=20.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=20.0,
        color=(100, 100, 100),
    )
    traffic_mgr.npcs = [npc]

    traffic_mgr.update(Car(x=100.0, y=100.0, heading=0.0, speed=0.0), dt=0.2)

    assert npc not in traffic_mgr.npcs
