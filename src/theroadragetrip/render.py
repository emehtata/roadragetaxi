import math
import os
from typing import List, Optional, Tuple

from .geo import clip_polygon_to_rect, dist_point_to_segment, meters_to_latlon
from .osm import Building, Place, Scenery, TaxiStop, Water, Way
from .physics import Car
from .taxi import TaxiManager, TaxiState
from .localization import tr

SCREEN_W, SCREEN_H = 1280, 720
FPS = 60
PX_PER_M = 0.7  # Default zoom level (pixels per meter)

_loading_image = None
_loading_image_path = os.path.join(os.path.dirname(__file__), "img", "theroadragetrip_1672_941.png")


def world_to_screen(
    wx: float,
    wy: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> tuple[int, int]:
    """Convert world meters -> screen pixels with north-up orientation."""
    sx = (wx - camx) * px_per_m + screen_w / 2
    sy = screen_h / 2 - (wy - camy) * px_per_m
    return int(sx), int(sy)


def get_viewport_bounds(
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    margin_m: float = 60.0,
) -> tuple[float, float, float, float]:
    """Calculate world coordinates (minx, miny, maxx, maxy) visible in the viewport."""
    half_w = (screen_w / 2.0) / px_per_m + margin_m
    half_h = (screen_h / 2.0) / px_per_m + margin_m
    return camx - half_w, camy - half_h, camx + half_w, camy + half_h


def _covered_by_higher_road(x: float, y: float, layer: int, ways: Optional[List[Way]]) -> bool:
    if not ways:
        return False
    for way in ways:
        if getattr(way, "layer", 0) <= layer or len(way.points_m) < 2:
            continue
        half_width = getattr(way, "half_width_m", 3.0)
        bbox = getattr(way, "bbox", None)
        if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
            xs = [point[0] for point in way.points_m]
            ys = [point[1] for point in way.points_m]
            bbox = (min(xs), min(ys), max(xs), max(ys))
        if bbox and not (bbox[0] - half_width <= x <= bbox[2] + half_width and bbox[1] - half_width <= y <= bbox[3] + half_width):
            continue
        if any(dist_point_to_segment(x, y, p1[0], p1[1], p2[0], p2[1]) <= half_width for p1, p2 in zip(way.points_m, way.points_m[1:])):
            return True
    return False


def draw_scenery(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    tree_effects=None,
    fallen_trees=None,
) -> None:
    """Draw parks, forests, and green spaces intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    colors = {
        "forest": (32, 95, 32),
        "wood": (32, 95, 32),
        "park": (42, 120, 42),
        "garden": (45, 125, 45),
        "meadow": (38, 110, 38),
        "grass": (36, 105, 36),
        "pitch": (48, 115, 55),
        "playground": (48, 115, 55),
        "sand": (160, 150, 110),
        "beach": (170, 160, 115),
    }

    for sc in sceneries:
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(sc.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in sc.points_m]
        color = colors.get(sc.kind.lower(), (38, 105, 38))
        pygame.draw.polygon(screen, color, pts)
        for tree_index, (tree_x, tree_y) in enumerate(getattr(sc, "trees", [])):
            if not (vminx <= tree_x <= vmaxx and vminy <= tree_y <= vmaxy):
                continue
            sx, sy = world_to_screen(tree_x, tree_y, camx, camy, px_per_m, screen_w, screen_h)
            tree_key = (id(sc), tree_index)
            effect = (tree_effects or {}).get(tree_key, {})
            shake = effect.get("shake", 0.0)
            if shake > 0.0:
                sx += math.sin(shake * 42.0) * max(1, int(2.0 * px_per_m))
            variation = abs(math.sin(tree_x * 12.9898 + tree_y * 78.233))
            size = 0.72 + variation * 0.62
            trunk = max(1, int(0.7 * size * px_per_m))
            trunk_height = max(2, int(1.5 * size * px_per_m))
            crown = max(2, int(2.2 * size * px_per_m))
            trunk_color = (78 + int(22 * variation), 52 + int(18 * variation), 27)
            crown_colors = ((25, 78, 29), (34, 101, 35), (48, 119, 42), (63, 112, 34))
            crown_color = crown_colors[min(len(crown_colors) - 1, int(variation * len(crown_colors)))]
            if tree_key in (fallen_trees or set()):
                fall_heading = effect.get("angle", 0.0)
                fall_x = sx + math.cos(fall_heading) * 3.2 * px_per_m
                fall_y = sy - math.sin(fall_heading) * 3.2 * px_per_m
                pygame.draw.line(screen, trunk_color, (sx, sy), (fall_x, fall_y), max(2, trunk))
                pygame.draw.circle(screen, crown_color, (int(fall_x), int(fall_y)), crown)
            else:
                pygame.draw.rect(screen, trunk_color, (sx - trunk // 2, sy, trunk, trunk_height))
                pygame.draw.circle(screen, crown_color, (sx, sy - crown // 2), crown)
            leaves_left = effect.get("leaves", 0.0)
            if leaves_left > 0.0:
                for leaf_index in range(8):
                    drift_x = math.sin(leaf_index * 2.7 + (1.2 - leaves_left) * 8.0) * 12.0 * px_per_m
                    drift_y = -(1.2 - leaves_left) * 20.0 * px_per_m + math.cos(leaf_index * 1.9) * 5.0 * px_per_m
                    pygame.draw.circle(screen, (82, 145, 44), (int(sx + drift_x), int(sy - crown + drift_y)), max(1, int(px_per_m * 0.22)))


def draw_taxi_smoke(screen, car: Car, camx: float, camy: float, px_per_m: float = PX_PER_M, timer: float = 0.0) -> None:
    """Draw smoke from a taxi disabled by a high-speed tree impact."""
    if timer <= 0.0:
        return
    import pygame

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
    age = 5.0 - timer
    for index in range(5):
        radius = max(3, int((2.0 + index * 0.8) * px_per_m))
        x = int(cx - math.cos(car.heading) * (index + 1) * px_per_m + math.sin(age * 5 + index) * 3 * px_per_m)
        y = int(cy + math.sin(car.heading) * (index + 1) * px_per_m - (index + 1) * 2 * px_per_m)
        surface = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(surface, (100, 105, 105, max(20, 120 - index * 18)), (radius + 1, radius + 1), radius)
        screen.blit(surface, (x - radius - 1, y - radius - 1))


def draw_waters(
    screen,
    waters: List[Water],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw water polygons and waterways intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    for w in waters:
        bb = getattr(w, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue

        is_closed = len(w.points_m) >= 4 and w.points_m[0] == w.points_m[-1]
        if w.is_polygon and is_closed and len(w.points_m) >= 3:
            # Clip large water polygons to viewport to avoid software scanline lag
            if len(w.points_m) > 40:
                clipped = clip_polygon_to_rect(w.points_m, vminx, vminy, vmaxx, vmaxy)
                if len(clipped) < 3:
                    continue
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in clipped]
            else:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
            pygame.draw.polygon(screen, (30, 100, 200), pts)
            pygame.draw.lines(screen, (20, 80, 160), True, pts, 1)
        else:
            if len(w.points_m) >= 2:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
                pygame.draw.lines(screen, (30, 100, 200), False, pts, max(2, int(3 * px_per_m)))


def draw_buildings(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw building footprints intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 50.0)

    for b in buildings:
        bb = getattr(b, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(b.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in b.points_m]
        height = max(3.0, float(getattr(b, "height_m", 8.0)))
        depth = min(30, max(3, int(height * 0.35 * px_per_m)))
        roof = [(x - depth * 0.7, y - depth) for x, y in pts]

        building_center_x = sum(point[0] for point in b.points_m) / len(b.points_m)
        building_center_y = sum(point[1] for point in b.points_m) / len(b.points_m)
        texture_seed = abs(math.sin(building_center_x * 0.013 + building_center_y * 0.017))
        wall_colors = ((158, 105, 82), (174, 166, 143), (116, 131, 119), (139, 139, 137))
        roof_colors = ((92, 57, 48), (102, 96, 82), (66, 83, 69), (83, 86, 87))
        texture_index = min(len(wall_colors) - 1, int(texture_seed * len(wall_colors)))
        pygame.draw.polygon(screen, (45, 42, 39), [(x + 2, y + 3) for x, y in roof])
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            next_roof = roof[(index + 1) % len(roof)]
            pygame.draw.polygon(screen, wall_colors[texture_index], [point, next_point, next_roof, roof[index]])
        roof_color = roof_colors[texture_index]
        pygame.draw.polygon(screen, roof_color, roof)
        pygame.draw.lines(screen, (70, 66, 61), True, roof, 1)

        # Add small facade details after the roof so they remain visible at low zoom.
        roof_dx = roof[0][0] - pts[0][0]
        roof_dy = roof[0][1] - pts[0][1]
        centroid_x = sum(point[0] for point in pts) / len(pts)
        centroid_y = sum(point[1] for point in pts) / len(pts)
        visible_edges = []
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            midpoint_x = (point[0] + next_point[0]) * 0.5
            midpoint_y = (point[1] + next_point[1]) * 0.5
            frontness = (midpoint_x - centroid_x) * -roof_dx + (midpoint_y - centroid_y) * -roof_dy
            if frontness > 0:
                visible_edges.append(index)
        longest_edge = max(
            visible_edges,
            key=lambda index: math.hypot(
                pts[(index + 1) % len(pts)][0] - pts[index][0],
                pts[(index + 1) % len(pts)][1] - pts[index][1],
            ),
            default=-1,
        )
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            roof_point = roof[index]
            next_roof = roof[(index + 1) % len(roof)]
            midpoint_x = (point[0] + next_point[0]) * 0.5
            midpoint_y = (point[1] + next_point[1]) * 0.5
            frontness = (midpoint_x - centroid_x) * -roof_dx + (midpoint_y - centroid_y) * -roof_dy
            if frontness <= 0:
                continue
            edge_x = next_point[0] - point[0]
            edge_y = next_point[1] - point[1]
            edge_length = math.hypot(edge_x, edge_y)
            if edge_length < 8:
                continue
            edge_x /= edge_length
            edge_y /= edge_length
            roof_x = roof_point[0] - point[0]
            roof_y = roof_point[1] - point[1]
            window_count = min(3, max(1, int(edge_length // 32)))

            for window_index in range(window_count):
                center = (window_index + 1) / (window_count + 1)
                center_x = point[0] + (next_point[0] - point[0]) * center + roof_x * 0.42
                center_y = point[1] + (next_point[1] - point[1]) * center + roof_y * 0.42
                window_width = min(10.0, edge_length / (window_count + 2) * 0.45)
                half_width = window_width / 2
                window_height = max(3.0, min(7.0, abs(roof_y) * 0.22))
                pane_x = -roof_x * window_height / max(abs(roof_y), 1.0)
                pane_y = -roof_y * window_height / max(abs(roof_y), 1.0)
                window = [
                    (center_x - edge_x * half_width, center_y - edge_y * half_width),
                    (center_x + edge_x * half_width, center_y + edge_y * half_width),
                    (center_x + edge_x * half_width + pane_x, center_y + edge_y * half_width + pane_y),
                    (center_x - edge_x * half_width + pane_x, center_y - edge_y * half_width + pane_y),
                ]
                pygame.draw.polygon(screen, (52, 82, 91), window)
                pygame.draw.lines(screen, (25, 42, 47), True, window, 1)
                pygame.draw.line(screen, (155, 180, 178), window[0], window[2], 1)

            if index == longest_edge:
                door_width = min(11.0, edge_length * 0.22)
                door_height = max(5.0, min(13.0, abs(roof_y) * 0.68))
                door_center = 0.5
                door_x = point[0] + (next_point[0] - point[0]) * door_center + roof_x * 0.48
                door_y = point[1] + (next_point[1] - point[1]) * door_center + roof_y * 0.48
                door_shift_x = -roof_x * door_height / max(abs(roof_y), 1.0)
                door_shift_y = -roof_y * door_height / max(abs(roof_y), 1.0)
                half_door = door_width / 2
                door = [
                    (door_x - edge_x * half_door, door_y - edge_y * half_door),
                    (door_x + edge_x * half_door, door_y + edge_y * half_door),
                    (door_x + edge_x * half_door + door_shift_x, door_y + edge_y * half_door + door_shift_y),
                    (door_x - edge_x * half_door + door_shift_x, door_y - edge_y * half_door + door_shift_y),
                ]
                pygame.draw.polygon(screen, (58, 48, 42), door)
                pygame.draw.lines(screen, (32, 28, 25), True, door, 1)


def draw_ways(
    screen,
    ways: List[Way],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw road ways intersecting viewport with highway-type proportional thickness and layer ordering."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 60.0)

    # Filter visible ways first, then sort only visible ways by layer
    visible_ways = []
    for w in ways:
        bb = getattr(w, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(w.points_m) >= 2:
            visible_ways.append(w)

    visible_ways.sort(key=lambda w: getattr(w, "layer", 0))

    for w in visible_ways:
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]

        thickness = max(1, int(w.half_width_m * 2 * px_per_m))

        if not w.is_drivable:
            # Pedestrian paths, footways, cycleways, sidewalks (subtle dark slate gray)
            ped_thickness = max(1, int(getattr(w, "half_width_m", 1.2) * 2 * px_per_m))
            ped_color = (65, 65, 65)
            pygame.draw.lines(screen, ped_color, False, pts, ped_thickness)
            continue

        # If it's a bridge or elevated layer, draw bridge outline/border
        is_bridge = getattr(w, "is_bridge", False) or getattr(w, "layer", 0) > 0
        if is_bridge:
            bridge_border_thickness = thickness + max(2, int(2 * px_per_m))
            pygame.draw.lines(screen, (30, 30, 30), False, pts, bridge_border_thickness)

        if w.is_ice_road:
            road_color = (160, 200, 225)
            center_color = (210, 235, 250)
        elif getattr(w, "is_busway", False) or w.highway == "busway":
            # Bus lanes / busways (slightly tinted warm amber/ochre asphalt for clear distinction)
            road_color = (80, 72, 60)
            center_color = (220, 180, 60)
        elif w.highway == "living_street":
            # Living streets / pihatiet (paved/cobblestone tone)
            road_color = (85, 80, 78)
            center_color = (130, 125, 120)
        else:
            # Regular drivable car roads (dark asphalt)
            road_color = (70, 70, 70)
            center_color = (110, 110, 110)

        pygame.draw.lines(screen, road_color, False, pts, thickness)
        if thickness >= 6:
            pygame.draw.lines(screen, center_color, False, pts, 1)

        # Draw one-way directional chevron indicators if zoomed in
        oneway_val = getattr(w, "oneway", 0)
        if oneway_val != 0 and px_per_m >= 0.3:
            pts_world = w.points_m if oneway_val > 0 else list(reversed(w.points_m))
            arrow_color = (200, 200, 200)
            step_dist = 40.0  # meters between arrows
            cum_dist = 0.0
            for i in range(len(pts_world) - 1):
                ax, ay = pts_world[i]
                bx, by = pts_world[i + 1]
                seg_len = math.hypot(bx - ax, by - ay)
                if seg_len < 1.0:
                    continue
                seg_angle = math.atan2(by - ay, bx - ax)
                while cum_dist < seg_len:
                    if cum_dist > 5.0:  # avoid right at vertices
                        px_w = ax + (cum_dist / seg_len) * (bx - ax)
                        py_w = ay + (cum_dist / seg_len) * (by - ay)
                        if vminx <= px_w <= vmaxx and vminy <= py_w <= vmaxy:
                            sc_x, sc_y = world_to_screen(px_w, py_w, camx, camy, px_per_m, screen_w, screen_h)
                            arr_len = max(3.0, 4.0 * px_per_m)
                            # Draw chevron >
                            left_x = sc_x - math.cos(seg_angle - 0.6) * arr_len
                            left_y = sc_y + math.sin(seg_angle - 0.6) * arr_len
                            right_x = sc_x - math.cos(seg_angle + 0.6) * arr_len
                            right_y = sc_y + math.sin(seg_angle + 0.6) * arr_len
                            pygame.draw.lines(
                                screen,
                                arrow_color,
                                False,
                                [(left_x, left_y), (sc_x, sc_y), (right_x, right_y)],
                                2,
                            )
                    cum_dist += step_dist
                cum_dist -= seg_len


def draw_crossings(
    screen,
    crossings: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw Finnish zebra pedestrian crossings (suojatiet) with white road stripes aligned to road geometry."""
    import pygame

    if not crossings:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    for c in crossings:
        cx_w = getattr(c, "x", 0.0)
        cy_w = getattr(c, "y", 0.0)
        if not (vminx <= cx_w <= vmaxx and vminy <= cy_w <= vmaxy):
            continue

        sc_x, sc_y = world_to_screen(cx_w, cy_w, camx, camy, px_per_m, screen_w, screen_h)

        road_angle = getattr(c, "direction_angle", None)
        if road_angle is None:
            road_angle = 0.0

        # Finnish standard zebra crossing:
        # Crosswalk spans across road width (perpendicular to road axis)
        # Stripes run along road length (parallel to road traffic direction)
        # Each stripe is ~0.5m wide with ~0.5m gap, stripe length ~2.0 - 2.5m
        cross_width_m = getattr(c, "width_m", 5.0)
        stripe_len_m = getattr(c, "length_m", 2.2)

        # Unit vectors:
        # u_along: parallel to road traffic direction (direction of zebra stripes)
        # u_across: perpendicular to road (lateral across the crosswalk)
        # Note: In Pygame screen space, positive Y is down, so world Y is inverted (-sin)
        u_along_x = math.cos(road_angle)
        u_along_y = -math.sin(road_angle)

        u_across_x = -u_along_y  # perpendicular (90 deg counter-clockwise)
        u_across_y = u_along_x

        stripe_len_px = max(2.0, stripe_len_m * px_per_m)
        stripe_width_m = 0.5
        stripe_spacing_m = 0.9

        num_stripes = max(3, int(cross_width_m / stripe_spacing_m))
        span_total_m = (num_stripes - 1) * stripe_spacing_m
        start_offset_m = -span_total_m / 2.0

        stripe_thickness = max(1, int(stripe_width_m * px_per_m))
        stripe_color = (245, 245, 245)

        for i in range(num_stripes):
            lat_m = start_offset_m + i * stripe_spacing_m
            lat_px_x = u_across_x * (lat_m * px_per_m)
            lat_px_y = u_across_y * (lat_m * px_per_m)

            stripe_center_x = sc_x + lat_px_x
            stripe_center_y = sc_y + lat_px_y

            half_len_x = u_along_x * (stripe_len_px / 2.0)
            half_len_y = u_along_y * (stripe_len_px / 2.0)

            p1 = (stripe_center_x - half_len_x, stripe_center_y - half_len_y)
            p2 = (stripe_center_x + half_len_x, stripe_center_y + half_len_y)

            pygame.draw.line(screen, stripe_color, p1, p2, stripe_thickness)


def draw_labels(
    screen,
    font,
    ways: List[Way],
    waters: List[Water],
    buildings: List[Building],
    sceneries: List[Scenery],
    places: List[Place],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    max_labels: int = 35,
) -> None:
    """Draw text labels and street names with decluttering and collision avoidance."""
    import pygame

    placed_rects: List[pygame.Rect] = []
    seen_names: set[str] = set()
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    district_font = font
    try:
        district_font = pygame.font.SysFont(None, 28, bold=True)
    except Exception:
        pass

    count = 0

    def render_label(
        text: str,
        wx: float,
        wy: float,
        text_color,
        bg_color=(20, 20, 20, 190),
        use_font=None,
        border_color=None,
    ) -> bool:
        nonlocal count
        if count >= max_labels:
            return False
        if not (vminx <= wx <= vmaxx and vminy <= wy <= vmaxy):
            return False

        sx, sy = world_to_screen(wx, wy, camx, camy, px_per_m, screen_w, screen_h)
        # Avoid HUD / top bar area
        if not (10 <= sx <= screen_w - 10 and 80 <= sy <= screen_h - 20):
            return False

        f = use_font or font
        txt_surf = f.render(text, True, text_color)
        rect = txt_surf.get_rect(center=(sx, sy))
        bg_rect = rect.inflate(10, 6)

        # Check collision with already placed labels
        for pr in placed_rects:
            if bg_rect.colliderect(pr):
                return False

        placed_rects.append(bg_rect)
        bg_surface = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg_surface.fill(bg_color)
        screen.blit(bg_surface, bg_rect.topleft)
        if border_color:
            pygame.draw.rect(screen, border_color, bg_rect, width=1, border_radius=3)
        screen.blit(txt_surf, rect)
        count += 1
        return True

    # 1. Kaupunginosat / Districts & Suburbs (high prominence, warm gold/amber)
    for p in places:
        if count >= max_labels:
            break
        name = getattr(p, "name", None)
        if name and name not in seen_names:
            if render_label(
                name.upper(),
                p.x,
                p.y,
                (255, 230, 120),
                (30, 25, 10, 220),
                use_font=district_font,
                border_color=(200, 170, 70),
            ):
                seen_names.add(name)

    # 2. Water bodies (cyan)
    for wat in waters:
        if count >= max_labels:
            break
        name = getattr(wat, "name", None)
        if not name or name in seen_names:
            continue
        bb = getattr(wat, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if wat.points_m:
            cx = (bb[0] + bb[2]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[0] for p in wat.points_m) / len(wat.points_m))
            cy = (bb[1] + bb[3]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[1] for p in wat.points_m) / len(wat.points_m))
            if render_label(name, cx, cy, (160, 225, 255), (10, 30, 50, 210)):
                seen_names.add(name)

    # 3. Scenery / Parks (green)
    for sc in sceneries:
        if count >= max_labels:
            break
        name = getattr(sc, "name", None)
        if not name or name in seen_names:
            continue
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if sc.points_m:
            cx = (bb[0] + bb[2]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[0] for p in sc.points_m) / len(sc.points_m))
            cy = (bb[1] + bb[3]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[1] for p in sc.points_m) / len(sc.points_m))
            if render_label(name, cx, cy, (190, 255, 190), (15, 45, 15, 210)):
                seen_names.add(name)

    # 4. Road / street names (white, only when sufficiently zoomed in)
    if px_per_m >= 0.35:
        for w in ways:
            if count >= max_labels:
                break
            name = getattr(w, "name", None)
            if not name or name in seen_names:
                continue
            bb = getattr(w, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            pts = w.points_m
            if len(pts) >= 2:
                mid_idx = len(pts) // 2
                mx = (pts[mid_idx - 1][0] + pts[mid_idx][0]) * 0.5
                my = (pts[mid_idx - 1][1] + pts[mid_idx][1]) * 0.5
                if render_label(name, mx, my, (255, 255, 255), (25, 25, 25, 210)):
                    seen_names.add(name)

    # 5. Buildings (warm yellow, only when sufficiently zoomed in and room left)
    if px_per_m >= 0.45 and count < max_labels:
        for b in buildings:
            if count >= max_labels:
                break
            name = getattr(b, "name", None)
            if not name or name in seen_names:
                continue
            bb = getattr(b, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            if b.points_m:
                cx = (bb[0] + bb[2]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[0] for p in b.points_m) / len(b.points_m))
                cy = (bb[1] + bb[3]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[1] for p in b.points_m) / len(b.points_m))
                if render_label(name, cx, cy, (255, 240, 180), (35, 30, 25, 210)):
                    seen_names.add(name)


