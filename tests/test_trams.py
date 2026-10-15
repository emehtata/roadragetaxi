"""Trams on their rails (docs/trams.md)."""
import math
import random

from theroadragetrip.osm.models import Railway
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager
from theroadragetrip.trains import build_rail_graph
from theroadragetrip.trams import STOP_DWELL_S, TRAM_SPEED_MPS, SAFETY_GAP_M, Tram, TramManager

LINE = Railway(points_m=[(0.0, 0.0), (2000.0, 0.0)], kind="tram", stops=[(800.0, 0.0, "Kauppatori")])


def _drive(manager, seconds, obstacles=(), view_centre=(1000.0, 0.0), view=None, dt=0.1):
    for _ in range(round(seconds / dt)):
        manager.update(dt, view_centre, view, obstacles)


def _tram_at(manager, x):
    """A tram on LINE with its front at x, heading +x."""
    nodes = sorted((n for n in manager.graph.nodes_near((x, 0.0), 2000.0) if abs(manager.graph.points[n][1]) < 0.01),
                   key=lambda n: manager.graph.points[n][0])
    tram = Tram(nodes=nodes, front_m=0.0, sections=manager.sections, profile=manager.profile, speed_mps=TRAM_SPEED_MPS)
    manager._measure(tram)
    tram.front_m = x - manager.graph.points[nodes[0]][0]
    manager.trams = [tram]
    manager._population_elapsed = -1e9  # (no population changes in these tests)
    return tram


def test_a_tram_stops_at_its_stop_waits_and_goes_on():
    manager = TramManager([LINE], "Helsinki", rng=random.Random(1))
    tram = _tram_at(manager, 500.0)
    for _ in range(600):  # until it stops
        _drive(manager, 0.1)
        if tram.state == "DWELLING":
            break
    front = manager._at(tram, tram.front_m)[0]
    assert tram.state == "DWELLING" and abs(front - 800.0) < 1.0  # at the stop, not past it
    _drive(manager, STOP_DWELL_S - 1.0)
    assert tram.state == "DWELLING"
    _drive(manager, 20.0)
    assert manager._at(tram, tram.front_m)[0] > 900.0 and tram.state == "RUNNING"


def test_a_tram_brakes_for_what_is_on_its_track_and_goes_when_it_is_clear():
    manager = TramManager([LINE], "Tampere", rng=random.Random(1))
    tram = _tram_at(manager, 100.0)
    taxi_on_the_rails = (300.0, 0.5)
    _drive(manager, 40.0, obstacles=[taxi_on_the_rails])
    front = manager._at(tram, tram.front_m)[0]
    assert tram.speed_mps == 0.0 and 300.0 - SAFETY_GAP_M - 2.0 <= front < 300.0  # stopped short of it
    beside = (500.0, 6.0)  # off the track: no reason to stop
    _drive(manager, 10.0, obstacles=[beside])
    assert tram.speed_mps > 5.0


def test_at_a_junction_a_tram_never_takes_a_corner_it_cannot():
    branch = Railway(points_m=[(1000.0, 0.0), (1000.0, -500.0)], kind="tram")  # a right angle off the line
    fork = Railway(points_m=[(1000.0, 0.0), (1400.0, 150.0)], kind="tram")  # ~20 degrees off it
    manager = TramManager([LINE, branch, fork], "Helsinki", rng=random.Random(3))
    went = set()
    for _ in range(40):
        tram = _tram_at(manager, 950.0)
        manager._extend(tram)
        went.add(round(manager.graph.points[tram.nodes[tram.nodes.index(manager.graph.node_at((1000.0, 0.0))) + 1]][1]))
    assert went <= {0, 19} and 0 in went  # straight on mostly, the gentle fork sometimes, never the right angle


def test_trams_come_and_go_with_the_viewpoint_out_of_sight():
    manager = TramManager([Railway(points_m=[(0.0, 0.0), (6000.0, 0.0)], kind="tram")], "Helsinki", rng=random.Random(2))
    view = (2900.0, -100.0, 3100.0, 100.0)  # mid-line: no track end within 30 s of a spawn
    _drive(manager, 30.0, view_centre=(3000.0, 0.0), view=view)
    assert manager.trams
    for tram in manager.trams:  # spawned out of sight
        assert tram.tram_id and math.dist(manager._at(tram, tram.front_m)[:2], (3000.0, 0.0)) < 1300.0
    _drive(manager, 3.0, view_centre=(5800.0, 5000.0), view=(5700.0, 4900.0, 5900.0, 5100.0))
    assert not manager.trams  # the viewpoint went far: they went


