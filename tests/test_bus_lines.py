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
    """The NPC system drives it (traffic rules and all): it stops on the road
    beside each stop in turn, never parks, and leaves at the terminus."""
    import math
    import random

    from theroadragetrip.npc import NPCState, NPCVehicleManager, spawn_npc
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.physics import is_point_on_road
    from theroadragetrip.traffic_world import TrafficWorld
    from tests.test_competitor_taxis import _city_block_grid

    random.seed(4)
    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    # On the right of the way the line goes (right-hand traffic): south of the eastbound road, east of the northbound one, ...
    stops = [_stop(150.0, -6.5, ("1", 0, "18")), _stop(306.5, 150.0, ("1", 1, "18")), _stop(210.0, 306.5, ("1", 2, "18"))]
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
        if job is not None and job.state == "stopped" and (not served or served[-1][0] is not job.stopped_at):
            served.append((job.stopped_at, (bus.x, bus.y)))
        if bus not in manager.vehicles or bus.state == NPCState.CRASHED:
            break
    assert bus.state != NPCState.CRASHED
    assert [stops.index(stop) for stop, _ in served] == [0, 1, 2], served  # the line in order
    assert bus not in manager.vehicles and bus.vehicle_id not in manager.drivers  # retired at the terminus (no viewport: unseen)
    for stop, (x, y) in served:
        assert math.hypot(x - stop.x, y - stop.y) < 12.0, (stop.x, stop.y, x, y)  # at the stop...
        assert is_point_on_road(x, y, ways=ways, car_roads_only=True)  # ...on the road, in its lane
