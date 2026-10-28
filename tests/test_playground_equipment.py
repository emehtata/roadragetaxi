"""Playground equipment (playground_equipment.py): a typical set inside each playground."""
import math

from theroadragetrip.geo import dist_point_to_segment, point_in_polygon
from theroadragetrip.playground_equipment import EQUIPMENT, playground_equipment


def test_a_playground_is_furnished_by_size_inside_its_edges_and_the_same_every_time():
    square = [(100.0, 200.0), (130.0, 200.0), (130.0, 225.0), (100.0, 225.0)]  # 750 m2: 8 items fit
    items = playground_equipment(square)
    assert [kind for _, _, kind, _ in items][:3] == ["sandpit", "swing", "slide"]
    assert len(items) >= 5 and items == playground_equipment(square)
    radius = dict(EQUIPMENT)
    edges = list(zip(square, square[1:] + square[:1]))
    for x, y, kind, angle in items:
        assert point_in_polygon(x, y, square) and angle == 0.0  # square to the long (south) edge
        assert min(dist_point_to_segment(x, y, *a, *b) for a, b in edges) >= radius[kind] - 0.1
    for i, (x, y, kind, _) in enumerate(items):
        for x2, y2, kind2, _ in items[i + 1:]:
            assert math.dist((x, y), (x2, y2)) >= radius[kind] + radius[kind2] - 0.15


def test_a_tiny_playground_gets_nothing_and_a_small_one_a_sandpit_and_swings():
    assert playground_equipment([(0.0, 0.0), (8.0, 0.0), (8.0, 8.0)]) == []
    small = playground_equipment([(0.0, 0.0), (12.0, 0.0), (12.0, 9.0), (0.0, 9.0)])  # 108 m2: two items
    assert [kind for _, _, kind, _ in small] == ["sandpit", "swing"]


def test_osm_equipment_is_parsed_from_nodes_and_areas():
    from theroadragetrip.osm.build import _scenery_object_kind

    assert _scenery_object_kind({"playground": "springy"}) == "spring_rider"
    assert _scenery_object_kind({"playground": "baby_swing"}) == "swing"
    assert _scenery_object_kind({"playground": "playhouse"}) is None  # not drawn


def test_a_playground_with_mapped_equipment_uses_it_and_one_without_is_furnished():
    from types import SimpleNamespace

    from theroadragetrip.playground_equipment import equipment_rows

    def playground(x0):
        return SimpleNamespace(kind="playground", points_m=[(x0, 0.0), (x0 + 20.0, 0.0), (x0 + 20.0, 15.0), (x0, 15.0)],
                               bbox=(0.0, 0.0, 0.0, 0.0), trees=())

    def equipment(kind, x, y, angle=None):
        return SimpleNamespace(kind=kind, x=x, y=y, direction_angle=angle, level=None)

    rows = equipment_rows([playground(0.0), playground(100.0)],
                          [equipment("slide", 5.0, 5.0), equipment("sandpit", 10.0, 8.0, 0.5), equipment("swing", 300.0, 300.0),
                           equipment("bench", 6.0, 6.0)])
    first = [row for row in rows if row[0] < 50.0]
    assert sorted(row[2] for row in first) == ["sandpit", "slide"]  # the mapped ones only
    assert [row[3] for row in first if row[2] == "slide"] == [0.0] and [row[3] for row in first if row[2] == "sandpit"] == [0.5]
    assert len([row for row in rows if 100.0 <= row[0] < 150.0]) == 7  # 300 m2: a furnished set
    assert [300.0, 300.0, "swing", 0.0] in rows  # mapped in no playground: drawn where it is


def test_build_ways_reads_equipment_nodes_and_areas_and_the_query_fetches_them():
    import inspect

    from theroadragetrip.osm import overpass
    from theroadragetrip.osm.build import build_ways

    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"playground": "swing"}},
        {"type": "node", "id": 2, "lat": 60.0001, "lon": 25.0001},
        {"type": "node", "id": 3, "lat": 60.0001, "lon": 25.0002},  # ~5.6 m east of 2: the long edge
        {"type": "node", "id": 4, "lat": 60.00012, "lon": 25.0002},
        {"type": "node", "id": 5, "lat": 60.00012, "lon": 25.0001},
        {"type": "way", "id": 2, "nodes": [2, 3, 4, 5, 2], "tags": {"playground": "sandpit"}},  # same id as a node
    ]
    objects = {obj.kind: obj for obj in build_ways(elements).scenery_objects}
    assert set(objects) == {"swing", "sandpit"} and objects["swing"].id == 1 and objects["sandpit"].id == -2
    assert abs(math.sin(objects["sandpit"].direction_angle)) < 0.06  # square to its long east-west edges (grid convergence ~2 deg)
    source = inspect.getsource(overpass)
    assert 'node["playground"]' in source and 'way["playground"]' in source
