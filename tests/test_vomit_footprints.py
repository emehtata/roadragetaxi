"""Pedestrians stepping in vomit curse and leave dirty footprints."""
from theroadragetrip.osm import Way
from theroadragetrip.pedestrian import DIRTY_FOOTPRINTS, FOOTPRINT_SPACING_M, Pedestrian, PedestrianManager


def test_stepping_in_vomit_curses_once_and_leaves_a_few_footprints():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)
    walker = Pedestrian(-3.0, 0.0, 0.0, 1.3, 1.3, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(walker)
    puddles = [(0.0, 0.0)]

    manager.track_vomit(puddles)
    assert not manager.curses and not manager.vomit_footprints  # not there yet
    x = -3.0
    while x < 12.0:  # walk through the puddle and on
        walker.x = x
        manager.track_vomit(puddles)
        x += 0.1
    assert len(manager.curses) == 1 and walker.curse_text  # one curse for one step in
    assert len(manager.vomit_footprints) == DIRTY_FOOTPRINTS  # then the shoes are clean
    xs = [foot[0] for foot in manager.vomit_footprints]
    assert all(b - a >= FOOTPRINT_SPACING_M - 0.11 for a, b in zip(xs, xs[1:]))
    sides = [foot[1] for foot in manager.vomit_footprints]
    assert all(a * b < 0 for a, b in zip(sides, sides[1:]))  # left, right, left ...
