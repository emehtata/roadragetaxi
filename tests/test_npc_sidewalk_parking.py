import pytest

from theroadragetrip.npc import place_parked_npc, _pick_npc_destination_candidates
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid


@pytest.mark.parametrize("indexed", [False, True])
def test_roadside_parking_cannot_overlap_the_sidewalk(indexed):
    road = Way([(0, 0), (100, 0)], "residential", 4.5)
    sidewalk = Way([(0, -6), (100, -6)], "footway", 1.0, is_drivable=False)
    ways = [road, sidewalk]
    grid = SpatialWayGrid(ways) if indexed else None
    assert not _pick_npc_destination_candidates(50, 0, ways=ways, spatial_grid=grid)
    assert place_parked_npc(1, (50, -5.9), None, ways=ways, spatial_grid=grid) is None
    assert place_parked_npc(1, (50, -9), None, ways=ways, spatial_grid=grid) is not None


def test_vehicle_edge_cannot_block_a_walkway_even_when_its_centre_is_clear():
    road = Way([(0, 0), (100, 0)], "residential", 4.5)
    sidewalk = Way([(0, -6), (100, -6)], "footway", 1.0, is_drivable=False)
    assert place_parked_npc(1, (50, -4.5), None, ways=[road, sidewalk]) is None


def test_a_walkway_on_a_different_layer_does_not_block_parking():
    road = Way([(0, 0), (100, 0)], "residential", 4.5)
    sidewalk = Way([(0, -6), (100, -6)], "footway", 1.0, is_drivable=False, layer=1)
    assert place_parked_npc(1, (50, -5.9), None, ways=[road, sidewalk]) is not None
