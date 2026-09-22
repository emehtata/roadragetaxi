from tools.osm.benchmark_finland_roads import benchmark_dataset, current_rss_bytes
from tools.osm.build_finland_roads import (
    RoadWay,
    V2DatasetWriter,
    _haversine_m,
    encode_coordinate,
)


def test_benchmark_uses_real_v2_reader_and_geometry(tmp_path):
    coordinates = {
        100: (encode_coordinate(65.0), encode_coordinate(25.0)),
        101: (encode_coordinate(65.01), encode_coordinate(25.01)),
        102: (encode_coordinate(65.02), encode_coordinate(25.02)),
    }
    ways = (
        RoadWay(200, "residential", (100, 101), name="First Road"),
        RoadWay(201, "service", (101, 102), surface="gravel"),
    )
    sections = tmp_path / "sections"
    sections.mkdir()
    binary = tmp_path / "roads_v2.bin"
    writer = V2DatasetWriter(sections)
    for node_id, (latitude, longitude) in coordinates.items():
        writer.write_node(node_id, latitude, longitude)
    for way in ways:
        writer.write_way(way)
    writer.finish(binary)
    expected_length_km = (
        _haversine_m(coordinates[100], coordinates[101])
        + _haversine_m(coordinates[101], coordinates[102])
    ) / 1000.0

    result = benchmark_dataset(
        binary,
        expected={
            "ways": 2,
            "nodes": 3,
            "geometry_points": 4,
            "road_length_km": expected_length_km,
        },
        sample_sizes=(10, 50),
    )

    assert result["validation"] == "PASS"
    assert result["format_version"] == 2
    assert result["ways"] == 2
    assert result["nodes"] == 3
    assert result["geometry_points"] == 4
    assert result["lookups"]["geometry"]["50"]["points_touched"] == 100
    assert result["nearest_road"] == "NOT IMPLEMENTED IN CURRENT V2 REPRESENTATION"
    assert result["parse_time_ms"] >= 0.0
    assert current_rss_bytes() > 0
