"""Tests for per-tree species classification and rendering: Finland's
three dominant forest trees (spruce, pine, birch) instead of every tree
being an identical shape - see osm/trees.py:classify_tree_kind and
render/scenery.py:_draw_trees_uncached.
"""
import pygame

from theroadragetrip.osm import Scenery, build_ways, classify_tree_kind, plant_trees
from theroadragetrip.render import draw_trees
from theroadragetrip.render.scenery import (
    BIRCH_TRUNK_COLOR,
    TREE_CROWN_PALETTES,
    _irregular_crown_points,
)


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


def test_plant_trees_procedural_forest_trees_are_mixed_species():
    forest = Scenery(
        points_m=[(0.0, 0.0), (500.0, 0.0), (500.0, 500.0), (0.0, 500.0)],
        kind="forest", bbox=(0.0, 0.0, 500.0, 500.0),
    )

    plant_trees([forest], [])

    assert len(forest.trees) > 10
    assert len(forest.tree_kinds) == len(forest.trees)
    assert len(set(forest.tree_kinds)) > 1  # not all the same species


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


def test_draw_trees_renders_a_visually_distinct_crown_color_per_species():
    """A standing tree, seen straight from above, shows only its canopy -
    no trunk (its own crown would hide it in reality) - so species must
    still read as visually distinct via crown color, not a trunk or a
    per-species silhouette (both removed - see draw_trees' docstring)."""
    from theroadragetrip.render import common as common_module

    def render_crown_colors(scenery, camx, camy):
        common_module._tree_frame_cache_key = None
        common_module._tree_frame_cache_surface = None
        common_module.begin_static_cache_frame()
        common_module._pending_static_rebuilds.clear()
        screen = pygame.Surface((200, 200))
        screen.fill((0, 0, 0))
        draw_trees(screen, [scenery], camx, camy, px_per_m=4.0, screen_w=200, screen_h=200)
        colors = {tuple(screen.get_at((x, y)))[:3] for x in range(200) for y in range(200)}
        colors.discard((0, 0, 0))
        return colors

    spruce = Scenery(
        [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], "forest",
        bbox=(0.0, 0.0, 40.0, 40.0), trees=[(20.0, 20.0)], tree_variations=[0.5], tree_kinds=["spruce"],
    )
    birch = Scenery(
        [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], "forest",
        bbox=(0.0, 0.0, 40.0, 40.0), trees=[(20.0, 20.0)], tree_variations=[0.5], tree_kinds=["birch"],
    )

    spruce_colors = render_crown_colors(spruce, 20.0, 20.0)
    birch_colors = render_crown_colors(birch, 20.0, 20.0)

    assert spruce_colors & set(TREE_CROWN_PALETTES["spruce"])
    assert birch_colors & set(TREE_CROWN_PALETTES["birch"])
    # No trunk while standing - straight overhead, a real tree's own
    # canopy would hide it completely (see draw_trees' docstring). Only a
    # *fallen* tree (drawn lying down) shows BIRCH_TRUNK_COLOR.
    assert BIRCH_TRUNK_COLOR not in birch_colors
    assert spruce_colors.isdisjoint(birch_colors), "spruce and birch must not render identically"


def test_irregular_crown_points_are_not_a_perfect_circle():
    """A perfect circle/ellipse/cone reads as a diagram, not foliage -
    straight overhead, a real canopy's outline is an irregular blob."""
    points = _irregular_crown_points(0.0, 0.0, 10.0, seed=1)
    radii = {round((x * x + y * y) ** 0.5, 3) for x, y in points}
    assert len(radii) > 1, "every vertex sits at the same radius - that's a perfect circle, not a blob"


def test_irregular_crown_points_are_deterministic_by_position():
    """Same seed (in practice, the tree's own world position - see
    draw_trees) must draw the exact same blob every time, not a new
    random shape each cache rebuild - a tree can't visibly change shape
    just because the camera moved and forced a static-cache rebuild."""
    first = _irregular_crown_points(5.0, -3.0, 8.0, seed=42)
    second = _irregular_crown_points(5.0, -3.0, 8.0, seed=42)
    assert first == second


def test_draw_trees_standing_tree_shows_no_trunk_of_any_species():
    """Straight overhead, a standing tree's own canopy hides its trunk -
    true for every species, not just birch (BIRCH_TRUNK_COLOR is the only
    one directly distinguishable from a crown color, but every kind's
    trunk_color computation runs the same way, so this checks the two
    less distinguishable ones can't leak a trunk rect onto the screen
    either, by requiring every rendered pixel to be one this species'
    crown palette actually contains)."""
    from theroadragetrip.render import common as common_module

    for kind in ("spruce", "pine", "birch"):
        common_module._tree_frame_cache_key = None
        common_module._tree_frame_cache_surface = None
        common_module.begin_static_cache_frame()
        common_module._pending_static_rebuilds.clear()
        scenery = Scenery(
            [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], "forest",
            bbox=(0.0, 0.0, 40.0, 40.0), trees=[(20.0, 20.0)], tree_variations=[0.5], tree_kinds=[kind],
        )
        screen = pygame.Surface((200, 200))
        screen.fill((0, 0, 0))
        draw_trees(screen, [scenery], 20.0, 20.0, px_per_m=4.0, screen_w=200, screen_h=200)
        colors = {tuple(screen.get_at((x, y)))[:3] for x in range(200) for y in range(200)}
        colors.discard((0, 0, 0))
        assert colors <= set(TREE_CROWN_PALETTES[kind]), f"{kind}: non-crown-palette pixel found - a trunk leaked through"


def test_draw_trees_fallen_tree_still_shows_a_trunk():
    """Regression guard: the request that removed the standing trunk was
    explicit that a *fallen* tree keeps looking like it does now (trunk
    line + crown circle) - only the standing case changed."""
    from theroadragetrip.render import common as common_module

    common_module.begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()
    scenery = Scenery(
        [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], "forest",
        bbox=(0.0, 0.0, 40.0, 40.0), trees=[(20.0, 20.0)], tree_variations=[0.5], tree_kinds=["birch"],
    )
    screen = pygame.Surface((200, 200))
    screen.fill((0, 0, 0))
    tree_key = (id(scenery), 0)
    draw_trees(
        screen, [scenery], 20.0, 20.0, px_per_m=4.0, screen_w=200, screen_h=200,
        fallen_trees={tree_key}, tree_effects={tree_key: {"angle": 0.0}},
    )
    colors = {tuple(screen.get_at((x, y)))[:3] for x in range(200) for y in range(200)}
    colors.discard((0, 0, 0))
    assert BIRCH_TRUNK_COLOR in colors
