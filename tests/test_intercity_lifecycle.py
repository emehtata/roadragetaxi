from io import BytesIO
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from theroadragetrip.intercity import IntercityGraph, ROAD_CLASSES, build_xml
from theroadragetrip.intercity_places import GATEWAY_VERSION, EXTENT_M, _extract_town_regions, attach_gateways, place_id, prepare_gateways
from theroadragetrip.intercity_navigation import IntercityPlanner
from theroadragetrip.navigation_route import NavigationRoute
from theroadragetrip.osm import AutoFetchManager, Way
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager, TaxiPassenger, TaxiState, TaxiTarget
from theroadragetrip.tile_streaming import TileCoord, active_tiles
from theroadragetrip.traffic_world import TrafficWorld


def build(path, *, local=False, disconnected=False):
    xml = '<osm version="0.6">'+''.join(f'<node id="{i}" lon="{x}" lat="{y}"/>' for i,x,y in
        [(1,0,0),(2,1000,0),(3,20000,0),(4,20100,0),(5,20000,200),(6,20100,200),(7,20200,0)])
    xml += '<way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/></way>'
    xml += '<way id="20"><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/></way>'
    if local:
        xml += '<way id="30"><nd ref="3"/><nd ref="4"/><nd ref="7"/><tag k="highway" v="residential"/></way>'
        if disconnected:
            xml += '<way id="40"><nd ref="5"/><nd ref="6"/><tag k="highway" v="residential"/></way>'
    build_xml(BytesIO((xml+'</osm>').encode()),path,lambda x,y:(x,y),
              (*ROAD_CLASSES,'residential') if local else ROAD_CLASSES,connector_extract=local)
    return path


