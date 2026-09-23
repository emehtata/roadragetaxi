from theroadragetrip.osm import Building, Way
from theroadragetrip.render.buildings import (
    _building_render_height,
    _nearest_house_driveway,
    _uses_gabled_roof,
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
