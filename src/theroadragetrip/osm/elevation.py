"""Ground elevation from an offline-sampled DEM raster (render only).

The raster is JSON next to the cached map data: {"origin": [x, y] (map metres,
the first cell's corner), "step": cell size m, "cols": n, "heights": row-major,
rows along +y}. Sampled from Copernicus GLO-30 / NLS 10 m by a manual tool step;
OSM `ele` nodes are too sparse for ground and are not used. JSON `null` is NoData.

`Dem80` reads the 80 m tile set (tools/dem80.py, docs/dem-terrain-80m.md):
`<cache>/dem80/dem80.json` + `dem80_<i>_<j>.bin`, absolute EPSG:3067 / N2000.
"""
import json
import logging
import math
import os
import re
import struct
import zlib
from functools import lru_cache
from pathlib import Path

DEM80_STEP = 80.0
DEM80_SIZE = 256
DEM80_SPAN = DEM80_STEP * DEM80_SIZE
DEM80_SCALE = 0.1
DEM80_NODATA = -32768
DEM80_CRS = "EPSG:3067"
_HEADER = struct.Struct("<4sHiiHffhI")  # magic, version, i, j, size, step, scale, nodata, crc32 of the raw int16


def _bilinear(sample, fx: float, fy: float) -> float | None:
    """Bilinear over sample(col, row) -> float | None; NoData samples are
    left out and the rest re-weighted; None when nothing valid has weight."""
    ix, iy = math.floor(fx), math.floor(fy)
    tx, ty = fx - ix, fy - iy
    total = weight = 0.0
    for dx, dy, w in ((0, 0, (1 - tx) * (1 - ty)), (1, 0, tx * (1 - ty)), (0, 1, (1 - tx) * ty), (1, 1, tx * ty)):
        if w > 0:
            v = sample(ix + dx, iy + dy)
            if v is not None:
                total, weight = total + v * w, weight + w
    return total / weight if weight > 0 else None


class Dem:
    def __init__(self, origin, step: float, cols: int, heights) -> None:
        self.x0, self.y0 = float(origin[0]), float(origin[1])
        self.step, self.cols = float(step), int(cols)
        self.rows = len(heights) // self.cols
        self.heights = [None if h is None else float(h) for h in heights]
        self.base = 0.0  # absolute heights; the chunk origin handles the render offset

    def height_m(self, x_m: float, y_m: float) -> float | None:
        """Bilinear between cell centres, clamped to the edge outside; None: NoData."""
        fx = min(max((x_m - self.x0) / self.step - 0.5, 0.0), self.cols - 1)
        fy = min(max((y_m - self.y0) / self.step - 0.5, 0.0), self.rows - 1)
        return _bilinear(lambda c, r: self.heights[min(r, self.rows - 1) * self.cols + min(c, self.cols - 1)], fx, fy)


