import math
from types import SimpleNamespace

from theroadragetrip import map_chunks


def test_plan_loads_the_square_around_the_player_nearest_first():
    to_load, to_drop = map_chunks.plan(set(), (0, 0), load_radius=1)
    assert to_load[0] == "0_0" and len(to_load) == 9 and to_drop == []


def test_plan_skips_loaded_chunks_and_drops_only_beyond_the_unload_radius():
    loaded = {"0_0", "1_0", "5_0", "-3_0"}
    to_load, to_drop = map_chunks.plan(loaded, (0, 0), load_radius=1, unload_radius=2)
    assert "0_0" not in to_load and "1_0" not in to_load
    assert to_drop == ["-3_0", "5_0"]


def test_a_feature_is_in_every_chunk_it_touches_and_negative_cells_work():
    way = SimpleNamespace(points_m=[(-10.0, 5.0), (510.0, 5.0)], half_width_m=3.0, highway="primary",
                          is_drivable=True, layer=0)
    world = SimpleNamespace(ways=[way], railways=[], waters=[], buildings=[])
    index = map_chunks.ChunkIndex(world, size=500.0)
    assert len(index.message("-1_0")["roads"]) == 1 and len(index.message("1_0")["roads"]) == 1
    assert index.message("0_0")["roads"] == []  # no vertex there (see module docstring)
    assert index.message("1_0")["bounds"] == [500.0, 0.0, 1000.0, 500.0]


def _points_world():
    """One of each gameplay point (godot-12), in chunks 0_0 and 1_0."""
    from theroadragetrip.osm.models import SceneryObject, TaxiStop, TrafficLight
    from theroadragetrip.roadworks import Roadwork

    road = SimpleNamespace(points_m=[(0.0, 0.0), (1000.0, 0.0)], half_width_m=3.5, highway="primary",
                           is_drivable=True, layer=0)
    lights = [
        TrafficLight(100.0, 50.0, id=9001, direction_angle=math.pi / 2, render_offset_m=2.0),
        TrafficLight(600.0, 50.0, id=None, direction_angle=0.0),  # a roadwork's temporary light: no OSM id
        TrafficLight(120.0, 50.0, id=9002, renderable=False),
    ]
    return SimpleNamespace(
        ways=[road], railways=[], waters=[], buildings=[],
        taxi_stops=[TaxiStop(20.0, 40.0, id=5)],
        scenery_objects=[SceneryObject(30.0, 60.0, "fuel", name="Neste", id=77, direction_angle=0.5, is_area=True),
                         SceneryObject(31.0, 61.0, "bench")],
        traffic_mgr=SimpleNamespace(traffic_lights=lights, sim_time=0.0),
        roadworks=[Roadwork(road, 480.0, 540.0, True, (480.0, 0.0), (540.0, 0.0))],
    )


def test_gameplay_points_are_each_in_exactly_one_chunk():
    from theroadragetrip.fuel import fuel_station_price_cents

    world = _points_world()
    index = map_chunks.ChunkIndex(world, size=500.0)
    here, east = index.message("0_0"), index.message("1_0")
    assert here["taxi_stands"] == [[20.0, 40.0]] and east["taxi_stands"] == []
    assert here["fuel_stations"] == [{"x": 30.0, "y": 60.0, "angle": 0.5, "is_area": True, "name": "Neste",
                                      "price_cents": fuel_station_price_cents(world.scenery_objects[0])}]
    # Posts by list index (stable for the session, unlike the missing roadwork ids), at
    # Pygame's render position; a non-renderable post is not sent.
    assert here["traffic_lights"] == [{"id": 0, "x": 102.0, "y": 50.0, "angle": round(math.pi / 2, 4)}]
    assert east["traffic_lights"] == [{"id": 1, "x": 600.0, "y": 50.0, "angle": 0.0}]
    # A roadwork crossing the chunk edge goes to its midpoint's chunk only.
    assert east["roadworks"] == [{"start": [480.0, 0.0], "end": [540.0, 0.0], "lane_closed": True, "half_width_m": 3.5}]
    assert here["roadworks"] == []
    assert index.message("7_7")["taxi_stands"] == []  # an empty chunk still has every list
    assert index.message("0_0") == here  # rebuilt identically: a reloaded chunk is the same chunk


