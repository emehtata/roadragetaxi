import importlib.util
import json
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from theroadragetrip.osm import elevation as el

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dem80_tool", ROOT / "tools" / "dem80.py")
dem80 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dem80)


def tile(fill=np.nan):
    return np.full((el.DEM80_SIZE, el.DEM80_SIZE), fill, dtype=np.float64)


def write_tif(path, heights_north_up, west, north, nodata=-9999.0):
    """A float32 GeoTIFF with the GeoTIFF tags KM10 carries (pixel scale, tiepoint, GDAL_NODATA)."""
    image = Image.fromarray(np.asarray(heights_north_up, dtype=np.float32), mode="F")
    tags = {33550: (10.0, 10.0, 0.0), 33922: (0.0, 0.0, 0.0, float(west), float(north), 0.0), 42113: str(nodata)}
    image.save(path, tiffinfo=tags)


def test_encode_decode_roundtrip_0p1m():
    h = tile(0.0)
    h[0, 0], h[1, 2], h[255, 255] = 12.34, -3.26, 1324.05
    i, j, back = el.decode_tile(el.encode_tile(5, 88, h))
    assert (i, j) == (5, 88)
    assert np.allclose(back, h, atol=0.05 + 1e-4)


def test_nodata_preserved_not_zero():
    h = tile(7.0)
    h[10, 20] = np.nan
    _, _, back = el.decode_tile(el.encode_tile(0, 0, h))
    assert np.isnan(back[10, 20]) and np.isnan(back).sum() == 1
    assert back[10, 21] == pytest.approx(7.0)


def test_tile_index_of_point_and_bounds():
    assert el.tile_of(0.0, 0.0) == (0, 0)
    assert el.tile_of(20479.9, 20480.0) == (0, 1)
    assert el.tile_of(-0.1, -20480.0) == (-1, -1)
    assert el.tile_of(430000.0, 7210000.0) == (20, 352)
    assert el.tile_bounds(20, 352) == (409600.0, 7208960.0, 430080.0, 7229440.0)


def test_mean_block_aggregation_excludes_nodata():
    a = np.full((8, 16), 2.0)
    a[:, 8:] = np.nan
    a[0, 8] = 10.0
    a[0, 0] = np.nan
    out = dem80.block_mean(a)
    assert out[0, 0] == pytest.approx(2.0)  # 63 valid twos, the NaN skipped
    assert out[0, 1] == pytest.approx(10.0)  # one valid cell of 64
    assert dem80.block_mean(np.full((8, 8), np.nan))[0, 0] != 0 and np.isnan(dem80.block_mean(np.full((8, 8), np.nan))[0, 0])


def test_geotiff_nodata_read_per_file_never_zero(tmp_path):
    a = np.full((16, 16), 5.0)
    a[:8, :8] = -32767.0
    write_tif(tmp_path / "a.tif", a, 409600, 7208960 + 160, nodata=-32767.0)
    heights, west, north, step = dem80.read_geotiff(tmp_path / "a.tif")
    assert (west, north, step) == (409600.0, 7209120.0, 10.0)
    assert np.isnan(heights[:8, :8]).all() and (heights[8:, :] == 5.0).all()