def load_dem(path) -> Dem | None:
    path = Path(path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return Dem(data["origin"], data["step"], data["cols"], data["heights"])


def tile_of(x_m: float, y_m: float) -> tuple[int, int]:
    return math.floor(x_m / DEM80_SPAN), math.floor(y_m / DEM80_SPAN)


def tile_bounds(i: int, j: int) -> tuple[float, float, float, float]:
    return i * DEM80_SPAN, j * DEM80_SPAN, (i + 1) * DEM80_SPAN, (j + 1) * DEM80_SPAN


def encode_tile(i: int, j: int, heights_m) -> bytes:
    """256x256 metres (rows along +y, NaN = NoData) to the RRD1 tile bytes."""
    import numpy as np
    h = np.asarray(heights_m, dtype=np.float64)
    if h.shape != (DEM80_SIZE, DEM80_SIZE):
        raise ValueError(f"tile shape {h.shape}")
    q = np.where(np.isnan(h), DEM80_NODATA, np.clip(np.round(np.nan_to_num(h) / DEM80_SCALE), -32767, 32767)).astype("<i2")
    raw = q.tobytes()
    return _HEADER.pack(b"RRD1", 1, i, j, DEM80_SIZE, DEM80_STEP, DEM80_SCALE, DEM80_NODATA, zlib.crc32(raw)) + zlib.compress(raw, 9)


def decode_tile(data: bytes):
    """RRD1 bytes to (i, j, float32 metres with NaN NoData); ValueError if invalid."""
    import numpy as np
    if len(data) < _HEADER.size:
        raise ValueError("short tile")
    magic, version, i, j, size, step, scale, nodata, crc = _HEADER.unpack_from(data)
    if magic != b"RRD1" or version != 1 or size != DEM80_SIZE or step != DEM80_STEP:
        raise ValueError("not an RRD1 v1 256x256 80 m tile")
    raw = zlib.decompress(data[_HEADER.size:])
    if len(raw) != size * size * 2 or zlib.crc32(raw) != crc:
        raise ValueError("tile crc32 mismatch")
    q = np.frombuffer(raw, "<i2").reshape(size, size)
    h = q.astype(np.float32) * np.float32(scale)
    h[q == nodata] = np.nan
    return i, j, h


def validate_index(index: dict) -> None:
    if (index.get("crs"), index.get("step_m"), index.get("tile_size"), index.get("scale"), index.get("nodata")) != (
            DEM80_CRS, DEM80_STEP, DEM80_SIZE, DEM80_SCALE, DEM80_NODATA):
        raise ValueError("dem80.json: not EPSG:3067 80 m 256 tiles, scale 0.1, nodata -32768")


_REPORTED: set = set()
PACKAGED_DEM80 = Path(__file__).parent.parent / "assets" / "dem80"


class Dem80:
    """The 80 m tile set; tiles open lazily, a few kept (LRU)."""
    base = 0.0

    def __init__(self, directory) -> None:
        self.dir = Path(directory)
        self._tile = lru_cache(maxsize=8)(self._load)

    def _load(self, i: int, j: int):
        path = self.dir / f"dem80_{i}_{j}.bin"
        if not path.is_file():
            return None
        try:
            return decode_tile(path.read_bytes())[2]
        except (ValueError, OSError, zlib.error) as error:  # corrupt tile: flat there, one error per file
            if path not in _REPORTED:
                _REPORTED.add(path)
                logging.getLogger(__name__).error("dem80 tile %s unreadable, flat ground there: %s", path, error)
            return None

    def _sample(self, gx: int, gy: int) -> float | None:
        h = self._tile(gx // DEM80_SIZE, gy // DEM80_SIZE)
        if h is None:
            return None
        v = float(h[gy % DEM80_SIZE, gx % DEM80_SIZE])
        return None if math.isnan(v) else v

    def height_m(self, x_m: float, y_m: float) -> float | None:
        """Bilinear between sample centres (x0 + 40 + 80c), across tile edges; None: NoData or no tile."""
        return _bilinear(self._sample, (x_m - DEM80_STEP / 2) / DEM80_STEP, (y_m - DEM80_STEP / 2) / DEM80_STEP)


def load_dem80(directory) -> Dem80 | None:
    index = Path(directory) / "dem80.json"
    if not index.is_file():
        return None
    validate_index(json.loads(index.read_text()))
    return Dem80(directory)


DEM80_ENV = "THEROADRAGETRIP_DEM80_DIR"
WSL_MARKER = Path("/proc/sys/fs/binfmt_misc/WSLInterop")  # the Makefile's WSL test too


def native_path(text: str) -> Path:
    """A path from the env var on this OS: C:\\x <-> /mnt/c/x between Windows and WSL."""
    if os.name == "nt" and (m := re.match(r"^/mnt/([a-zA-Z])(/.*)?$", text)):
        return Path(f"{m[1].upper()}:" + (m[2] or "/").replace("/", "\\"))
    if os.name != "nt" and WSL_MARKER.exists() and (m := re.match(r"^([a-zA-Z]):[\\/](.*)$", text)):
        return Path(f"/mnt/{m[1].lower()}") / m[2].replace("\\", "/")
    return Path(text)


def dem80_dirs(cache_root) -> list:
    return [Path(cache_root) / "dem80"] + ([native_path(env)] if (env := os.environ.get(DEM80_ENV)) else []) + [PACKAGED_DEM80]


def missing_ground_message(cache_root, city: str) -> str:
    return (f"terrain on but no DEM ground: tried {', '.join(str(d / 'dem80.json') for d in dem80_dirs(cache_root))} "
            f"and {Path(cache_root) / f'{city}.dem.json'}; set {DEM80_ENV} to a dem80 folder "
            "(or run make dem80-windows under WSL); the ground stays flat")


def load_ground(cache_root, city: str, dem80_enabled: bool):
    """The render-only ground: <cache>/dem80/ (or $THEROADRAGETRIP_DEM80_DIR) when enabled,
    else <city>.dem.json, else None (flat; logged as an error when terrain was asked for)."""
    for directory in dem80_dirs(cache_root) if dem80_enabled else []:
        try:
            if ground := load_dem80(directory):
                return ground
        except (ValueError, OSError):  # corrupt dem80.json: try the next folder, else the error below
            pass
    ground = load_dem(Path(cache_root) / f"{city}.dem.json")
    if ground is None and dem80_enabled:
        logging.getLogger(__name__).error(missing_ground_message(cache_root, city))
    return ground
