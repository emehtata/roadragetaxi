import pytest

from theroadragetrip import map_style
from theroadragetrip.osm import Way


def test_road_style_keeps_surface_and_highway_fallbacks():
    concrete = Way([(0.0, 0.0), (1.0, 0.0)], "service", 3.0, surface="concrete")
    track = Way([(0.0, 0.0), (1.0, 0.0)], "track", 3.0)
    assert map_style.road_color_for_way(concrete) == map_style.SURFACE_COLORS["concrete"]
    assert map_style.road_color_for_way(track) == map_style.LEGACY_HIGHWAY_COLORS["track"]


@pytest.mark.parametrize('surface', [
    'sett', 'cobblestone', 'unhewn_cobblestone', 'paving_stones', 'paving_stones:lanes',
    'concrete', 'concrete:plates', 'concrete:lanes', 'chipseal', 'grass_paver', 'grass_paver:lanes',
    'metal', 'gravel', 'fine_gravel', 'compacted', 'pebblestone', 'rock', 'dirt', 'ground',
    'earth', 'clay', 'mud', 'sand', 'grass', 'wood', 'woodchips', 'snow', 'ice',
])
def test_material_colours_survive_road_chunk_encoding(surface):
    from types import SimpleNamespace
    from theroadragetrip.map_chunks import ChunkIndex
    from theroadragetrip.protocol import decode
    road = Way([(10, 10), (90, 10)], 'residential', 3, surface=surface)
    world = SimpleNamespace(ways=[road], railways=[], waters=[], buildings=[])
    row = decode(ChunkIndex(world).encoded('0_0'))['roads'][0]
    assert row['color'] == list(map_style.SURFACE_COLORS[surface])
    assert tuple(row['color']) != map_style.SURFACE_COLORS['asphalt']


def test_surface_variants_and_unknown_materials_keep_their_fallbacks():
    assert map_style.surface_color(' Sett ; asphalt ') == map_style.surface_color('sett')
    for surface in (None, '', 'unknown_material'):
        assert map_style.surface_color(surface) is None
        road = Way([(0, 0), (1, 0)], 'residential', 3, surface=surface)
        assert map_style.road_color_for_way(road) == map_style.LEGACY_HIGHWAY_COLORS['residential']
    assert map_style.surface_color('paved') == map_style.surface_color('asphalt')
    assert map_style.surface_color('concrete:plates') == map_style.surface_color('concrete')
    assert map_style.surface_color('paving_stones:lanes') == map_style.surface_color('paving_stones')
    assert map_style.surface_color('sett') != map_style.surface_color('paving_stones')
