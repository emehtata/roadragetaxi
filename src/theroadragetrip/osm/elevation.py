"""Ground elevation from an offline-sampled DEM raster (render only).

The raster is JSON next to the cached map data: {"origin": [x, y] (map metres,
the first cell's corner), "step": cell size m, "cols": n, "heights": row-major,
rows along +y}. Sampled from Copernicus GLO-30 / NLS 10 m by a manual tool step;
OSM `ele` nodes are too sparse for ground and are not used.
"""
import json
from pathlib import Path


class Dem:
    def __init__(self, origin, step: float, cols: int, heights) -> None:
        self.x0, self.y0 = float(origin[0]), float(origin[1])
        self.step, self.cols = float(step), int(cols)
        self.rows = len(heights) // self.cols
        self.heights = [float(h) for h in heights]
        self.base = 0.0
        self.base = self.height_m(0.0, 0.0)

    def height_m(self, x_m: float, y_m: float) -> float:
        """Bilinear between cell centres, clamped to the edge outside;
        relative to the map origin's height."""
        fx = min(max((x_m - self.x0) / self.step - 0.5, 0.0), self.cols - 1)
        fy = min(max((y_m - self.y0) / self.step - 0.5, 0.0), self.rows - 1)
        ix, iy = min(int(fx), max(self.cols - 2, 0)), min(int(fy), max(self.rows - 2, 0))
        tx, ty = fx - ix, fy - iy
        h, c = self.heights, self.cols
        ix1, iy1 = min(ix + 1, self.cols - 1), min(iy + 1, self.rows - 1)
        low = h[iy * c + ix] * (1 - tx) + h[iy * c + ix1] * tx
        high = h[iy1 * c + ix] * (1 - tx) + h[iy1 * c + ix1] * tx
        return low * (1 - ty) + high * ty - self.base


def load_dem(path) -> Dem | None:
    path = Path(path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return Dem(data["origin"], data["step"], data["cols"], data["heights"])
