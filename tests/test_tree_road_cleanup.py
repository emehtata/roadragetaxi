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