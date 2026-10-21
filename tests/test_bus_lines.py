"""Bus lines from OSM route relations (docs/bus-lines.md)."""
from types import SimpleNamespace

from theroadragetrip import bus_lines
from theroadragetrip.osm.build import build_ways


def _stop(x, y, *routes):
    return SimpleNamespace(x=x, y=y, routes=[list(route) for route in routes])


def test_route_relation_orders_its_stops_and_snaps_stop_positions():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"highway": "bus_stop", "name": "A"}},
        {"type": "node", "id": 2, "lat": 60.01, "lon": 25.0, "tags": {"highway": "bus_stop", "name": "B"}},
        {"type": "node", "id": 3, "lat": 60.02, "lon": 25.0, "tags": {"highway": "bus_stop", "name": "C"}},
        {"type": "node", "id": 4, "lat": 60.0201, "lon": 25.0, "tags": {"public_transport": "stop_position", "bus": "yes"}},
        {"type": "relation", "id": 100, "tags": {"type": "route", "route": "bus", "ref": "18"}, "members": [
            {"type": "node", "ref": 2, "role": "platform"},  # out of order on purpose: the member index decides
            {"type": "node", "ref": 999, "role": "platform"},  # not loaded
            {"type": "node", "ref": 1, "role": "platform"},
        ]},
        {"type": "relation", "id": 101, "tags": {"type": "route", "route": "bus", "ref": "18"}, "members": [
            {"type": "node", "ref": 4, "role": "stop"},  # a stop_position: snapped to stop C (11 m)
            {"type": "node", "ref": 2, "role": "stop"},
        ]},
    ]

    stops = {stop.name: stop for stop in build_ways(elements).bus_stops}

    assert stops["B"].routes == [["100", 0, "18"], ["101", 1, "18"]]
    assert stops["A"].routes == [["100", 2, "18"]] and stops["C"].routes == [["101", 0, "18"]]
    found = bus_lines.lines(list(stops.values()))
    assert [s.name for s in found["100"].stops] == ["B", "A"] and [s.name for s in found["101"].stops] == ["C", "B"]


def test_a_line_needs_two_loaded_stops():
    assert bus_lines.lines([_stop(0, 0, ("7", 0, "7"))]) == {}


def test_a_bus_walks_its_line_stop_by_stop_to_the_terminus():
    a, b, c = _stop(0, 0, ("1", 0, "5")), _stop(100, 0, ("1", 1, "5")), _stop(200, 0, ("1", 2, "5"))
    found = bus_lines.lines([c, a, b])
    job = bus_lines.start_job(found, 90, 5)
    assert job.target_stop is b and job.state == "driving"

    assert not job.at_stop(5.0, 40, 0) and job.state == "await_departure" and job.target_stop is b  # stopped elsewhere
    job.departing()
    assert not job.at_stop(10.0, 99, 2) and job.state == "stopped"  # arrived: dwelling
    assert not job.at_stop(10.0 + bus_lines.STOP_DWELL_S - 1, 99, 2)
    assert not job.at_stop(10.0 + bus_lines.STOP_DWELL_S, 99, 2) and job.state == "await_departure" and job.target_stop is c
    job.departing()
    job.at_stop(50.0, 200, 2)
    assert job.at_stop(50.0 + bus_lines.STOP_DWELL_S, 200, 2)  # the terminus served


def test_unroutable_stops_are_skipped_then_the_line_ends():
    found = bus_lines.lines([_stop(0, 0, ("1", 0, "5")), _stop(100, 0, ("1", 1, "5"))])
    job = bus_lines.BusJob(found["1"], 1)
    results = [job.route_failed() for _ in range(bus_lines.MAX_ROUTE_ATTEMPTS)]
    assert results == [False] * (bus_lines.MAX_ROUTE_ATTEMPTS - 1) + [True]


