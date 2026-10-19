import math
from types import SimpleNamespace

import pytest

from theroadragetrip import map_chunks


@pytest.mark.parametrize("kind", ["biergarten", "grave_yard"])
def test_point_sites_are_streamed_to_the_renderer(kind):
    from theroadragetrip.osm import SceneryObject

    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[],
                            scenery_objects=[SceneryObject(10, 20, kind)])
    assert map_chunks.ChunkIndex(world).message("0_0")["scenery_objects"] == [[10, 20, kind, 0.0]]


def test_runtime_camera_updates_only_its_chunk_and_invalidates_wire_cache():
    from theroadragetrip.police import SpeedCamera

    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[])
    index = map_chunks.ChunkIndex(world)
    before = index.encoded("0_0")
    other = index.encoded("2_0")
    camera = SpeedCamera(100, 100, 0, 50, 1)
    assert index.add_speed_camera(camera, 7) == "0_0"
    assert index.message("0_0")["speed_cameras"] == [[7, 100, 100, 0]]
    assert index.encoded("0_0") != before
    assert index.encoded("2_0") is other


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
    assert len(index.message("0_0")["roads"]) == 1  # the segment crosses it without a vertex there
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
    # their render position (protocol.traffic_light_render_point); a non-renderable post is not sent.
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


@pytest.mark.parametrize("kind", ["biergarten", "grave_yard", "cemetery"])
def test_decorated_site_kind_survives_chunk_clipping(kind):
    from theroadragetrip.osm import Scenery

    points = [(100, 100), (600, 100), (600, 200), (100, 200)]
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[],
                            sceneries=[Scenery(points, kind, bbox=(100, 100, 600, 200))])
    index = map_chunks.ChunkIndex(world)
    for cid in ("0_0", "1_0"):
        area = index.message(cid)["landuse"][0]
        assert area[3] == kind and area[1] == 1
        assert all(int(cid[0]) * 500 <= p[0] <= (int(cid[0]) + 1) * 500 for p in area[2])


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
    assert [l[0] for l in here["landuse"]] == [[100, 145, 80], [170, 142, 96]]  # park, construction (map_style.py colours)


def test_road_style_follows_the_map_style():
    from theroadragetrip import static_world
    from theroadragetrip.map_style import road_color_for_way

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


def test_parallel_tracks_form_one_bridge_over_a_below_grade_road():
    from shapely.geometry import Polygon
    from theroadragetrip import static_world
    from theroadragetrip.osm.models import Railway, Way

    road = Way([(50.0, -10.0), (50.0, 30.0)], "primary", 4.0, is_tunnel=True, layer=-1)
    tracks = [Railway([(0.0, y), (100.0, y)]) for y in (10.0, 17.0)]
    parts = static_world.rail_bridge_parts(tracks, [road])
    decks = static_world.rail_bridge_decks(tracks, [road])

    assert len(parts) == 2
    assert len(decks) == 1
    assert Polygon(decks[0]).bounds == pytest.approx((43.0, 8.3, 57.0, 18.7))

    world = _obstacle_world()
    world.ways = [road]
    world.railways = tracks
    chunk = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    assert len(chunk["rail_bridges"]) == 2
    assert len(chunk["rail_decks"]) == 1


def test_bus_stop_shapes_follow_the_nearest_road():
    """godot-16: a bus stop's bay and shelter, computed once."""
    from theroadragetrip import map_style, static_world

    road = SimpleNamespace(points_m=[(0.0, 0.0), (100.0, 0.0)], half_width_m=3.0, is_drivable=True, layer=0, highway="residential")
    stop = SimpleNamespace(x=50.0, y=6.0, layer=0, shelter=True, bench=True)
    shapes = static_world.bus_stop_shapes(stop, [road])
    assert shapes["bay"] == [[34.0, 3.0], [66.0, 3.0], [61.0, 6.0], [39.0, 6.0]]  # on the stop's side of the road
    assert shapes["color"] == list(map_style.road_color_for_way(road))  # the road's own asphalt
    # North of an eastbound road buses drive west: the sign at the bay's west (front) end; "BUS" upright.
    assert shapes["sign"] == [41.0, 7.6] and shapes["label"] == [50.0, 4.5] and shapes["angle"] == 0.0
    west = static_world.bus_stop_shapes(stop, [SimpleNamespace(**{**vars(road), "points_m": [(100.0, 0.0), (0.0, 0.0)]})])
    assert west["angle"] == 0.0 and west["sign"] == [41.0, 7.6]  # the way's direction changes neither
    assert shapes["shelter"] is not None and shapes["bench"] is None  # a shelter has its own seat
    assert static_world.bus_stop_shapes(SimpleNamespace(x=50.0, y=80.0, layer=0, shelter=False), [road]) is None  # beyond 45 m




