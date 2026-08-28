from theroadragetrip.osm import BBOX_PRESETS, CITY_CENTERS, DEFAULT_BBOX, bbox_from_center


def test_bbox_presets():
    assert "oulu" in BBOX_PRESETS
    assert "helsinki" in BBOX_PRESETS
    assert "tampere" in BBOX_PRESETS
    assert "espoo" in BBOX_PRESETS
    assert "turku" in BBOX_PRESETS
    assert "vantaa" in BBOX_PRESETS
    assert "jyväskylä" in BBOX_PRESETS
    assert "kuopio" in BBOX_PRESETS
    assert "lahti" in BBOX_PRESETS
    assert "sysmä" in BBOX_PRESETS
    assert len(BBOX_PRESETS["oulu"]) == 4
    assert len(BBOX_PRESETS["helsinki"]) == 4
    assert DEFAULT_BBOX == BBOX_PRESETS["oulu"]


def test_bbox_from_center_dimensions():
    # 4x4 km area
    south, west, north, east = bbox_from_center(60.169525, 24.935446, size_km=4.0)
    assert south < 60.169525 < north
    assert west < 24.935446 < east
    # Approx 4 km span in latitude (~0.036 degrees)
    lat_span = north - south
    assert 0.03 < lat_span < 0.04