def test_traffic_light_phases_are_the_simulations_near_the_player():
    from theroadragetrip import protocol

    world = _points_world()
    mgr = world.traffic_mgr
    phases = protocol._traffic_light_phases(mgr, 100.0, 50.0)
    assert phases == {"0": mgr.traffic_lights[0].get_state(0.0), "1": mgr.traffic_lights[1].get_state(0.0)}
    mgr.sim_time = 6.0  # past the green: the phase comes from the light's own cycle
    assert protocol._traffic_light_phases(mgr, 100.0, 50.0)["0"] == mgr.traffic_lights[0].get_state(6.0) != phases["0"]
    assert protocol._traffic_light_phases(mgr, 5000.0, 50.0) == {}  # none near: nothing sent


def _obstacle_world():
    """godot-13: a tree, a construction site across a chunk edge, a bollard and a lamp."""
    from theroadragetrip.osm.models import SceneryObject

    park = SimpleNamespace(kind="park", points_m=[(0, 0), (50, 0), (50, 50)], bbox=(0, 0, 50, 50),
                           trees=[(10.0, 20.0), (30.0, 20.0)], tree_kinds=["pine", "birch"], tree_variations=[0.25, 0.8])
    site = SimpleNamespace(kind="construction", points_m=[(490.0, 10.0), (520.0, 10.0), (520.0, 40.0), (490.0, 40.0)],
                           bbox=(490, 10, 520, 40), trees=[])
    objects = [SceneryObject(40.0, 0.0, "bollard"), SceneryObject(45.0, 0.0, "street_lamp"), SceneryObject(46.0, 0.0, "bench")]
    return SimpleNamespace(ways=[], railways=[], waters=[], buildings=[], sceneries=[park, site], scenery_objects=objects,
                           taxi_stops=[], roadworks=[], traffic_mgr=SimpleNamespace(traffic_lights=[], sim_time=0.0))


def test_obstacles_are_each_in_exactly_one_chunk():
    index = map_chunks.ChunkIndex(_obstacle_world(), size=500.0)
    here, east = index.message("0_0"), index.message("1_0")
    assert here["trees"] == [[10.0, 20.0, "pine", 0.25], [30.0, 20.0, "birch", 0.8]] and east["trees"] == []
    # The site spans two chunks: one owner (its first corner's), the whole ring.
    assert here["construction_fences"] == [[[490.0, 10.0], [520.0, 10.0], [520.0, 40.0], [490.0, 40.0]]]
    assert east["construction_fences"] == []
    assert here["bollards"] == [[40.0, 0.0]]  # a street lamp is not a bollard; a bench collides with nothing


def test_felled_trees_and_knocked_posts_reach_the_state_from_the_real_collisions():
    from theroadragetrip import protocol
    from theroadragetrip.physics import Car
    from theroadragetrip.taxi import TaxiManager

    world = _obstacle_world()
    world.taxi_mgr = TaxiManager(ways=[])
    assert protocol._fallen_and_knocked(world, 0.0, 0.0) == ([], [])
    car = Car(x=10.0, y=19.0, heading=0.0, speed=25.0)  # 90 km/h into the pine
    assert world.taxi_mgr.check_tree_collision(car, world.sceneries, 0.0, previous_position=(5.0, 19.0))
    car = Car(x=40.0, y=0.0, heading=math.pi, speed=17.0)  # 61 km/h through the bollard
    assert world.taxi_mgr.check_post_collision(car, world.scenery_objects, 0.0)
    fallen, knocked = protocol._fallen_and_knocked(world, 0.0, 0.0)
    assert fallen == [[10.0, 20.0, 0.0]]  # felled the way the taxi was heading
    assert knocked == [[40.0, 0.0, round(math.pi, 3), "bollard"]]
    assert protocol._fallen_and_knocked(world, 5000.0, 0.0) == ([], [])  # far away: not sent


