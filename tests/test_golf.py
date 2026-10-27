"""Golf map loading and the real pedestrian activity update loop."""
import math
import random

import pytest

from theroadragetrip import protocol
from theroadragetrip.activities.base import ActivityInstance
from theroadragetrip.activities import ActivityManager, ActivityRegistry
from theroadragetrip.activities.plugins.golf import GolfPlugin
from theroadragetrip.osm import Scenery, build_ways
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter
from test_activities import _context, _make_manager_and_pedestrian


def golf_map():
    coords = [(0, 0), (0, .002), (.002, .002), (.002, 0),
              (.0002, .0002), (.0005, .0008), (.0015, .0015)]
    nodes = [dict(type="node", id=i, lat=lat, lon=lon)
             for i, (lat, lon) in enumerate(coords, 1)]
    return nodes + [
        dict(type="way", id=10, nodes=[1, 2, 3, 4, 1], tags={"leisure": "golf_course"}),
        dict(type="way", id=11, nodes=[5, 6, 7], tags={"golf": "hole", "ref": "1"}),
        dict(type="way", id=12, nodes=[5, 7], tags={"golf": "hole", "layer": "1"}),
        dict(type="way", id=13, nodes=[5, 99, 7], tags={"golf": "hole"}),
    ]


def test_hole_line_is_server_metadata_and_survives_cache(tmp_path):
    world = build_ways(golf_map())
    course, = world.sceneries
    assert course.kind == "golf_course"
    assert len(course.golf_holes) == 1
    assert len(course.golf_holes[0]) == 3
    assert not world.ways  # a golf line is neither a road nor a footpath
    path = tmp_path / "golf.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="golf")
    cached = BinaryWorldCacheLoader().load(path)
    assert cached.sceneries[0].golf_holes == course.golf_holes


def local_course():
    return Scenery(
        points_m=[(0, -10), (100, -10), (100, 100), (0, 100)],
        kind="golf_course", bbox=(0, -10, 100, 100),
        golf_holes=[[(10, 0), (80, 0), (80, 80)]],
    )


def playing_golf(sceneries=None):
    course = (sceneries or [local_course()])[0]
    manager, pedestrian = _make_manager_and_pedestrian(sceneries=sceneries or [course])
    manager.soccer_open = True
    pedestrian.x, pedestrian.y = course.golf_holes[0][0]
    registry = ActivityRegistry()
    registry.register(GolfPlugin())
    manager.activity_manager = ActivityManager(registry)
    plugin, location = manager.activity_manager.select_activity(_context(manager, pedestrian))
    assert manager.activity_manager._reservations[location.reservation_key] == id(pedestrian)
    pedestrian.activity = ActivityInstance("golf", location, 0.0)
    pedestrian.state = "walking_to_activity"
    for _ in range(1000):
        manager._update_activity(pedestrian, .1)
        if pedestrian.state == "performing_activity":
            break
    assert pedestrian.state == "performing_activity"
    return manager, pedestrian


def mapped_course():
    course = Scenery(
        points_m=[(0, -20), (460, -20), (460, 100), (0, 100)],
        kind="golf_course", bbox=(0, -20, 460, 100),
        golf_holes=[[(10, 0), (230, 0), (430, 60)]],
    )
    fairway = Scenery([(25, -12), (425, -12), (425, 72), (25, 72)],
                      kind="golf_fairway", bbox=(25, -12, 425, 72))
    green = Scenery([(415, 45), (445, 45), (445, 75), (415, 75)],
                    kind="golf_green", bbox=(415, 45, 445, 75))
    return [course, fairway, green]


