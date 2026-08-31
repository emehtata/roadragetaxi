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


def segments_intersect(
    first_start: Tuple[float, float],
    first_end: Tuple[float, float],
    second_start: Tuple[float, float],
    second_end: Tuple[float, float],
) -> bool:
    """Return whether two line segments intersect, including endpoints."""
    def orientation(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(start, end, point) -> bool:
        return (
            min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
            and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
        )

    orientations = (
        orientation(first_start, first_end, second_start),
        orientation(first_start, first_end, second_end),
        orientation(second_start, second_end, first_start),
        orientation(second_start, second_end, first_end),
    )
    first_a, first_b, second_a, second_b = (
        0 if abs(value) < 1e-9 else value
        for value in orientations
    )
    return (
        (first_a == 0 and on_segment(first_start, first_end, second_start))
        or (first_b == 0 and on_segment(first_start, first_end, second_end))
        or (second_a == 0 and on_segment(second_start, second_end, first_start))
        or (second_b == 0 and on_segment(second_start, second_end, first_end))
        or ((first_a > 0) != (first_b > 0) and (second_a > 0) != (second_b > 0))
    )


def clip_polygon_to_rect(
    points: list[Tuple[float, float]],
    rminx: float,
    rminy: float,
    rmaxx: float,
    rmaxy: float,
) -> list[Tuple[float, float]]:
    """Sutherland-Hodgman polygon clipping algorithm against an AABB rectangle."""
    output = points
    edges = ((0, rminx, True), (0, rmaxx, False), (1, rminy, True), (1, rmaxy, False))
    for axis, boundary, keep_greater in edges:
        input_list = output
        output = []
        if not input_list:
            break

        def inside(point: Tuple[float, float]) -> bool:
            return point[axis] >= boundary if keep_greater else point[axis] <= boundary

        def intersect(start: Tuple[float, float], end: Tuple[float, float]) -> Tuple[float, float]:
            delta = end[axis] - start[axis]
            t = (boundary - start[axis]) / delta if delta else 0.0
            return (
                start[0] + t * (end[0] - start[0]),
                start[1] + t * (end[1] - start[1]),
            )

        s = input_list[-1]
        for e in input_list:
            e_in = inside(e)
            s_in = inside(s)
            if e_in and not s_in:
                output.append(intersect(s, e))
            if e_in:
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
