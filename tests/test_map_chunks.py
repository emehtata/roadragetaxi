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