@pytest.mark.parametrize("dt", [.05, .5, 2.0])
def test_golfer_drives_approaches_putts_and_releases_hole(dt):
    from theroadragetrip.geo import point_in_polygon

    random.seed(12)
    course, fairway, green = mapped_course()
    manager, pedestrian = playing_golf([course, fairway, green])
    instance = pedestrian.activity
    data = instance.data
    assert data["ball"] == [10, 0, 0]
    assert data["strokes"] == 0
    clubs, phases = set(), set()
    flight_height = 0.0
    stopped_ball = None
    for _ in range(int(1200 / dt)):
        before_phase, before_strokes = data["phase"], data["strokes"]
        before_ped = pedestrian.x, pedestrian.y
        before_ball = data["ball"][:]
        clubs.add(data["club"])
        phases.add(before_phase)
        if data["club"] == "putter":
            assert point_in_polygon(*data["ball"][:2], green.points_m)
            assert data["ball"][2] == 0
        manager._update_activity(pedestrian, dt)
        flight_height = max(flight_height, data["ball"][2])
        if before_phase in {"prepare", "swing", "flight", "roll"}:
            assert (pedestrian.x, pedestrian.y) == before_ped
        if before_phase == "walk":
            assert data["ball"] == before_ball
            assert data["strokes"] == before_strokes
        if before_phase == "roll" and data["phase"] == "walk" and data["strokes"] == 1:
            stopped_ball = data["ball"][:]
            assert point_in_polygon(*stopped_ball[:2], fairway.points_m)
        if pedestrian.activity is None:
            break
    assert pedestrian.activity is None
    assert {"driver", "iron", "putter"} <= clubs
    assert {"prepare", "swing", "flight", "roll", "walk"} == phases
    assert flight_height > 2
    assert stopped_ball is not None
    assert data["holed"]
    assert data["ball"][:2] == list(course.golf_holes[0][-1])
    assert math.dist((pedestrian.x, pedestrian.y), course.golf_holes[0][-1]) < .2
    assert data["strokes"] >= 4
    cues = [group for group, _ in manager.sound_events]
    assert {"sport.golf_hit", "sport.golf_putt", "sport.golf_cup"} == set(cues)
    assert len(cues) == data["strokes"] + 1 and cues.count("sport.golf_cup") == 1
    assert manager.sound_events[-1] == ("sport.golf_cup", tuple(course.golf_holes[0][-1]))
    assert instance.location.reservation_key not in manager.activity_manager._reservations
    assert "golf" not in protocol._pedestrian_to_dict(pedestrian)


def test_ball_and_club_state_reaches_client_and_cleans_up_on_closure():
    manager, pedestrian = playing_golf(mapped_course())
    instance = pedestrian.activity
    for _ in range(200):
        manager._update_activity(pedestrian, .05)
        if instance.data["ball"][2] > 1:
            break
    row = protocol._pedestrian_to_dict(pedestrian)
    decoded = protocol.decode(protocol.encode({"type": "state", "version": protocol.PROTOCOL_VERSION, "pedestrians": [row]}))
    golf = decoded["pedestrians"][0]["golf"]
    assert golf["phase"] == "flight"
    assert golf["club"] == "driver"
    assert golf["strokes"] == 1
    assert golf["ball"][2] > 1
    assert golf["pin"] == [430, 60]
    manager.soccer_open = False
    manager._update_activity(pedestrian, .1)
    assert pedestrian.activity is None
    assert "golf" not in protocol._pedestrian_to_dict(pedestrian)
    assert instance.location.reservation_key not in manager.activity_manager._reservations


@pytest.mark.parametrize("kind", ["tee", "fairway", "green"])
@pytest.mark.parametrize("relation", [False, True])
def test_mapped_golf_surfaces_are_preserved_and_cached(tmp_path, kind, relation):
    elements = golf_map()
    tags = {"golf": kind, "landuse": "grass"}
    elements.append(dict(type="way", id=21, nodes=[3, 4, 7, 3], tags={} if relation else tags))
    if relation:
        elements.append(dict(type="relation", id=22, tags={"type": "multipolygon", **tags},
                             members=[dict(type="way", ref=21, role="outer")]))
    world = build_ways(elements)
    surface, = [s for s in world.sceneries if s.kind == "golf_" + kind]
    assert len(surface.points_m) >= 3
    path = tmp_path / "golf.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="golf")
    cached = BinaryWorldCacheLoader().load(path)
    assert any(s.kind == surface.kind and s.points_m == surface.points_m for s in cached.sceneries)


def test_golf_requires_nearby_mapped_tee_and_open_season():
    course = local_course()
    manager, pedestrian = _make_manager_and_pedestrian(sceneries=[course])
    plugin = GolfPlugin()
    context = _context(manager, pedestrian)
    assert plugin.find_location(context) is None
    manager.soccer_open = True
    pedestrian.x, pedestrian.y = course.golf_holes[0][0]
    location = plugin.find_location(context)
    assert location is not None
    instance = ActivityInstance("golf", location, 0.0)
    plugin.start(context, instance)
    manager.soccer_open = False
    assert plugin.update(context, instance, .1)
    manager.soccer_open = True
    pedestrian.x += 1000
    assert plugin.find_location(context) is None


def test_short_hole_can_be_holed_without_a_putt(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.0)
    manager, pedestrian = playing_golf()
    data = pedestrian.activity.data
    clubs = set()
    for _ in range(1000):
        clubs.add(data["club"])
        manager._update_activity(pedestrian, .5)
        if pedestrian.activity is None:
            break
    assert pedestrian.activity is None
    assert data["holed"]
    assert data["strokes"] == 1
    assert clubs == {"driver"}


