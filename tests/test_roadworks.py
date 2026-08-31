import random

from theroadragetrip.osm import TrafficLight, Way
from theroadragetrip.roadworks import Roadwork, _point_at, _way_length, create_roadworks


def make_way(length=120.0, drivable=True):
    return Way(
        osm_id=1,
        points_m=[(0.0, 0.0), (length, 0.0)],
        highway="primary",
        is_drivable=drivable,
        half_width_m=4.0,
    )


def test_roadwork_helpers_and_contains():
    way = make_way()
    work = Roadwork(way, 20.0, 70.0, True, (20.0, 0.0), (70.0, 0.0))

    assert _way_length(way) == 120.0
    assert _point_at(way, 30.0) == (30.0, 0.0)
    assert _point_at(way, 999.0) == (120.0, 0.0)
    assert work.contains(45.0, 3.0)
    assert work.contains(15.0, 0.0, margin_m=6.0)
    assert not work.contains(45.0, 5.0)


def test_roadwork_contains_degenerate_segment():
    way = make_way()
    work = Roadwork(way, 0.0, 0.0, False, (1.0, 1.0), (1.0, 1.0))

    assert not work.contains(1.0, 1.0)


def test_create_roadworks_adds_lights_for_closed_lane(monkeypatch):
    way = make_way()
    values = iter([0.5])
    monkeypatch.setattr(random, "shuffle", lambda items: None)
    monkeypatch.setattr(random, "uniform", lambda low, high: low)
    monkeypatch.setattr(random, "random", lambda: next(values))

    roadworks, lights = create_roadworks([way], count=1)

    assert len(roadworks) == 1
    assert roadworks[0].lane_closed
    assert len(lights) == 2
    assert all(isinstance(light, TrafficLight) for light in lights)


def test_create_roadworks_skips_short_and_non_drivable_ways():
    short_way = make_way(89.0)
    blocked_way = make_way(120.0, drivable=False)

    roadworks, lights = create_roadworks([short_way, blocked_way], count=2)

    assert roadworks == []
    assert lights == []