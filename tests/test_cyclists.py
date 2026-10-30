"""Cyclists as NPC traffic (rrt-019-cyclists; docs/finnish-npc-traffic-law.md)."""
import math

from theroadragetrip.cycling import cycle_cost_factor, is_cyclable_way, route_legs
from theroadragetrip.osm import Way
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps


def _way(points, highway, **kw):
    return Way(points_m=points, highway=highway, half_width_m=kw.pop("half_width_m", 3.0 if highway != "cycleway" else 1.5), **kw)


def _route(world, start, target):
    points = run_route_steps(world.plan_cycle_route_steps(start, target))
    return None if points is None else route_legs(world.cycle_graph, points)


def test_cyclable_ways_follow_access_tags():
    assert is_cyclable_way(_way([(0, 0), (10, 0)], "cycleway"))
    assert is_cyclable_way(_way([(0, 0), (10, 0)], "residential"))
    assert is_cyclable_way(_way([(0, 0), (10, 0)], "footway", bicycle="designated"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "footway"))  # no bicycle tag: pedestrians only
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "motorway"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "trunk", motorroad=True))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "primary", bicycle="no"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "primary", bicycle="use_sidepath"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "steps", bicycle="yes"))
    assert cycle_cost_factor(_way([(0, 0), (1, 0)], "cycleway")) < cycle_cost_factor(_way([(0, 0), (1, 0)], "primary"))


def test_cycle_route_honours_oneway_and_contraflow():
    oneway = _way([(0, 0), (100, 0)], "residential", oneway=1)
    world = TrafficWorld([oneway])
    assert _route(world, (0, 0), (100, 0)) is not None
    assert _route(world, (100, 0), (0, 0)) is None  # against a one-way street
    contraflow = _way([(0, 0), (100, 0)], "residential", oneway=1, oneway_bicycle=0)
    world = TrafficWorld([contraflow])
    assert _route(world, (100, 0), (0, 0)) is not None  # oneway:bicycle=no


def test_cycle_route_prefers_cycle_path_and_never_cuts_across_open_ground():
    # A busy road straight across, a cycle path detour of 1.4x its length.
    road = _way([(0, 0), (200, 0)], "primary")
    path = _way([(0, 0), (0, 40), (100, 60), (200, 40), (200, 0)], "cycleway")
    world = TrafficWorld([road, path])
    points, ways = _route(world, (0, 0), (200, 0))
    assert all(way is path for way in ways)
    # A pedestrian-only footway is no link: the far cycleway is unreachable.
    far = _way([(300, 0), (400, 0)], "cycleway")
    footway = _way([(200, 0), (300, 0)], "footway")
    world = TrafficWorld([road, footway, far])
    assert _route(world, (0, 0), (400, 0)) is None


# --- lifecycle and behaviour through the real NPC update loop -------------

from types import SimpleNamespace

from theroadragetrip import cycling
from theroadragetrip.npc import NPCState, NPCVehicleManager
from theroadragetrip.osm import TrafficLight
from theroadragetrip.physics import Car, SpatialWayGrid
from theroadragetrip.residents import ResidentManager

DT = 1 / 30


class _World:
    def __init__(self, ways, lights=()):
        self.ways = ways
        self.traffic = TrafficWorld(ways, traffic_lights=list(lights))
        self.grid = SpatialWayGrid(ways)
        self.residents = ResidentManager()
        self.manager = NPCVehicleManager(target_count=0, min_count=0, max_count=0)
        self.manager._population_elapsed = -1e9  # no population ticks: the test places traffic itself
        self.traffic.npcs = self.manager.vehicles

    def cyclist(self, start, destination, cruise=5.0):
        route = run_route_steps(cycling.cycle_trip_steps(
            self.traffic.cycle_graph, start, self.grid, 0.6, destination=destination))
        assert route is not None
        route.cruise_mps = cruise
        job = {"kind": "cycle", "vehicle": None}
        self.manager._finish_cycle_job(job, route, 1e6, 1e6, None, self.residents)
        vehicle = self.manager.vehicles[-1]
        vehicle.car.speed = 0.0
        return vehicle

    def tick(self, seconds, player=None, pedestrians=(), until=None):
        peds = None if not pedestrians else SimpleNamespace(pedestrians=list(pedestrians))
        for _ in range(int(seconds / DT)):
            self.manager.update(DT, 50.0, 0.0, self.residents, self.traffic, self.ways, spatial_grid=self.grid,
                                player_car=player, pedestrian_mgr=peds)
            self.traffic.advance_time(DT)
            if until is not None and until():
                return True
        return False