def test_railings_decorations_and_street_lights_are_each_in_one_chunk():
    """godot-15: drawing-only static world."""
    from theroadragetrip.osm.models import Railing, SceneryObject

    world = _obstacle_world()
    world.railings = [Railing([(480.0, 5.0), (530.0, 5.0)], kind="hedge"), Railing([(10.0, 10.0)], kind="wall")]
    world.scenery_objects += [SceneryObject(12.0, 13.0, "bench", direction_angle=0.5), SceneryObject(14.0, 15.0, "gate")]
    world.street_light_points = [(100.0, 100.0, 1.25, 14.0), (600.0, 100.0, 0.0, 14.0)]
    index = map_chunks.ChunkIndex(world, size=500.0)
    here, east = index.message("0_0"), index.message("1_0")
    assert here["railings"] == [["hedge", [[480.0, 5.0], [530.0, 5.0]]]] and east["railings"] == []  # first point's chunk, whole
    assert here["scenery_objects"] == [[46.0, 0.0, "bench", 0.0], [12.0, 13.0, "bench", 0.5], [14.0, 15.0, "gate", 0.0]]
    assert here["street_lights"] == [[100.0, 100.0, 1.25, 14.0]] and east["street_lights"] == [[600.0, 100.0, 0.0, 14.0]]


def test_landuse_is_clipped_to_the_chunks_it_covers_without_overlap():
    """godot-16: a big area is cut along the chunk grid - each piece in its
    own chunk, together exactly the original."""
    from shapely.geometry import Polygon
    from theroadragetrip import static_world

    forest = [(100.0, 100.0), (900.0, 100.0), (900.0, 300.0), (100.0, 300.0)]
    pieces = list(static_world.clipped_pieces(forest, 500.0))
    assert sorted(cell for cell, _ in pieces) == [(0, 0), (1, 0)]
    assert abs(sum(Polygon(ring).area for _, ring in pieces) - Polygon(forest).area) < 1.0
    assert all(Polygon(ring).bounds[0] >= cell[0] * 500.0 - 0.1 and Polygon(ring).bounds[2] <= (cell[0] + 1) * 500.0 + 0.1
               for cell, ring in pieces)