def test_boundary_continuity_across_sheets(tmp_path):
    rng = np.random.default_rng(1)
    whole = rng.uniform(0, 100, (32, 64))  # north-up, 10 m, spans two tiles across x = 20480
    west, north = 20480 - 320, 20480 + 160
    write_tif(tmp_path / "whole.tif", whole, west, north)
    write_tif(tmp_path / "w.tif", whole[:, :24], west, north)  # sheet seam at 240 m: inside an 80 m block
    write_tif(tmp_path / "e.tif", whole[:, 24:], west + 240, north)
    dem80.convert([tmp_path / "whole.tif"], tmp_path / "one")
    dem80.convert([tmp_path / "w.tif", tmp_path / "e.tif"], tmp_path / "two")
    for name in ("dem80_0_1.bin", "dem80_1_1.bin"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    dem = el.load_dem80(tmp_path / "two")
    left, right = dem.height_m(20480 - 1e-6, 20480 + 80), dem.height_m(20480 + 1e-6, 20480 + 80)
    assert left == pytest.approx(right, abs=1e-3)  # bilinear across the tile edge, no crack


def test_header_and_index_metadata_valid(tmp_path):
    data = el.encode_tile(3, 4, tile(1.0))
    magic, version, i, j, size, step, scale, nodata, crc = struct.unpack_from("<4sHiiHffhI", data)
    assert (magic, version, i, j, size, step, nodata) == (b"RRD1", 1, 3, 4, 256, 80.0, -32768)
    assert scale == pytest.approx(0.1)
    assert crc == zlib.crc32(zlib.decompress(data[struct.calcsize("<4sHiiHffhI"):]))
    broken = bytearray(data)
    broken[struct.calcsize("<4sHiiHffhI") - 1] ^= 1  # crc byte
    with pytest.raises(ValueError):
        el.decode_tile(bytes(broken))
    with pytest.raises(ValueError):
        el.decode_tile(b"XXXX" + data[4:])
    write_tif(tmp_path / "a.tif", np.full((8, 8), 3.0), 0, 80)
    dem80.convert([tmp_path / "a.tif"], tmp_path / "out", source_date="11/2026")
    index = json.loads((tmp_path / "out" / "dem80.json").read_text())
    el.validate_index(index)
    assert index["crs"] == "EPSG:3067" and "Maanmittauslaitos" in index["attribution"] and "11/2026" in index["attribution"]
    assert index["tiles"][0]["file"] == "dem80_0_0.bin"
    for bad in ({**index, "crs": "EPSG:4326"}, {**index, "step_m": 10}, {**index, "tile_size": 512}):
        with pytest.raises(ValueError):
            el.validate_index(bad)


def test_conversion_reproducible_bytes(tmp_path):
    write_tif(tmp_path / "a.tif", np.arange(256, dtype=float).reshape(16, 16), 1000, 7000)
    dem80.convert([tmp_path / "a.tif"], tmp_path / "x")
    dem80.convert([tmp_path / "a.tif"], tmp_path / "y")
    names = sorted(p.name for p in (tmp_path / "x").iterdir())
    assert names == sorted(p.name for p in (tmp_path / "y").iterdir())
    for name in names:
        assert (tmp_path / "x" / name).read_bytes() == (tmp_path / "y" / name).read_bytes()


def test_height_m_matches_tile_sample_at_centres(tmp_path):
    h = tile(np.nan)
    h[0, 0], h[0, 1], h[1, 0] = 10.0, 20.0, 30.0
    (tmp_path / "dem80_0_0.bin").write_bytes(el.encode_tile(0, 0, h))
    (tmp_path / "dem80.json").write_text(json.dumps(dem80.index_for([(0, 0)], [], "unknown")))
    dem = el.load_dem80(tmp_path)
    assert dem.height_m(40, 40) == pytest.approx(10.0)
    assert dem.height_m(120, 40) == pytest.approx(20.0)
    assert dem.height_m(40, 120) == pytest.approx(30.0)
    assert dem.height_m(80, 40) == pytest.approx(15.0)
    assert dem.height_m(5000, 5000) is None  # NoData: no height, not 0 m
    assert dem.height_m(-5000, 40) is None  # no tile
    assert el.load_dem80(tmp_path / "missing") is None


def test_download_requires_env_key(monkeypatch, capsys):
    monkeypatch.delenv("MML_API_KEY", raising=False)
    monkeypatch.setattr(dem80.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no network without a key"))
    with pytest.raises(SystemExit) as stop:
        dem80.main(["download", "--out", "x"])
    assert "MML_API_KEY" in str(stop.value)


def test_download_never_prints_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MML_API_KEY", "secret-key-123")
    seen = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"processes": [{"id": "p1", "title": "t"}]}'

    monkeypatch.setattr(dem80.urllib.request, "urlopen", lambda request, timeout: seen.append(request) or Reply())
    with pytest.raises(SystemExit):
        dem80.main(["download", "--out", str(tmp_path)])
    out = capsys.readouterr()
    assert "secret-key-123" not in out.out + out.err
    assert seen[0].full_url.startswith(dem80.MML_OGC_PROCESSES)
    assert "secret-key-123" not in json.dumps(json.loads((tmp_path / "processes.json").read_text()))


def write_cop_tif(path, heights_north_up, lat, lon, epsg=4326):
    """A Copernicus-like 1x1 degree float32 COG stand-in: EPSG:4326 geokeys, corner tiepoint, no NoData tag."""
    h = np.asarray(heights_north_up, dtype=np.float32)
    keys = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, epsg)
    tags = {33550: (1.0 / h.shape[1], 1.0 / h.shape[0], 0.0), 33922: (0.0, 0.0, 0.0, float(lon), float(lat + 1), 0.0), 34735: keys}
    Image.fromarray(h, mode="F").save(path, tiffinfo=tags)