def _distance_to_ways(x, y, ways):
    from theroadragetrip.geo import dist_point_to_segment
    return min(dist_point_to_segment(x, y, *a, *b) for way in ways for a, b in zip(way.points_m, way.points_m[1:]))


def test_cyclist_lifecycle_ride_arrive_and_retire_keeps_the_resident():
    path = _way([(0, 0), (150, 0)], "cycleway")
    world = _World([path])
    bike = world.cyclist((0, 0), (150, 0))
    driver = world.manager.drivers[bike.vehicle_id]
    rider = world.residents.get(driver.resident_id)
    assert bike.vehicle_type == "bicycle" and bike.owner_id == rider.resident_id
    assert world.tick(60, until=lambda: bike.state == NPCState.PARKED)
    assert abs(bike.x - 150) < 2.5 and bike.speed == 0.0
    world.manager._top_up_cyclists(1e6, 1e6, world.traffic, world.residents, world.grid, None, lambda v: True)
    assert bike not in world.manager.vehicles and bike.vehicle_id not in world.manager.drivers
    assert world.residents.get(rider.resident_id) is not None and rider.active_vehicle_id is None


def test_cyclist_follows_infrastructure_across_a_transition_without_shortcuts():
    # Cycle path, then a residential street (the transition), then a cycle path again.
    ways = [_way([(0, 0), (60, 0)], "cycleway"),
            _way([(60, 0), (60, 80)], "residential", half_width_m=4.0),
            _way([(60, 80), (140, 80)], "cycleway")]
    world = _World(ways)
    bike = world.cyclist((0, 0), (140, 80))
    worst = 0.0
    for _ in range(int(60 / DT)):
        world.tick(DT)
        worst = max(worst, _distance_to_ways(bike.x, bike.y, ways))
        if bike.state == NPCState.PARKED:
            break
    assert bike.state == NPCState.PARKED
    assert worst < 4.5  # on the mapped ways (a carriageway's right edge included), never cutting the corner


def test_cyclist_stops_at_red_and_goes_on_green():
    """§ 74 / annex 2: red keeps a cyclist on the carriageway behind the signal."""
    road = _way([(40, 0), (200, 0)], "residential")
    light = TrafficLight(x=60.0, y=-2.0, cycle_time=16.0, offset=-7.0, direction_angle=0.0)  # red at t=0..7.5
    world = _World([road], [light])
    bike = world.cyclist((40, 0), (200, 0), cruise=6.0)
    light.offset = -9.0  # red now, green at about t = 9 s: the cyclist arrives during red
    stopped = False
    while light.get_state(world.traffic.sim_time) in ("red", "red+yellow"):
        world.tick(DT)
        assert bike.x < 60.0 - 1.0  # red+yellow prepares for green; it is no permission to go
        stopped = stopped or bike.speed < 0.05
    assert stopped
    assert world.tick(10.0, until=lambda: bike.x > 70.0)


def _crossing_world():
    # A cycle path crossing a two-way street at x = 50.
    path = _way([(50, -20), (50, 40)], "cycleway")
    road = _way([(0, 0), (200, 0)], "secondary", half_width_m=4.0)
    return _World([path, road]), road


def test_cyclist_from_a_cycle_path_yields_to_carriageway_traffic():
    """§ 24(3): entry from a path - the cyclist yields to traffic on the road, from either side."""
    world, road = _crossing_world()
    bike = world.cyclist((50, -20), (50, 40))
    car = Car(x=-20.0, y=-1.8, heading=0.0, speed=10.0)  # reaches the crossing as the cyclist does
    waited = False
    for _ in range(int(18 / DT)):
        car.x += car.speed * DT
        world.tick(DT, player=car)
        if abs(bike.y) < 6.0 and bike.speed < 0.3 and car.x < 50:
            waited = True
        assert not (abs(bike.y) < 4.0 and abs(car.x - 50) < 3.0), "cyclist rode into the car's path"
    assert waited and bike.y > 10.0


