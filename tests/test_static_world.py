

def test_a_building_part_takes_its_colour_named_buildings_colour():
    """Valkealinnantalo (white by name) and its unnamed, taller building:part
    over the same footprint: the part is white too, not a palette brown
    covering the named roof. A part elsewhere, or a named building, keeps
    its own colour."""
    from types import SimpleNamespace

    from theroadragetrip import static_world
    from theroadragetrip.render.buildings import FINNISH_BUILDING_COLOR_NAMES

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
