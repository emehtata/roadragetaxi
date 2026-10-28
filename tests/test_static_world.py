

def test_a_building_part_takes_its_colour_named_buildings_colour():
    """Valkealinnantalo (white by name) and its unnamed, taller building:part
    over the same footprint: the part is white too, not a palette brown
    covering the named roof. A part elsewhere, or a named building, keeps
    its own colour."""
    from types import SimpleNamespace

    from theroadragetrip import static_world
    from theroadragetrip.building_style import FINNISH_BUILDING_COLOR_NAMES

    def building(points, name=None, building_type="yes", height=10.0):
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return SimpleNamespace(points_m=points, name=name, building_type=building_type, height_m=height,
                               bbox=(min(xs), min(ys), max(xs), max(ys)), center_m=(sum(xs) / len(xs), sum(ys) / len(ys)),
                               texture_seed=0.03, entrances=(), levels=None, roof_shape=None, venue_type=None)

    square = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
    white = building(square, name="Valkealinnantalo", height=20.0)
    part = building([(2.0, 2.0), (36.0, 2.0), (36.0, 28.0), (2.0, 28.0)], building_type=None, height=30.0)
    elsewhere = building([(100.0, 0.0), (120.0, 0.0), (120.0, 20.0)], building_type=None)
    assert static_world.inherit_part_colours([white, part, elsewhere]) == 1
    valko = list(FINNISH_BUILDING_COLOR_NAMES["valko"])
    assert static_world.building_style(part)[4] == valko and static_world.building_style(white)[4] == valko
    assert static_world.building_style(elsewhere)[4] != valko


def test_greenhouses_are_flagged_as_glass():
    from types import SimpleNamespace

    from theroadragetrip import static_world

    def building(building_type):
        return SimpleNamespace(points_m=[(0.0, 0.0), (30.0, 0.0), (30.0, 10.0), (0.0, 10.0)], name=None,
                               building_type=building_type, height_m=4.0, bbox=(0.0, 0.0, 30.0, 10.0),
                               center_m=(15.0, 5.0), texture_seed=0.5, entrances=(), levels=None, roof_shape=None,
                               venue_type=None)

    assert static_world.building_style(building("greenhouse"))[7:] == [2]
    assert static_world.building_style(building("Glasshouse"))[7:] == [2]
    assert static_world.building_style(building("barn"))[7:] == []


def test_untagged_building_types_take_their_typical_shape():
    """Without OSM height or levels: outbuildings 3 m with plain walls, a
    terrace (rivitalo) a pitched 4.5 m house, an industrial hall 8 m with one
    window row, a carport an open 2.5 m roof. A tagged height still wins."""
    from types import SimpleNamespace

    from theroadragetrip import static_world

    def building(building_type, size=(60.0, 40.0), **tags):
        w, h = size
        fields = dict(points_m=[(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)], name=None, building_type=building_type,
                      height_m=20.0, bbox=(0.0, 0.0, w, h), center_m=(w / 2, h / 2), texture_seed=0.5, entrances=(),
                      levels=None, roof_shape=None, venue_type=None, height_is_explicit=False)
        fields.update(tags)
        return SimpleNamespace(**fields)

    garage = static_world.building_style(building("garage", (6.0, 3.0)))
    assert garage[2] == 3.0 and garage[6] == 3  # height, plain walls
    terrace = static_world.building_style(building("terrace"))
    assert terrace[1] == 1 and terrace[2] == 4.5 and terrace[6] == 1  # pitched, house windows
    hall = static_world.building_style(building("warehouse"))
    assert hall[2] == 8.0 and hall[5] == 1
    assert static_world.is_open_roof(building("carport")) and static_world.building_style(building("carport"))[2] == 2.5
    tall = static_world.building_style(building("warehouse", height_m=15.0, height_is_explicit=True))
    assert tall[2] == 15.0 and tall[5] == 1  # still one hall storey; building:levels would set more