def _draw_vehicle(
    screen,
    cx: float,
    cy: float,
    heading: float,
    length_px: float,
    width_px: float,
    body_color: Tuple[int, int, int],
    outline_color: Tuple[int, int, int] = (20, 20, 20),
    is_taxi: bool = False,
    turn_signal: str = "",
    turn_signal_elapsed: float = 0.0,
) -> None:
    """Draw an oriented vehicle box on scale with headlights (white) and taillights (red)."""
    import pygame

    cos_h = math.cos(heading)
    sin_h = math.sin(heading)

    # Local vehicle axes:
    # Forward vector in screen coordinates (screen y is inverted relative to world y)
    fx = cos_h
    fy = -sin_h

    # Right perpendicular vector
    rx = sin_h
    ry = cos_h

    hl = length_px / 2.0
    hw = width_px / 2.0

    # 4 corners of rectangle: Front-Right, Front-Left, Rear-Left, Rear-Right
    c_fr = (cx + fx * hl + rx * hw, cy + fy * hl + ry * hw)
    c_fl = (cx + fx * hl - rx * hw, cy + fy * hl - ry * hw)
    c_rl = (cx - fx * hl - rx * hw, cy - fy * hl - ry * hw)
    c_rr = (cx - fx * hl + rx * hw, cy - fy * hl + ry * hw)

    # Vehicle body
    pygame.draw.polygon(screen, body_color, [c_fr, c_fl, c_rl, c_rr])
    pygame.draw.polygon(screen, outline_color, [c_fr, c_fl, c_rl, c_rr], 1)

    # Windshield / cabin accent
    if length_px >= 6.0:
        cabin_hl = hl * 0.45
        cabin_hw = hw * 0.75
        cab_fr = (cx + fx * (cabin_hl * 0.4) + rx * cabin_hw, cy + fy * (cabin_hl * 0.4) + ry * cabin_hw)
        cab_fl = (cx + fx * (cabin_hl * 0.4) - rx * cabin_hw, cy + fy * (cabin_hl * 0.4) - ry * cabin_hw)
        cab_rl = (cx - fx * (cabin_hl * 0.8) - rx * cabin_hw, cy - fy * (cabin_hl * 0.8) - ry * cabin_hw)
        cab_rr = (cx - fx * (cabin_hl * 0.8) + rx * cabin_hw, cy - fy * (cabin_hl * 0.8) + ry * cabin_hw)
        pygame.draw.polygon(screen, (30, 35, 45), [cab_fr, cab_fl, cab_rl, cab_rr])

    # Taxi sign on roof
    if is_taxi and length_px >= 6.0:
        tx_hl = hl * 0.2
        tx_hw = hw * 0.4
        t_fr = (cx + fx * tx_hl + rx * tx_hw, cy + fy * tx_hl + ry * tx_hw)
        t_fl = (cx + fx * tx_hl - rx * tx_hw, cy + fy * tx_hl - ry * tx_hw)
        t_rl = (cx - fx * tx_hl - rx * tx_hw, cy - fy * tx_hl - ry * tx_hw)
        t_rr = (cx - fx * tx_hl + rx * tx_hw, cy - fy * tx_hl + ry * tx_hw)
        pygame.draw.polygon(screen, (240, 220, 20), [t_fr, t_fl, t_rl, t_rr])
        pygame.draw.polygon(screen, (30, 30, 30), [t_fr, t_fl, t_rl, t_rr], 1)

    # Lights (front white, back red)
    light_inset = hw * 0.7
    light_r = max(1.0, min(2.5, width_px * 0.15))

    # Front headlights (white / yellow-white)
    f_r = (cx + fx * (hl - 0.5) + rx * light_inset, cy + fy * (hl - 0.5) + ry * light_inset)
    f_l = (cx + fx * (hl - 0.5) - rx * light_inset, cy + fy * (hl - 0.5) - ry * light_inset)
    pygame.draw.circle(screen, (255, 255, 230), (int(f_r[0]), int(f_r[1])), int(light_r))
    pygame.draw.circle(screen, (255, 255, 230), (int(f_l[0]), int(f_l[1])), int(light_r))

    # Rear taillights (red)
    r_r = (cx - fx * (hl - 0.5) + rx * light_inset, cy - fy * (hl - 0.5) + ry * light_inset)
    r_l = (cx - fx * (hl - 0.5) - rx * light_inset, cy - fy * (hl - 0.5) - ry * light_inset)
    pygame.draw.circle(screen, (230, 30, 30), (int(r_r[0]), int(r_r[1])), int(light_r))
    pygame.draw.circle(screen, (230, 30, 30), (int(r_l[0]), int(r_l[1])), int(light_r))

    if turn_signal and (turn_signal_elapsed < 0.45 or (pygame.time.get_ticks() // 450) % 2 == 0):
        signal_color = (255, 170, 20)
        signal_side = 1.0 if turn_signal == "right" else -1.0
        signal_x = cx + fx * (hl - 0.5) + rx * (light_inset * signal_side)
        signal_y = cy + fy * (hl - 0.5) + ry * (light_inset * signal_side)
        pygame.draw.circle(screen, signal_color, (int(signal_x), int(signal_y)), int(light_r + 0.5))


def draw_car(
    screen,
    car: Car,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    shout_timer: float = 0.0,
    font=None,
    shout_text: str = "PRKL!",
) -> None:
    """Draw player taxi scaled in meters with headlights and taillights."""
    import pygame

    if _covered_by_higher_road(car.x, car.y, getattr(car, "layer", 0), ways):
        return
    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, screen_w, screen_h)
    length_m = getattr(car, "length_m", 4.0)
    width_m = getattr(car, "width_m", 1.8)
    length_px = max(6.0, length_m * px_per_m)
    width_px = max(3.0, width_m * px_per_m)

    _draw_vehicle(
        screen,
        cx=cx,
        cy=cy,
        heading=car.heading,
        length_px=length_px,
        width_px=width_px,
        body_color=(235, 195, 30),  # Yellow taxi
        outline_color=(30, 30, 30),
        is_taxi=True,
    )

    if shout_timer > 0.0 and font:
        alpha = int(min(255, (shout_timer / 0.5) * 255)) if shout_timer < 0.5 else 255
        shout_surf = font.render(shout_text, True, (240, 40, 40))
        shout_surf.set_alpha(alpha)
        text_width, text_height = shout_surf.get_size()
        bubble_width, bubble_height = text_width + 8, text_height + 4
        bubble_x = cx - bubble_width / 2
        bubble_y = cy - max(22, int(length_px * 0.7)) - bubble_height - 6
        bubble_surf = pygame.Surface((bubble_width, bubble_height), pygame.SRCALPHA)
        pygame.draw.rect(
            bubble_surf,
            (255, 255, 255, min(240, alpha)),
            (0, 0, bubble_width, bubble_height),
            border_radius=4,
        )
        pygame.draw.rect(
            bubble_surf,
            (200, 30, 30, alpha),
            (0, 0, bubble_width, bubble_height),
            width=1,
            border_radius=4,
        )
        bubble_surf.blit(shout_surf, (4, 2))
        screen.blit(bubble_surf, (int(bubble_x), int(bubble_y)))


def draw_npc_cars(
    screen,
    npcs: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
) -> None:
    """Draw autonomous NPC cars scaled in meters with headlights and taillights."""
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    for npc in npcs:
        if not (vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy):
            continue
        if _covered_by_higher_road(npc.x, npc.y, getattr(npc, "layer", getattr(npc.way, "layer", 0)), ways):
            continue

        cx, cy = world_to_screen(npc.x, npc.y, camx, camy, px_per_m, screen_w, screen_h)
        length_m = getattr(npc, "length_m", 4.0)
        width_m = getattr(npc, "width_m", 1.8)
        length_px = max(5.0, length_m * px_per_m)
        width_px = max(2.5, width_m * px_per_m)

        _draw_vehicle(
            screen,
            cx=cx,
            cy=cy,
            heading=npc.heading,
            length_px=length_px,
            width_px=width_px,
            body_color=npc.color,
            outline_color=(20, 20, 20),
            is_taxi=getattr(npc, "is_taxi", False),
            turn_signal=getattr(npc, "turn_signal", ""),
            turn_signal_elapsed=getattr(npc, "turn_signal_elapsed", 0.0),
        )

        # Draw animated smoke puff effect if NPC is disabled from a crash
        crashed_timer = getattr(npc, "crashed_timer", 0.0)
        if crashed_timer > 0.0:
            import pygame
            t = 5.0 - crashed_timer
            # 3 animated puff particles floating upwards from engine bay
            fx = math.cos(npc.heading)
            fy = -math.sin(npc.heading)
            front_cx = cx + fx * (length_px * 0.4)
            front_cy = cy + fy * (length_px * 0.4)
            for puff_idx in range(4):
                offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
                puff_x = front_cx + math.sin(t * 3.0 + puff_idx) * (4.0 * offset_t)
                puff_y = front_cy - offset_t * 14.0  # drifts upwards
                radius = int(3.0 + offset_t * 5.0)
                alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
                smoke_surf = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(smoke_surf, (180, 180, 180, alpha), (radius + 1, radius + 1), radius)
                screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_pedestrians(
    screen,
    pedestrians: List,
    camx: float,
    camy: float,
    font=None,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
) -> None:
    """Draw pedestrians as colored circles with movement heading and comic cursing speech bubbles."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)

    for ped in pedestrians:
        if not (vminx <= ped.x <= vmaxx and vminy <= ped.y <= vmaxy):
            continue
        if _covered_by_higher_road(ped.x, ped.y, getattr(ped, "layer", getattr(ped.way, "layer", 0)), ways):
            continue

        cx, cy = world_to_screen(ped.x, ped.y, camx, camy, px_per_m, screen_w, screen_h)
        radius_px = max(3.0, getattr(ped, "radius_m", 0.45) * px_per_m)

        # Body shadow / outline
        pygame.draw.circle(screen, (20, 20, 20), (int(cx), int(cy)), int(radius_px + 1.5))
        # Body
        pygame.draw.circle(screen, ped.color, (int(cx), int(cy)), int(radius_px))

        # Direction indicator (head / shoulders notch)
        hx = cx + math.cos(ped.heading) * (radius_px * 0.9)
        hy = cy + math.sin(ped.heading) * (radius_px * 0.9)
        pygame.draw.circle(screen, (255, 255, 255), (int(hx), int(hy)), max(1, int(radius_px * 0.45)))

        # Comic cursing bubble when startled/dodging
        curse_timer = getattr(ped, "curse_timer", 0.0)
        if curse_timer > 0.0 and font:
            curse_txt = getattr(ped, "curse_text", "@#*!%")
            # Alpha fadeout in last 0.5s
            alpha = int(min(255, (curse_timer / 0.5) * 255)) if curse_timer < 0.5 else 255

            txt_surf = font.render(curse_txt, True, (240, 40, 40))
            tw, th = txt_surf.get_size()
            bw, bh = tw + 8, th + 4
            bx = cx - bw / 2
            by = cy - radius_px - bh - 6

            # Speech bubble background
            bubble_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
            pygame.draw.rect(bubble_surf, (255, 255, 255, min(240, alpha)), (0, 0, bw, bh), border_radius=4)
            pygame.draw.rect(bubble_surf, (200, 30, 30, alpha), (0, 0, bw, bh), width=1, border_radius=4)
            if alpha < 255:
                txt_surf.set_alpha(alpha)
            bubble_surf.blit(txt_surf, (4, 2))
            screen.blit(bubble_surf, (int(bx), int(by)))


def draw_cyclists(
    screen,
    cyclists: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
) -> None:
    """Draw cyclists as compact riders with bicycle wheels."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)
    for cyclist in cyclists:
        if not (vminx <= cyclist.x <= vmaxx and vminy <= cyclist.y <= vmaxy):
            continue
        if _covered_by_higher_road(cyclist.x, cyclist.y, getattr(cyclist.way, "layer", 0), ways):
            continue
        cx, cy = world_to_screen(cyclist.x, cyclist.y, camx, camy, px_per_m, screen_w, screen_h)
        scale = max(3.0, px_per_m)
        # Convert world heading to screen direction; screen y grows downward.
        direction_x = math.cos(cyclist.heading)
        direction_y = -math.sin(cyclist.heading)
        side_x = -direction_y
        side_y = direction_x
        wheel_gap = 1.2 * scale
        frame_width = max(1, int(0.14 * scale))
        detail_width = max(1, int(0.12 * scale))
        front = (cx + direction_x * wheel_gap, cy + direction_y * wheel_gap)
        rear = (cx - direction_x * wheel_gap, cy - direction_y * wheel_gap)
        handlebar = (front[0] - direction_x * 0.12 * scale, front[1] - direction_y * 0.12 * scale)
        rack = (rear[0] + direction_x * 0.18 * scale, rear[1] + direction_y * 0.18 * scale)

        # Top-down silhouette: tires barely protrude beyond the frame.
        pygame.draw.line(
            screen,
            (28, 28, 28),
            (rear[0] - direction_x * 0.18 * scale, rear[1] - direction_y * 0.18 * scale),
            (front[0] + direction_x * 0.18 * scale, front[1] + direction_y * 0.18 * scale),
            detail_width,
        )
        pygame.draw.line(screen, (218, 157, 45), rear, front, frame_width)
        pygame.draw.line(
            screen,
            (218, 157, 45),
            handlebar,
            (handlebar[0] + side_x * 0.3 * scale, handlebar[1] + side_y * 0.3 * scale),
            frame_width,
        )
        pygame.draw.line(
            screen,
            (55, 45, 35),
            rack,
            (rack[0] + side_x * 0.28 * scale, rack[1] + side_y * 0.28 * scale),
            frame_width,
        )
        pygame.draw.circle(screen, (25, 25, 25), (int(front[0]), int(front[1])), max(1, int(0.16 * scale)))
        pygame.draw.circle(screen, (25, 25, 25), (int(rear[0]), int(rear[1])), max(1, int(0.16 * scale)))
        pygame.draw.circle(screen, cyclist.color, (int(cx), int(cy)), max(2, int(0.3 * scale)))


def draw_traffic_lights(
    screen,
    traffic_lights: List,
    sim_time: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw traffic signal posts and active lights."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    for tl in traffic_lights:
        if not (vminx <= tl.x <= vmaxx and vminy <= tl.y <= vmaxy):
            continue

        cx, cy = world_to_screen(tl.x, tl.y, camx, camy, px_per_m, screen_w, screen_h)
        state = tl.get_state(sim_time)

        # Colors for 3 lamps (dim when off, bright with glow when on)
        is_red = state in ("red", "red+yellow")
        is_yellow = state in ("yellow", "red+yellow")
        is_green = state == "green"

        r_col = (255, 30, 30) if is_red else (60, 10, 10)
        y_col = (255, 210, 0) if is_yellow else (60, 50, 0)
        g_col = (40, 240, 60) if is_green else (10, 50, 15)

        lamp_r = 2
        signal_surface = pygame.Surface((7, 18), pygame.SRCALPHA)
        signal_surface.fill((15, 15, 15, 255))
        pygame.draw.rect(signal_surface, (70, 70, 70), signal_surface.get_rect(), width=1, border_radius=2)
        for y, color, active in ((4, r_col, is_red), (9, y_col, is_yellow), (14, g_col, is_green)):
            if active:
                pygame.draw.circle(signal_surface, (*color, 90), (3, y), 4)
            pygame.draw.circle(signal_surface, color, (3, y), lamp_r)

        # Rotate the housing itself so its long axis shows the controlled approach.
        rotation = 90.0 - math.degrees(tl.direction_angle or 0.0)
        rotated = pygame.transform.rotate(signal_surface, rotation)
        screen.blit(rotated, rotated.get_rect(center=(int(cx), int(cy))))


def draw_taxi_stops(
    screen,
    taxi_stops: List[TaxiStop],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw yellow TAXI signs at OSM taxi stops."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    for stop in taxi_stops:
        if not (vminx <= stop.x <= vmaxx and vminy <= stop.y <= vmaxy):
            continue

        cx, cy = world_to_screen(stop.x, stop.y, camx, camy, px_per_m, screen_w, screen_h)
        pole_bottom = cy + 11
        pygame.draw.line(screen, (55, 55, 55), (cx, cy - 1), (cx, pole_bottom), 2)
        sign = pygame.Rect(cx - 14, cy - 13, 28, 14)
        pygame.draw.rect(screen, (20, 20, 20), sign, border_radius=2)
        inner_sign = sign.inflate(-2, -2)
        pygame.draw.rect(screen, (255, 205, 25), inner_sign, border_radius=1)
        sign_font = pygame.font.Font(None, 11)
        sign_text = sign_font.render("TAXI", True, (20, 20, 20))
        screen.blit(sign_text, sign_text.get_rect(center=inner_sign.center))


def draw_speed_cameras(
    screen,
    cameras,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    flash_index: Optional[int] = None,
    flash_active: bool = False,
) -> None:
    """Draw roadside speed-camera boxes and their posts."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    for camera_index, camera in enumerate(cameras):
        if not (vminx <= camera.x <= vmaxx and vminy <= camera.y <= vmaxy):
            continue
        cx, cy = world_to_screen(camera.x, camera.y, camx, camy, px_per_m, screen_w, screen_h)
        scale = max(0.7, min(1.5, px_per_m / PX_PER_M))
        pole_height = max(10, int(18 * scale))
        pygame.draw.line(screen, (48, 52, 56), (cx, cy + 2), (cx, cy + pole_height), max(2, int(2 * scale)))
        direction_x = -math.cos(camera.heading)
        direction_y = math.sin(camera.heading)
        side_x = -direction_y
        side_y = direction_x
        half_width = 8 * scale
        half_height = 5.5 * scale
        front_x = cx + direction_x * half_height
        front_y = cy + direction_y * half_height
        back_x = cx - direction_x * half_height
        back_y = cy - direction_y * half_height
        corners = [
            (back_x + side_x * half_width, back_y + side_y * half_width),
            (front_x + side_x * half_width, front_y + side_y * half_width),
            (front_x - side_x * half_width, front_y - side_y * half_width),
            (back_x - side_x * half_width, back_y - side_y * half_width),
        ]
        pygame.draw.polygon(screen, (35, 40, 44), corners)
        pygame.draw.lines(screen, (190, 198, 202), True, corners, 1)
        lens_x = front_x + direction_x * 1.5 * scale
        lens_y = front_y + direction_y * 1.5 * scale
        pygame.draw.circle(screen, (220, 45, 35), (int(lens_x), int(lens_y)), max(2, int(2.5 * scale)))
        if flash_active and flash_index == camera_index:
            flash = pygame.Surface((70, 70), pygame.SRCALPHA)
            pygame.draw.circle(flash, (255, 255, 235, 150), (35, 35), 30)
            pygame.draw.circle(flash, (255, 255, 255, 235), (35, 35), 12)
            screen.blit(flash, (int(lens_x - 35), int(lens_y - 35)))
        arrow_start = (front_x + direction_x * 3 * scale, front_y + direction_y * 3 * scale)
        arrow_end = (front_x + direction_x * 15 * scale, front_y + direction_y * 15 * scale)
        pygame.draw.line(screen, (245, 205, 35), arrow_start, arrow_end, max(2, int(2 * scale)))
        arrow_side = max(2.5, 4 * scale)
        pygame.draw.polygon(screen, (245, 205, 35), [
            arrow_end,
            (arrow_end[0] - direction_x * arrow_side + side_x * arrow_side, arrow_end[1] - direction_y * arrow_side + side_y * arrow_side),
            (arrow_end[0] - direction_x * arrow_side - side_x * arrow_side, arrow_end[1] - direction_y * arrow_side - side_y * arrow_side),
        ])


def draw_taxi_target(
    screen,
    taxi_mgr: TaxiManager,
    camx: float,
    camy: float,
    font,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw pulsing waypoint circle, pin icon, and on-screen navigation arrow for active pickup/dropoff."""
    import pygame

    target = taxi_mgr.get_current_target()
    if not target:
        return

    is_pickup = taxi_mgr.state in (TaxiState.WAITING_FOR_PICKUP, TaxiState.CLIENT_WALKING_TO_CAR)
    main_color = (255, 200, 0) if is_pickup else (50, 220, 100)
    bg_marker_color = (255, 200, 0, 70) if is_pickup else (50, 220, 100, 70)

    # World position to screen
    sx, sy = world_to_screen(target.x, target.y, camx, camy, px_per_m, screen_w, screen_h)

    # Check if target is inside screen viewport
    in_view = 30 <= sx <= screen_w - 30 and 30 <= sy <= screen_h - 30

    if in_view:
        # Draw radius zone
        rad_px = max(8, int(target.radius_m * px_per_m))
        rad_surf = pygame.Surface((rad_px * 2 + 4, rad_px * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(rad_surf, bg_marker_color, (rad_px + 2, rad_px + 2), rad_px)
        pygame.draw.circle(rad_surf, main_color, (rad_px + 2, rad_px + 2), rad_px, 2)
        screen.blit(rad_surf, (sx - rad_px - 2, sy - rad_px - 2))

        # Center pulsing marker
        pygame.draw.circle(screen, main_color, (sx, sy), 7)
        pygame.draw.circle(screen, (20, 20, 20), (sx, sy), 7, 2)

        # Label above target
        tag_text = tr(language, "pickup") if is_pickup else tr(language, "to")
        lbl_surf = font.render(f"[{tag_text}] {target.address}", True, (255, 255, 255))
        rect = lbl_surf.get_rect(center=(sx, sy - rad_px - 14))
        bg_rect = rect.inflate(8, 4)
        bg = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg.fill((20, 20, 20, 220))
        screen.blit(bg, bg_rect.topleft)
        pygame.draw.rect(screen, main_color, bg_rect, width=1, border_radius=3)
        screen.blit(lbl_surf, rect)


        # Draw client pedestrian waiting or walking into the taxi
        p = taxi_mgr.current_passenger
        if is_pickup and p and not p.boarded:
            ped_sx, ped_sy = world_to_screen(p.ped_x, p.ped_y, camx, camy, px_per_m, screen_w, screen_h)
            ped_r = max(4.0, 0.5 * px_per_m)
            # Outline
            pygame.draw.circle(screen, (20, 20, 20), (int(ped_sx), int(ped_sy)), int(ped_r + 2))
            # Client body in distinct passenger color
            pygame.draw.circle(screen, p.ped_color, (int(ped_sx), int(ped_sy)), int(ped_r))
            # Heading notch
            hx = ped_sx + math.cos(p.ped_heading) * (ped_r * 0.9)
            hy = ped_sy + math.sin(p.ped_heading) * (ped_r * 0.9)
            pygame.draw.circle(screen, (255, 255, 255), (int(hx), int(hy)), max(1, int(ped_r * 0.45)))

            # Passenger name tag over client
            walking_label = "KYYTIIN" if language == "fi" else "TO TAXI"
            p_lbl = font.render(
                f"[{walking_label}] {p.name}" if p.is_walking_to_car else f"[P] {p.name}",
                True,
                (255, 230, 80),
            )
            p_rect = p_lbl.get_rect(center=(int(ped_sx), int(ped_sy - ped_r - 12)))
            p_bg = pygame.Surface((p_rect.width + 6, p_rect.height + 4), pygame.SRCALPHA)
            p_bg.fill((20, 20, 20, 200))
            screen.blit(p_bg, (p_rect.left - 3, p_rect.top - 2))
            screen.blit(p_lbl, p_rect)
    else:
        # Off-screen direction indicator arrow pointing towards target
        dx = target.x - camx
        dy = target.y - camy
        angle = math.atan2(dy, dx)
        dist_m = math.hypot(dx, dy)

        # Screen margin clamp for arrow
        edge_margin = 65
        center_x = screen_w / 2
        center_y = screen_h / 2
        # Ray-intersect with screen bounding rectangle
        dir_x = math.cos(angle)
        dir_y = -math.sin(angle)  # Inverted Y for screen coords

        max_dx = (screen_w / 2) - edge_margin
        max_dy = (screen_h / 2) - edge_margin

        scale_x = abs(max_dx / dir_x) if dir_x != 0 else float("inf")
        scale_y = abs(max_dy / dir_y) if dir_y != 0 else float("inf")
        scale = min(scale_x, scale_y)

        arrow_x = int(center_x + dir_x * scale)
        arrow_y = int(center_y + dir_y * scale)

        # Draw arrow triangle
        a_len = 16
        p1 = (arrow_x + math.cos(angle) * a_len, arrow_y - math.sin(angle) * a_len)
        p2 = (arrow_x + math.cos(angle + 2.5) * a_len * 0.7, arrow_y - math.sin(angle + 2.5) * a_len * 0.7)
        p3 = (arrow_x + math.cos(angle - 2.5) * a_len * 0.7, arrow_y - math.sin(angle - 2.5) * a_len * 0.7)
        pygame.draw.polygon(screen, main_color, [p1, p2, p3])
        pygame.draw.polygon(screen, (20, 20, 20), [p1, p2, p3], 1)

        # Distance tag on edge pointer
        d_str = f"{dist_m:.0f}m" if dist_m < 1000 else f"{dist_m / 1000.0:.1f}km"
        tag = "PICKUP" if is_pickup else "DROPOFF"
        d_surf = font.render(f"{tag} {d_str}", True, (255, 255, 255))
        d_rect = d_surf.get_rect(center=(arrow_x, arrow_y + 18 if arrow_y < screen_h - 40 else arrow_y - 18))
        d_bg = pygame.Surface((d_rect.width + 6, d_rect.height + 4), pygame.SRCALPHA)
        d_bg.fill((15, 15, 15, 210))
        screen.blit(d_bg, (d_rect.x - 3, d_rect.y - 2))
        screen.blit(d_surf, d_rect)


def draw_phone_offers(screen, taxi_mgr: TaxiManager, font, small_font, screen_w: int, screen_h: int, language: str = "fi") -> None:
    """Draw the in-game phone with selectable taxi offers."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((5, 8, 12, 170))
    screen.blit(overlay, (0, 0))

    phone = pygame.Rect(screen_w // 2 - 250, screen_h // 2 - 250, 500, 500)
    pygame.draw.rect(screen, (18, 22, 28), phone, border_radius=18)
    pygame.draw.rect(screen, (92, 105, 116), phone, width=3, border_radius=18)
    pygame.draw.rect(screen, (38, 48, 57), (phone.x + 180, phone.y + 12, 140, 5), border_radius=2)
    title = font.render("TAXI PHONE" if language == "en" else "TAKSIPUHELIN", True, (245, 220, 110))
    screen.blit(title, title.get_rect(center=(phone.centerx, phone.y + 48)))
    subtitle = small_font.render(tr(language, "select_ride"), True, (185, 195, 202))
    screen.blit(subtitle, subtitle.get_rect(center=(phone.centerx, phone.y + 78)))

    if taxi_mgr.current_passenger:
        message = small_font.render(tr(language, "finish_or_cancel"), True, (245, 150, 120))
        screen.blit(message, message.get_rect(center=phone.center))
    elif not taxi_mgr.offers:
        message = small_font.render(tr(language, "no_requests"), True, (220, 220, 220))
        screen.blit(message, message.get_rect(center=phone.center))
    else:
        for index, offer in enumerate(taxi_mgr.offers[:3]):
            y = phone.y + 112 + index * 105
            row = pygame.Rect(phone.x + 28, y, phone.width - 56, 88)
            pygame.draw.rect(screen, (30, 39, 47), row, border_radius=6)
            pygame.draw.rect(screen, (75, 88, 97), row, width=1, border_radius=6)
            passenger = offer.passenger
            distance = offer.pickup_distance_m
            distance_text = f"{distance:.0f} m" if distance < 1000 else f"{distance / 1000.0:.2f} km"
            label = small_font.render(f"[{index + 1}]  {passenger.name}", True, (245, 245, 240))
            pickup = small_font.render(f"{tr(language, 'pickup')}: {passenger.pickup.address}", True, (190, 205, 212))
            dropoff = small_font.render(f"{tr(language, 'to')}: {passenger.dropoff.address}", True, (170, 190, 175))
            dist = small_font.render(f"{tr(language, 'distance_client')}: {distance_text}", True, (255, 215, 95))
            screen.blit(label, (row.x + 12, row.y + 8))
            screen.blit(pickup, (row.x + 12, row.y + 29))
            screen.blit(dropoff, (row.x + 12, row.y + 48))
            screen.blit(dist, (row.x + 12, row.y + 67))

    hint_text = tr(language, "close_phone")
    if taxi_mgr.offers:
        hint_text += f"  |  {tr(language, 'reject_phone')}"
    hint = small_font.render(hint_text, True, (180, 185, 190))
    screen.blit(hint, hint.get_rect(center=(phone.centerx, phone.bottom - 20)))


def draw_compass(screen, car: Car, cx: int, cy: int, r: int, font, target_pos: Optional[tuple[float, float]] = None) -> None:
    """Draw circular north-up compass with heading needle, bearing degrees, and taxi nav arrow."""
    import pygame

    pygame.draw.circle(screen, (40, 40, 40), (cx, cy), r)
    pygame.draw.circle(screen, (200, 200, 200), (cx, cy), r, 2)

    n_t = font.render("N", True, (240, 240, 240))
    n_rect = n_t.get_rect(center=(cx, cy - r + 10))
    screen.blit(n_t, n_rect)

    # If taxi destination exists, draw green/gold guidance pointer
    if target_pos:
        tx, ty = target_pos
        dx = tx - car.x
        dy = ty - car.y
        t_ang = math.atan2(dy, dx)
        # Draw destination indicator arrow on compass ring
        t_nx = cx + math.cos(t_ang) * (r - 4)
        t_ny = cy - math.sin(t_ang) * (r - 4)
        t_ah = 8
        t_p1 = (t_nx + math.cos(t_ang + 2.5) * t_ah, t_ny - math.sin(t_ang + 2.5) * t_ah)
        t_p2 = (t_nx + math.cos(t_ang - 2.5) * t_ah, t_ny - math.sin(t_ang - 2.5) * t_ah)
        pygame.draw.polygon(screen, (255, 215, 0), [(t_nx, t_ny), t_p1, t_p2])

    ang = car.heading
    nx = cx + math.cos(ang) * (r - 8)
    ny = cy - math.sin(ang) * (r - 8)
    pygame.draw.line(screen, (220, 40, 40), (cx, cy), (nx, ny), 3)

    ah = 6
    ph1 = (nx + math.cos(ang + 2.4) * ah, ny - math.sin(ang + 2.4) * ah)
    ph2 = (nx + math.cos(ang - 2.4) * ah, ny - math.sin(ang - 2.4) * ah)
    pygame.draw.polygon(screen, (220, 40, 40), [(nx, ny), ph1, ph2])

    deg = (90.0 - math.degrees(ang)) % 360.0
    b_t = font.render(f"{int(deg):03d}\u00B0", True, (240, 240, 240))
    b_rect = b_t.get_rect(center=(cx, cy + r - 12))
    screen.blit(b_t, b_rect)


def draw_loading_screen(
    screen,
    font,
    progress: float,
    message: str = "Loading scenery...",
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    show_details: bool = True,
) -> None:
    """Draw a standalone loading screen with a progress meter bar and message."""
    import pygame

    global _loading_image

    if _loading_image is None and os.path.exists(_loading_image_path):
        try:
            _loading_image = pygame.image.load(_loading_image_path).convert()
        except pygame.error:
            _loading_image = False

    if _loading_image:
        image_w, image_h = _loading_image.get_size()
        scale = max(screen_w / image_w, screen_h / image_h)
        scaled_size = (round(image_w * scale), round(image_h * scale))
        background = pygame.transform.smoothscale(_loading_image, scaled_size)
        image_x = (screen_w - scaled_size[0]) // 2
        image_y = (screen_h - scaled_size[1]) // 2
        screen.blit(background, (image_x, image_y))
        overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 105))
        screen.blit(overlay, (0, 0))
    else:
        screen.fill((20, 25, 30))

    if not show_details:
        return

    # Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 40, bold=True)
    except Exception:
        pass
    title_surf = title_font.render("THE ROAD RAGE TRIP", True, (240, 240, 240))
    title_rect = title_surf.get_rect(center=(screen_w // 2, screen_h // 2 - 70))
    screen.blit(title_surf, title_rect)

    # Subtitle
    sub_surf = font.render("Loading OpenStreetMap roads & scenery...", True, (160, 175, 190))
    sub_rect = sub_surf.get_rect(center=(screen_w // 2, screen_h // 2 - 35))
    screen.blit(sub_surf, sub_rect)

    # Progress bar dimensions
    bar_w = 440
    bar_h = 24
    bar_x = (screen_w - bar_w) // 2
    bar_y = screen_h // 2 + 5

    # Outer frame and background
    pygame.draw.rect(screen, (35, 42, 50), (bar_x, bar_y, bar_w, bar_h), border_radius=4)
    pygame.draw.rect(screen, (100, 115, 130), (bar_x, bar_y, bar_w, bar_h), width=2, border_radius=4)

    # Fill
    clamped_prog = max(0.0, min(1.0, progress))
    fill_w = int((bar_w - 4) * clamped_prog)
    if fill_w > 0:
        pygame.draw.rect(screen, (40, 180, 100), (bar_x + 2, bar_y + 2, fill_w, bar_h - 4), border_radius=2)

    # Percentage and message
    pct_str = f"{int(clamped_prog * 100)}%"
    msg_surf = font.render(f"{message} ({pct_str})", True, (220, 230, 240))
    msg_rect = msg_surf.get_rect(center=(screen_w // 2, bar_y + bar_h + 22))
    screen.blit(msg_surf, msg_rect)


def draw_city_selection_menu(
    screen,
    font,
    cities: List[str],
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw city selection menu with 10 largest cities in Finland."""
    import pygame

    draw_loading_screen(screen, font, 1.0, "Ready", screen_w, screen_h, show_details=False)
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((8, 14, 22, 135))
    screen.blit(overlay, (0, 0))

    # Header / Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 38, bold=True)
    except Exception:
        pass

    t_surf = title_font.render("THE ROAD RAGE TRIP", True, (245, 245, 245))
    t_rect = t_surf.get_rect(center=(screen_w // 2, 45))
    screen.blit(t_surf, t_rect)

    sub_font = font
    try:
        sub_font = pygame.font.SysFont(None, 22)
    except Exception:
        pass

    sub_surf = sub_font.render(tr(language, "select_city"), True, (150, 180, 210))
    sub_rect = sub_surf.get_rect(center=(screen_w // 2, 80))
    screen.blit(sub_surf, sub_rect)

    # 2-column city grid
    cols = 2
    rows = (len(cities) + cols - 1) // cols
    item_w = 320
    item_h = 42
    gap_x = 24
    gap_y = 10
    total_w = cols * item_w + (cols - 1) * gap_x
    start_x = (screen_w - total_w) // 2
    start_y = 115

    for idx, city in enumerate(cities):
        col = idx // rows
        row = idx % rows
        ix = start_x + col * (item_w + gap_x)
        iy = start_y + row * (item_h + gap_y)

        is_sel = idx == selected_idx
        bg_color = (45, 80, 130) if is_sel else (28, 36, 48)
        border_color = (100, 200, 255) if is_sel else (60, 75, 95)
        text_color = (255, 255, 255) if is_sel else (200, 210, 220)

        pygame.draw.rect(screen, bg_color, (ix, iy, item_w, item_h), border_radius=6)
        pygame.draw.rect(screen, border_color, (ix, iy, item_w, item_h), width=2 if is_sel else 1, border_radius=6)

        num_prefix = f"{(idx + 1) % 10}: "
        city_label = f"{num_prefix}{city}"
        if is_sel:
            city_label = f"> {city_label}"

        c_surf = font.render(city_label, True, text_color)
        c_rect = c_surf.get_rect(midleft=(ix + 16, iy + item_h // 2))
        screen.blit(c_surf, c_rect)

    # Navigation hint
    hint_surf = sub_font.render(
        tr(language, "city_hint"),
        True,
        (130, 150, 170),
    )
    hint_rect = hint_surf.get_rect(center=(screen_w // 2, screen_h - 35))
    screen.blit(hint_surf, hint_rect)


def draw_help_screen(
    screen,
    font,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw the game's objective and keyboard controls over the current frame."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((5, 10, 16, 220))
    screen.blit(overlay, (0, 0))

    panel = pygame.Rect(90, 45, screen_w - 180, screen_h - 90)
    pygame.draw.rect(screen, (22, 30, 40), panel, border_radius=8)
    pygame.draw.rect(screen, (100, 170, 220), panel, width=2, border_radius=8)

    title_font = pygame.font.SysFont(None, 38, bold=True)
    section_font = pygame.font.SysFont(None, 25, bold=True)
    title = title_font.render("THE ROAD RAGE TRIP", True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, panel.y + 38)))

    sections = [
        (tr(language, "story"), [
            "Olet kaiken kokenut taksikuski, joka ajaa keikkaa Suomen eri kaupungeissa." if language == "fi" else "You are a veteran taxi driver working rides across Finnish cities.",
            "Joka paikkaa yhdistävät samat riesat: idiootit kanssakuskit, ääliöt pyöräilijät" if language == "fi" else "Everywhere has the same problems: foolish drivers, awful cyclists",
            "ja eteen pyrkivät jalankulkijat. Vuosien ajo on kehittänyt sinulle supervoiman:" if language == "fi" else "and pedestrians stepping in front of you. Years on the road gave you a superpower:",
            "raivohuuto tyhjentää tien häiriöistä. Raivomittari kasvaa rajoitusten mukaan ajaessa" if language == "fi" else "the rage shout clears obstacles. Rage grows when you follow limits",
            "ja pienenee, kun käytät raivovoimaa tehdäksesi tietä." if language == "fi" else "and drains when you use it to clear the way.",
        ]),
        (tr(language, "idea"), [
            "Aja asiakkaan luo, ota hänet kyytiin ja vie perille." if language == "fi" else "Drive to clients, pick them up, and take them to their destination.",
            "Nouda asiakkaat kaduilta, taksiasemilta tai nimetyiltä rakennuksilta." if language == "fi" else "Pick up clients from streets, taxi stops, or named buildings.",
            "Pysy tiellä, vältä kolareita ja kerää pisteitä nopeista onnistuneista kyydeistä." if language == "fi" else "Stay on the road, avoid crashes, and score points for successful rides.",
        ]),
    ]
    y = panel.y + 78
    for heading, lines in sections:
        heading_surface = section_font.render(heading, True, (255, 215, 95))
        screen.blit(heading_surface, (panel.x + 28, y))
        y += 30
        for line in lines:
            line_surface = font.render(line, True, (220, 228, 235))
            screen.blit(line_surface, (panel.x + 42, y))
            y += 25
        y += 16

    control_font = pygame.font.SysFont("monospace", 20)
    controls = [
        ("W / Up", tr(language, "drive")),
        ("S / Down", tr(language, "brake")),
        ("A / Left", tr(language, "left")),
        ("D / Right", tr(language, "right")),
        ("P", tr(language, "phone")),
        ("1 - 3", tr(language, "select_ride")),
        ("Space", tr(language, "rage")),
        ("R", tr(language, "respawn")),
        ("X", tr(language, "cancel_ride")),
        ("T", tr(language, "reset_trip")),
        ("L", tr(language, "labels")),
        ("K", tr(language, "lane_assist")),
        ("V", tr(language, "speed_limiter")),
        ("B", tr(language, "red_assist")),
        ("+ / -", tr(language, "zoom")),
        ("Esc", tr(language, "pause")),
        ("F1", tr(language, "help_short")),
    ]
    heading_surface = section_font.render("Ohjaus" if language == "fi" else "Controls", True, (255, 215, 95))
    screen.blit(heading_surface, (panel.x + 28, y))
    y += 30
    column_width = panel.width // 2
    rows_per_column = (len(controls) + 1) // 2
    for row in range(rows_per_column):
        for column in range(2):
            index = row + column * rows_per_column
            if index >= len(controls):
                continue
            key, action = controls[index]
            column_x = panel.x + 28 + column * column_width
            key_surface = control_font.render(key, True, (255, 215, 95))
            action_surface = font.render(action, True, (220, 228, 235))
            screen.blit(key_surface, (column_x, y))
            screen.blit(action_surface, (column_x + 105, y))
        y += 20

    hint = font.render(tr(language, "help_close"), True, (160, 190, 215))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, panel.bottom - 25)))


def draw_pause_menu(
    screen,
    font,
    options: List[str],
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw semi-transparent pause menu overlay with selectable options."""
    import pygame

    # Semi-transparent dark overlay
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((10, 15, 20, 190))
    screen.blit(overlay, (0, 0))

    # Menu panel
    panel_w = min(420, screen_w - 40)
    panel_h = min(screen_h - 40, max(280, 110 + len(options) * 56))
    panel_x = (screen_w - panel_w) // 2
    panel_y = (screen_h - panel_h) // 2

    panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel_surf.fill((22, 28, 38, 230))
    screen.blit(panel_surf, (panel_x, panel_y))
    pygame.draw.rect(screen, (70, 120, 180), (panel_x, panel_y, panel_w, panel_h), width=2, border_radius=8)

    # Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 36, bold=True)
    except Exception:
        pass
    t_surf = title_font.render(tr(language, "paused"), True, (245, 245, 245))
    t_rect = t_surf.get_rect(center=(screen_w // 2, panel_y + 40))
    screen.blit(t_surf, t_rect)

    # Options buttons
    item_w = 340
    item_h = 44
    start_y = panel_y + 80
    gap_y = 12

    for idx, opt in enumerate(options):
        iy = start_y + idx * (item_h + gap_y)
        ix = panel_x + (panel_w - item_w) // 2

        is_sel = idx == selected_idx
        bg_color = (45, 85, 140) if is_sel else (32, 40, 52)
        border_color = (100, 200, 255) if is_sel else (65, 80, 100)
        text_color = (255, 255, 255) if is_sel else (200, 210, 220)

        pygame.draw.rect(screen, bg_color, (ix, iy, item_w, item_h), border_radius=6)
        pygame.draw.rect(screen, border_color, (ix, iy, item_w, item_h), width=2 if is_sel else 1, border_radius=6)

        prefix = "> " if is_sel else "   "
        o_surf = font.render(f"{prefix}{opt}", True, text_color)
        o_rect = o_surf.get_rect(midleft=(ix + 20, iy + item_h // 2))
        screen.blit(o_surf, o_rect)

    # Hint
    sub_font = font
    try:
        sub_font = pygame.font.SysFont(None, 18)
    except Exception:
        pass
    h_surf = sub_font.render("UP/DOWN = select | ENTER/SPACE = choose | ESC = resume", True, (140, 160, 180))
    h_rect = h_surf.get_rect(center=(screen_w // 2, panel_y + panel_h - 20))
    screen.blit(h_surf, h_rect)


def draw_settings_menu(
    screen,
    font,
    language: str,
    master_volume: float,
    music_volume: float,
    effects_volume: float,
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw language and audio settings."""
    import pygame

    screen.fill((18, 24, 32))
    panel = pygame.Rect(100, 70, screen_w - 200, screen_h - 140)
    pygame.draw.rect(screen, (22, 30, 40), panel, border_radius=8)
    pygame.draw.rect(screen, (100, 170, 220), panel, width=2, border_radius=8)
    title_font = pygame.font.SysFont(None, 36, bold=True)
    title = title_font.render(tr(language, "settings"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, panel.y + 42)))

    rows = [
        (tr(language, "language"), "Suomi" if language == "fi" else "English", None),
        (tr(language, "master_volume"), f"{master_volume * 100:.0f}%", master_volume),
        (tr(language, "music_volume"), f"{music_volume * 100:.0f}%", music_volume),
        (tr(language, "effects_volume"), f"{effects_volume * 100:.0f}%", effects_volume),
    ]
    for idx, (label, value, volume) in enumerate(rows):
        y = panel.y + 100 + idx * 58
        selected = idx == selected_idx
        color = (255, 215, 95) if selected else (220, 228, 235)
        label_surface = font.render(label, True, color)
        screen.blit(label_surface, (panel.x + 38, y))
        if volume is None:
            value_surface = font.render(value, True, color)
            screen.blit(value_surface, (panel.right - 190, y))
        else:
            bar = pygame.Rect(panel.right - 240, y + 5, 150, 16)
            pygame.draw.rect(screen, (45, 55, 65), bar, border_radius=3)
            pygame.draw.rect(screen, (55, 180, 110), (bar.x, bar.y, int(bar.width * volume), bar.height), border_radius=3)
            value_surface = font.render(value, True, color)
            screen.blit(value_surface, (panel.right - 75, y))

    hint = pygame.font.SysFont(None, 18).render(tr(language, "settings_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, panel.bottom - 28)))


def draw_hud(
    screen,
    font,
    car: Car,
    on_road: bool,
    ways_count: int,
    px_per_m: float,
    transformer_to_ll,
    is_auto_fetching: bool = False,
    show_labels: bool = True,
    auto_fetch_progress: float = 0.0,
    taxi_mgr: Optional[TaxiManager] = None,
    current_road_name: Optional[str] = None,
    speed_limit_kmh: Optional[int] = None,
    speed_limiter_enabled: bool = True,
    red_light_assist_enabled: bool = False,
    rage_power: float = 0.0,
    language: str = "fi",
) -> None:
    """Draw speed, trip, odometer, on-road status, current road name, lat/lon, taxi mission bar, notifications."""
    import pygame

    lat, lon = meters_to_latlon(car.x, car.y, transformer=transformer_to_ll)
    lat_s = f"{lat:.5f}" if lat is not None else "N/A"
    lon_s = f"{lon:.5f}" if lon is not None else "N/A"

    trip_s = f"{car.trip_m:.0f} m" if car.trip_m < 1000 else f"{car.trip_m / 1000.0:.2f} km"
    odo_s = f"{car.odometer_m / 1000.0:.2f} km" if car.odometer_m >= 1000 else f"{car.odometer_m:.0f} m"

    labels_status = "ON" if show_labels else "OFF"
    lane_assist_status = "ON" if getattr(car, "lane_assist_enabled", False) else "OFF"
    speed_limiter_status = "ON" if speed_limiter_enabled else "OFF"
    red_light_assist_status = "ON" if red_light_assist_enabled else "OFF"
    road_name_s = current_road_name if current_road_name else tr(language, "off_road")
    limit_s = f" [{tr(language, 'limit')}: {speed_limit_kmh} km/h]" if speed_limit_kmh is not None else ""
    assist_s = " | [Lane Assist]" if getattr(car, "lane_assist_active", False) else ""
    hud = (
        f"{tr(language, 'road')}: {road_name_s}{limit_s}{assist_s} | {tr(language, 'trip')}: {trip_s} | {tr(language, 'odometer')}: {odo_s} | "
        f"Ways: {ways_count} | Zoom: {px_per_m:.2f} px/m | Lat: {lat_s} Lon: {lon_s}"
    )
    text = font.render(hud, True, (240, 240, 240))
    screen.blit(text, (10, 10))

    hint = (
        f"Controls: W/S/A/D = drive | +/- = zoom | R = respawn | X = cancel fare | T = reset trip | "
        f"L = labels ({labels_status}) | K = lane assist ({lane_assist_status}) | V = limiter ({speed_limiter_status}) | B = red assist ({red_light_assist_status}) | Space = rage | ESC = pause"
    )
    hint_t = font.render(hint, True, (220, 220, 220))
    screen.blit(hint_t, (10, 34))

    # Taxi mission banner / status bar
    if taxi_mgr:
        taxi_y = 58
        target = taxi_mgr.get_current_target()
        dist_m = math.hypot(car.x - target.x, car.y - target.y) if target else 0.0
        dist_s = f"{dist_m:.0f}m" if dist_m < 1000 else f"{dist_m / 1000.0:.2f}km"

        p = taxi_mgr.current_passenger
        if p is None:
            if taxi_mgr.offers:
                role_text = f"[TAXI] {tr(language, 'phone_available')}"
                role_color = (255, 95, 60)
            else:
                role_text = f"[TAXI] {tr(language, 'no_requests')}"
                role_color = (190, 200, 205)
        elif taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP:
            role_text = f"[TAXI] FARE: Pickup {p.name if p else 'Client'} at: {target.address if target else '...'} ({dist_s})"
            role_color = (255, 215, 60)
        else:
            cur_speed_kmh = (dist_m / max(1.0, taxi_mgr.elapsed_time)) * 3.6 if taxi_mgr.elapsed_time > 0 else 0.0
            role_text = (
                f"[TAXI] FARE: Take {p.name if p else 'Client'} to: {target.address if target else '...'} "
                f"({dist_s} left, Time: {taxi_mgr.elapsed_time:.1f}s)"
            )
            role_color = (100, 240, 140)

        # Draw taxi score and stats on top right
        score_text = f"{tr(language, 'score')}: {taxi_mgr.total_score} pts | {tr(language, 'fares')}: {taxi_mgr.completed_fares}"
        score_surf = font.render(score_text, True, (255, 230, 110))
        score_rect = score_surf.get_rect(topright=(SCREEN_W - 140, 10))
        bg_s = pygame.Surface((score_rect.width + 12, score_rect.height + 6), pygame.SRCALPHA)
        bg_s.fill((20, 20, 20, 200))
        screen.blit(bg_s, (score_rect.x - 6, score_rect.y - 3))
        pygame.draw.rect(screen, (220, 180, 50), (score_rect.x - 6, score_rect.y - 3, score_rect.width + 12, score_rect.height + 6), 1, border_radius=3)
        screen.blit(score_surf, score_rect)

        # Mission header bar
        mission_surf = font.render(role_text, True, role_color)
        m_rect = mission_surf.get_rect(topleft=(10, taxi_y))
        m_bg = pygame.Surface((m_rect.width + 12, m_rect.height + 6), pygame.SRCALPHA)
        m_bg.fill((25, 30, 35, 220))
        screen.blit(m_bg, (m_rect.x - 6, m_rect.y - 3))
        pygame.draw.rect(screen, role_color, (m_rect.x - 6, m_rect.y - 3, m_rect.width + 12, m_rect.height + 6), 1, border_radius=3)
        screen.blit(mission_surf, m_rect)

        # In-game notification banner (e.g. Fare completed, new pickup)
        if taxi_mgr.notification_timer > 0.0 and taxi_mgr.notification_msg:
            notif_surf = font.render(taxi_mgr.notification_msg, True, (255, 255, 255))
            notif_rect = notif_surf.get_rect(center=(SCREEN_W // 2, SCREEN_H - 45))
            n_bg = pygame.Surface((notif_rect.width + 24, notif_rect.height + 12), pygame.SRCALPHA)
            n_bg.fill((20, 30, 40, 235))
            screen.blit(n_bg, (notif_rect.x - 12, notif_rect.y - 6))
            pygame.draw.rect(screen, (255, 200, 50), (notif_rect.x - 12, notif_rect.y - 6, notif_rect.width + 24, notif_rect.height + 12), 2, border_radius=5)
            screen.blit(notif_surf, notif_rect)

    # Keep driving instruments together in the lower-left corner.
    speed_text = font.render(f"{tr(language, 'speed')}: {car.speed * 3.6:.0f} km/h", True, (240, 240, 240))
    rage_text = font.render(f"{tr(language, 'rage_meter')}: {rage_power * 100:.0f}%", True, (255, 120, 100))
    instrument_width = max(speed_text.get_width(), rage_text.get_width()) + 20
    instrument_height = speed_text.get_height() + rage_text.get_height() + 22
    instrument_x = 10
    instrument_y = SCREEN_H - instrument_height - 10
    pygame.draw.rect(
        screen,
        (20, 25, 30, 220),
        (instrument_x, instrument_y, instrument_width, instrument_height),
        border_radius=4,
    )
    pygame.draw.rect(
        screen,
        (130, 140, 150),
        (instrument_x, instrument_y, instrument_width, instrument_height),
        width=1,
        border_radius=4,
    )
    screen.blit(speed_text, (instrument_x + 10, instrument_y + 6))
    rage_y = instrument_y + speed_text.get_height() + 8
    screen.blit(rage_text, (instrument_x + 10, rage_y))
    rage_bar = pygame.Rect(instrument_x + 10, rage_y + rage_text.get_height() + 2, instrument_width - 20, 6)
    pygame.draw.rect(screen, (45, 30, 30), rage_bar)
    pygame.draw.rect(
        screen,
        (220, 55, 35),
        (rage_bar.x, rage_bar.y, int(rage_bar.width * max(0.0, min(1.0, rage_power))), rage_bar.height),
    )

    # Auto-fetch scenery loading progress meter
    if is_auto_fetching:
        prog = max(0.0, min(1.0, auto_fetch_progress if auto_fetch_progress > 0.0 else 0.65))
        bar_w = 160
        bar_h = 14
        bar_x = 10
        bar_y = 86 if taxi_mgr else 58

        # Background and border
        pygame.draw.rect(screen, (30, 35, 40), (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        pygame.draw.rect(screen, (140, 150, 160), (bar_x, bar_y, bar_w, bar_h), width=1, border_radius=3)

        # Progress fill
        fill_w = int((bar_w - 2) * prog)
        if fill_w > 0:
            pygame.draw.rect(screen, (255, 190, 40), (bar_x + 1, bar_y + 1, fill_w, bar_h - 2), border_radius=2)

        load_t = font.render(f"Loading scenery... {int(prog * 100)}%", True, (255, 215, 60))
        screen.blit(load_t, (bar_x + bar_w + 10, bar_y - 2))

