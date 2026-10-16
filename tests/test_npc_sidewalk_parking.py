import pytest

from theroadragetrip.npc import place_parked_npc, _pick_npc_destination_candidates
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip import npc
from theroadragetrip.osm import ParkingSpace


def _spaces(count):
    return [ParkingSpace(
        points_m=[(x, 0), (x + 6, 0), (x + 6, 3), (x, 3)],
        bbox=(x, 0, x + 6, 3),
    ) for x in range(count)]


def test_selection_stops_after_enough_valid_candidates(monkeypatch):
    checked = []

    def overlaps(x, *args):
        checked.append(x)
        return x < 6  # Reject the three closest, not the whole tier.

    monkeypatch.setattr(npc, "_parking_overlaps_walkway", overlaps)
    spaces = _spaces(100)
    result = _pick_npc_destination_candidates(0, 0, parking_spaces=spaces, limit=2)
    assert [space for _, space in result] == spaces[3:5]
    assert len(checked) == 5
    assert not any(space.reserved or space.occupied for space in spaces)


def test_candidate_collection_and_validation_are_resumable(monkeypatch):
    checked = []
    monkeypatch.setattr(npc, "_parking_overlaps_walkway", lambda *args: checked.append(args) or False)
    steps = npc._pick_npc_destination_candidates_steps(0, 0, parking_spaces=_spaces(100), limit=2)
    for _ in range(101):  # Initial checkpoint plus one per space.
        next(steps)
    assert not checked
    next(steps)  # Checkpoint before the first expensive footprint test.
    assert not checked
    next(steps)
    assert len(checked) == 1
    with pytest.raises(StopIteration) as finished:
        next(steps)
    assert len(finished.value.value) == 2


def test_expired_selection_does_not_validate_or_reserve_spaces(monkeypatch):
    def unexpected(*args):
        pytest.fail("Expired parking search performed a footprint check")

    monkeypatch.setattr(npc, "_parking_overlaps_walkway", unexpected)
    spaces = _spaces(100)
    assert _pick_npc_destination_candidates(0, 0, parking_spaces=spaces, deadline=0) == []
    assert not any(space.reserved or space.occupied for space in spaces)


def test_deadline_interrupts_candidate_collection(monkeypatch):
    clock = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr(npc.time, "perf_counter", lambda: next(clock))
    spaces = _spaces(100)
    assert _pick_npc_destination_candidates(0, 0, parking_spaces=spaces, deadline=2.0) == []
    assert not any(space.reserved or space.occupied for space in spaces)


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
