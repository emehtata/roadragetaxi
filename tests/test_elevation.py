import json

from theroadragetrip.osm import elevation


def test_bilinear_and_edge_clamp(tmp_path):
    path = tmp_path / "dem.json"  # 2 x 2 cells of 10 m, centres at (5, 5) .. (15, 15); absolute heights
    path.write_text(json.dumps({"origin": [0.0, 0.0], "step": 10.0, "cols": 2, "heights": [1.0, 3.0, 5.0, 7.0]}))
    dem = elevation.load_dem(path)
    assert dem.height_m(15.0, 5.0) == 3.0  # a cell centre: its value (base 0, absolute N2000)
    assert dem.height_m(10.0, 5.0) == 2.0  # halfway along x
    assert dem.height_m(10.0, 10.0) == 4.0  # bilinear in the middle
    assert dem.height_m(-50.0, 100.0) == 5.0  # outside: the nearest edge value
    assert elevation.load_dem(tmp_path / "missing.json") is None


def test_nodata_null_is_skipped_never_zero(tmp_path):
    path = tmp_path / "dem.json"
    path.write_text(json.dumps({"origin": [0.0, 0.0], "step": 10.0, "cols": 2, "heights": [None, 4.0, None, 4.0]}))
    dem = elevation.load_dem(path)
    assert dem.height_m(10.0, 5.0) == 4.0  # the NoData neighbour is skipped, not averaged in as 0 m
    assert dem.height_m(5.0, 5.0) is None


def test_make_dem_asc_keeps_nodata_and_absolute_base(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("make_dem", Path(__file__).resolve().parents[1] / "tools" / "make_dem.py")
    make_dem = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_dem)
    asc = tmp_path / "a.asc"
    asc.write_text("ncols 2\nnrows 1\nxllcorner 400000\nyllcorner 7200000\ncellsize 10\nNODATA_value -9999\n-9999 12.5\n")
    data = make_dem.from_asc(asc)
    assert data["heights"] == [None, 12.5]
    dem = elevation.Dem(data["origin"], data["step"], data["cols"], data["heights"])
    assert dem.base == 0.0 and dem.height_m(400015.0, 7200005.0) == 12.5


def test_ground_heights_no_zero_for_nodata():
    from types import SimpleNamespace
    from theroadragetrip import map_chunks
    dem = SimpleNamespace(height_m=lambda x, y: None if x < 250 else 7.0)
    world = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[], dem=dem)
    heights = map_chunks.ChunkIndex(world).message("0_0")["ground_heights"]["heights"]
    assert heights and all(h == 7.0 for h in heights)  # NoData filled from the nearest valid sample
    empty = SimpleNamespace(ways=[], railways=[], waters=[], buildings=[], dem=SimpleNamespace(height_m=lambda x, y: None))
    assert "ground_heights" not in map_chunks.ChunkIndex(empty).message("0_0")


def test_server_falls_back_to_flat_without_dem80(tmp_path, monkeypatch):
    monkeypatch.setattr(elevation, "PACKAGED_DEM80", tmp_path / "no-packaged")
    assert elevation.load_ground(tmp_path, "Oulu", dem80_enabled=True) is None  # nothing: flat
    (tmp_path / "Oulu.dem.json").write_text(json.dumps({"origin": [0, 0], "step": 10, "cols": 1, "heights": [3.0]}))
    assert isinstance(elevation.load_ground(tmp_path, "Oulu", dem80_enabled=True), elevation.Dem)
    (tmp_path / "dem80").mkdir()
    (tmp_path / "dem80" / "dem80.json").write_text(json.dumps(
        {"crs": "EPSG:3067", "step_m": 80, "tile_size": 256, "scale": 0.1, "nodata": -32768, "tiles": []}))
    assert isinstance(elevation.load_ground(tmp_path, "Oulu", dem80_enabled=True), elevation.Dem80)
    assert isinstance(elevation.load_ground(tmp_path, "Oulu", dem80_enabled=False), elevation.Dem)  # switch off: as today


