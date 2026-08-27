from theroadragetrip.osm import _stitch_member_ways_into_rings


def test_stitch_open_riverbank_not_closed():
    # Two open segments along a riverbank (does not close)
    ways_by_id = {
        10: {"nodes": [1, 2, 3]},
        11: {"nodes": [3, 4, 5]},
    }
    nodes_m = {
        1: (0.0, 0.0),
        2: (10.0, 5.0),
        3: (20.0, 10.0),
        4: (30.0, 15.0),
        5: (40.0, 20.0),
    }

    def process_node_ids(node_ids):
        return [nodes_m[nid] for nid in node_ids]

    rings = _stitch_member_ways_into_rings([10, 11], ways_by_id, process_node_ids)
    assert len(rings) == 1
    pts, is_closed = rings[0]
    assert len(pts) == 5
    assert is_closed is False  # Not closed, so should not be filled as a massive diagonal polygon!


def test_stitch_closed_lake_multipolygon():
    # Three outer ways that form a triangle loop
    ways_by_id = {
        10: {"nodes": [1, 2]},
        11: {"nodes": [2, 3]},
        12: {"nodes": [3, 1]},
    }
    nodes_m = {
        1: (0.0, 0.0),
        2: (10.0, 0.0),
        3: (5.0, 10.0),
    }

    def process_node_ids(node_ids):
        return [nodes_m[nid] for nid in node_ids]

    rings = _stitch_member_ways_into_rings([10, 11, 12], ways_by_id, process_node_ids)
    assert len(rings) == 1
    pts, is_closed = rings[0]
    assert len(pts) == 4
    assert is_closed is True
    assert pts[0] == pts[-1]
