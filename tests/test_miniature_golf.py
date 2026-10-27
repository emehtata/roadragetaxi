"""Mapped miniature-golf facilities populate putting-only games."""
import pytest
from shapely.geometry import LineString, Point, Polygon

from theroadragetrip import protocol
from theroadragetrip.activities import ActivityContext
from theroadragetrip.activities.plugins.miniature_golf import MiniatureGolfPlugin
from theroadragetrip.osm import Way, build_ways
from theroadragetrip.pedestrian import PedestrianManager, SPORTS_SPAWNS_PER_CHECK
from theroadragetrip.physics import Car
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def facility(kind="area", mapped_hole=False, **tags):
    coords = [(60, 25), (60, 25.0003), (60.0001, 25.0003), (60.0001, 25),
              (60.00004, 25.00005), (60.00004, 25.00014), (60.00007, 25.00014)]
    elements = [dict(type="node", id=i, lat=lat, lon=lon)
                for i, (lat, lon) in enumerate(coords, 1)]
    course_tags = {"leisure": "miniature_golf", **tags}
    if kind == "node":
        elements.append(dict(type="node", id=20, lat=60.00005, lon=25.00015, tags=course_tags))
    else:
        elements.append(dict(type="way", id=10, nodes=[1, 2, 3, 4, 1], tags=course_tags if kind == "area" else {}))
        if kind == "relation":
            elements.append(dict(type="relation", id=30, tags={"type": "multipolygon", **course_tags},
                                 members=[dict(type="way", ref=10, role="outer")]))
    if mapped_hole:
        elements.append(dict(type="way", id=11, nodes=[5, 6, 7], tags={"golf": "hole"}))
    return build_ways(elements)


def manager_for(course):
    x0, y0, x1, y1 = course.bbox
    way = Way([(x0, y0-2), (x1, y0-2)], "footway", 1.5)
    manager = PedestrianManager([way], target_count=0, sceneries=[course])
    manager.soccer_open = True
    car = Car(x=(x0+x1)/2, y=y0-3, heading=0, speed=0)
    view = x0-5, y0-5, x1+5, y1+5
    return manager, car, view


@pytest.mark.parametrize("kind", ["node", "area", "relation"])
def test_tag_only_facilities_get_bounded_lanes_and_cache_them(kind, tmp_path):
    world = facility(kind)
    course, = world.sceneries
    assert course.kind == "miniature_golf"
    assert len(course.golf_holes) == 9
    shape = Polygon(course.points_m)
    for hole in course.golf_holes:
        assert 2 <= LineString(hole).length <= 8.01
        assert shape.covers(LineString(hole).buffer(.7))
    path = tmp_path / "mini.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="mini")
    assert BinaryWorldCacheLoader().load(path).sceneries[0].golf_holes == course.golf_holes


def test_mapped_hole_lines_are_used_without_generated_lanes():
    course, = facility(mapped_hole=True).sceneries
    assert len(course.golf_holes) == 1
    assert len(course.golf_holes[0]) == 3


@pytest.mark.parametrize("tags", [{"level": "-1"}, {"layer": "1"}, {"indoor": "yes"}])
def test_other_levels_do_not_spawn_surface_games(tags):
    course, = facility(**tags).sceneries
    assert course.golf_holes == []
    manager, car, view = manager_for(course)
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    assert not manager.pedestrians


def test_visible_facility_plays_only_putts_and_releases_its_reservation():
    course, = facility(mapped_hole=True).sceneries
    manager, car, view = manager_for(course)
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    player, = manager.pedestrians
    instance = player.activity
    assert instance.plugin_id == "miniature_golf"
    assert instance.data["club"] == "putter" and instance.data["strokes"] == 0
    assert protocol.shown_pedestrians(manager, car.x, car.y) == [player]
    assert protocol._pedestrian_to_dict(player)["golf"]["club"] == "putter"
    line = LineString(instance.location.extra)
    phases = set()
    for _ in range(1500):
        phases.add(instance.data["phase"])
        assert instance.data["club"] == "putter"
        assert instance.data["ball"][2] == 0
        assert line.distance(Point(*instance.data["ball"][:2])) < 1e-6
        manager._update_activity(player, .1)
        if player.activity is None:
            break
    assert player.activity is None
    assert "roll" in phases and "flight" not in phases
    assert instance.data["holed"] and instance.data["strokes"] >= 2  # mapped corner needs another stroke
    assert instance.location.reservation_key not in manager.activity_manager._reservations


def test_ambient_walkers_can_select_miniature_golf_and_population_stays_bounded():
    course, = facility().sceneries
    manager, car, view = manager_for(course)
    player = manager.spawn_pedestrian_at(*course.golf_holes[0][0])
    context = ActivityContext(player, manager, manager.residents, manager.sim_time)
    location = MiniatureGolfPlugin().find_location(context)
    assert location is not None
    manager.soccer_open = False
    assert not MiniatureGolfPlugin().can_start(context)
    manager.soccer_open = True
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == SPORTS_SPAWNS_PER_CHECK
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == SPORTS_SPAWNS_PER_CHECK
    manager.sim_time += 2
    manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == 2 * SPORTS_SPAWNS_PER_CHECK
    for _ in range(3):
        manager.sim_time += 2
        manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == 9
    assert len({p.activity.location.reservation_key for p in manager.pedestrians}) == 9
    manager.sim_time += 2
    manager.ensure_sports_players(car, (0, 0, 10, 10))
    assert not manager.pedestrians
    assert not manager.activity_manager._reservations


def test_nine_tracks_cover_an_irregular_site_and_clear_buildings_and_paths():
    from shapely.geometry import box
    from theroadragetrip.osm.miniature_golf import miniature_golf_holes

    area = Polygon([(0, 0), (70, 0), (70, 55), (45, 55), (45, 42), (0, 42)])
    obstacles = [box(28, 20, 38, 28), LineString([(45, 0), (45, 35), (70, 35)]).buffer(1.5)]
    holes = miniature_golf_holes(list(area.exterior.coords), obstacles)
    assert len(holes) == 9
    assert holes == miniature_golf_holes(list(area.exterior.coords), obstacles)
    footprints = [LineString(hole).buffer(.8) for hole in holes]
    for i, footprint in enumerate(footprints):
        assert area.covers(footprint)
        assert all(footprint.disjoint(obstacle) for obstacle in obstacles)
        assert all(footprint.disjoint(other) for other in footprints[:i])
    centres = [LineString(hole).centroid for hole in holes]
    assert max(p.x for p in centres) - min(p.x for p in centres) > 45
    assert max(p.y for p in centres) - min(p.y for p in centres) > 30
    assert any(len(hole) > 2 and not LineString(hole).equals(LineString([hole[0], hole[-1]])) for hole in holes)


def test_tiny_sites_do_not_force_overlapping_or_out_of_bounds_tracks():
    from shapely.geometry import box
    from theroadragetrip.osm.miniature_golf import miniature_golf_holes

    area = box(0, 0, 2, 2)
    assert miniature_golf_holes(list(area.exterior.coords)) == []