def test_static_world_lists_in_the_chunks():
    from theroadragetrip.osm.models import Building, Crossing, Railway, SpeedBump, StopSign
    from theroadragetrip import static_world

    world = _obstacle_world()
    world.sceneries[0].name = "Hupisaaret"
    world.buildings = [Building([(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)], building_type="house", name="Sininen talo"),
                       Building([(30.0, 30.0), (40.0, 30.0), (40.0, 40.0), (30.0, 40.0)], building_type="roof")]
    world.crossings = [Crossing(50.0, 60.0, direction_angle=0.5, width_m=6.0, length_m=2.5)]
    world.speed_bumps = [SpeedBump(70.0, 60.0, direction_angle=1.0, width_m=4.0, kind="table")]
    world.stop_signs = [StopSign(80.0, 60.0, direction_angle=0.0)]
    world.speed_cameras = [SimpleNamespace(x=90.0, y=60.0, heading=1.5)]
    world.railways = [Railway([(0.0, 400.0), (100.0, 400.0)], is_bridge=True), Railway([(0.0, 450.0), (100.0, 450.0)])]
    index = map_chunks.ChunkIndex(world, size=500.0)
    here = index.message("0_0")
    assert here["buildings"] == [[[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]]  # the canopy is not a building
    assert here["canopies"] == [[[30.0, 30.0], [40.0, 30.0], [40.0, 40.0], [30.0, 40.0]]]
    assert here["building_styles"] == [static_world.building_style(world.buildings[0])]
    assert here["building_styles"][0][0] == [40, 63, 92] and here["building_styles"][0][1] == 1  # "Sininen": a blue roof, gabled house
    assert here["crossings"] == [[50.0, 60.0, 0.5, 6.0, 2.5]] and here["speed_bumps"] == [[70.0, 60.0, 1.0, 4.0, "table"]]
    assert here["signs"] == [[80.0, 60.0, "stop", 0.0]] and here["speed_cameras"] == [[0, 90.0, 60.0, 1.5]]
    assert here["rail_bridges"] == [[[0.0, 400.0], [100.0, 400.0]]] and here["railways"] == [[[0.0, 450.0], [100.0, 450.0]]]
    assert len(here["rail_decks"]) == 1  # the bridge track's deck
    assert [l for l in here["labels"] if l[2] == "Hupisaaret"][0][3] == static_world.LABEL_AREA
    assert any(l[2] == "Sininen talo" and l[3] == static_world.LABEL_BUILDING for l in here["labels"])
    assert [l[0] for l in here["landuse"]] == [[100, 145, 80], [170, 142, 96]]  # park, construction (render/scenery.py colours)


def test_road_style_follows_pygames_road_look():
    from theroadragetrip import static_world
    from theroadragetrip.render.common import road_color_for_way

    two_way = SimpleNamespace(is_drivable=True, highway="primary", lanes=4, oneway=0, is_ice_road=False, surface="")
    oneway = SimpleNamespace(is_drivable=True, highway="residential", lanes=1, oneway=-1, is_ice_road=False, surface="", is_bridge=True)
    path = SimpleNamespace(is_drivable=False, highway="footway", surface="")
    assert static_world.road_style(two_way) == {"color": list(road_color_for_way(two_way)), "center": [110, 110, 110, 2]}
    assert static_world.road_style(oneway) == {"color": list(road_color_for_way(oneway)), "center": [110, 110, 110, 1], "oneway": -1, "bridge": True}
    assert static_world.road_style(path) == {"color": list(road_color_for_way(path))}


def test_bridge_guardrails_run_along_the_outside_only():
    from theroadragetrip import static_world

    left = SimpleNamespace(points_m=[(0.0, 0.0), (100.0, 0.0)], half_width_m=3.0, is_bridge=True)
    right = SimpleNamespace(points_m=[(0.0, 6.5), (100.0, 6.5)], half_width_m=3.0, is_bridge=True)  # a parallel carriageway
    rails = static_world.bridge_guardrails([left, right])
    ys = sorted({round(y, 1) for a, b in rails for _, y in (a, b)})
    assert ys == [-3.0, 9.5]  # the two outer edges, nothing between the carriageways, no end caps


def test_bus_stop_shapes_follow_the_nearest_road():
    """godot-16: render/roads.py draw_bus_stops' bay and shelter, computed once."""
    from theroadragetrip import static_world

    road = SimpleNamespace(points_m=[(0.0, 0.0), (100.0, 0.0)], half_width_m=3.0, is_drivable=True, layer=0)
    stop = SimpleNamespace(x=50.0, y=6.0, layer=0, shelter=True)
    shapes = static_world.bus_stop_shapes(stop, [road])
    assert shapes["bay"] == [[36.0, 3.0], [64.0, 3.0], [60.0, 5.2], [40.0, 5.2]]  # on the stop's side of the road
    assert shapes["shelter"] is not None and shapes["label"] == [50.0, 6.2] and shapes["angle"] == 0.0
    assert static_world.bus_stop_shapes(SimpleNamespace(x=50.0, y=80.0, layer=0, shelter=False), [road]) is None  # beyond 45 m


def test_buildings_have_one_owner_and_their_facade_style():
    """godot-17: a building drawn as a volume belongs to one chunk (its
    centre's); its style carries the wall colour, floors and category the
    facades and windows use (render/buildings.py's own picks)."""
    from theroadragetrip.osm.models import Building
    from theroadragetrip.render import buildings as rb
    from theroadragetrip import static_world

    across = Building([(480.0, 10.0), (530.0, 10.0), (530.0, 30.0), (480.0, 30.0)], building_type="apartments", levels=5)
    canopy = Building([(490.0, 100.0), (520.0, 100.0), (520.0, 120.0), (490.0, 120.0)], building_type="roof")
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[across, canopy])
    index = map_chunks.ChunkIndex(world, size=500.0)
    west, east = index.message("0_0"), index.message("1_0")
    assert west["buildings"] == [] and len(east["buildings"]) == 1  # centre x = 505: east owns it, once
    roof, gabled, height, entrances, wall, floors, category = east["building_styles"][0]
    assert floors == 5 and category == 0 and wall in [list(c) for c in rb.BUILDING_WALL_COLORS]
    assert rb.BUILDING_WALL_COLORS.index(tuple(wall)) == rb.BUILDING_ROOF_COLORS.index(tuple(roof))  # the pair Pygame uses
    assert east["canopies"] and east["canopy_heights"] == [static_world.building_style(canopy)[2]]
    assert static_world.building_style(Building([(0, 0), (9, 0), (9, 9)], building_type="house"))[6] == 1