def test_short_approach_uses_wedge_then_putts_on_unmapped_green(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.9)
    monkeypatch.setattr(random, "uniform", lambda low, high: 120.0 if low == 180.0 else (low + high) / 2)
    manager, pedestrian = playing_golf()
    data = pedestrian.activity.data
    saw_putt = False
    saw_wedge = False
    for _ in range(1000):
        saw_wedge |= data["club"] == "wedge"
        if data["club"] == "putter":
            saw_putt = True
            assert math.dist(data["ball"][:2], data["pin"]) <= 12.0
        manager._update_activity(pedestrian, .5)
        if pedestrian.activity is None:
            break
    assert pedestrian.activity is None
    assert saw_putt and saw_wedge
    assert data["holed"]


def test_another_holes_green_does_not_trigger_a_long_distance_putt(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.9)
    sceneries = mapped_course()
    sceneries.append(Scenery([(170, -10), (270, -10), (270, 20), (170, 20)],
                             kind="golf_green", bbox=(170, -10, 270, 20)))
    manager, pedestrian = playing_golf(sceneries)
    data = pedestrian.activity.data
    for _ in range(1000):
        manager._update_activity(pedestrian, .5)
        if data["strokes"] == 1 and data["phase"] == "prepare":
            break
    assert data["strokes"] == 1
    assert data["phase"] == "prepare"
    assert data["club"] == "iron"


def test_visible_green_gets_a_game_without_a_walker_near_the_tee():
    from theroadragetrip.pedestrian import PedestrianManager
    from theroadragetrip.osm import Way
    from theroadragetrip.physics import Car

    manager = PedestrianManager([Way([(0, 0), (500, 0)], "footway", 1.5)],
                                target_count=0, sceneries=mapped_course())
    manager.soccer_open = True
    car = Car(x=450, y=20, heading=0, speed=0)
    view = (400, 40, 450, 80)
    manager.sim_time = 2.0
    manager.ensure_sports_players(car, view)
    golfer, = manager.pedestrians
    assert golfer.activity.plugin_id == "golf"
    assert golfer.activity.data["progress"] > 300  # the tee is nowhere near this camera
    assert golfer.activity.data["club"] == "putter"
    assert golfer.activity.data["strokes"] > 0
    assert protocol.shown_pedestrians(manager, car.x, car.y) == [golfer]  # even with no ambient population
    key = golfer.activity.location.reservation_key
    for _ in range(40):
        manager.ensure_sports_players(car, view)
        manager.update(car, .1, viewport_bounds=view)
    assert golfer.activity.data["strokes"] >= 4
    assert manager.pedestrians == [golfer]
    assert manager.activity_manager._reservations[key] == id(golfer)
    # Camera movement releases both the person and its hole, then allows a fresh game.
    manager.sim_time += 2.0
    manager.ensure_sports_players(car, (1000, 1000, 1100, 1100))
    assert manager.pedestrians == []
    assert key not in manager.activity_manager._reservations
    manager.sim_time += 2.0
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == 1
    assert manager.pedestrians[0] is not golfer


def test_golf_population_is_seasonal_unique_and_shares_the_sports_spawn_budget():
    from theroadragetrip.pedestrian import PedestrianManager, SPORTS_SPAWNS_PER_CHECK
    from theroadragetrip.osm import Way
    from theroadragetrip.physics import Car

    course = mapped_course()[0]
    course.golf_holes = [[(x, y + offset) for x, y in course.golf_holes[0]] for offset in range(8)]
    # Streamed overlap can include the same hole on two enclosing areas.
    manager = PedestrianManager([Way([(0, 0), (500, 0)], "footway", 1.5)],
                                target_count=0, sceneries=[course, course])
    car = Car(x=450, y=20, heading=0, speed=0)
    view = (400, 40, 450, 80)
    manager.sim_time = 2.0
    manager.ensure_sports_players(car, view)
    assert not manager.pedestrians
    manager.soccer_open = True
    manager.sim_time += 2.0
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == SPORTS_SPAWNS_PER_CHECK
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == SPORTS_SPAWNS_PER_CHECK  # no second pass within the interval
    manager.sim_time += 2.0
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == 2 * SPORTS_SPAWNS_PER_CHECK
    keys = [p.activity.location.reservation_key for p in manager.pedestrians]
    assert len(set(keys)) == len(keys)
    for golfer in manager.pedestrians[:]:
        manager.soccer_open = False
        manager._update_activity(golfer, .1)
        assert golfer.activity is None
    assert not manager.activity_manager._reservations
