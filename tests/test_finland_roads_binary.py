import json
import shutil
import struct
import subprocess

import pytest

from tools.osm.build_finland_roads import (
    COORDINATE_SCALE,
    DRIVABLE_HIGHWAY_TYPES,
    FORMAT_VERSION,
    HEADER,
    MAGIC,
    WAY,
    RoadDatasetError,
    RoadWay,
    V2DatasetWriter,
    V2_HEADER,
    analyze_road_binary,
    build_finland_roads,
    compare_road_datasets,
    decode_coordinate,
    encode_coordinate,
    load_road_dataset,
    validate_road_dataset,
    write_road_dataset,
)


def _fixture():
    nodes = {
        10: (encode_coordinate(65.0123456), encode_coordinate(25.4687654)),
        11: (encode_coordinate(65.013), encode_coordinate(25.469)),
    }
    ways = [RoadWay(
        osm_id=20,
        highway="residential",
        node_ids=(10, 11),
        oneway=1,
        layer=1,
        lanes=2,
        maxspeed_kmh=40,
        name="Testitie",
        ref="123",
        junction="roundabout",
        surface="asphalt",
        bridge=True,
    )]
    return nodes, ways


def test_highway_whitelist_is_exact():
    assert DRIVABLE_HIGHWAY_TYPES == {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary",
        "primary_link", "secondary", "secondary_link", "tertiary",
        "tertiary_link", "unclassified", "residential", "living_street",
        "service", "road",
    }
    assert DRIVABLE_HIGHWAY_TYPES.isdisjoint({"footway", "path", "cycleway", "track"})


def test_coordinate_encoding_round_trip():
    value = 65.0123456
    assert encode_coordinate(value) == 650123456
    assert decode_coordinate(encode_coordinate(value)) == pytest.approx(value, abs=1 / COORDINATE_SCALE)


def test_binary_header_and_round_trip(tmp_path):
    path = tmp_path / "roads.bin"
    nodes, ways = _fixture()
    write_road_dataset(path, nodes, ways)

    magic, version, exponent, flags, node_count, way_count = HEADER.unpack(path.read_bytes()[:HEADER.size])
    assert (magic, version, exponent, flags, node_count, way_count) == (MAGIC, FORMAT_VERSION, 7, 0, 2, 1)
    loaded = load_road_dataset(path)
    assert loaded.nodes == nodes
    assert loaded.ways == tuple(ways)
    assert validate_road_dataset(path) == {"nodes": 2, "ways": 1}


def test_malformed_binary_is_rejected(tmp_path):
    path = tmp_path / "broken.bin"
    path.write_bytes(b"not a road file")
    with pytest.raises(RoadDatasetError):
        load_road_dataset(path)


def test_trailing_data_is_rejected(tmp_path):
    path = tmp_path / "roads.bin"
    nodes, ways = _fixture()
    write_road_dataset(path, nodes, ways)
    path.write_bytes(path.read_bytes() + b"junk")
    with pytest.raises(RoadDatasetError, match="trailing"):
        load_road_dataset(path)


def test_missing_referenced_node_is_rejected(tmp_path):
    path = tmp_path / "roads.bin"
    nodes, ways = _fixture()
    write_road_dataset(path, nodes, ways)
    data = bytearray(path.read_bytes())
    first_way_offset = HEADER.size + len(nodes) * struct.calcsize("<qii")
    first_ref_offset = first_way_offset + WAY.size
    struct.pack_into("<q", data, first_ref_offset, 999)
    path.write_bytes(data)
    with pytest.raises(RoadDatasetError, match="missing node 999"):
        load_road_dataset(path)


def test_statistics_json_shape(tmp_path):
    stats = {
        "format_version": FORMAT_VERSION,
        "input_file_size": 100,
        "output_file_size": 25,
        "total_ways": 4,
        "drivable_ways": 1,
        "total_nodes": 5,
        "stored_nodes": 2,
        "geometry_points": 2,
        "highway_types": {"residential": 1},
        "processing_seconds": 0.1,
    }
    path = tmp_path / "roads.stats.json"
    path.write_text(json.dumps(stats))
    loaded = json.loads(path.read_text())
    assert loaded["format_version"] == 1
    assert loaded["output_file_size"] / loaded["input_file_size"] == 0.25


