from theroadragetrip.osm import Scenery, Way, remove_trees_under_roads


def test_remove_trees_under_drivable_roads_keeps_variations_aligned():
    scenery = Scenery(
        points_m=[(-10.0, -10.0), (110.0, -10.0), (110.0, 30.0), (-10.0, 30.0)],
        kind="park",
        bbox=(-10.0, -10.0, 110.0, 30.0),
        trees=[(50.0, 0.0), (50.0, 20.0)],
        tree_variations=[0.1, 0.2],
    )
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)

    remove_trees_under_roads([scenery], [road])

    assert scenery.trees == [(50.0, 20.0)]
    assert scenery.tree_variations == [0.2]


def test_remove_trees_under_roads_ignores_non_drivable_ways():
    scenery = Scenery(
        points_m=[(-10.0, -10.0), (110.0, -10.0), (110.0, 30.0), (-10.0, 30.0)],
        kind="park",
        bbox=(-10.0, -10.0, 110.0, 30.0),
        trees=[(50.0, 0.0)],
        tree_variations=[0.1],
    )
    footway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=2.0,
        is_drivable=False,
    )

    remove_trees_under_roads([scenery], [footway])

    assert scenery.trees == [(50.0, 0.0)]
    assert scenery.tree_variations == [0.1]


def test_already_checked_sceneries_are_not_rescanned():
    """Regression: every tile-streaming merge used to re-run this over the
    full accumulated ways/sceneries lists, growing slower with the explored
    map until a later merge could stall the main thread for tens of
    seconds. A scenery already swept once must be skipped on a later call
    even if a new road now overlaps its (already-decided) trees."""
    scenery = Scenery(
        points_m=[(-10.0, -10.0), (110.0, -10.0), (110.0, 30.0), (-10.0, 30.0)],
        kind="park",
        bbox=(-10.0, -10.0, 110.0, 30.0),
        trees=[(50.0, 0.0)],
        tree_variations=[0.1],
    )
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)

    remove_trees_under_roads([scenery], [road])
    assert scenery.trees == []
    assert scenery.trees_checked_against_roads is True

    # A second scenery's trees are the only ones a later merge should touch.
    other = Scenery(
        points_m=[(-10.0, 40.0), (110.0, 40.0), (110.0, 80.0), (-10.0, 80.0)],
        kind="park",
        bbox=(-10.0, 40.0, 110.0, 80.0),
        trees=[(50.0, 50.0)],
        tree_variations=[0.3],
    )
    scenery.trees = [(50.0, 0.0)]  # put a tree back under the road
    remove_trees_under_roads([scenery, other], [road])

    assert scenery.trees == [(50.0, 0.0)], "already-checked scenery was rescanned"
    assert other.trees == [(50.0, 50.0)]
    assert other.trees_checked_against_roads is True