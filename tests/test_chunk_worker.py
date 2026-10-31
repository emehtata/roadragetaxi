"""The chunk worker builds the same lamps and chunks as the server would in process."""
from types import SimpleNamespace

from theroadragetrip import chunk_worker
from theroadragetrip.map_chunks import ChunkIndex
from theroadragetrip.osm.models import Building, SceneryObject, Water, Way


def _world():
    def road(points, highway="residential", lit="yes"):
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return Way(points_m=points, highway=highway, half_width_m=4.5, lit=lit, bbox=(min(xs), min(ys), max(xs), max(ys)))

    def house(x, y):
        return Building(points_m=[(x, y), (x + 12, y), (x + 12, y + 10), (x, y + 10)], building_type="house",
                        bbox=(x, y, x + 12, y + 10))

    lake = [(900.0, 300.0), (1300.0, 300.0), (1300.0, 700.0), (900.0, 700.0), (900.0, 300.0)]
    ways = [road([(0.0, 100.0), (2000.0, 100.0)], "primary"), road([(600.0, 0.0), (600.0, 1200.0)]),
            road([(100.0, 900.0), (800.0, 900.0)], lit="no")]
    return SimpleNamespace(
        ways=ways, railways=[], waters=[Water(points_m=lake, kind="lake", is_polygon=True, bbox=(900, 300, 1300, 700))],
        buildings=[house(x, 120.0) for x in range(20, 1900, 60)] + [house(620.0, y) for y in range(200, 1100, 50)],
        sceneries=[], scenery_objects=[SceneryObject(x=890.0, y=500.0, kind="firepit"),
                                       SceneryObject(x=300.0, y=110.0, kind="street_lamp")],
        taxi_stops=[], railings=[], street_light_points=[], parking_spaces=[], curbs=[], crossings=[],
        speed_bumps=[], stop_signs=[], yield_signs=[], bus_stops=[], level_ways=[], places=[],
        street_lamps=[], roadworks=[], speed_cameras=[], traffic_mgr=SimpleNamespace(traffic_lights=[]),
    )


def test_the_worker_builds_the_lamps_and_chunks_of_the_in_process_rebuild():
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.server import place_street_lights

    world = _world()
    world.street_lamps = [o for o in world.scenery_objects if o.kind == "street_lamp"]
    for name, items in (("spatial_grid", world.ways), ("building_grid", world.buildings),
                        ("street_lamp_grid", world.street_lamps), ("water_grid", world.waters)):
        grid = SpatialWayGrid()
        grid.rebuild(items)
        setattr(world, name, grid)
    world.street_light_points = place_street_lights(world)
    old = ChunkIndex(world)
    area = (500.0, 0.0, 1400.0, 800.0)

    lamps = place_street_lights(world, region=area)
    previous = world.street_light_points
    world.street_light_points = [p for p in previous if not (area[0] <= p[0] <= area[2] and area[1] <= p[1] <= area[3])] + lamps
    expected, expected_changed = ChunkIndex.updated(old, world, area)
    world.street_light_points = previous

    worker_lamps, built = chunk_worker.build_area(chunk_worker.snapshot(world, area, previous, old.size), area, old.size, True)
    import pickle
    index, changed = ChunkIndex.replaced(old, [(cid, None if c is None else pickle.loads(c), wire) for cid, c, wire in built])

    assert lamps and sorted(worker_lamps) == sorted(lamps)
    assert index._chunks == expected._chunks and changed == expected_changed
    assert all(wire == expected.encoded(cid) for cid, _, wire in built)


def test_replaced_keeps_the_chunks_outside_and_reports_only_real_changes():
    old = ChunkIndex(SimpleNamespace(ways=[], railways=[], waters=[], buildings=[]))
    old._chunks = {"0_0": {"roads": [1]}, "1_0": {"roads": [2]}}
    old._encoded = {"0_0": b"a", "1_0": b"b"}
    index, changed = ChunkIndex.replaced(old, [("1_0", {"roads": [2]}, b"b2"), ("2_0", {"roads": [3]}, b"c")])
    assert changed == {"2_0"}  # 1_0 rebuilt the same
    assert index._chunks["0_0"] is old._chunks["0_0"] and index._encoded["0_0"] == b"a"
    assert index._encoded["2_0"] == b"c" and index.is_encoded("1_0")