def test_a_line_bus_drives_its_stops_on_real_roads_then_retires_out_of_sight():
    """The NPC system drives it (traffic rules and all): it stops in each
    stop's bay in turn, its riders aboard, and leaves at the terminus."""
    import math
    import random

    from theroadragetrip.npc import NPCState, NPCVehicleManager, spawn_npc
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.static_world import bus_stop_point
    from theroadragetrip.traffic_world import TrafficWorld
    from tests.test_competitor_taxis import _city_block_grid

    random.seed(4)
    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    # On the right of the way the line goes (right-hand traffic): south of the eastbound road, east of the northbound one, ...
    stops = [_stop(172.0, -6.5, ("1", 0, "18")),  # just before a junction: the route node nearest is past it
             _stop(306.5, 150.0, ("1", 1, "18")), _stop(210.0, 306.5, ("1", 2, "18"))]
    for stop in stops:
        stop.layer = 0
    _, driver, bus = spawn_npc(1, residents, traffic_world, ways, (30.0, 0.0), (90.0, 0.0), vehicle_type="bus")
    bus.state = NPCState.PARKED
    manager = NPCVehicleManager(target_count=1, spawn_radius_m=300.0, vehicle_distribution={"car": 1.0})
    manager.line_buses = 0  # just this one
    manager.bus_stops = stops
    manager.vehicles.append(bus)
    manager.drivers[bus.vehicle_id] = driver
    bus.vehicle_kind = "bus_line"
    bus.bus_job = bus_lines.BusJob(manager.bus_lines()["1"], 0, state="await_departure")
    served = []
    for _ in range(30 * 60 * 8):  # up to 8 minutes
        traffic_world.advance_time(1.0 / 30.0)
        manager.update(1.0 / 30.0, 210.0, 210.0, residents, traffic_world, ways)
        job = bus.bus_job
        if job is not None and job.state == "driving":  # approaching: never in the oncoming lane
            (px, py), (nx, ny), _ = bus_stop_point(job.target_stop, ways)
            if math.hypot(bus.x - px, bus.y - py) < 20.0:
                assert (bus.x - px) * nx + (bus.y - py) * ny > 0.5, (job.target_stop.x, job.target_stop.y, bus.x, bus.y)
        if job is not None and job.state == "stopped" and (not served or served[-1][0] is not job.stopped_at):
            served.append((job.stopped_at, (bus.x, bus.y)))
        assert "road boundary" not in bus.debug_waiting_for, (bus.x, bus.y)  # into and out of each bay cleanly
        if bus not in manager.vehicles or bus.state == NPCState.CRASHED:
            break
    assert bus.state != NPCState.CRASHED
    assert [stops.index(stop) for stop, _ in served] == [0, 1, 2], served  # the line in order
    assert bus not in manager.vehicles and bus.vehicle_id not in manager.drivers  # retired at the terminus (no viewport: unseen)
    for stop, (x, y) in served:
        (px, py), (nx, ny), way = bus_stop_point(stop, ways)
        assert math.hypot(x - stop.x, y - stop.y) < 12.0, (stop.x, stop.y, x, y)  # at the stop...
        assert (x - px) * nx + (y - py) * ny > way.half_width_m, (stop.x, stop.y, x, y)  # ...in its bay, off the carriageway


def test_a_line_bus_keeps_its_riders_aboard_at_a_stop():
    """A parked NPC car's group walks off to a building; a line bus at a stop
    is not their destination (bug: every rider left at the first stop)."""
    from theroadragetrip.npc import NPCState, TripGroup
    from theroadragetrip.pedestrian import PedestrianManager

    group = TripGroup(group_id=1, vehicle_id=1, member_resident_ids=[1, 2, 3])
    bus = SimpleNamespace(state=NPCState.PARKED, vehicle_kind="bus_line", is_taxi=False, trip_group=group,
                          x=0.0, y=0.0, heading=0.0, length_m=11.0, width_m=2.5)
    from theroadragetrip.osm import Way
    sidewalk = Way(points_m=[(-30.0, 5.0), (30.0, 5.0)], highway="footway", half_width_m=1.2)
    manager = PedestrianManager([sidewalk], target_count=0, traffic_vehicles=[bus])
    manager.entrance_locations = [(20.0, 0.0)]

    manager._materialize_parked_drivers()

    assert manager.pedestrians == [] and group.disembarked_resident_ids == set()


