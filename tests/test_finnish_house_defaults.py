from theroadragetrip.npc import _pick_npc_destination_candidates
from theroadragetrip.osm import Building, Way
from theroadragetrip.render.buildings import (
    _building_render_height,
    _nearest_house_driveway,
    _uses_gabled_roof,
    generate_detached_house_parking,
    generate_detached_house_parking_chunk,
)


def _detached_house(**kwargs):
    return Building(
        points_m=[(0.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0)],
        bbox=(0.0, 0.0, 12.0, 8.0),
        building_type="detached",
        **kwargs,
    )


def test_untagged_detached_house_gets_finnish_gable_and_one_and_half_storey_height():
    house = _detached_house()

    assert _uses_gabled_roof(house)
    assert _building_render_height(house) == 4.5


def test_explicit_osm_roof_shape_and_height_override_house_defaults():
    house = _detached_house(roof_shape="flat", height_m=7.0, height_is_explicit=True)

    assert not _uses_gabled_roof(house)
    assert _building_render_height(house) == 7.0


def test_detached_house_gets_shortest_connection_to_nearest_road():
    house = _detached_house()
    road = Way(points_m=[(-20.0, -10.0), (30.0, -10.0)], highway="residential", half_width_m=3.0)

    driveway = _nearest_house_driveway(house, [road])

    assert driveway is not None
    house_edge, road_edge = driveway
    assert house_edge == (6.0, 0.0)
    assert road_edge == (6.0, -7.0)


def test_mapped_driveway_suppresses_procedural_duplicate():
    house = _detached_house()
    road = Way(points_m=[(-20.0, -10.0), (30.0, -10.0)], highway="residential", half_width_m=3.0)
    driveway = Way(
        points_m=[(6.0, -10.0), (6.0, 0.0)],
        highway="service",
        half_width_m=1.5,
        service="driveway",
    )

    assert _nearest_house_driveway(house, [road, driveway]) is None


def test_generated_house_driveway_adds_two_reservable_residential_bays():
    house = _detached_house()
    road = Way(points_m=[(-20.0, -10.0), (30.0, -10.0)], highway="residential", half_width_m=3.0)
    parking_spaces = []

    added = generate_detached_house_parking([house], [road], parking_spaces)

    assert added == 2
    assert len(parking_spaces) == 2
    assert parking_spaces[0].source_building_key == parking_spaces[1].source_building_key
    assert all(space.access_path == [(6.0, 0.0), (6.0, -7.0)] for space in parking_spaces)
    assert all(not space.occupied and not space.reserved for space in parking_spaces)


def test_generated_house_parking_is_idempotent_across_map_syncs():
    house = _detached_house()
    road = Way(points_m=[(-20.0, -10.0), (30.0, -10.0)], highway="residential", half_width_m=3.0)
    parking_spaces = []

    assert generate_detached_house_parking([house], [road], parking_spaces) == 2
    assert generate_detached_house_parking([house], [road], parking_spaces) == 0
    assert len(parking_spaces) == 2


def test_chunked_house_parking_matches_synchronous_result_exactly():
    """bin-loader-v3.md: generate_detached_house_parking_chunk() must
    produce the same parking spaces as generate_detached_house_parking(),
    just spread across multiple calls instead of paid in one."""
    road = Way(points_m=[(-20.0, -10.0), (500.0, -10.0)], highway="residential", half_width_m=3.0)
    houses = [
        Building(
            points_m=[(i * 20.0, 0.0), (i * 20.0 + 12.0, 0.0), (i * 20.0 + 12.0, 8.0), (i * 20.0, 8.0)],
            bbox=(i * 20.0, 0.0, i * 20.0 + 12.0, 8.0),
            building_type="detached",
        )
        for i in range(15)
    ]

    sync_spaces = []
    added_sync = generate_detached_house_parking(houses, [road], sync_spaces)

    chunk_spaces = []
    index = 0
    total_added = 0
    steps = 0
    finished = False
    while not finished:
        index, added = generate_detached_house_parking_chunk(houses, [road], chunk_spaces, None, index, 0.0)
        total_added += added
        steps += 1
        finished = index >= len(houses)
        assert steps < 1000, "chunked parking generation never finished"

    assert steps > 1, "a zero budget must force multiple calls"
    assert added_sync == total_added
    assert len(sync_spaces) == len(chunk_spaces)
    assert sorted(s.source_building_key for s in sync_spaces) == sorted(s.source_building_key for s in chunk_spaces)


def test_chunked_house_parking_is_idempotent_across_repeated_batches():
    """A second chunked pass over the same buildings (a later map-sync
    cycle re-processing the same buildings list) must not add duplicate
    bays - existing_keys is recomputed fresh from parking_spaces each
    start, matching generate_detached_house_parking()'s own idempotency."""
    road = Way(points_m=[(-20.0, -10.0), (30.0, -10.0)], highway="residential", half_width_m=3.0)
    house = _detached_house()
    parking_spaces = []

    index, added_first = generate_detached_house_parking_chunk([house], [road], parking_spaces, None, 0, 10.0)
    assert added_first == 2
    assert index == 1

    index, added_second = generate_detached_house_parking_chunk([house], [road], parking_spaces, None, 0, 10.0)
    assert added_second == 0
    assert len(parking_spaces) == 2


def test_house_resident_and_guest_can_use_separate_driveway_bays():
    house = _detached_house()
    road = Way(points_m=[(-20.0, -10.0), (30.0, -10.0)], highway="residential", half_width_m=3.0)
    parking_spaces = []
    generate_detached_house_parking([house], [road], parking_spaces)

    resident_bay = parking_spaces[0]
    resident_bay.reserved = True
    resident_bay.vehicle_id = 101
    guest_candidates = _pick_npc_destination_candidates(
        6.0, -7.0, parking_spaces=parking_spaces
    )

    assert len(guest_candidates) == 1
    assert guest_candidates[0][1] is parking_spaces[1]
