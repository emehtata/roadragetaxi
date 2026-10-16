"""On-foot player can't walk through building walls, but walks under open
roofs (station canopies)."""
from theroadragetrip.osm import Building
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.simulation import walk_blocked_by_walls

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _manager(building_type):
    manager = PedestrianManager([], target_count=0)
    manager.set_venue_buildings([Building(SQUARE, bbox=(0.0, 0.0, 10.0, 10.0), building_type=building_type)], resync=False)
    return manager


def test_wall_blocks_and_player_slides_along_it():
    blocked = _manager("yes")._point_inside_building
    assert walk_blocked_by_walls(-0.5, 5.0, 1.0, 0.0, blocked) == (-0.5, 5.0)  # straight into the wall
    assert walk_blocked_by_walls(-0.5, 5.0, 1.0, 1.0, blocked) == (-0.5, 6.0)  # slides along it
    assert walk_blocked_by_walls(-0.5, 5.0, -1.0, 0.0, blocked) == (-1.5, 5.0)  # walks away


def test_player_inside_a_building_can_walk_out():
    blocked = _manager("yes")._point_inside_building
    assert walk_blocked_by_walls(5.0, 5.0, 1.0, 0.0, blocked) == (6.0, 5.0)


def test_open_roof_does_not_block():
    blocked = _manager("canopy")._point_inside_building
    assert walk_blocked_by_walls(-0.5, 5.0, 1.0, 0.0, blocked) == (0.5, 5.0)


def test_spawning_far_from_every_way_searches_once_until_the_map_changes(monkeypatch):
    from theroadragetrip import pedestrian
    from theroadragetrip.osm.models import Way

    far = Way(points_m=[(50_000.0, 0.0), (50_100.0, 0.0)], highway="footway", half_width_m=1.0, is_drivable=False,
              bbox=(50_000.0, 0.0, 50_100.0, 0.0))
    manager = PedestrianManager([far], target_count=0)
    scans = []
    real = pedestrian.bbox_distance_sq
    monkeypatch.setattr(pedestrian, "bbox_distance_sq", lambda *a: scans.append(1) or real(*a))
    assert manager.spawn_pedestrian(0.0, 0.0) is None and scans  # nothing within reach (a Home jump's empty area)
    scans.clear()
    assert manager.spawn_pedestrian(0.0, 0.0) is None and not scans  # same place, same map: not searched again
    manager._spawn_ways = list(manager._spawn_ways)  # the map synced
    manager.spawn_pedestrian(0.0, 0.0)
    assert scans
