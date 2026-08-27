from theroadragetrip.osm import BBOX_PRESETS, DEFAULT_BBOX


def test_bbox_presets():
    assert "oulu" in BBOX_PRESETS
    assert "helsinki" in BBOX_PRESETS
    assert len(BBOX_PRESETS["oulu"]) == 4
    assert len(BBOX_PRESETS["helsinki"]) == 4
    assert DEFAULT_BBOX == BBOX_PRESETS["oulu"]
