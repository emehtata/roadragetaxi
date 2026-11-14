import json
import logging
from types import SimpleNamespace

from theroadragetrip.map_chunks import CHUNK_SIZE_M, ChunkIndex
from theroadragetrip.osm import elevation as el

POINT = (427666.0, 7210769.1)


class MeasuredDem:
    """Synthetic ground around the test hill: about 4 m rise per 100 m eastwards, as sampled."""

    def height_m(self, x, y):
        return 6.4 + 0.043 * max(0.0, x - POINT[0] + 35.0)


def test_testhill_chunk_grid_not_flat():
    ix, iy = int(POINT[0] // CHUNK_SIZE_M), int(POINT[1] // CHUNK_SIZE_M)
    grid = ChunkIndex._ground_heights(SimpleNamespace(size=CHUNK_SIZE_M, _dem=MeasuredDem()), ix, iy)
    assert grid is not None
    cols, step = grid["cols"], grid["step"]
    x0, y0 = grid["origin"]
    near = [h for k, h in enumerate(grid["heights"])
            if ((x0 + k % cols * step - POINT[0]) ** 2 + (y0 + k // cols * step - POINT[1]) ** 2) <= 100.0 ** 2]
    assert max(near) - min(near) >= 2.0


def test_load_ground_env_fallback_and_warning(tmp_path, monkeypatch, caplog):
    dem_dir = tmp_path / "dem80"
    dem_dir.mkdir()
    (dem_dir / "dem80.json").write_text(json.dumps({"crs": el.DEM80_CRS, "step_m": el.DEM80_STEP, "tile_size": el.DEM80_SIZE,
                                                    "scale": el.DEM80_SCALE, "nodata": el.DEM80_NODATA}))
    empty = tmp_path / "cache"
    empty.mkdir()
    monkeypatch.setenv("THEROADRAGETRIP_DEM80_DIR", str(dem_dir))
    assert isinstance(el.load_ground(empty, "oulu", True), el.Dem80)
    monkeypatch.delenv("THEROADRAGETRIP_DEM80_DIR")
    monkeypatch.setattr(el, "PACKAGED_DEM80", tmp_path / "none")  # no packaged tiles either
    with caplog.at_level(logging.WARNING):
        assert el.load_ground(empty, "oulu", True) is None
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1
    assert "THEROADRAGETRIP_DEM80_DIR" in caplog.text


def test_env_path_maps_between_windows_and_wsl(monkeypatch):
    monkeypatch.setattr(el, "WSL_MARKER", type("M", (), {"exists": staticmethod(lambda: True)})())
    if el.os.name != "nt":
        assert el.native_path(r"C:\Users\me\AppData\Local\RoadRageTrip\dem80").as_posix() == \
            "/mnt/c/Users/me/AppData/Local/RoadRageTrip/dem80"
        assert el.native_path("/home/me/dem80").as_posix() == "/home/me/dem80"