def test_garage_aisles_are_not_sent_as_surface_roads():
    """Bug: a map_level -1 garage aisle (kept in world.ways) was sent with
    the surface roads, so Godot drew it over the street map. The surface
    roads are only SURFACE_MAP_LEVELS; underground roads are
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


def test_a_river_line_is_a_line_not_a_filled_area():
    """Only closed water areas are filled: Oulujoki's centre line
    (waterway=river, open) sent as an area flooded the city."""
    from types import SimpleNamespace

    from theroadragetrip.map_chunks import ChunkIndex

    lake = SimpleNamespace(points_m=[(10.0, 10.0), (60.0, 10.0), (60.0, 60.0), (10.0, 10.0)], is_polygon=True)
    river = SimpleNamespace(points_m=[(5.0, 5.0), (80.0, 30.0), (150.0, 90.0)], is_polygon=False)
    world = SimpleNamespace(ways=[], railways=[], waters=[lake, river], buildings=[])
    chunks = ChunkIndex(world)._chunks.values()
    assert sum(len(c["waters"]) for c in chunks) == 1
    assert sum(len(c["water_lines"]) for c in chunks) >= 1


def test_buildings_have_one_owner_and_their_facade_style():
    """godot-17: a building drawn as a volume belongs to one chunk (its
    centre's); its style carries the wall colour, floors and category the
    facades and windows use (building_style.py's picks)."""
    from theroadragetrip.osm.models import Building
    from theroadragetrip import building_style as rb
    from theroadragetrip import static_world

    across = Building([(480.0, 10.0), (530.0, 10.0), (530.0, 30.0), (480.0, 30.0)], building_type="apartments", levels=5)
    canopy = Building([(490.0, 100.0), (520.0, 100.0), (520.0, 120.0), (490.0, 120.0)], building_type="roof")
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[across, canopy])
    index = map_chunks.ChunkIndex(world, size=500.0)
    west, east = index.message("0_0"), index.message("1_0")
    assert west["buildings"] == [] and len(east["buildings"]) == 1  # centre x = 505: east owns it, once
    roof, gabled, height, entrances, wall, floors, category = east["building_styles"][0]
    assert floors == 5 and category == 0 and wall in [list(c) for c in rb.BUILDING_WALL_COLORS]
    assert rb.BUILDING_WALL_COLORS.index(tuple(wall)) == rb.BUILDING_ROOF_COLORS.index(tuple(roof))  # a matching wall and roof pair
    assert east["canopies"] and east["canopy_heights"] == [static_world.building_style(canopy)[2]]
    assert static_world.building_style(Building([(0, 0), (9, 0), (9, 9)], building_type="house"))[6] == 1


def test_a_region_update_matches_a_full_rebuild_and_keeps_the_other_chunks():
    def road(x0, x1, y):
        return SimpleNamespace(points_m=[(x0, y), (x1, y)], half_width_m=3.0, highway="primary", is_drivable=True,
                               layer=0, bbox=(x0, y, x1, y))

    old_roads = [road(0.0, 400.0, 10.0), road(3000.0, 3400.0, 10.0)]
    new_road = road(3100.0, 3900.0, 260.0)  # merged later, in and next to the far chunks only
    old = map_chunks.ChunkIndex(SimpleNamespace(ways=old_roads, railways=[], waters=[], buildings=[]))
    old.encoded("0_0")
    grown = SimpleNamespace(ways=old_roads + [new_road], railways=[], waters=[], buildings=[])
    index, changed = map_chunks.ChunkIndex.updated(old, grown, new_road.bbox)

    assert index._chunks == map_chunks.ChunkIndex(grown)._chunks
    assert changed == {"6_0", "7_0"}  # the chunks the new road reaches
    assert index._chunks["0_0"] is old._chunks["0_0"] and index._encoded["0_0"] is old._encoded["0_0"]  # untouched, kept


def test_a_region_update_keeps_the_encoding_of_a_rebuilt_chunk_that_did_not_change():
    def road(x0, x1, y):
        return SimpleNamespace(points_m=[(x0, y), (x1, y)], half_width_m=3.0, highway="primary", is_drivable=True,
                               layer=0, bbox=(x0, y, x1, y))

    old_roads = [road(3000.0, 3400.0, 10.0)]
    old = map_chunks.ChunkIndex(SimpleNamespace(ways=old_roads, railways=[], waters=[], buildings=[]))
    old.encoded("5_0")
    old.encoded("6_0")
    grown = SimpleNamespace(ways=old_roads + [road(3100.0, 3900.0, 260.0)], railways=[], waters=[], buildings=[])
    index, changed = map_chunks.ChunkIndex.updated(old, grown, (2600.0, 0.0, 3900.0, 300.0))  # 5_0 .. 7_0 rebuilt
    assert changed == {"6_0", "7_0"}
    assert index._encoded == {"5_0": old._encoded["5_0"]}  # the unchanged one isn't encoded again


def test_sports_fields_freeze_and_are_floodlit():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    pitch = [(10.0, 10.0), (110.0, 10.0), (110.0, 70.0), (10.0, 70.0)]
    world.sceneries = [Scenery(points_m=pitch, kind="pitch"), Scenery(points_m=[(200.0, 200.0), (260.0, 200.0), (260.0, 260.0)], kind="flowerbed")]
    here = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    assert [area[1] for area in here["landuse"]] == [2, 1]  # pitch: frozen to ice; flowerbed: snow
    assert len(here["floodlit"]) == 1  # only the pitch


def test_sports_lights_burn_only_from_7_to_22():
    from datetime import datetime
    from theroadragetrip.calendar import sports_lights_hours

    assert [sports_lights_hours(datetime(2026, 1, 10, h, 30)) for h in (6, 7, 21, 22)] == [False, True, True, False]


def test_nested_areas_draw_on_top_of_their_container():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    pitch = Scenery(points_m=[(10.0, 10.0), (60.0, 10.0), (60.0, 40.0), (10.0, 40.0)], kind="pitch")
    centre = Scenery(points_m=[(0.0, 0.0), (200.0, 0.0), (200.0, 150.0), (0.0, 150.0)], kind="sports_centre")
    world.sceneries = [pitch, centre]  # OSM order: the container last
    here = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    assert [area[1] for area in here["landuse"]] == [1, 2]  # sports centre (snowy) under, the pitch over it


def test_an_ice_rink_gets_its_boards_and_a_frame_for_its_hockey_markings():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    angle = 0.3  # a 60 x 30 m rink, turned
    corners = [(-30.0, -15.0), (30.0, -15.0), (30.0, 15.0), (-30.0, 15.0)]
    rink = [(100.0 + x * math.cos(angle) - y * math.sin(angle), 100.0 + x * math.sin(angle) + y * math.cos(angle)) for x, y in corners]
    world.sceneries = [Scenery(points_m=rink, kind="ice_rink")]
    here = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    (x, y, rink_angle, length, width), = here["rinks"]
    assert (round(x), round(y), round(length), round(width)) == (100, 100, 60, 30)
    assert round(math.cos(2 * (rink_angle - angle)), 6) == 1.0  # along the long side, either way
    assert [r[0] for r in here["railings"]].count("boards") == 1


def test_floodlit_fields_get_light_poles_round_them():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    pitch = [(100.0, 100.0), (200.0, 100.0), (200.0, 160.0), (100.0, 160.0)]
    next_pitch = [(200.0, 100.0), (300.0, 100.0), (300.0, 160.0), (200.0, 160.0)]  # shares a side
    tennis = [(100.0, 300.0), (124.0, 300.0), (124.0, 311.0), (100.0, 311.0)]
    world.sceneries = [Scenery(points_m=ring, kind="pitch") for ring in (pitch, next_pitch, tennis)]
    poles = map_chunks.ChunkIndex(world, size=500.0).message("0_0")["floodlight_poles"]
    assert sorted((round(p[0]), round(p[1])) for p in poles) == [  # corners and long-side middles, 2 m out
        (98, 98), (98, 162), (150, 98), (150, 162), (202, 98), (202, 162),  # the shared corners once
        (250, 98), (250, 162), (302, 98), (302, 162)]  # no poles for the tennis court
    for x, y, direction, reach in poles:  # street-light pools aimed into the field
        assert 15.0 <= reach <= 40.0
        assert max(math.cos(direction - math.atan2(130.0 - y, cx - x)) for cx in (150.0, 250.0)) > 0.99


def test_soccer_pitches_get_a_frame_for_their_lines():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    pitch = [(100.0, 100.0), (205.0, 100.0), (205.0, 168.0), (100.0, 168.0)]
    world.sceneries = [Scenery(points_m=pitch, kind="pitch", sport="soccer;pesäpallo"),
                       Scenery(points_m=[(300.0, 300.0), (330.0, 300.0), (330.0, 320.0), (300.0, 320.0)], kind="pitch", sport="tennis")]
    (frame,) = map_chunks.ChunkIndex(world, size=500.0).message("0_0")["soccer_pitches"]
    assert [round(v) for v in (frame[0], frame[1], frame[3], frame[4])] == [152, 134, 105, 68]


def test_kerbed_islands_and_traffic_islands_redraw_over_the_roads_and_only_rinks_get_hockey_lines():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    square = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]
    world.sceneries = [Scenery(points_m=square, kind="traffic_island"),
                       Scenery(points_m=[(x + 100, y) for x, y in square], kind="grass", kerbed=True),
                       Scenery(points_m=[(x + 200, y + 200) for x, y in square], kind="stadium")]
    here = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
    assert len(here["traffic_islands"]) == 2
    assert here["rinks"] == []  # a stadium is no rink