def _oulu_xy():
    from pyproj import Transformer
    return Transformer.from_crs(4326, 3067, always_xy=True).transform(25.4682, 65.0121)  # Oulu city centre


def test_packaged_dem80_loads_and_validates(tmp_path, monkeypatch):
    monkeypatch.delenv(elevation.DEM80_ENV, raising=False)
    ground = elevation.load_ground(tmp_path, "Oulu", dem80_enabled=True)
    assert isinstance(ground, elevation.Dem80) and ground.dir == elevation.PACKAGED_DEM80
    index = json.loads((elevation.PACKAGED_DEM80 / "dem80.json").read_text())
    elevation.validate_index(index)
    assert "Copernicus" in json.dumps(index) and len(index["tiles"]) > 100


def test_packaged_dem80_oulu_centre_not_flat():
    dem = elevation.load_dem80(elevation.PACKAGED_DEM80)
    x, y = _oulu_xy()
    assert dem.height_m(x, y) is not None
    ring = [dem.height_m(x + dx, y + dy) for dx in range(-1000, 1001, 100) for dy in range(-1000, 1001, 100)
            if dx * dx + dy * dy <= 1000 ** 2]
    ring = [h for h in ring if h is not None]
    assert ring and max(ring) - min(ring) > 1.0


def _copy_with_oulu_tile(tmp_path):
    import shutil
    x, y = _oulu_xy()
    i, j = elevation.tile_of(x, y)
    shutil.copy(elevation.PACKAGED_DEM80 / "dem80.json", tmp_path)
    shutil.copy(elevation.PACKAGED_DEM80 / f"dem80_{i}_{j}.bin", tmp_path)
    return tmp_path / f"dem80_{i}_{j}.bin", x, y


def test_dem80_missing_tile_is_flat(tmp_path):
    tile, x, y = _copy_with_oulu_tile(tmp_path)
    assert elevation.load_dem80(tmp_path).height_m(x, y) is not None
    tile.unlink()
    assert elevation.load_dem80(tmp_path).height_m(x, y) is None


def test_dem80_corrupt_tile_logs_once_and_is_flat(tmp_path, caplog):
    import logging
    tile, x, y = _copy_with_oulu_tile(tmp_path)
    data = bytearray(tile.read_bytes())
    data[27] ^= 0xFF  # the header crc32 field: bad crc
    tile.write_bytes(bytes(data))
    dem = elevation.load_dem80(tmp_path)
    with caplog.at_level(logging.ERROR):
        assert dem.height_m(x, y) is None
        dem._tile.cache_clear()
        assert dem.height_m(x + 80, y) is None
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and tile.name in errors[0].getMessage()


def _oulu_only_cache(tmp_path, monkeypatch):
    monkeypatch.delenv(elevation.DEM80_ENV, raising=False)
    (tmp_path / "dem80").mkdir()
    return _copy_with_oulu_tile(tmp_path / "dem80")


def test_packaged_tile_used_outside_oulu_only_cache(tmp_path, monkeypatch):
    _oulu_only_cache(tmp_path, monkeypatch)
    ground = elevation.load_ground(tmp_path, "Oulu", dem80_enabled=True)
    assert ground.height_m(430800, 6819170) is not None  # Sysmä: only in the packaged set


def test_cache_tile_wins_over_packaged(tmp_path, monkeypatch):
    tile, x, y = _oulu_only_cache(tmp_path, monkeypatch)
    i, j = elevation.tile_of(x, y)
    tile.write_bytes(elevation.encode_tile(i, j, [[1234.5] * elevation.DEM80_SIZE] * elevation.DEM80_SIZE))
    ground = elevation.load_ground(tmp_path, "Oulu", dem80_enabled=True)
    assert abs(ground.height_m(x, y) - 1234.5) < 0.01
