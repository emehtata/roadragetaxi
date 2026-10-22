"""Camping props follow mapped pitches and stay clear of access routes."""
from types import SimpleNamespace

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Polygon, box

from theroadragetrip.map_chunks import ChunkIndex
from theroadragetrip.osm import Building, Railing, Water, Way, build_ways
from theroadragetrip.osm.campsites import populate_camp_pitches
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def pitches():
    nodes = {i:(i*14.,0.) for i in range(1,9)}
    elements = [dict(type="node",id=i,tags={"tourism":"camp_pitch"}) for i in nodes]
    return elements,nodes


def footprint(obj):
    length,width = (3.2,2.4) if obj.kind == "tent" else (6.2,2.5)
    return translate(rotate(box(-length/2,-width/2,length/2,width/2),obj.direction_angle,use_radians=True),obj.x,obj.y)


def test_mapped_pitches_have_repeatable_mixed_occupancy_and_empty_spaces():
    elements,nodes = pitches()
    objects = populate_camp_pitches(elements,nodes,[],[],[],[])
    assert 2 < len(objects) < len(nodes)
    assert {o.kind for o in objects} == {"tent","camper_van"}
    assert objects == populate_camp_pitches(elements,nodes,[],[],[],[])
    subset = populate_camp_pitches(elements[2:],nodes,[],[],[],[])
    assert [(o.id,o.kind) for o in subset] == [(o.id,o.kind) for o in objects if o.id not in {-1,-2}]
    assert all((o.x,o.y) in nodes.values() for o in objects)
    for i,obj in enumerate(objects):
        assert all(footprint(obj).distance(footprint(other)) > .8 for other in objects[:i])
    world = SimpleNamespace(ways=[],railways=[],waters=[],buildings=[],sceneries=[],scenery_objects=objects)
    index = ChunkIndex(world)
    assert sum(len(chunk["scenery_objects"]) for chunk in index._chunks.values()) == len(objects)


def test_footprints_avoid_buildings_water_roads_and_hedges():
    elements,nodes = pitches()
    building = Building([(11,-4),(17,-4),(17,4),(11,4)])
    water = Water([(25,-4),(31,-4),(31,4),(25,4)],"water",True)
    road = Way([(40,-6),(44,6)],"service",2)
    hedge = Railing([(54,-6),(58,6)],kind="hedge")
    objects = populate_camp_pitches(elements,nodes,[building],[water],[road],[hedge])
    assert objects
    blockers = [Polygon(building.points_m), Polygon(water.points_m), LineString(road.points_m).buffer(road.half_width_m),LineString(hedge.points_m).buffer(.5)]
    assert all(not footprint(obj).intersects(blocker) for obj in objects for blocker in blockers)
    assert all(o.id not in {-1,-2,-3,-4} for o in objects)


def test_pitch_restrictions_layers_and_incomplete_ways():
    elements,nodes = pitches()
    elements[0]["tags"].update(tents="no")
    elements[1]["tags"].update(caravans="no",motorhome="no")
    elements[2]["tags"].update(layer="1")
    elements[3]["tags"].update(indoor="yes")
    elements += [dict(type="way",id=99,nodes=[1,2,999,1],tags={"tourism":"camp_pitch"})]
    objects = populate_camp_pitches(elements,nodes,[],[],[],[])
    assert next(o for o in objects if o.id == -1).kind == "camper_van"
    assert next(o for o in objects if o.id == -2).kind == "tent"
    assert all(o.id not in {-3,-4,-99} for o in objects)


def test_osm_campsite_area_and_pitch_objects_survive_cache(tmp_path):
    positions = [(60,25),(60,25.003),(60.002,25.003),(60.002,25),(60.001,25.001),(60.001,25.002)]
    elements = [dict(type="node",id=i,lat=lat,lon=lon,**({"tags":{"tourism":"camp_pitch"}} if i>4 else {})) for i,(lat,lon) in enumerate(positions,1)]
    elements += [dict(type="way",id=20,nodes=[1,2,3,4,1],tags={"tourism":"camp_site","name":"Camping"})]
    world = build_ways(elements)
    assert any(s.kind == "camp_site" for s in world.sceneries)
    props = [o for o in world.scenery_objects if o.kind in {"tent","camper_van"}]
    assert len(props) == 1  # pitch 5 is deliberately left empty
    path = tmp_path / "camp.rwc"
    BinaryWorldCacheWriter().write(path,world,area_id="camp")
    assert [o for o in BinaryWorldCacheLoader().load(path).scenery_objects if o.kind in {"tent","camper_van"}] == props


def test_small_polygon_pitch_fits_a_tent_instead_of_a_camper():
    nodes = {1:(0,0),2:(4,0),3:(4,3),4:(0,3)}
    elements = [dict(type="way",id=2,nodes=[1,2,3,4,1],tags={"tourism":"camp_pitch"})]
    obj, = populate_camp_pitches(elements,nodes,[],[],[],[])
    assert obj.kind == "tent"
    assert Polygon(list(nodes.values())).covers(footprint(obj))