def test_a_line_bus_exchanges_visible_passengers_at_a_stop():
    from theroadragetrip.activities import ActivityInstance, ActivityLocation
    from theroadragetrip.npc import NPCState, TripGroup
    from theroadragetrip.osm import Way
    from theroadragetrip.pedestrian import PedestrianManager
    from theroadragetrip.residents import ResidentManager

    residents = ResidentManager()
    driver = residents.create("driving")
    rider = residents.create("riding")
    waiter = residents.create("walking")
    group = TripGroup(1, 1, [driver.resident_id, rider.resident_id],
                      boarded_resident_ids={driver.resident_id, rider.resident_id})
    bus = SimpleNamespace(
        state=NPCState.PARKED, vehicle_kind="bus_line", trip_group=group,
        owner_id=driver.resident_id, vehicle_id=1, available_seats=3,
        x=0.0, y=0.0, heading=0.0, width_m=2.5,
    )
    sidewalk = Way(points_m=[(-30.0, -3.0), (30.0, -3.0)], highway="footway", half_width_m=1.2)
    manager = PedestrianManager([sidewalk], target_count=0, traffic_vehicles=[bus], residents=residents)
    pedestrian = manager.spawn_pedestrian_at(0.0, -3.0, resident_id=waiter.resident_id)
    manager.add_pedestrian(pedestrian)
    pedestrian.activity = ActivityInstance("bus_stop_waiting", ActivityLocation(0.0, 3.0), 0.0)
    pedestrian.state = "performing_activity"

    manager.exchange_bus_passengers(bus, _stop(0.0, -3.0))

    assert rider.resident_id not in group.member_resident_ids
    leaving = next(p for p in manager.pedestrians if p.resident_id == rider.resident_id)
    assert leaving.y < bus.y  # eastbound: the right/passenger side is south, away from traffic
    assert waiter.resident_id in group.member_resident_ids
    assert pedestrian.linked_vehicle_id == id(bus) and pedestrian.state == "returning_to_vehicle"


def test_a_stop_is_never_served_from_the_far_side():
    """South of an eastbound street, a stop serves eastbound buses. A bus
    coming from the east would cross the oncoming lane into the bay
    (bug: a head-on crash with the player), so that leg is refused."""
    from theroadragetrip.npc import _bus_leg_steps, run_route_steps
    from theroadragetrip.traffic_world import TrafficWorld
    from tests.test_competitor_taxis import _city_block_grid

    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    stop = _stop(150.0, -6.5, ("1", 0, "18"))
    stop.layer = 0
    job = bus_lines.BusJob(bus_lines.Line("1", "18", [stop, stop]), 0)

    def leg(x, y):
        bus = SimpleNamespace(car=SimpleNamespace(x=x, y=y), length_m=11.0, width_m=2.5)
        return run_route_steps(_bus_leg_steps(bus, job, traffic_world, ways, None, None, None, None, None), 1e9)

    assert leg(30.0, -2.0) is not None  # from the west, the stop on its right
    assert leg(330.0, 2.0) is None  # from the east: refused


def test_a_line_bus_starts_only_beside_its_own_stops():
    a, b = _stop(0, 0, ("4", 0, "4")), _stop(400, 0, ("4", 1, "4"))
    found = bus_lines.lines([a, b])
    assert bus_lines.start_job(found, 200, 300) is None  # a side street off the route: an ordinary car instead
    assert bus_lines.start_job(found, 30, 20).target_stop is a


def test_a_route_relation_marks_the_streets_it_runs_on():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.0},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
        {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "residential"}},
        {"type": "relation", "id": 400, "tags": {"type": "route", "route": "bus", "ref": "4"}, "members": [
            {"type": "way", "ref": 10, "role": ""},
            {"type": "way", "ref": 11, "role": "platform"},  # a platform way, not the street driven
        ]},
    ]
    ways = {way.osm_id: way for way in build_ways(elements).ways}
    assert ways[10].bus_routes == ["400"] and ways[11].bus_routes == []


def test_a_line_bus_keeps_to_its_route_streets_not_the_shortcut():
    from theroadragetrip.osm import Way
    from theroadragetrip.traffic_world import TrafficWorld, run_route_steps
    shortcut = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=3.0)  # Tervakukkatie
    route = Way(points_m=[(0.0, 0.0), (0.0, 50.0), (100.0, 50.0), (100.0, 0.0)], highway="residential",
                half_width_m=3.0, bus_routes=["4"])
    world = TrafficWorld([shortcut, route])
    car = run_route_steps(world.plan_route_steps((0.0, 0.0), (100.0, 0.0)), float("inf"))
    bus = run_route_steps(world.plan_route_steps((0.0, 0.0), (100.0, 0.0), bus_route="4"), float("inf"))
    assert max(y for _, y in car) < 1.0  # an ordinary car takes the shortcut
    assert max(y for _, y in bus) > 49.0  # line 4 drives its route