def test_town_source_is_spatially_reduced_before_street_filtering(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('theroadragetrip.intercity_places.subprocess.run',lambda args,**kwargs:calls.append(args))
    polygon = tmp_path/'regions.geojson'
    _extract_town_regions('osmium',tmp_path/'finland.pbf',tmp_path/'regions.pbf',polygon,
                          [('a','A',0,0,1,None),('b','B',EXTENT_M,0,1,None)],lambda x,y:(x,y))
    geometry = json.loads(polygon.read_text())['geometry']
    assert geometry['type'] == 'Polygon'  # overlapping areas are merged for one cheap spatial test
    xs = [point[0] for point in geometry['coordinates'][0]]
    assert min(xs) == -EXTENT_M and max(xs) == 2*EXTENT_M
    assert calls == [['osmium','extract','-s','simple','-p',str(polygon),str(tmp_path/'finland.pbf'),
                      '-o',str(tmp_path/'regions.pbf')]]


def test_gateway_preparation_falls_back_only_for_missing_places(monkeypatch):
    places = [('a','A',0,0,1,None),('b','B',1,0,1,None)]
    calls = []
    monkeypatch.setattr('theroadragetrip.intercity_places.catalogue',lambda:places)
    def prepare(source,path,selected,classes,**kwargs):
        calls.append(([place[0] for place in selected],classes,kwargs.get('append',False),kwargs))
        if len(calls) == 1:
            return {'supported':['a'],'missing':[{'id':'b'}],'connectors':[]}
        return {'supported':['a','b'],'missing':[],'connectors':[]}
    monkeypatch.setattr('theroadragetrip.intercity_places._prepare_gateway_pass',prepare)
    assert prepare_gateways('source','output')['supported'] == ['a','b']
    assert calls[0][0] == ['a','b'] and calls[0][2] is False
    assert calls[1][0] == ['b'] and calls[1][2] is True
    assert [place[0] for place in calls[1][3]['region_places']] == ['a','b']


def test_gateway_fallback_merges_places_and_reports(tmp_path):
    path = build(tmp_path/'national.sqlite')
    local = build(tmp_path/'local.sqlite',local=True)
    first = place_id('First',20200,0)
    second = place_id('Second',20200,0)
    attach_gateways(path,local,[(first,'First',20200,0,1,None)])
    report = attach_gateways(path,local,[(second,'Second',20200,0,1,None)],append=True)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM places').fetchone()[0] == 2
    assert report['supported'] == [first,second] and not report['missing']


def prepared(tmp_path):
    path = build(tmp_path/'national.sqlite')
    local = build(tmp_path/'local.sqlite',local=True)
    identity = place_id('Town',20200,0)
    report = attach_gateways(path,local,[(identity,'Town',20200,0,100,None)])
    assert report['supported'] == [identity]
    return path,identity


def test_gateway_uses_connected_osm_roads_not_nearest_carriageway(tmp_path):
    path = build(tmp_path/'national.sqlite')
    local = build(tmp_path/'local.sqlite',local=True,disconnected=True)
    # All three nearest street anchors for this landmark are disconnected.
    missing = place_id('Island',20000,950,'airport')
    good = place_id('Town',20200,0)
    report = attach_gateways(path,local,[(missing,'Island',20000,950,1,'airport'),(good,'Town',20200,0,100,None)])
    assert report['supported'] == [good]
    assert report['missing'][0]['id'] == missing
    graph = IntercityGraph(path)
    try:
        anchor = graph.db.execute('SELECT anchor FROM places WHERE id=?',(good,)).fetchone()[0]
        assert graph.route(1,anchor).points[-1] == (20200,0)
        assert graph.metadata['gateway_version'] == GATEWAY_VERSION
        assert graph.metadata['junction_nodes'] == len(graph.nodes)
        assert graph.db.execute("SELECT COUNT(*) FROM segments WHERE way=40").fetchone()[0] == 0
    finally:
        graph.close()
    assert place_id('Town',0,0) != place_id('Town',20000,0)


def test_background_planner_reuses_route_and_rejects_unloaded_departure(tmp_path):
    path,identity = prepared(tmp_path)
    way = Way([(0,0),(1000,0)],'primary',4,osm_id=10)
    traffic = TrafficWorld([way])
    planner = IntercityPlanner(path)
    try:
        result = planner.request((100,0),identity,traffic.route_graph(),ways=(way,)).result(5)
        assert result and result['points'][0] == (100,0) and result['points'][-1] == (20200,0)
        assert result['place_id'] == identity and result['segments']
        cached = list(planner.cache.values())
        assert planner.request((100,0),identity,traffic.route_graph(),ways=(way,)).result(5) == result
        assert list(planner.cache.values()) == cached
        assert planner.request((100,0),identity,traffic.route_graph(),ways=()).result(5) is None
        assert planner.request((100,0),'missing',traffic.route_graph(),ways=(way,)).result(5) is None
    finally:
        planner.close()


def finish(nav,world,car):
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        nav.update(world,car)
        if nav._future is None and nav._job is None:
            return
        time.sleep(.001)
    pytest.fail('navigation did not finish')


def test_real_streaming_final_address_handoff_preserves_group(tmp_path):
    path,identity = prepared(tmp_path)
    road = Way([(0,0),(1000,0)],'primary',4,osm_id=10)
    traffic = TrafficWorld([road])
    taxi = TaxiManager([road])
    town = TaxiTarget(20200,0,'Town',municipality='Town',intercity_place_id=identity)
    companion = TaxiPassenger('Companion',TaxiTarget(0,0,'Start'),town,boarded=True)
    passenger = TaxiPassenger('Passenger',TaxiTarget(0,0,'Start'),town,boarded=True,companions=[companion])
    taxi.current_passenger = passenger
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    priorities = []
    manager = SimpleNamespace(set_route_tiles=lambda tiles:priorities.append(tiles))
    world = SimpleNamespace(traffic_mgr=traffic,taxi_mgr=taxi,intercity_database=path,auto_fetch_manager=manager)
    car = Car(x=100,y=0,heading=0,speed=0)
    nav = NavigationRoute()
    try:
        finish(nav,world,car)
        assert nav.points and nav._national
        plans = nav.plans_started
        traffic.route_graph_revision += 1
        finish(nav,world,car)
        assert nav.plans_started == plans  # tile merges do not invalidate the national route
        assert priorities and all(len(tiles) <= 3 for tiles in priorities)
        assert any(tiles for tiles in priorities)  # even the 19-km straight segment gets lookahead
        car.x = 20000
        taxi.update(car,.1)
        assert passenger.dropoff is town  # no address before destination map arrives
        arrival = Way([(19900,0),(20300,0)],'residential',4,name='Arrival road',osm_id=30)
        taxi.sync_map_data([arrival])
        world.traffic_mgr = TrafficWorld([arrival])
        taxi.update(car,3)
        assert passenger.dropoff.municipality is None and companion.dropoff is passenger.dropoff
        finish(nav,world,car)
        assert nav._national is None and nav._future is None
        assert nav.points and priorities[-1] == []
        taxi.current_passenger = None
        nav.update(world,car)
        assert nav.instruction == {'maneuver':'no_target'} and not nav.points
    finally:
        nav.close()


def test_cancelled_intercity_job_cannot_publish_old_fare(tmp_path):
    path,identity = prepared(tmp_path)
    way = Way([(0,0),(1000,0)],'primary',4,osm_id=10)
    taxi = SimpleNamespace(target=TaxiTarget(20200,0,'Town',municipality='Town',intercity_place_id=identity))
    taxi.get_current_target = lambda:taxi.target
    world = SimpleNamespace(taxi_mgr=taxi,traffic_mgr=TrafficWorld([way]),intercity_database=path)
    car = Car(x=100,y=0,heading=0,speed=0)
    nav = NavigationRoute()
    try:
        nav.update(world,car)
        taxi.target = TaxiTarget(800,0,'Local')
        finish(nav,world,car)
        assert nav._national is None and nav.points[-1] == [800,0]
    finally:
        nav.close()


def test_route_tile_priorities_are_bounded_and_removed_on_cancel():
    manager = AutoFetchManager([], (0,0,1000,1000),transformer=None)
    manager.update_player_tile(500,500)
    core = set(active_tiles(TileCoord(0,0)))
    manager.set_route_tiles([TileCoord(i,0) for i in range(2,20)])
    manager.update_player_tile(500,500)
    assert len(manager.active_tiles-core) == 3
    manager.set_route_tiles([])
    manager.update_player_tile(500,500)
    assert manager.active_tiles == core


def test_gateway_failure_does_not_replace_previous_database(tmp_path,monkeypatch):
    from theroadragetrip.intercity import prepare_database
    source = tmp_path/'source.pbf'
    source.write_bytes(b'placeholder')
    path = build(tmp_path/'national.sqlite')
    previous = path.read_bytes()
    monkeypatch.setattr('theroadragetrip.intercity.build_pbf',lambda a,b:build(b))
    def fail(*args):
        raise ValueError('No usable gateways')
    monkeypatch.setattr('theroadragetrip.intercity_places.prepare_gateways',fail)
    with pytest.raises(ValueError,match='No usable gateways'):
        prepare_database(source,path)
    assert path.read_bytes() == previous


def test_departure_preserves_the_incoming_turn_restriction(tmp_path):
    path = tmp_path/'turn.sqlite'
    xml = '''<osm version="0.6"><node id="1" lon="0" lat="0"/>
    <node id="2" lon="100" lat="0"/><node id="3" lon="100" lat="100"/>
    <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/><tag k="oneway" v="yes"/></way>
    <way id="20"><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/><tag k="oneway" v="yes"/></way>
    <relation id="99"><member type="way" role="from" ref="10"/><member type="way" role="to" ref="20"/>
    <member type="node" role="via" ref="2"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation></osm>'''
    build_xml(BytesIO(xml.encode()),path,lambda x,y:(x,y))
    graph = IntercityGraph(path)
    way = Way([(0,0),(100,0)],'primary',4,osm_id=10,oneway=1)
    try:
        incoming = IntercityPlanner._entry(graph,2,[(0,0),(100,0)],[way])
        assert incoming[0] == 10
        assert graph.route(2,3) is not None
        assert graph.route(2,3,incoming=incoming) is None
    finally:
        graph.close()


def test_preparation_records_bounded_connector_provenance(tmp_path):
    path,identity = prepared(tmp_path)
    report = json.loads(sqlite3.connect(path).execute('SELECT value FROM gateway_report').fetchone()[0])
    assert identity in report['supported']
    assert all(connector['in_m'] <= 8000 and connector['out_m'] <= 8000 for connector in report['connectors'])


def test_existing_landmark_aliases_and_source_ids_are_preserved(tmp_path,monkeypatch):
    identity = place_id('Town',20200,0)
    monkeypatch.setattr('theroadragetrip.intercity_places.landmark_provenance',
                        lambda:[(identity,'Staden','existing-place-id','["node", 123]')])
    path,_ = prepared(tmp_path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT place_id,source_id,source_osm FROM place_aliases WHERE alias=?',('Staden',)).fetchone() == (
            identity,'existing-place-id','["node", 123]')


def test_per_town_connector_policy_does_not_expand_the_backbone(tmp_path):
    path = build(tmp_path/'national.sqlite')
    local = build(tmp_path/'local.sqlite',local=True)
    identity = place_id('Town',20200,0)
    attach_gateways(path,local,[(identity,'Town',20200,0,100,None)],
                    town_policies={identity:{'classes':[],'max_length_m':50}})
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT anchor FROM places').fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM segments WHERE highway='residential'").fetchone()[0] == 0