def test_cyclist_crosses_without_stopping_when_the_road_is_clear():
    world, _ = _crossing_world()
    bike = world.cyclist((50, -20), (50, 40))
    min_speed = 99.0
    world.tick(2.0)
    for _ in range(int(15 / DT)):
        world.tick(DT)
        if -3 < bike.y < 3:
            min_speed = min(min_speed, bike.speed)
    assert bike.y > 10.0 and min_speed > 1.0


def test_car_right_hand_rule_ignores_a_cyclist_still_on_a_cycle_path():
    from theroadragetrip.traffic_rules import crossing_yield_decision
    road = _way([(0, 0), (100, 0)], "residential")
    car = SimpleNamespace(x=30.0, y=0.0, heading=0.0, speed=8.0, length_m=4.3, way=road)
    on_path = SimpleNamespace(x=50.0, y=-15.0, heading=math.pi / 2, speed=5.0, length_m=1.8,
                              way=_way([(50, -40), (50, 40)], "cycleway"), state="CRUISING")
    on_road = SimpleNamespace(**{**vars(on_path), "way": _way([(50, -40), (50, 40)], "residential")})
    assert crossing_yield_decision(car, [on_path]) is None  # § 24(3): the path user yields
    assert crossing_yield_decision(car, [on_road]) is not None  # § 24(1): a vehicle from the right


def test_turning_car_yields_to_a_cyclist_crossing_its_exit():
    """§ 24(2): turning into a street, give way to the cyclist crossing it."""
    car = SimpleNamespace(x=0.0, y=0.0, heading=0.0, speed=6.0, length_m=4.3)
    crossing = SimpleNamespace(x=5.0, y=-6.0, heading=0.0, speed=5.0, vehicle_type="bicycle", state="CRUISING")
    # Car turns right at (15, 0) into a street heading south (-pi/2); the cyclist rides east across it.
    assert cycling.turning_yield_to_cyclists(car, (15.0, -3.0), -math.pi / 2, 15.0, [crossing]) is not None
    along_exit = SimpleNamespace(**{**vars(crossing), "x": 15.0, "y": -12.0, "heading": -math.pi / 2})
    assert cycling.turning_yield_to_cyclists(car, (15.0, -3.0), -math.pi / 2, 15.0, [along_exit]) is None
    committed = cycling.turning_yield_to_cyclists(car, (15.0, -3.0), -math.pi / 2, 1.0, [crossing])
    assert committed is None  # already in the turn: clear the junction


def test_cyclist_slows_for_and_never_rides_into_a_pedestrian_on_a_shared_path():
    """§§ 3-5: care for pedestrians - priority never authorizes a collision."""
    path = _way([(0, 0), (120, 0)], "footway", bicycle="designated", half_width_m=1.5)
    world = _World([path])
    bike = world.cyclist((0, 0), (120, 0))
    walker = SimpleNamespace(x=40.0, y=-0.4, radius_m=0.3, state="walking")  # in the bike's line
    closest = 99.0
    for _ in range(int(20 / DT)):
        world.tick(DT, pedestrians=[walker])
        closest = min(closest, math.hypot(bike.x - walker.x, bike.y - walker.y))
    assert closest > 1.2 and bike.x < walker.x
    walker.y = 1.4  # steps aside: the cyclist passes slowly
    assert world.tick(30, pedestrians=[walker], until=lambda: bike.x > walker.x + 3)


def test_two_cyclists_keep_their_distance_and_meet_oncoming_on_the_right():
    path = _way([(0, 0), (200, 0)], "cycleway", half_width_m=1.5)
    world = _World([path])
    lead = world.cyclist((0, 0), (200, 0), cruise=4.0)
    world.tick(8.0)
    rear = world.cyclist((0, 0), (200, 0), cruise=6.5)
    oncoming = world.cyclist((200, 0), (0, 0), cruise=5.0)
    for _ in range(int(30 / DT)):
        world.tick(DT)
        if lead.state != NPCState.CRASHED:
            assert lead.x - rear.x > 1.8 or lead.state == NPCState.PARKED
    for bike in (lead, rear, oncoming):
        assert bike.state != NPCState.CRASHED
    assert rear.y < 0 < oncoming.y or oncoming.state == NPCState.PARKED  # each keeps to its right half


