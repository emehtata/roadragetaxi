import re

from theroadragetrip.map_chunks import LANDMARKS

ARGS = {"circle": 3, "rect": 4, "line": 5, "polygon": 1}


def test_every_landmark_shape_is_drawable():
    assert "Toripolliisi" in LANDMARKS
    for name, spec in LANDMARKS.items():
        assert spec.get("scale", 1.0) > 0, name
        for shape in spec["shapes"]:
            assert len(shape) == ARGS[shape[0]] + 2, (name, shape)
            assert re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", shape[-1]), (name, shape)
            if shape[0] == "polygon":
                assert len(shape[1]) >= 6 and len(shape[1]) % 2 == 0, (name, shape)
