import math
from typing import Optional, Tuple


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp value `v` between `lo` and `hi`."""
    return lo if v < lo else hi if v > hi else v


def compute_bbox(points_m: list[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Compute (minx, miny, maxx, maxy) bounding box for points in meters."""
    if not points_m:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in points_m]
    ys = [p[1] for p in points_m]
    return min(xs), min(ys), max(xs), max(ys)


def dist_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from point P(px, py) to segment AB in meters."""
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    ab_len2 = abx * abx + aby * aby
    if ab_len2 == 0:
        return math.hypot(px - ax, py - ay)
    t = (apx * abx + apy * aby) / ab_len2
    t = clamp(t, 0.0, 1.0)
    cx = ax + t * abx
    cy = ay + t * aby
    return math.hypot(px - cx, py - cy)


def point_in_polygon(px: float, py: float, polygon: list[Tuple[float, float]]) -> bool:
    """Ray casting algorithm to determine if point (px, py) is inside a 2D polygon."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if min(p1y, p2y) < py <= max(p1y, p2y):
            if px <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (py - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or px <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def clip_polygon_to_rect(
    points: list[Tuple[float, float]],
    rminx: float,
    rminy: float,
    rmaxx: float,
    rmaxy: float,
) -> list[Tuple[float, float]]:
    """Sutherland-Hodgman polygon clipping algorithm against an AABB rectangle."""
    output = points
    for edge in range(4):
        input_list = output
        output = []
        if not input_list:
            break
        s = input_list[-1]
        for e in input_list:
            if edge == 0:  # left: x >= rminx
                e_in = e[0] >= rminx
                s_in = s[0] >= rminx
                def intersect(p1, p2):
                    dx = p2[0] - p1[0]
                    t = (rminx - p1[0]) / dx if dx else 0.0
                    return (rminx, p1[1] + t * (p2[1] - p1[1]))
            elif edge == 1:  # right: x <= rmaxx
                e_in = e[0] <= rmaxx
                s_in = s[0] <= rmaxx
                def intersect(p1, p2):
                    dx = p2[0] - p1[0]
                    t = (rmaxx - p1[0]) / dx if dx else 0.0
                    return (rmaxx, p1[1] + t * (p2[1] - p1[1]))
            elif edge == 2:  # bottom: y >= rminy
                e_in = e[1] >= rminy
                s_in = s[1] >= rminy
                def intersect(p1, p2):
                    dy = p2[1] - p1[1]
                    t = (rminy - p1[1]) / dy if dy else 0.0
                    return (p1[0] + t * (p2[0] - p1[0]), rminy)
            else:  # top: y <= rmaxy
                e_in = e[1] <= rmaxy
                s_in = s[1] <= rmaxy
                def intersect(p1, p2):
                    dy = p2[1] - p1[1]
                    t = (rmaxy - p1[1]) / dy if dy else 0.0
                    return (p1[0] + t * (p2[0] - p1[0]), rmaxy)

            if e_in:
                if not s_in:
                    output.append(intersect(s, e))
                output.append(e)
            elif s_in:
                output.append(intersect(s, e))
            s = e
    return output


def meters_to_latlon(
    x: float, y: float, transformer: Optional[object] = None
) -> Tuple[Optional[float], Optional[float]]:
    """Convert meters (EPSG:3067) back to (lat, lon).

    Returns (lat, lon) or (None, None) if conversion isn't available.
    """
    try:
        if transformer is None:
            from pyproj import Transformer

            transformer = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
        # transformer.transform(x, y) returns (lon, lat) when always_xy=True
        lon, lat = transformer.transform(x, y)
        return lat, lon
    except Exception:
        return None, None
