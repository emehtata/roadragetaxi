from io import BytesIO
import sqlite3

import pytest

from theroadragetrip.intercity import IntercityGraph, ROAD_CLASSES, build_xml


def fixture(tmp_path,nodes,ways,relations=""):
    xml = '<osm version="0.6">'+"".join(f'<node id="{i}" lon="{x}" lat="{y}"/>' for i,x,y in nodes)
    for identifier,refs,tags in ways:
        tags = {"highway":"primary",**tags}
        xml += f'<way id="{identifier}">'+"".join(f'<nd ref="{ref}"/>' for ref in refs)
        xml += "".join(f'<tag k="{key}" v="{value}"/>' for key,value in tags.items())+"</way>"
    path = tmp_path/"intercity.sqlite"
    stats = build_xml(BytesIO((xml+relations+"</osm>").encode()),path,lambda x,y:(x,y))
    return path,stats


def restriction(incoming,outgoing,via,kind,via_type="node"):
    return f'<relation id="900"><member type="way" role="from" ref="{incoming}"/><member type="{via_type}" role="via" ref="{via}"/><member type="way" role="to" ref="{outgoing}"/><tag k="type" v="restriction"/><tag k="restriction" v="{kind}"/></relation>'


def test_build_stage_is_reported_even_before_the_first_large_parse_batch(tmp_path, monkeypatch):
    from theroadragetrip import intercity
    messages = []
    monkeypatch.setattr(intercity, "_report", messages.append)
    fixture(tmp_path, [(1, 0, 0), (2, 100, 0)], [(10, [1, 2], {})])
    assert messages == ["2/4"]


def test_geometry_is_compacted_once_and_reconstructed_in_both_directions(tmp_path):
    path,stats = fixture(tmp_path,[(1,0,0),(2,50,10),(3,100,0)],[(10,[1,2,3],{})])
    assert stats["source_geometry_nodes"] == 3 and stats["junction_nodes"] == 2
    assert stats["segments"] == 1 and stats["directed_segments"] == 2
    graph = IntercityGraph(path)
    try:
        route = graph.route(1,3)
        assert route.points == ((0,0),(50,10),(100,0))
        assert graph.route(3,1).points == tuple(reversed(route.points))
        assert route.distance_m == pytest.approx(2*(50**2+10**2)**0.5)
        assert route.duration_s == pytest.approx(route.distance_m/(80/3.6))
    finally:
        graph.close()


def test_oneway_and_true_topology_at_crossings(tmp_path):
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0),(3,100,0),(4,100,100)],
                     [(10,[1,2],{"oneway":"yes"}),(20,[3,4],{"bridge":"yes","layer":"1"})])
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,2) is not None
        assert graph.route(2,1) is None
        assert graph.route(1,4) is None
        assert graph.route(1,999) is None
        assert graph.connectivity()["weak_components"] == 2
    finally:
        graph.close()


def test_shared_osm_junction_is_preserved(tmp_path):
    path,stats = fixture(tmp_path,[(1,0,0),(2,100,0),(3,200,0),(4,100,100)],
                         [(10,[1,2,3],{}),(20,[2,4],{})])
    graph = IntercityGraph(path)
    try:
        assert 2 in graph.nodes and graph.route(1,4).points == ((0,0),(100,0),(100,100))
    finally:
        graph.close()


def test_time_cost_can_choose_a_longer_but_faster_road(tmp_path):
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0),(3,50,50)],
                     [(10,[1,2],{"maxspeed":"20"}),(20,[1,3,2],{"maxspeed":"100"})])
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,2).points == ((0,0),(50,50),(100,0))
    finally:
        graph.close()


@pytest.mark.parametrize("kind",["no_left_turn","only_straight_on"])
def test_node_restrictions_survive_compaction(tmp_path,kind):
    target = 20 if kind.startswith("no_") else 30
    relation = restriction(10,target,2,kind)
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0),(3,100,100),(4,200,0)],
                     [(10,[1,2],{"oneway":"yes"}),(20,[2,3],{"oneway":"yes"}),(30,[2,4],{"oneway":"yes"})],relation)
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,3) is None
        assert graph.route(1,4) is not None
    finally:
        graph.close()


def test_via_way_restriction_survives_compaction(tmp_path):
    relation = restriction(10,30,20,"no_straight_on","way")
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0),(3,200,0),(4,300,0)],
                     [(10,[1,2],{"oneway":"yes"}),(20,[2,3],{"oneway":"yes"}),(30,[3,4],{"oneway":"yes"})],relation)
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,4) is None
        assert graph.route(2,4) is not None
    finally:
        graph.close()


