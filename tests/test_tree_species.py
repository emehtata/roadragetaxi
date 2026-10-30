"""Tests for per-tree species classification and rendering: Finland's
three dominant forest trees (spruce, pine, birch) instead of every tree
being an identical shape - see osm/trees.py:classify_tree_kind.
"""

from theroadragetrip.osm import Scenery, build_ways, classify_tree_kind, plant_trees


def test_classify_tree_kind_uses_genus_tag_outright():
    assert classify_tree_kind({"genus": "Picea"}, 0.0, 0.0) == "spruce"
    assert classify_tree_kind({"genus": "Pinus"}, 0.0, 0.0) == "pine"
    assert classify_tree_kind({"genus": "Betula"}, 0.0, 0.0) == "birch"


def test_classify_tree_kind_uses_species_and_finnish_names():
    assert classify_tree_kind({"species": "Picea abies"}, 0.0, 0.0) == "spruce"
    assert classify_tree_kind({"species:fi": "mänty"}, 0.0, 0.0) == "pine"
    assert classify_tree_kind({"taxon": "Betula pendula"}, 0.0, 0.0) == "birch"


def test_classify_tree_kind_leaf_type_broadleaved_is_birch():
    assert classify_tree_kind({"leaf_type": "broadleaved"}, 5.0, 5.0) == "birch"


def test_classify_tree_kind_leaf_type_needleleaved_never_picks_birch():
    # "Definitely a conifer, species unspecified" must still only ever
    # resolve to one of the two actual conifers.
    for x in range(20):
        assert classify_tree_kind({"leaf_type": "needleleaved"}, float(x), float(x) * 3.0) in ("pine", "spruce")


def test_classify_tree_kind_with_no_tags_mixes_all_three_species():
    """The actual point of this feature: an unspecified forest must not
    render as a wall of one identical shape - sampling many positions
    must produce all three kinds, not just one."""
    kinds = {classify_tree_kind({}, float(x) * 7.3, float(x) * 2.1) for x in range(200)}
    assert kinds == {"spruce", "pine", "birch"}


def test_classify_tree_kind_is_deterministic_by_position():
    assert classify_tree_kind({}, 123.4, 567.8) == classify_tree_kind({}, 123.4, 567.8)


def test_plant_trees_uses_real_species_tags_over_the_position_mix():
    forest = Scenery(
        points_m=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        kind="forest", bbox=(0.0, 0.0, 100.0, 100.0),
    )
    real_trees = [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)]
    real_tree_tags = [{"genus": "Picea"}, {"genus": "Betula"}, {}]

    plant_trees([forest], [], real_trees=real_trees, real_tree_tags=real_tree_tags)

    assert forest.tree_kinds[0] == "spruce"
    assert forest.tree_kinds[1] == "birch"
    assert forest.tree_kinds[2] in ("spruce", "pine", "birch")  # untagged - still a concrete, mixed-in kind


def test_forests_do_not_create_server_tree_positions():
    forest = Scenery(
        points_m=[(0.0, 0.0), (500.0, 0.0), (500.0, 500.0), (0.0, 500.0)],
        kind="forest", bbox=(0.0, 0.0, 500.0, 500.0),
    )

    plant_trees([forest], [])

    assert forest.trees == []
    assert forest.tree_kinds == []
    assert forest.tree_variations == []


def test_build_ways_real_tree_genus_tag_picks_its_species():
    elements = [
        {"type": "node", "id": 1, "lat": 60.1, "lon": 25.1},
        {"type": "node", "id": 2, "lat": 60.1, "lon": 25.14},
        {"type": "node", "id": 3, "lat": 60.14, "lon": 25.14},
        {"type": "node", "id": 4, "lat": 60.14, "lon": 25.1},
        {"type": "way", "id": 20, "nodes": [1, 2, 3, 4, 1], "tags": {"natural": "wood"}},
        {"type": "node", "id": 5, "lat": 60.12, "lon": 25.12, "tags": {"natural": "tree", "genus": "Picea"}},
    ]

    _, _, _, sceneries, _, _ = build_ways(elements)

    assert sceneries[0].tree_kinds == ["spruce"]


def test_standalone_osm_trees_are_retained_without_a_green_area():
    elements = [
        {"type": "node", "id": 1, "lat": 60.1, "lon": 25.1,
         "tags": {"natural": "tree", "genus": "Pinus"}},
        {"type": "node", "id": 2, "lat": 60.11, "lon": 25.11,
         "tags": {"natural": "tree", "genus": "Betula"}},
    ]
    world = build_ways(elements)
    assert sum(len(s.trees) for s in world.sceneries) == 2
    assert {kind for s in world.sceneries for kind in s.tree_kinds} == {"pine", "birch"}
    assert all(s.trees_from_osm and len(s.points_m) == 1 for s in world.sceneries)
    from theroadragetrip.map_chunks import ChunkIndex
    index = ChunkIndex(world)
    assert sum(len(chunk["trees"]) for chunk in index._chunks.values()) == 2


def test_osm_trees_are_owned_once_and_unmapped_old_trees_are_removed():
    square = [(0, 0), (100, 0), (100, 100), (0, 100)]
    forest = Scenery(square, "forest", bbox=(0, 0, 100, 100), trees=[(50, 50)])
    park = Scenery(square, "park", bbox=(0, 0, 100, 100))
    sceneries = [forest, park]
    plant_trees(sceneries, [], real_trees=[(10, 10), (200, 200)],
                real_tree_tags=[{"genus": "Picea"}, {"genus": "Betula"}])
    assert [tree for s in sceneries for tree in s.trees] == [(10, 10), (200, 200)]
    plant_trees(sceneries, [])
    assert [tree for s in sceneries for tree in s.trees] == [(10, 10), (200, 200)]