def test_blocked_cyclist_neither_spins_nor_waits_forever():
    path = _way([(0, 0), (100, 0)], "cycleway")
    world = _World([path])
    bike = world.cyclist((0, 0), (100, 0))
    wreck = Car(x=40.0, y=-0.4, heading=0.0, speed=0.0)
    wreck.state = "CRASHED"
    gone = world.tick(60, player=wreck, until=lambda: bike not in world.manager.vehicles)
    assert gone  # out of view: jam cleanup after the stuck timeout
    assert bike.x < 40.0


def test_cyclists_do_not_take_car_population_targets():
    path = _way([(0, 0), (150, 0)], "cycleway")
    world = _World([path])
    world.cyclist((0, 0), (150, 0))
    manager = world.manager
    assert manager._pedestrian_lookup(None, manager.vehicles)(0, 0) == ()
    from theroadragetrip.vehicles.base import vehicle_definition
    assert vehicle_definition("bicycle").movement == "cycle"
    assert "bicycle" not in [vehicle_id for vehicle_id in manager.vehicle_distribution
                             if vehicle_definition(vehicle_id).movement == "road" and manager.vehicle_distribution[vehicle_id] > 0]


def test_car_behind_a_cyclist_follows_without_hitting_it():
    """§ 20 following distance: a car meeting a slower cyclist on its street keeps behind it."""
    from theroadragetrip.npc import spawn_npc
    road = [_way([(i * 50.0, 0.0), ((i + 1) * 50.0, 0.0)], "residential", half_width_m=4.5) for i in range(8)]
    world = _World(road)
    bike = world.cyclist((100.0, 0.0), (400.0, 0.0), cruise=4.0)
    world.tick(2.0)
    _resident, driver, car = spawn_npc(99, world.residents, world.traffic, road, (0.0, 0.0), (400.0, 0.0))
    world.manager.vehicles.append(car)
    world.manager.drivers[car.vehicle_id] = driver
    closest = 99.0
    for _ in range(int(40 / DT)):
        world.tick(DT)
        if bike.state == NPCState.PARKED:
            break
        closest = min(closest, bike.x - car.x)
    assert car.state != NPCState.CRASHED and bike.state != NPCState.CRASHED
    assert (car.length_m + bike.length_m) / 2 < closest < 15.0  # it did catch up, and stayed behind


class _Lowest:
    """An rng whose every draw is the low end of its range: a trip from the
    west end of the path below ends 180 m east of it, near the player."""
    def uniform(self, low, high):
        return low


def test_cyclists_park_in_a_free_rack_hoop_near_their_destination():
    from theroadragetrip.osm.models import SceneryObject
    world = _World([_way([(0, 0), (250, 0)], "cycleway")])
    rack = SceneryObject(x=170.0, y=3.0, kind="bicycle_parking", direction_angle=0.0)
    world.manager.scenery_objects = [rack]
    bikes = []
    for _ in range(2):
        route = run_route_steps(cycling.cycle_trip_steps(
            world.traffic.cycle_graph, (0, 0), world.grid, 0.6, rng=_Lowest(), racks=world.manager.bicycle_racks()))
        assert route is not None and route.rack is rack
        world.manager._finish_cycle_job({"kind": "cycle", "vehicle": None}, route, 1e6, 1e6, None, world.residents)
        bikes.append(world.manager.vehicles[-1])
        assert world.tick(120, until=lambda: bikes[-1].state == NPCState.PARKED)  # then the next one sets off
    slots = cycling.rack_slots(rack)
    parked = [next(s for s in slots if math.hypot(b.x - s[0], b.y - s[1]) < 1e-6) for b in bikes]
    assert parked[0] != parked[1]  # one bike per hoop
    assert all(abs(math.sin(b.car.heading)) > 0.99 for b in bikes)  # across the row


def _rack_trip(ways, rack, manager_racks=None):
    world = _World(ways)
    world.manager.scenery_objects = [rack]
    route = run_route_steps(cycling.cycle_trip_steps(
        world.traffic.cycle_graph, (0, 0), world.grid, 0.6, rng=_Lowest(), racks=world.manager.bicycle_racks()))
    return world, route


