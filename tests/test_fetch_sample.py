from theroadragetrip import build_ways, load_local_sample


def test_sample_exists_and_is_list():
    els = load_local_sample()
    assert els is not None and isinstance(els, list) and len(els) > 0


def test_sample_covers_current_overpass_feature_tags():
    elements = load_local_sample()
    tags = [element.get("tags", {}) for element in elements]

    assert any(item.get("highway") == "stop" for item in tags)
    assert any(item.get("highway") == "give_way" for item in tags)
    assert any(item.get("highway") == "crossing" for item in tags)
    assert any(item.get("highway") == "taxi_stop" for item in tags)
    assert any(item.get("highway") == "bus_stop" for item in tags)
    assert any(item.get("public_transport") == "platform" for item in tags)
    assert any(item.get("entrance") for item in tags)
    assert any(item.get("amenity") == "parking_space" for item in tags)
    assert any(item.get("amenity") == "parking" for item in tags)
    assert any(item.get("service") == "parking_aisle" for item in tags)
    assert any(item.get("bridge") == "yes" for item in tags)
    assert any(item.get("tunnel") == "yes" for item in tags)

    result = build_ways(elements)
    assert result.stop_signs
    assert result.yield_signs
    assert result.crossings
    assert result.taxi_stops
    assert result.bus_stops
    assert result.parking_spaces
    assert all(way.name != "Pysäköintiajorata" for way in result.ways)
