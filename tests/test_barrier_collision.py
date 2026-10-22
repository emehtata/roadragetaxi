from theroadragetrip.osm import Railing, Way
from theroadragetrip.osm.build import _split_at_openings
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager

FENCE = Railing(points_m=[(10.0, -20.0), (10.0, 20.0)], bbox=(10.0, -20.0, 10.0, 20.0))  # a yard fence across x = 10


def _drive_east(manager, railings, current_way=None, layer=0):
    car = Car(x=0.0, y=0.0, heading=0.0, speed=5.0, layer=layer)
    for step in range(1, 40):
        previous = (car.x, car.y)
        car.x += 0.5
        if manager.check_barrier_collision(car, railings, sim_time=step / 10, previous_position=previous,
                                           current_way=current_way):
            return car, True
    return car, False


def test_a_yard_fence_stops_the_taxi_with_one_penalty():
    manager = TaxiManager([])
    car, hit = _drive_east(manager, [FENCE])
    assert hit and car.speed == 0.0 and car.x + car.length_m / 2 < 10.0
    assert manager.total_score == -150
    _drive_east(manager, [FENCE])  # pushing on at once: the same impact, no second penalty
    assert manager.total_score == -150


def test_the_taxi_drives_through_a_gate():
    nodes = {1: (10.0, -20.0), 2: (10.0, 0.0), 3: (10.0, 20.0)}  # node 2: barrier=gate
    parts = _split_at_openings([1, 2, 3], {2}, nodes)
    railings = [Railing(points_m=part, bbox=(10.0, min(p[1] for p in part), 10.0, max(p[1] for p in part)))
                for part in parts]
    manager = TaxiManager([])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=5.0, width_m=1.2)  # narrower than the 3 m opening
    for _ in range(40):
        previous = (car.x, car.y)
        car.x += 0.5
        assert not manager.check_barrier_collision(car, railings, 1.0, previous)


def test_no_fence_blocks_a_road_or_another_layer():
    road = Way(points_m=[(-10.0, 0.0), (40.0, 0.0)], highway="residential", half_width_m=3.0)
    assert not _drive_east(TaxiManager([]), [FENCE], current_way=road)[1]  # mapped across the road: not a wall
    bridge_railing = Railing(points_m=FENCE.points_m, bbox=FENCE.bbox, layer=1)
    assert not _drive_east(TaxiManager([]), [bridge_railing])[1]  # the railing is on the bridge above


def test_gate_after_gate_and_gaps_split_cleanly():
    nodes = {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (20.0, 0.0), 4: (30.0, 0.0)}
    assert _split_at_openings([1, 2, 3, 4], {2, 3}, nodes) == [[(0.0, 0.0), (8.5, 0.0)], [(21.5, 0.0), (30.0, 0.0)]]
    assert _split_at_openings([1, 2, 9, 3, 4], set(), nodes) == [[(0.0, 0.0), (10.0, 0.0)], [(20.0, 0.0), (30.0, 0.0)]]
    assert _split_at_openings([2, 3], {2, 3}, nodes) == []
    for part in _split_at_openings([1, 2, 3, 4], {1, 2, 4}, nodes):
        assert None not in part


def test_hedges_break_with_physics_and_leave_a_reusable_local_gap():
    from shapely.geometry import MultiLineString, Point
    from theroadragetrip.physics import update_car_physics
    hedge = Railing(FENCE.points_m, bbox=FENCE.bbox, kind="hedge")
    manager = TaxiManager([])
    car = Car(x=0, y=0, heading=0, speed=5)
    hits = 0
    for step in range(180):
        previous = (car.x, car.y)
        update_car_physics(car, 1, 0, 0, 0, 1/30, ways=[], block_offroad=False)
        hits += manager.check_barrier_collision(car, [hedge], step/30, previous)
    assert car.x > 20 and car.speed > 0 and hits >= 1
    assert manager.total_score == -150
    key = manager.hedge_key(hedge)
    remains = MultiLineString(manager.broken_hedges[key])
    assert remains.distance(Point(10,0)) > car.width_m / 2 + .5
    assert remains.distance(Point(10,8)) == 0
    before = manager.broken_hedges.copy()
    # Streamed/recreated geometry keeps its existing gap.
    restored = Railing(list(hedge.points_m), bbox=hedge.bbox, kind="hedge")
    assert not _drive_east(manager, [restored])[1]
    assert manager.broken_hedges == before and manager.total_score == -150
    # The intact section farther along can still break.
    car.x, car.y, car.speed = 10, 8, 5
    assert manager.check_barrier_collision(car,[restored],10, (9,8))
    assert MultiLineString(manager.broken_hedges[key]).distance(Point(10,8)) > 1


def test_fast_hedge_crossing_is_swept_and_other_layers_do_not_break():
    hedge = Railing(FENCE.points_m,bbox=FENCE.bbox,kind="hedge")
    manager = TaxiManager([])
    car = Car(x=25,y=0,heading=0,speed=40)
    assert manager.check_barrier_collision(car,[hedge],1,(0,0))
    assert car.x == 25 and 0 < car.speed < 40
    assert manager.broken_hedges
    manager = TaxiManager([])
    car.layer = 1
    assert not manager.check_barrier_collision(car,[hedge],1,(0,0))
    assert not manager.broken_hedges


def test_hedge_damage_protocol_is_nearby_and_layer_identified():
    from types import SimpleNamespace
    from theroadragetrip.protocol import _broken_hedges
    manager = TaxiManager([])
    hedge = Railing(FENCE.points_m,bbox=FENCE.bbox,kind="hedge")
    car = Car(x=10,y=0,heading=0,speed=5)
    manager.check_barrier_collision(car,[hedge],1,(9,0))
    world = SimpleNamespace(taxi_mgr=manager,railings=[hedge])
    row, = _broken_hedges(world,10,0)
    assert row[0] == 0 and row[1] == [[10,-20],[10,20]] and len(row[2]) == 2
    assert _broken_hedges(world,10000,10000) == []


def test_entire_short_hedge_can_be_destroyed():
    hedge = Railing([(10,-.5),(10,.5)], bbox=(10,-.5,10,.5), kind="hedge")
    manager = TaxiManager([])
    car = Car(x=10,y=0,heading=0,speed=5)
    assert manager.check_barrier_collision(car,[hedge],1,(9,0))
    assert manager.broken_hedges[manager.hedge_key(hedge)] == []
    assert not manager.check_barrier_collision(car,[hedge],2,(9,0))