def test_a_rack_across_a_road_or_under_a_bridge_is_not_used():
    from theroadragetrip.osm.models import SceneryObject
    rack = SceneryObject(x=170.0, y=5.0, kind="bicycle_parking", direction_angle=0.0, id=7)
    road = _way([(100, 2.5), (250, 2.5)], "residential")  # between the cycleway and the rack
    _, route = _rack_trip([_way([(0, 0), (250, 0)], "cycleway"), road], rack)
    assert route is not None and route.rack is None  # walking the bike across the carriageway: no
    _, route = _rack_trip([_way([(0, 0), (250, 0)], "cycleway", layer=1)], rack)
    assert route is not None and route.rack is None  # from a bridge down to a rack under it: no


def test_a_full_rack_leaves_the_bike_where_the_ride_ended():
    from theroadragetrip.osm.models import SceneryObject
    rack = SceneryObject(x=170.0, y=3.0, kind="bicycle_parking", direction_angle=0.0, id=7)
    world, route = _rack_trip([_way([(0, 0), (250, 0)], "cycleway")], rack)
    for index in range(len(cycling.RACK_HOOPS_M)):  # every hoop already has a bike
        world.manager.drivers[-1 - index] = SimpleNamespace(rack_claim=(7, index), rack_slot=None)
    world.manager._finish_cycle_job({"kind": "cycle", "vehicle": None}, route, 1e6, 1e6, None, world.residents)
    bike = world.manager.vehicles[-1]
    assert world.tick(120, until=lambda: bike.state == NPCState.PARKED)
    assert abs(bike.y - route.points[-1][1]) < 0.5  # on its riding line, not in a hoop


class _Thieves:
    """The pedestrian manager surface a bike theft uses: spawned walkers stand where asked."""
    def __init__(self):
        self.pedestrians = []

    def spawn_pedestrian_at(self, x, y, heading=0.0, resident_id=None):
        return SimpleNamespace(x=x, y=y, speed=1.3, base_speed=1.3, route=None, thief_target=None, state="walking")

    def add_pedestrian(self, pedestrian):
        self.pedestrians.append(pedestrian)
        return True


class _Always(_Lowest):
    def random(self):
        return 0.0

    def choice(self, items):
        return items[0]


def test_a_bike_thief_runs_to_a_racked_bike_and_rides_it_away_fast():
    from theroadragetrip.osm.models import SceneryObject
    rack = SceneryObject(x=170.0, y=3.0, kind="bicycle_parking", direction_angle=0.0, id=7)
    world, route = _rack_trip([_way([(-600, 0), (600, 0)], "cycleway")], rack)
    world.manager._finish_cycle_job({"kind": "cycle", "vehicle": None}, route, 1e6, 1e6, None, world.residents)
    bike = world.manager.vehicles[-1]
    assert world.tick(120, until=lambda: bike.state == NPCState.PARKED)
    view = (100.0, -50.0, 250.0, 50.0)
    peds = _Thieves()
    manager = world.manager
    manager._update_bike_thefts(DT, peds, view, world.traffic, world.grid, rng=_Always())
    thief = peds.pedestrians[0]
    assert thief.thief_target == (bike.x, bike.y) and thief.base_speed == cycling.THIEF_RUN_MPS  # running for it
    assert 20.0 <= math.hypot(thief.x - bike.x, thief.y - bike.y) <= 35.0
    thief.x, thief.y = bike.x, bike.y + 1.0  # (the pedestrian manager runs it there)
    manager._update_bike_thefts(DT, peds, view, world.traffic, world.grid, rng=__import__("random").Random(1))
    assert thief.state == "despawning" and bike.state == NPCState.CRUISING
    driver = manager.drivers[bike.vehicle_id]
    assert driver.stolen and driver.rack_claim is None  # the hoop is free again
    world.tick(10)
    assert driver.cycle.cruise_mps >= cycling.CYCLIST_SPEED_MPS[0] * cycling.THIEF_CRUISE_FACTOR - 1e-6
    assert math.hypot(bike.x - 170.0, bike.y - 3.0) > 20.0  # gone