def test_copernicus_tiles_picked_by_bbox():
    assert dem80.cop_tiles(dem80.OULU_BBOX) == [(64, 24), (64, 25), (64, 26), (65, 24), (65, 25), (65, 26)]
    assert dem80.cop_name(65, 25) == "Copernicus_DSM_COG_10_N65_00_E025_00_DEM"


def test_copernicus_bounds_and_crs_verified(tmp_path):
    path = tmp_path / (dem80.cop_name(65, 25) + ".tif")
    write_cop_tif(path, np.full((36, 18), 4.0), 65, 25)
    heights, lon0, lat1, dlon, dlat = dem80.read_copernicus(path)
    assert (lon0, lat1, heights.shape) == (25.0, 66.0, (36, 18))
    write_cop_tif(path, np.full((36, 18), 4.0), 64, 25)  # bounds do not match the name
    with pytest.raises(ValueError):
        dem80.read_copernicus(path)
    write_cop_tif(path, np.full((36, 18), 4.0), 65, 25, epsg=3857)
    with pytest.raises(ValueError):
        dem80.read_copernicus(path)


def test_copernicus_convert_mean_nodata_reproducible(tmp_path):
    path = tmp_path / (dem80.cop_name(65, 25) + ".tif")
    h = np.full((360, 180), 30.0)
    h[:, :90] = 10.0  # west half 10 m, east half 30 m
    write_cop_tif(path, h, 65, 25)
    bbox = (430000.0, 7230000.0, 432000.0, 7232000.0)  # inside N65 E025
    dem80.convert_copernicus([path], tmp_path / "a", bbox)
    dem80.convert_copernicus([path], tmp_path / "b", bbox)
    for p in (tmp_path / "a").iterdir():
        assert p.read_bytes() == (tmp_path / "b" / p.name).read_bytes()
    index = json.loads((tmp_path / "a" / "dem80.json").read_text())
    assert index["vertical"] == "EGM2008" and "Airbus" in index["attribution"]
    dem = el.load_dem80(tmp_path / "a")
    assert 9.95 <= dem.height_m(431000, 7231000) <= 30.05  # block means of the source, never 0 m
    assert dem.height_m(500000, 7231000) is None  # outside the bbox: NoData, not 0 m


COP_REAL = Path(__import__("pwd").getpwuid(__import__("os").getuid()).pw_dir) / ".cache" / "copernicus-dem30" / (dem80.cop_name(65, 25) + ".tif")


@pytest.mark.skipif(not COP_REAL.is_file(), reason="real Copernicus N65 E025 tile not cached")
def test_real_copernicus_tile_roundtrip(tmp_path):
    from pyproj import Transformer
    heights, lon0, lat1, dlon, dlat = dem80.read_copernicus(COP_REAL)
    bbox = (427200.0, 7210000.0, 428800.0, 7211600.0)  # 1.6 km square in Oulu
    dem80.convert_copernicus([COP_REAL], tmp_path, bbox)
    dem = el.load_dem80(tmp_path)
    to_ll = Transformer.from_crs(3067, 4326, always_xy=True)
    lon, lat = to_ll.transform(428000.0 - 40, 7210800.0 - 40)
    near = heights[int((lat1 - lat) / dlat) - 3:int((lat1 - lat) / dlat) + 4, int((lon - lon0) / dlon) - 3:int((lon - lon0) / dlon) + 4]
    assert near.min() - 0.1 <= dem.height_m(428000.0 - 40, 7210800.0 - 40) <= near.max() + 0.1


COP_NOTICE = ("produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH "
              "2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved")


def test_copernicus_notice_in_docs_tool_and_credits():
    assert COP_NOTICE in (ROOT / "docs" / "dem-terrain-80m.md").read_text(encoding="utf-8").replace("\n", " ")
    assert "https://doi.org/10.5270/ESA-c5d3d65" in (ROOT / "docs" / "dem-terrain-80m.md").read_text(encoding="utf-8")
    assert dem80.COP_ATTRIBUTION == COP_NOTICE
    i18n = (ROOT / "godot" / "i18n.gd").read_text(encoding="utf-8")
    entries = [line for line in i18n.split('"credits_terrain": ')[1:]]
    assert len(entries) == 3 and all(COP_NOTICE in e.split('",')[0] for e in entries)  # fi, en, de