def test_only_via_way_restriction_blocks_early_exit(tmp_path):
    relation = restriction(10,30,20,"only_straight_on","way")
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0),(3,200,0),(4,300,0),(5,200,100)],
                     [(10,[1,2],{"oneway":"yes"}),(20,[2,3],{"oneway":"yes"}),
                      (30,[3,4],{"oneway":"yes"}),(40,[3,5],{"oneway":"yes"})],relation)
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,4) is not None
        assert graph.route(1,5) is None
    finally:
        graph.close()


def test_directional_vehicle_access_is_respected(tmp_path):
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0)],[(10,[1,2],{"motor_vehicle:backward":"no"})])
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,2) is not None
        assert graph.route(2,1) is None
    finally:
        graph.close()


def test_backbone_excludes_local_streets_and_private_roads(tmp_path):
    path,stats = fixture(tmp_path,[(1,0,0),(2,100,0),(3,200,0),(4,300,0)],
                         [(10,[1,2],{}),(20,[2,3],{"highway":"residential"}),
                          (30,[3,4],{"access":"private"})])
    assert stats["segments"] == 1
    assert "residential" not in stats["road_classes"]
    assert len(ROAD_CLASSES) == 8
    graph = IntercityGraph(path)
    try:
        assert graph.route(1,4) is None
    finally:
        graph.close()


def test_invalid_artifact_and_failed_build_preserve_previous_output(tmp_path):
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0)],[(10,[1,2],{})])
    original = path.read_bytes()
    with pytest.raises(ValueError,match="Incomplete"):
        build_xml(BytesIO(b'<osm><way id="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/></way></osm>'),path,lambda x,y:(x,y))
    assert path.read_bytes() == original
    with sqlite3.connect(path) as db:
        db.execute("UPDATE metadata SET value='{}'")
    with pytest.raises(ValueError,match="Invalid intercity"):
        IntercityGraph(path)


def test_corrupt_geometry_cannot_publish_a_disconnected_route(tmp_path):
    import struct
    import zlib
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0)],[(10,[1,2],{})])
    with sqlite3.connect(path) as db:
        db.execute("UPDATE segments SET geometry=?",(zlib.compress(struct.pack('<dddd',10,10,110,10)),))
    graph = IntercityGraph(path)
    try:
        with pytest.raises(ValueError,match="source junctions"):
            graph.route(1,2)
    finally:
        graph.close()


def test_user_initialization_reuses_matching_database_and_rebuilds_changed_source(tmp_path,monkeypatch):
    from theroadragetrip.intercity import prepare_database
    source = tmp_path/"finland.pbf"
    source.write_bytes(b"source")
    path,_ = fixture(tmp_path,[(1,0,0),(2,100,0)],[(10,[1,2],{})])
    stat = source.stat()
    import json
    with sqlite3.connect(path) as db:
        metadata = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        metadata["source"] = {"path":str(source.resolve()),"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
        metadata.update(gateway_version=1,gateway_places=1)
        from theroadragetrip.intercity_places import catalogue_digest
        metadata["catalogue_digest"] = catalogue_digest()
        from theroadragetrip.intercity_places import CONNECTOR_CLASSES
        metadata["connector_policy"] = {"extent_m":6000,"max_length_m":8000,"classes":list(CONNECTOR_CLASSES)}
        db.execute("UPDATE metadata SET value=?",(json.dumps(metadata),))
    calls = []
    def rebuild(a,b):
        import shutil
        calls.append(a)
        shutil.copyfile(path,b)
    monkeypatch.setattr("theroadragetrip.intercity.build_pbf",rebuild)
    monkeypatch.setattr("theroadragetrip.intercity_places.prepare_gateways",lambda a,b: None)
    assert prepare_database(source,path) == path and not calls
    source.write_bytes(b"updated source")
    prepare_database(source,path)
    assert calls == [source]


def test_intercity_initialization_is_explicitly_opt_in(monkeypatch):
    import sys
    import configparser
    from theroadragetrip.config import DEFAULT_CONFIG
    from theroadragetrip.game_args import parse_args
    config = configparser.ConfigParser()
    config.read_dict(DEFAULT_CONFIG)
    monkeypatch.setattr(sys,"argv",["server"])
    assert not parse_args(config).intercity_fares
    monkeypatch.setattr(sys,"argv",["server","--intercity-fares"])
    assert parse_args(config).intercity_fares
    monkeypatch.setattr(sys,"argv",["server","--no-intercity-fares"])
    assert not parse_args(config).intercity_fares