def test_a_stadium_gets_its_stands_round_an_open_pitch():
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    world.buildings = []
    outline = [(100.0, 100.0), (240.0, 100.0), (240.0, 200.0), (100.0, 200.0)]
    pitch = [(117.5, 116.0), (222.5, 116.0), (222.5, 184.0), (117.5, 184.0)]  # 105 x 68 inside
    for ring in (outline, outline[::-1]):  # either winding
        world.sceneries = [Scenery(points_m=ring, kind="stadium"), Scenery(points_m=pitch, kind="pitch", sport="soccer")]
        here = map_chunks.ChunkIndex(world, size=500.0).message("0_0")
        assert len(here["buildings"]) == 4 and all(s == map_chunks.STADIUM_STAND_STYLE for s in here["building_styles"])
        stands = unary_union([Polygon(piece) for piece in here["buildings"]])
        open_middle = Polygon(pitch).buffer(map_chunks.STADIUM_PITCH_MARGIN_M, join_style=2)
        assert abs(stands.area - (Polygon(outline).area - open_middle.area)) < 1.0  # the whole ring...
        assert stands.intersection(open_middle).area < 1.0  # ...and the pitch open
        assert not any(r[0] == "wall" for r in here["railings"])
    world.sceneries = [Scenery(points_m=outline, kind="stadium")]  # no pitch mapped: stands 15 m deep
    assert len(map_chunks.ChunkIndex(world, size=500.0).message("0_0")["buildings"]) == 4


def test_a_stadium_mapped_twice_gets_one_ring_of_stands():
    from theroadragetrip.osm.models import Scenery

    world = _obstacle_world()
    world.buildings = []
    outline = [(100.0, 100.0), (240.0, 100.0), (240.0, 200.0), (100.0, 200.0)]
    world.sceneries = [Scenery(points_m=outline, kind="stadium", name="Bolt Arena"), Scenery(points_m=outline[::-1], kind="stadium")]
    assert len(map_chunks.ChunkIndex(world, size=500.0).message("0_0")["buildings"]) == 4