def test_no_trams_without_tram_track():
    manager = TramManager([Railway(points_m=[(0.0, 0.0), (2000.0, 0.0)], kind="rail")], "Oulu")
    _drive(manager, 10.0)
    assert not manager.has_track and not manager.trams


def test_driving_into_a_tram_is_a_crash_and_a_taxi_it_hit_can_drive_out():
    manager = TramManager([LINE], "Helsinki")
    tram = _tram_at(manager, 500.0)
    taxi = TaxiManager([])
    car = Car(x=488.0, y=6.0, heading=-math.pi / 2, speed=8.0)  # into its side, crossing it
    before = (488.0, 6.0)
    car.y = 1.5
    assert taxi.check_tram_collision(car, manager, 10.0, previous_position=before)
    assert (car.x, car.y, car.speed) == (488.0, 6.0, 0.0) and taxi.total_score < 0
    stuck = Car(x=490.0, y=0.0, heading=math.pi / 2, speed=2.0)  # the tram came into it
    assert taxi.check_tram_collision(stuck, manager, 20.0, previous_position=(490.0, -0.2))
    assert (stuck.x, stuck.y) == (490.0, 0.0)  # not pinned: free to drive out


def test_tram_stops_are_read_from_osm_and_trains_keep_off_tram_track():
    from theroadragetrip.osm.build import build_ways

    nodes = [{"type": "node", "id": 1, "lat": 60.17, "lon": 24.94},
             {"type": "node", "id": 2, "lat": 60.17, "lon": 24.945, "tags": {"railway": "tram_stop", "name": "Senaatintori"}},
             {"type": "node", "id": 3, "lat": 60.17, "lon": 24.95}]
    line = {"type": "way", "id": 9, "nodes": [1, 2, 3], "tags": {"railway": "tram"}}
    (railway,) = build_ways(nodes + [line]).railways
    assert railway.kind == "tram" and [name for _, _, name in railway.stops] == ["Senaatintori"]
    assert not build_rail_graph([railway]).edges and build_rail_graph([railway], kind="tram").edges


def test_a_tram_stop_beside_the_track_is_its_stop():
    from theroadragetrip.osm.build import build_ways

    nodes = [{"type": "node", "id": 1, "lat": 60.17, "lon": 24.94}, {"type": "node", "id": 3, "lat": 60.17, "lon": 24.95},
             {"type": "node", "id": 2, "lat": 60.17006, "lon": 24.945, "tags": {"railway": "tram_stop", "name": "Ritarihuone"}},
             {"type": "node", "id": 4, "lat": 60.22, "lon": 24.945, "tags": {"railway": "tram_stop", "name": "Far away"}}]
    line = {"type": "way", "id": 9, "nodes": [1, 3], "tags": {"railway": "tram"}}
    (railway,) = build_ways(nodes + [line]).railways
    assert [name for _, _, name in railway.stops] == ["Ritarihuone"]  # ~7 m beside it; not the one ~5.5 km off
    manager = TramManager([railway], "Helsinki")
    assert list(manager.stop_nodes.values()) == ["Ritarihuone"]


def test_trams_keep_right_on_a_double_line():
    eastbound = Railway(points_m=[(0.0, 0.0), (3000.0, 0.0)], kind="tram")
    westbound = Railway(points_m=[(0.0, 3.5), (3000.0, 3.5)], kind="tram")  # 3.5 m to the north: the left, going east
    manager = TramManager([eastbound, westbound], "Helsinki", rng=random.Random(5))
    seen = 0
    for _ in range(20):
        manager.trams = []
        tram = manager._spawn((1500.0, 0.0), None)
        if tram is None:
            continue
        seen += 1
        (ax, ay), (bx, by) = manager.graph.points[tram.nodes[-2]], manager.graph.points[tram.nodes[-1]]
        assert (by < 1.0) == (bx > ax)  # on y=0 it heads east, on y=3.5 west: the right-hand track
    assert seen >= 10
