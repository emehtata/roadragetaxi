import json

from theroadragetrip.osm import elevation


def test_bilinear_and_edge_clamp(tmp_path):
    path = tmp_path / "dem.json"  # 2 x 2 cells of 10 m, centres at (5, 5) .. (15, 15); map origin (0, 0) clamps to 1.0
    path.write_text(json.dumps({"origin": [0.0, 0.0], "step": 10.0, "cols": 2, "heights": [1.0, 3.0, 5.0, 7.0]}))
    dem = elevation.load_dem(path)
    assert dem.height_m(15.0, 5.0) == 2.0  # a cell centre: its value, relative to the origin's height
    assert dem.height_m(10.0, 5.0) == 1.0  # halfway along x
    assert dem.height_m(10.0, 10.0) == 3.0  # bilinear in the middle
    assert dem.height_m(-50.0, 100.0) == 4.0  # outside: the nearest edge value
    assert elevation.load_dem(tmp_path / "missing.json") is None