def test_v2_is_smaller_than_v1_for_repeated_road_records(tmp_path):
    nodes = {
        node_id: (encode_coordinate(60.0 + node_id / 100_000), encode_coordinate(25.0))
        for node_id in range(1, 1002)
    }
    ways = [
        RoadWay(
            osm_id=10_000 + index,
            highway="residential",
            node_ids=(index + 1, index + 2),
            name="Repeated Road",
            surface="asphalt",
        )
        for index in range(1000)
    ]
    v1_path = tmp_path / "roads_v1.bin"
    v2_path = tmp_path / "roads_v2.bin"
    write_road_dataset(v1_path, nodes, ways)
    sections = tmp_path / "sections"
    sections.mkdir()
    writer = V2DatasetWriter(sections)
    for node_id, (latitude, longitude) in nodes.items():
        writer.write_node(node_id, latitude, longitude)
    for way in ways:
        writer.write_way(way)
    writer.finish(v2_path)

    second_sections = tmp_path / "second_sections"
    second_sections.mkdir()
    second_v2 = tmp_path / "roads_v2_again.bin"
    writer = V2DatasetWriter(second_sections)
    for node_id, (latitude, longitude) in nodes.items():
        writer.write_node(node_id, latitude, longitude)
    for way in ways:
        writer.write_way(way)
    writer.finish(second_v2)

    assert v2_path.stat().st_size < v1_path.stat().st_size
    assert v2_path.read_bytes() == second_v2.read_bytes()
    assert compare_road_datasets(v1_path, v2_path)["validation"] == "PASS"


def test_v2_invalid_local_node_reference_is_rejected(tmp_path):
    nodes, ways = _fixture()
    sections = tmp_path / "sections"
    sections.mkdir()
    path = tmp_path / "roads_v2.bin"
    writer = V2DatasetWriter(sections)
    for node_id, (latitude, longitude) in nodes.items():
        writer.write_node(node_id, latitude, longitude)
    writer.write_way(ways[0])
    writer.finish(path)

    data = bytearray(path.read_bytes())
    geometry_offset = V2_HEADER.unpack(data[:V2_HEADER.size])[11]
    data[geometry_offset] = 127
    path.write_bytes(data)

    with pytest.raises(RoadDatasetError, match="invalid local node"):
        validate_road_dataset(path)


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires osmium-tool")
def test_build_from_small_pbf_and_write_statistics(tmp_path):
    source_xml = tmp_path / "source.osm"
    source_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="65.0" lon="25.0"/>
          <node id="2" lat="65.1" lon="25.1"/>
          <node id="3" lat="65.2" lon="25.2"/>
          <way id="10">
            <nd ref="1"/><nd ref="2"/>
            <tag k="highway" v="residential"/>
            <tag k="name" v="Testitie"/>
            <tag k="maxspeed" v="40"/>
          </way>
          <way id="11">
            <nd ref="2"/><nd ref="3"/>
            <tag k="highway" v="footway"/>
          </way>
        </osm>
        """,
        encoding="utf-8",
    )
    source_pbf = tmp_path / "source.osm.pbf"
    subprocess.run(["osmium", "cat", str(source_xml), "-o", str(source_pbf)], check=True)
    output = tmp_path / "finland_roads.bin"

    stats = build_finland_roads(source_pbf, output)

    assert stats["total_ways"] == 2
    assert stats["drivable_ways"] == 1
    assert stats["stored_nodes"] == 2
    assert stats["geometry_points"] == 2
    assert stats["highway_types"]["residential"] == 1
    assert stats["validation"] == "PASS"
    assert json.loads(output.with_suffix(".stats.json").read_text()) == stats
    loaded_v1 = load_road_dataset(output)
    assert loaded_v1.ways[0].name == "Testitie"

    output_v2 = tmp_path / "finland_roads_v2.bin"
    stats_v2 = build_finland_roads(source_pbf, output_v2, format_version=2)
    loaded_v2 = load_road_dataset(output_v2)
    assert stats_v2["format_version"] == 2
    assert loaded_v2.ways[0].name == "Testitie"
    assert nodes_for(loaded_v2) == nodes_for(loaded_v1)
    assert compare_road_datasets(output, output_v2)["validation"] == "PASS"
    analysis = analyze_road_binary(output_v2)
    assert analysis["format_version"] == 2
    assert sum(analysis["sections"].values()) == output_v2.stat().st_size


def nodes_for(dataset):
    return [dataset.nodes[node_id] for node_id in dataset.ways[0].node_ids]
