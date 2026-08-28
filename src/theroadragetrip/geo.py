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


def closest_point_and_dist_to_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> Tuple[float, float, float, float]:
    """Find closest point (cx, cy), parameter t, and distance from P to segment AB."""
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    ab_len2 = abx * abx + aby * aby
    if ab_len2 == 0:
        return ax, ay, 0.0, math.hypot(px - ax, py - ay)
    t = (apx * abx + apy * aby) / ab_len2
    t_clamped = clamp(t, 0.0, 1.0)
    cx = ax + t_clamped * abx
    cy = ay + t_clamped * aby
    return cx, cy, t_clamped, math.hypot(px - cx, py - cy)


def get_oriented_box_corners(
    cx: float, cy: float, heading: float, length: float, width: float
) -> list[Tuple[float, float]]:
    """Return the 4 corner points of an oriented bounding box."""
    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    hl = length / 2.0
    hw = width / 2.0

    fx, fy = cos_h, sin_h
    rx, ry = sin_h, -cos_h

    return [
        (cx + fx * hl + rx * hw, cy + fy * hl + ry * hw),
        (cx + fx * hl - rx * hw, cy + fy * hl - ry * hw),
        (cx - fx * hl - rx * hw, cy - fy * hl - ry * hw),
        (cx - fx * hl + rx * hw, cy - fy * hl + ry * hw),
    ]


def boxes_intersect(
    cx1: float, cy1: float, h1: float, l1: float, w1: float,
    cx2: float, cy2: float, h2: float, l2: float, w2: float,
) -> bool:
    """Check if two oriented bounding boxes collide using the Separating Axis Theorem (SAT)."""
    # Quick circle bounding check
    max_r1 = math.hypot(l1, w1) * 0.5
    max_r2 = math.hypot(l2, w2) * 0.5
    if (cx1 - cx2) ** 2 + (cy1 - cy2) ** 2 > (max_r1 + max_r2) ** 2:
        return False

    box1 = get_oriented_box_corners(cx1, cy1, h1, l1, w1)
    box2 = get_oriented_box_corners(cx2, cy2, h2, l2, w2)

    # 4 separating axes (2 per box)
    axes = [
        (math.cos(h1), math.sin(h1)),
        (math.sin(h1), -math.cos(h1)),
        (math.cos(h2), math.sin(h2)),
        (math.sin(h2), -math.cos(h2)),
    ]

    for ax, ay in axes:
        # Project box1 onto axis
        min1 = max1 = box1[0][0] * ax + box1[0][1] * ay
        for p in box1[1:]:
            proj = p[0] * ax + p[1] * ay
            if proj < min1:
                min1 = proj
            elif proj > max1:
                max1 = proj

        # Project box2 onto axis
        min2 = max2 = box2[0][0] * ax + box2[0][1] * ay
        for p in box2[1:]:
            proj = p[0] * ax + p[1] * ay
            if proj < min2:
                min2 = proj
            elif proj > max2:
                max2 = proj

        # Check for separation gap
        if max1 < min2 or max2 < min1:
            return False

    return True


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