def test_garage_aisles_are_not_sent_as_surface_roads():
    """Bug: a map_level -1 garage aisle (kept in world.ways) was sent with
    the surface roads, so Godot drew it over the street map. Pygame's
    draw_ways takes only SURFACE_MAP_LEVELS; underground roads are
    level_roads, shown on their own level."""
    street = SimpleNamespace(points_m=[(0.0, 5.0), (100.0, 5.0)], half_width_m=4.0, highway="residential",
                             is_drivable=True, layer=0, map_level=0)
    unlevelled = SimpleNamespace(points_m=[(0.0, 50.0), (100.0, 50.0)], half_width_m=4.0, highway="residential",
                                 is_drivable=True, layer=0, map_level=None)
    aisle = SimpleNamespace(points_m=[(10.0, 20.0), (60.0, 20.0)], half_width_m=3.0, highway="service",
                            is_drivable=True, layer=-1, map_level=-1, tags={"level": "-1"})
    world = SimpleNamespace(ways=[street, unlevelled, aisle], railways=[], waters=[], buildings=[], level_ways=[aisle])
    chunk = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    assert [road["points"][0] for road in chunk["roads"]] == [[0.0, 5.0], [0.0, 50.0]]
    assert len(chunk["level_roads"]) == 1 and -1 in chunk["level_roads"][0][0]  # still there, for its level


def test_garage_crossings_and_bumps_are_not_surface_markings():
    """Bug: a crossing on a level -1 garage aisle was drawn over the street
    map (the OSM build snaps it to its road at layer 0, whatever the level)."""
    street = SimpleNamespace(points_m=[(0.0, 0.0), (100.0, 0.0)], half_width_m=4.0, highway="residential",
                             is_drivable=True, layer=0, map_level=None)
    aisle = SimpleNamespace(points_m=[(100.0, 0.0), (100.0, 60.0)], half_width_m=3.0, highway="service",
                            is_drivable=True, layer=0, map_level=-1)  # its mouth meets the street at (100, 0)
    mark = lambda x, y: SimpleNamespace(x=x, y=y, direction_angle=0.0, width_m=4.0, length_m=2.4, kind="bump")
    world = SimpleNamespace(ways=[street, aisle], railways=[], waters=[], buildings=[], level_ways=[aisle],
                            crossings=[mark(50.0, 0.0), mark(100.0, 30.0), mark(100.0, 0.0)],
                            speed_bumps=[mark(100.0, 45.0), mark(20.0, 0.1)])
    chunk = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    assert [c[:2] for c in chunk["crossings"]] == [[50.0, 0.0], [100.0, 0.0]]  # the street's and the ramp mouth's
    assert [b[:2] for b in chunk["speed_bumps"]] == [[20.0, 0.1]]