def test_thieves_and_stolen_bikes_stay_anonymous_in_the_protocol():
    from theroadragetrip import protocol
    from theroadragetrip.pedestrian import Pedestrian
    thief = Pedestrian(x=0.0, y=0.0, heading=0.0, speed=4.5, base_speed=4.5, way=None, segment_idx=0, direction=1,
                       color=(1, 2, 3), resident_id=5)
    residents = {5: SimpleNamespace()}
    thief.thief_target = (10.0, 0.0)
    row = protocol._pedestrian_to_dict(thief, residents)
    assert row["thief"] and row["resident"] is None  # no personality to reveal, and the client skips it
    thief.thief_target = None
    assert not protocol._pedestrian_to_dict(thief, {})["thief"]

    world = _World([_way([(0, 0), (150, 0)], "cycleway")])
    bike = world.cyclist((0, 0), (150, 0))
    bike.stolen = True
    row = protocol._npc_to_dict(bike, world.residents.residents if hasattr(world.residents, "residents") else {})
    assert row["thief"] and row["owner"] is None and row["occupants"] == []


def test_a_held_up_cyclist_rings_the_bell_now_and_then():
    """A walker in the way: the rider rings (sound only), at most every BELL_COOLDOWN_S."""
    path = _way([(0, 0), (120, 0)], "footway", bicycle="designated", half_width_m=1.5)
    world = _World([path])
    world.cyclist((0, 0), (120, 0))
    walker = SimpleNamespace(x=40.0, y=-0.4, radius_m=0.3, state="walking")
    world.tick(20, pedestrians=[walker])
    assert 1 <= len(world.manager.bicycle_bells) <= 20 / cycling.BELL_COOLDOWN_S + 1
    clear = _World([path])
    clear.cyclist((0, 0), (120, 0))
    clear.tick(10)
    assert clear.manager.bicycle_bells == []  # nobody in the way: no bell


def test_a_cyclist_rides_around_a_car_parked_at_the_kerb():
    """A car parked on the right edge of a residential street, angled a little: the rider swings out past it."""
    road = _way([(0, 0), (120, 0)], "residential", half_width_m=4.0)
    world = _World([road])
    bike = world.cyclist((0, 0), (120, 0))
    parked = Car(x=40.0, y=-2.6, heading=0.4, speed=0.0)
    parked.state = "PARKED"
    closest = 99.0
    for _ in range(int(40 / DT)):
        world.tick(DT, player=parked)
        closest = min(closest, abs(bike.x - parked.x) + abs(bike.y - parked.y))
        if bike.x > 50.0:
            break
        assert bike.shaken_timer == 0.0  # never touched it (a touch shakes the rider)
    assert bike.x > 50.0 and NPCState.CRASHED != bike.state  # past it, not into it


def test_cyclists_meeting_on_a_narrow_path_pass_each_other():
    """A 1.5 m path: each keeps further right while they meet - they used to collide head-on."""
    path = _way([(0, 0), (120, 0)], "path", bicycle="designated", half_width_m=0.75)
    world = _World([path])
    east = world.cyclist((0, 0), (120, 0))
    west = world.cyclist((120, 0), (0, 0))
    assert world.tick(40, until=lambda: east.x > 80 and west.x < 40)
    assert NPCState.CRASHED not in (east.state, west.state)


def test_a_cyclist_past_a_hairpin_rides_on_instead_of_circling():
    """Reported: a cyclist circling on the spot, through a building. Recorded in
    Oulu: a 2.2 m leg, then the route turning back ~160 degrees (a service road
    onto a cycle path). Steering a few metres ahead it turned early, inside the
    corner; its projection on the short leg never reached the leg's end, so the
    leg never advanced and it circled the fixed aim point at riding speed."""
    from theroadragetrip.cycling import CycleRoute
    points = [(6.4, 8.1), (0.4, -1.1), (1.7, -2.9), (-15.4, 8.9), (-27.9, 17.6), (-38.0, 23.8)]
    ways = [_way([points[0], points[1], points[2]], "service"), _way(points[2:], "cycleway")]
    world = _World(ways + [_way([(0, 200), (150, 200)], "cycleway")])
    bike = world.cyclist((0, 200), (150, 200))  # a ride to set it up; its route is replaced by the recorded one
    driver = world.manager.drivers[bike.vehicle_id]
    driver.cycle = CycleRoute(points, [ways[0], ways[0], ways[1], ways[1], ways[1]], [], 4.5)
    driver.path_index = 1
    bike.car.x, bike.car.y = points[0]
    bike.car.heading = math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
    bike.car.speed = 4.0
    for _ in range(int(30 / DT)):
        world.tick(DT)
        if math.dist((bike.x, bike.y), points[4]) < 3.0:
            break
    assert math.dist((bike.x, bike.y), points[4]) < 3.0  # past the hairpin and on along the cycle path
