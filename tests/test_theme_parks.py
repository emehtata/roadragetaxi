"""Theme park layout, bounded visitors, full rides and camera cleanup."""
from types import SimpleNamespace

from shapely.geometry import LineString, Point, Polygon

from theroadragetrip import protocol
from theroadragetrip.osm import Scenery, Way, build_ways
from theroadragetrip.osm.theme_parks import prepare_theme_parks
from theroadragetrip.map_chunks import ChunkIndex
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def park_world():
    park = Scenery([(0, 0), (120, 0), (120, 90), (0, 90)], "theme_park", bbox=(0, 0, 120, 90))
    road = Way([(-10, -4), (130, -4)], "footway", 1.5)
    sceneries = [park]
    prepare_theme_parks(sceneries, [], {}, [], [], [road])
    manager = PedestrianManager([road], target_count=0, sceneries=sceneries)
    return manager, sceneries, Car(x=60, y=-10, heading=0, speed=0), (-20, -20, 140, 110)


def test_fallback_rides_distributed_in_clear_park_space():
    manager, sceneries, car, view = park_world()
    rides = sceneries[1:]
    assert len(rides) == 4
    assert len(set(r.kind for r in rides)) == 4
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[], sceneries=sceneries)
    index = ChunkIndex(world)
    assert sum(len(chunk["attractions"]) for chunk in index._chunks.values()) >= 4
    for i, ride in enumerate(rides):
        footprint = Polygon(ride.points_m)
        assert Polygon(sceneries[0].points_m).contains(footprint)
        assert footprint.contains(LineString(ride.attraction_path))
        assert all(not footprint.intersects(Polygon(other.points_m)) for other in rides[:i])
    obstacle = SimpleNamespace(points_m=sceneries[0].points_m, bbox=sceneries[0].bbox)
    clear = [sceneries[0]]
    prepare_theme_parks(clear, [], {}, [obstacle], [], [])
    assert len(clear) == 1


def test_visitors_queue_ride_disembark_and_release_seats():
    manager, sceneries, car, view = park_world()
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    assert not manager.pedestrians
    manager.soccer_open = True
    for _ in range(30):
        before = len(manager.pedestrians)
        manager.sim_time += 2
        manager.ensure_sports_players(car, view)
        assert len(manager.pedestrians) - before <= 2
    assert len(manager.pedestrians) == 24
    assert len(manager.activity_manager._reservations) == 24
    assert len(protocol.shown_pedestrians(manager, car.x, car.y)) == 24
    assert all(p.animation_state == "idle" for p in manager.pedestrians)
    starts = {id(p): (p.x, p.y) for p in manager.pedestrians}
    for _ in range(120):
        manager.sim_time += .1
        for p in manager.pedestrians:
            manager._update_activity(p, .1)
    assert all(p.animation_state == "riding" for p in manager.pedestrians)
    assert all(Point(p.x, p.y).distance(Point(*starts[id(p)])) > 1 for p in manager.pedestrians)
    assert all(Polygon(p.activity.location.extra.points_m).contains(Point(p.x, p.y)) for p in manager.pedestrians)
    manager.soccer_open = False
    for _ in range(240):
        manager.sim_time += .1
        for p in manager.pedestrians:
            manager._update_activity(p, .1)
    assert all(p.activity is None for p in manager.pedestrians)
    assert not manager.activity_manager._reservations
    assert all(Point(p.x, p.y).distance(Point(*starts[id(p)])) < .01 for p in manager.pedestrians)


def test_visitors_cleanup_outside_view_and_walking_visitors_find_rides():
    manager, sceneries, car, view = park_world()
    manager.soccer_open = True
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    assert manager.pedestrians
    plugin = manager.activity_manager.registry.get("theme_park")
    context = manager._activity_context(manager.pedestrians[0])
    assert plugin.find_location(context) is not None
    manager.sim_time += 2
    manager.ensure_sports_players(car, (1000, 1000, 1100, 1100))
    assert not manager.pedestrians and not manager.activity_manager._reservations


def test_osm_park_and_mapped_rides_override_fallback_and_ignore_other_layers(tmp_path):
    nodes = [{"type": "node", "id": i+1, "lat": lat, "lon": lon} for i, (lat, lon) in enumerate(
        [(65, 25), (65, 25.003), (65.002, 25.003), (65.002, 25)])]
    elements = nodes + [
        {"type": "way", "id": 20, "nodes": [1, 2, 3, 4, 1], "tags": {"tourism": "theme_park", "name": "Test park"}},
        {"type": "node", "id": 10, "lat": 65.001, "lon": 25.001, "tags": {"attraction": "carousel", "name": "Horses"}},
        {"type": "node", "id": 11, "lat": 65.001, "lon": 25.002, "tags": {"attraction": "ferris_wheel", "layer": "1"}},
    ]
    world = build_ways(elements)
    assert any(s.kind == "theme_park" for s in world.sceneries)
    rides = [s for s in world.sceneries if s.kind.startswith("attraction_")]
    assert len(rides) == 1 and rides[0].name == "Horses"
    assert rides[0].attraction_path

    cache = tmp_path / "park.rwc"
    BinaryWorldCacheWriter().write(cache, world, area_id="park")
    loaded = BinaryWorldCacheLoader().load(cache)
    assert next(s for s in loaded.sceneries if s.kind == "attraction_carousel").attraction_path == rides[0].attraction_path
    incomplete = [{"type": "way", "id": 30, "nodes": [1, 2, 999, 1], "tags": {"attraction": "carousel"}}]
    result = []
    prepare_theme_parks(result, incomplete, {1: (0, 0), 2: (20, 0)}, [], [], [])
    assert result == []
