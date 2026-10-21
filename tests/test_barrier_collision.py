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
