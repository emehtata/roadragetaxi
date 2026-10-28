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
