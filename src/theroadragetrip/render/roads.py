from . import common
from .common import (
    SCREEN_W,
    SCREEN_H,
    PX_PER_M,
    CACHE_PADDING_PX,
    DEFAULT_SUN_LATITUDE,
    DEFAULT_SUN_LONGITUDE,
    _render_logger,
    _rebuild_or_stale,
    _static_cache_zoom,
    _reusable_alpha_surface,
    solar_altitude_and_events,
    _format_solar_time,
    world_to_screen,
    asphalt_texture_tile_size,
    road_color_for_way,
    road_render_priority,
    get_viewport_bounds,
    _segment_viewport_t_range,
)
import math
import logging
import os
import time
from typing import List, Optional, Tuple

from shapely.geometry import LineString
from shapely.ops import unary_union

from ..geo import dist_point_to_segment, point_in_polygon
from ..osm import Building, BusStop, TaxiStop, Way


BRIDGE_GUARDRAIL_COLOR = (196, 200, 204)  # light guardrail, contrasts against dark asphalt - shared by road and rail bridges so both read as the same "elevated structure" cue
MAX_VISIBLE_STREET_LIGHTS = 400
STREET_LIGHT_SPACING_M = 12.0
STREET_LIGHT_JUNCTION_CLEARANCE_M = 3.0
STREET_LIGHT_SHADE_COLOR = (0, 0, 0)
STREET_LIGHT_BUILDING_DISTANCE_M = 200.0
STREET_LIGHT_POOL_ADD_COLOR = (22, 22, 22)
STREET_LIGHT_POOL_HALF_ANGLE = math.radians(135.0)
STREET_LIGHT_POOL_STEPS = 16
STREET_LIGHT_CORE_COLOR = (215, 215, 200, 230)
_asphalt_texture_tile = None
_asphalt_texture_source = None
_asphalt_texture_tile_size = None
_street_light_junction_cache = None
_street_light_junction_grid_cache = None
_street_light_building_grid_cache = None
_taxi_sign_text = None
_bus_stop_geometry_cache = None
_bus_stop_font_cache = {}
_bus_stop_label_cache = {}
_traffic_light_surface_cache = {}
_street_light_glow_cache = {}
_street_light_frame_cache_key = None
_street_light_frame_cache_surface = None
_street_light_frame_pool_surface = None
_street_light_frame_cache_camera = None
_street_light_geometry_cache_key = None
_street_light_geometry_cache = []
_street_light_way_lit_cache_key = None
_street_light_way_lit_cache = {}
_street_light_last_debug_log_ms = 0


def draw_ways(
    screen,
    ways: List[Way],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    profiler=None,
) -> None:
    """Draw road ways intersecting viewport with highway-type proportional thickness and layer ordering."""
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    road_cache_key = (
        id(ways),
        len(ways),
        id(ways[-1]) if ways else None,
        round(camx * cache_zoom / 128.0),
        round(camy * cache_zoom / 128.0),
        cache_zoom,
        screen_w,
        screen_h,
    )
    if road_cache_key == common._road_frame_cache_key and common._road_frame_cache_surface is not None:
        cached_camx, cached_camy = common._road_frame_cache_camera
        screen.blit(
            common._road_frame_cache_surface,
            (
                round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
                round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
            ),
        )
        return
    if _rebuild_or_stale(screen, "roads", common._road_frame_cache_surface, common._road_frame_cache_camera, camx, camy, cache_zoom):
        return
    px_per_m = cache_zoom
    destination_screen = screen
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    screen = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    screen_w = cache_width
    screen_h = cache_height

    # screen_w/screen_h here are already the padded cache surface's own
    # dimensions (CACHE_PADDING_PX baked in above), so this margin is pure
    # extra beyond that - and the cache's offset-blit reuse can never take
    # advantage of more than CACHE_PADDING_PX/px_per_m of it anyway (that's
    # the whole pan distance a reuse can cover before a real rebuild is
    # needed regardless). A wide margin here was making every rebuild
    # select and fully render roads tens of meters past anything the cache
    # could ever actually show before its next rebuild - real cost in a
    # busy area (occasional multi-ten-millisecond "culprit: rendering"
    # spikes) for no visual benefit. A small fixed margin is still kept as
    # pop-in insurance for wide roads/long endpoint-joins near the edge -
    # 25m comfortably covers the widest endpoint join_distance possible
    # (a motorway's 2*7.0+4.0=18m) with headroom to spare.
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 25.0)

    # Filter visible ways first, then sort only visible ways by layer
    if spatial_grid is not None:
        visible_ways = [w for w in spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy) if len(w.points_m) >= 2]
    else:
        visible_ways = []
        for w in ways:
            bb = getattr(w, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            if len(w.points_m) >= 2:
                visible_ways.append(w)

    visible_ways.sort(
        key=lambda w: (
            getattr(w, "layer", 0),
            getattr(w, "is_drivable", True),
            road_render_priority(w),
        )
    )

    endpoints = []
    for way in visible_ways:
        if len(way.points_m) < 2:
            continue
        for endpoint_index in (0, -1):
            endpoints.append((
                way,
                endpoint_index,
                way.points_m[endpoint_index],
                getattr(way, "layer", 0),
                bool(way.is_drivable),
            ))

    endpoint_connections = {}
    endpoint_cell_size = 32.0
    endpoint_cells = {}
    for endpoint in endpoints:
        way, endpoint_index, point, layer, is_drivable = endpoint
        cell = (math.floor(point[0] / endpoint_cell_size), math.floor(point[1] / endpoint_cell_size), layer, is_drivable)
        endpoint_cells.setdefault(cell, []).append(endpoint)

    if px_per_m > 1.5:
        for way, endpoint_index, point, layer, is_drivable in endpoints:
            nearest = None
            nearest_distance = float("inf")
            join_distance = max(8.0, 2.0 * getattr(way, "half_width_m", 4.0) + 4.0)
            cell_x = math.floor(point[0] / endpoint_cell_size)
            cell_y = math.floor(point[1] / endpoint_cell_size)
            search_radius = max(1, math.ceil(join_distance / endpoint_cell_size))
            for nearby_cell_x in range(cell_x - search_radius, cell_x + search_radius + 1):
                for nearby_cell_y in range(cell_y - search_radius, cell_y + search_radius + 1):
                    for other_way, other_index, other_point, other_layer, other_is_drivable in endpoint_cells.get(
                        (nearby_cell_x, nearby_cell_y, layer, is_drivable), ()
                    ):
                        if way is other_way:
                            continue
                        distance = math.hypot(point[0] - other_point[0], point[1] - other_point[1])
                        if distance < nearest_distance:
                            nearest = (other_way, other_index, other_point)
                            nearest_distance = distance
            if nearest is not None and nearest_distance <= join_distance:
                endpoint_connections[(id(way), endpoint_index)] = nearest[2]

    asphalt_polygons = []
    center_lines = []
    bridge_edges = []

    def draw_joined_line(color, points, width, connections=()):
        if len(points) < 2:
            return
        if px_per_m <= 1.5:
            pygame.draw.lines(screen, color, False, points, max(1, round(width)))
            for start, end in connections:
                pygame.draw.line(screen, color, start, end, max(1, round(width)))
            return
        half_width = width * 0.5
        left_edge = []
        right_edge = []

        def offset_point(point, direction, side):
            return (
                point[0] - direction[1] * half_width * side,
                point[1] + direction[0] * half_width * side,
            )

        for index, point in enumerate(points):
            if index == 0:
                dx = points[1][0] - point[0]
                dy = points[1][1] - point[1]
                length = math.hypot(dx, dy)
                direction = (dx / length, dy / length) if length > 1e-9 else (1.0, 0.0)
                left_edge.append(offset_point(point, direction, 1.0))
                right_edge.append(offset_point(point, direction, -1.0))
                continue
            if index == len(points) - 1:
                dx = point[0] - points[index - 1][0]
                dy = point[1] - points[index - 1][1]
                length = math.hypot(dx, dy)
                direction = (dx / length, dy / length) if length > 1e-9 else (1.0, 0.0)
                left_edge.append(offset_point(point, direction, 1.0))
                right_edge.append(offset_point(point, direction, -1.0))
                continue

            previous_dx = point[0] - points[index - 1][0]
            previous_dy = point[1] - points[index - 1][1]
            next_dx = points[index + 1][0] - point[0]
            next_dy = points[index + 1][1] - point[1]
            previous_length = math.hypot(previous_dx, previous_dy)
            next_length = math.hypot(next_dx, next_dy)
            if previous_length <= 1e-9 or next_length <= 1e-9:
                direction = (
                    next_dx / next_length,
                    next_dy / next_length,
                ) if next_length > 1e-9 else (1.0, 0.0)
                left_edge.append(offset_point(point, direction, 1.0))
                right_edge.append(offset_point(point, direction, -1.0))
                continue

            previous_direction = (previous_dx / previous_length, previous_dy / previous_length)
            next_direction = (next_dx / next_length, next_dy / next_length)
            left_start = offset_point(point, previous_direction, 1.0)
            left_end = offset_point(point, next_direction, 1.0)
            right_start = offset_point(point, previous_direction, -1.0)
            right_end = offset_point(point, next_direction, -1.0)

            def intersect(first, first_direction, second, second_direction):
                cross = first_direction[0] * second_direction[1] - first_direction[1] * second_direction[0]
                if abs(cross) <= 1e-9:
                    return ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)
                delta_x = second[0] - first[0]
                delta_y = second[1] - first[1]
                distance = (delta_x * second_direction[1] - delta_y * second_direction[0]) / cross
                result = (first[0] + first_direction[0] * distance, first[1] + first_direction[1] * distance)
                if math.hypot(result[0] - point[0], result[1] - point[1]) > half_width * 4.0:
                    return ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)
                return result

            left_edge.append(intersect(left_start, previous_direction, left_end, next_direction))
            right_edge.append(intersect(right_start, previous_direction, right_end, next_direction))

        polygon = left_edge + list(reversed(right_edge))
        pygame.draw.polygon(screen, color, polygon)
        for start, end in connections:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            normal_x = -dy / length * half_width
            normal_y = dx / length * half_width
            connection_polygon = [
                (start[0] + normal_x, start[1] + normal_y),
                (end[0] + normal_x, end[1] + normal_y),
                (end[0] - normal_x, end[1] - normal_y),
                (start[0] - normal_x, start[1] - normal_y),
            ]
            pygame.draw.polygon(screen, color, connection_polygon)

        if False and color == (70, 70, 70) and width >= 2:
            asphalt_polygons.append(polygon)
            asphalt_polygons.extend(
                [
                    (start[0] + normal_x, start[1] + normal_y),
                    (end[0] + normal_x, end[1] + normal_y),
                    (end[0] - normal_x, end[1] - normal_y),
                    (start[0] - normal_x, start[1] - normal_y),
                ]
                for start, end in connections
                for dx, dy in [(end[0] - start[0], end[1] - start[1])]
                for length in [math.hypot(dx, dy)]
                if length > 1e-9
                for normal_x, normal_y in [(-dy / length * half_width, dx / length * half_width)]
            )
            return

        if False:
            texture_tile_size = max(24, min(256, round(64.0 * px_per_m / 0.7)))
            if _asphalt_texture_source is None:
                texture_path = os.path.join(os.path.dirname(__file__), "..", "assets", "asphalt128.png")
                try:
                    _asphalt_texture_source = pygame.image.load(texture_path).convert()
                except (pygame.error, OSError):
                    _asphalt_texture_source = False
            if _asphalt_texture_source:
                if _asphalt_texture_tile_size != texture_tile_size:
                    _asphalt_texture_tile = pygame.transform.smoothscale(
                        _asphalt_texture_source,
                        (texture_tile_size, texture_tile_size),
                    )
                    _asphalt_texture_tile_size = texture_tile_size
                all_polygons = [polygon]
                all_polygons.extend(
                    [
                        (start[0] + normal_x, start[1] + normal_y),
                        (end[0] + normal_x, end[1] + normal_y),
                        (end[0] - normal_x, end[1] - normal_y),
                        (start[0] - normal_x, start[1] - normal_y),
                    ]
                    for start, end in connections
                    for dx, dy in [(end[0] - start[0], end[1] - start[1])]
                    for length in [math.hypot(dx, dy)]
                    if length > 1e-9
                    for normal_x, normal_y in [(-dy / length * half_width, dx / length * half_width)]
                )
                min_x = max(0, int(math.floor(min(point[0] for shape in all_polygons for point in shape))))
                min_y = max(0, int(math.floor(min(point[1] for shape in all_polygons for point in shape))))
                max_x = min(screen.get_width(), int(math.ceil(max(point[0] for shape in all_polygons for point in shape))) + 1)
                max_y = min(screen.get_height(), int(math.ceil(max(point[1] for shape in all_polygons for point in shape))) + 1)
                if max_x > min_x and max_y > min_y:
                    size = (max_x - min_x, max_y - min_y)
                    texture_surface = pygame.Surface(size, pygame.SRCALPHA)
                    texture_origin_x = screen_w * 0.5 - camx * px_per_m
                    texture_origin_y = screen_h * 0.5 + camy * px_per_m
                    first_tile_x = -int((min_x - texture_origin_x) % texture_tile_size)
                    first_tile_y = -int((min_y - texture_origin_y) % texture_tile_size)
                    for tile_x in range(first_tile_x - texture_tile_size, size[0] + texture_tile_size, texture_tile_size):
                        for tile_y in range(first_tile_y - texture_tile_size, size[1] + texture_tile_size, texture_tile_size):
                            texture_surface.blit(_asphalt_texture_tile, (tile_x, tile_y))
                    mask = pygame.Surface(size, pygame.SRCALPHA)
                    for shape in all_polygons:
                        pygame.draw.polygon(
                            mask,
                            (255, 255, 255, 255),
                            [(point[0] - min_x, point[1] - min_y) for point in shape],
                        )
                    texture_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                    screen.blit(texture_surface, (min_x, min_y))

    def draw_center_line(color, points, connections=(), solid=False):
        if solid:
            draw_joined_line(color, points, 1, connections)
            return
        dash_length = max(6.0, 8.0 * px_per_m)
        gap_length = max(4.0, 6.0 * px_per_m)
        distance = 0.0
        for first, second in zip(points, points[1:]):
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            segment_length = math.hypot(dx, dy)
            if segment_length <= 1e-9:
                continue
            segment_offset = 0.0
            while segment_offset < segment_length:
                cycle_position = distance % (dash_length + gap_length)
                remaining = (
                    dash_length - cycle_position
                    if cycle_position < dash_length
                    else dash_length + gap_length - cycle_position
                )
                piece_length = min(segment_length - segment_offset, remaining)
                if piece_length <= 1e-6:
                    piece_length = min(segment_length - segment_offset, 1e-6)
                if cycle_position < dash_length:
                    start_ratio = segment_offset / segment_length
                    end_ratio = (segment_offset + piece_length) / segment_length
                    pygame.draw.line(
                        screen,
                        color,
                        (first[0] + dx * start_ratio, first[1] + dy * start_ratio),
                        (first[0] + dx * end_ratio, first[1] + dy * end_ratio),
                        1,
                    )
                segment_offset += piece_length
                distance += piece_length

        for start, end in connections:
            pygame.draw.line(screen, color, start, end, 1)

    for w in visible_ways:
        if px_per_m <= 1.5 and not w.is_drivable:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]

        thickness = max(1, int(w.half_width_m * 2 * px_per_m))

        if not w.is_drivable:
            # Pedestrian paths, footways, cycleways, sidewalks.
            ped_thickness = max(1, int(getattr(w, "half_width_m", 1.2) * 2 * px_per_m))
            ped_color = road_color_for_way(w)
            connections = [
                (pts[0], world_to_screen(*endpoint_connections[(id(w), 0)], camx, camy, px_per_m, screen_w, screen_h))
                for endpoint in (0,)
                if (id(w), endpoint) in endpoint_connections
            ] + [
                (pts[-1], world_to_screen(*endpoint_connections[(id(w), -1)], camx, camy, px_per_m, screen_w, screen_h))
                for endpoint in (-1,)
                if (id(w), endpoint) in endpoint_connections
            ]
            draw_joined_line(ped_color, pts, ped_thickness, connections)
            continue

        connections = [
            (pts[0], world_to_screen(*endpoint_connections[(id(w), 0)], camx, camy, px_per_m, screen_w, screen_h))
            for endpoint in (0,)
            if (id(w), endpoint) in endpoint_connections
        ] + [
            (pts[-1], world_to_screen(*endpoint_connections[(id(w), -1)], camx, camy, px_per_m, screen_w, screen_h))
            for endpoint in (-1,)
            if (id(w), endpoint) in endpoint_connections
        ]
        road_color = road_color_for_way(w)
        if w.is_ice_road:
            center_color = (210, 235, 250)
        elif w.highway == "living_street":
            center_color = (130, 125, 120)
        else:
            center_color = (110, 110, 110)

        draw_joined_line(road_color, pts, thickness, connections)
        if thickness >= 6:
            lanes = max(1, int(getattr(w, "lanes", 1) or 1))
            lanes_forward = getattr(w, "lanes_forward", None)
            lanes_backward = getattr(w, "lanes_backward", None)
            solid_center_line = (
                getattr(w, "oneway", 0) == 0
                and (
                    lanes >= 3
                    or (lanes_forward is not None and lanes_forward >= 2)
                    or (lanes_backward is not None and lanes_backward >= 2)
                )
            )
            center_lines.append((center_color, pts, connections, solid_center_line))
        if getattr(w, "is_bridge", False) and px_per_m > 1.5:
            bridge_edges.append((w, pts, thickness))

        # Draw one-way directional chevron indicators if zoomed in
        oneway_val = getattr(w, "oneway", 0)
        if oneway_val != 0 and px_per_m > 1.5:
            pts_world = w.points_m if oneway_val > 0 else list(reversed(w.points_m))
            arrow_color = (200, 200, 200)
            step_dist = 40.0  # meters between arrows
            cum_dist = 0.0
            segment_lengths = getattr(w, "segment_lengths", ())
            segment_headings = getattr(w, "segment_headings", ())
            for i in range(len(pts_world) - 1):
                ax, ay = pts_world[i]
                bx, by = pts_world[i + 1]
                seg_len = segment_lengths[i] if i < len(segment_lengths) else math.hypot(bx - ax, by - ay)
                if seg_len < 1.0:
                    continue
                seg_angle = segment_headings[i] if i < len(segment_headings) else math.atan2(by - ay, bx - ax)
                if oneway_val < 0:
                    seg_angle += math.pi
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

    global _asphalt_texture_source, _asphalt_texture_tile, _asphalt_texture_tile_size
    if False and asphalt_polygons:
        texture_tile_size = asphalt_texture_tile_size(px_per_m)
        if _asphalt_texture_source is None:
            texture_path = os.path.join(os.path.dirname(__file__), "..", "assets", "asphalt128.png")
            try:
                _asphalt_texture_source = pygame.image.load(texture_path).convert()
            except (pygame.error, OSError):
                _asphalt_texture_source = False
        if _asphalt_texture_source:
            if _asphalt_texture_tile_size != texture_tile_size:
                _asphalt_texture_tile = pygame.transform.smoothscale(
                    _asphalt_texture_source, (texture_tile_size, texture_tile_size)
                )
                _asphalt_texture_tile_size = texture_tile_size
            texture_origin_x = screen_w * 0.5 - camx * px_per_m
            texture_origin_y = screen_h * 0.5 + camy * px_per_m
            texture_surface = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
            first_tile_x = int(texture_origin_x % texture_tile_size) - texture_tile_size
            first_tile_y = int(texture_origin_y % texture_tile_size) - texture_tile_size
            for tile_x in range(first_tile_x, screen_w, texture_tile_size):
                for tile_y in range(first_tile_y, screen_h, texture_tile_size):
                    texture_surface.blit(_asphalt_texture_tile, (tile_x, tile_y))
            mask = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
            for shape in asphalt_polygons:
                pygame.draw.polygon(mask, (255, 255, 255, 255), shape)
            texture_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            screen.blit(texture_surface, (0, 0))

    for center_color, points, connections, solid_center_line in center_lines:
        draw_center_line(center_color, points, connections, solid_center_line)

    # Draw guardrails only on the outer boundary of the union of all overlapping
    # bridge lanes, so parallel/adjacent bridge ways never get a railing between them.
    bridge_polygons = []
    for way, points, thickness in bridge_edges:
        if len(points) < 2:
            continue
        half_width = max(thickness * 0.5, 0.5)
        line = LineString(points)
        if line.length <= 1e-9:
            continue
        bridge_polygons.append(line.buffer(half_width, cap_style="flat", join_style="mitre"))

    edge_color = BRIDGE_GUARDRAIL_COLOR
    edge_width = max(2, round(px_per_m * 0.18))
    if bridge_polygons:
        # Original centerline segments, used to tell side edges (parallel to a
        # bridge way) apart from flat end caps (perpendicular, at bridge ends).
        centerline_segments = [
            (first, second)
            for _, points, _ in bridge_edges
            for first, second in zip(points, points[1:])
        ]

        def is_side_edge(edge_start, edge_end):
            edge_angle = math.atan2(edge_end[1] - edge_start[1], edge_end[0] - edge_start[0])
            mid_x = (edge_start[0] + edge_end[0]) * 0.5
            mid_y = (edge_start[1] + edge_end[1]) * 0.5
            best_distance = float("inf")
            best_angle_diff = math.pi / 2.0
            for seg_start, seg_end in centerline_segments:
                distance = dist_point_to_segment(mid_x, mid_y, seg_start[0], seg_start[1], seg_end[0], seg_end[1])
                if distance < best_distance:
                    seg_angle = math.atan2(seg_end[1] - seg_start[1], seg_end[0] - seg_start[0])
                    angle_diff = abs((edge_angle - seg_angle + math.pi / 2.0) % math.pi - math.pi / 2.0)
                    best_distance = distance
                    best_angle_diff = angle_diff
            return best_angle_diff < math.radians(30)

        # OSM often represents one carriageway with parallel bridge ways. Close
        # small gaps before union so their shared inner boundary is not railed.
        join_tolerance = max(1.0, px_per_m * 3.0)
        merged = unary_union(
            [polygon.buffer(join_tolerance) for polygon in bridge_polygons]
        ).buffer(-join_tolerance)
        polygons = merged.geoms if merged.geom_type == "MultiPolygon" else [merged]
        for polygon in polygons:
            boundary_rings = [polygon.exterior]
            for ring in boundary_rings:
                ring_points = list(ring.coords)
                for edge_start, edge_end in zip(ring_points, ring_points[1:]):
                    if is_side_edge(edge_start, edge_end):
                        pygame.draw.line(screen, edge_color, edge_start, edge_end, edge_width)

    destination_screen.blit(screen, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))
    if profiler is not None:
        profiler.record("render:roads_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._road_frame_cache_key = road_cache_key
    common._road_frame_cache_surface = screen
    common._road_frame_cache_camera = (camx, camy)


def _way_has_street_lighting(way: Way) -> bool:
    """Use explicit OSM lighting, with residential streets as the fallback."""
    lit = getattr(way, "lit", None)
    return lit == "yes" or (lit is None and getattr(way, "highway", "") in {"residential", "living_street"})


def _point_is_near_building(
    point: Tuple[float, float],
    buildings: Optional[List[Building]],
    building_grid=None,
) -> bool:
    """Return whether a point is within the taajama building distance."""
    if not buildings:
        return False
    point_x, point_y = point
    candidates = buildings
    if building_grid is not None:
        cell_size = STREET_LIGHT_BUILDING_DISTANCE_M
        cell_x = math.floor(point_x / cell_size)
        cell_y = math.floor(point_y / cell_size)
        candidates = {
            id(building): building
            for nearby_x in (cell_x - 1, cell_x, cell_x + 1)
            for nearby_y in (cell_y - 1, cell_y, cell_y + 1)
            for building in building_grid.get((nearby_x, nearby_y), ())
        }.values()
    for building in candidates:
        points = getattr(building, "points_m", ())
        if len(points) >= 3:
            if point_in_polygon(point_x, point_y, points):
                return True
            if any(
                dist_point_to_segment(
                    point_x, point_y, start[0], start[1], end[0], end[1]
                ) < STREET_LIGHT_BUILDING_DISTANCE_M
                for start, end in zip(points, points[1:] + points[:1])
            ):
                return True
            continue
        bbox = getattr(building, "bbox", None)
        if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        nearest_x = min(max(point_x, bbox[0]), bbox[2])
        nearest_y = min(max(point_y, bbox[1]), bbox[3])
        if (
            (point_x - nearest_x) ** 2 + (point_y - nearest_y) ** 2
            < STREET_LIGHT_BUILDING_DISTANCE_M * STREET_LIGHT_BUILDING_DISTANCE_M
        ):
            return True
    return False


def _way_should_have_street_lighting(
    way: Way,
    buildings: Optional[List[Building]],
    point: Optional[Tuple[float, float]] = None,
    building_grid=None,
) -> bool:
    urban_highways = {
        "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "unclassified", "residential",
        "living_street", "service",
    }
    return _way_has_street_lighting(way) or (
        getattr(way, "lit", None) is None
        and getattr(way, "highway", "") in urban_highways
        and point is not None
        and _point_is_near_building(point, buildings, building_grid)
    )


def draw_street_lights(
    screen,
    ways: List[Way],
    camx: float,
    camy: float,
    game_time_seconds: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    visible_road_count: Optional[int] = None,
    daylight_surface=None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
    buildings: Optional[List[Building]] = None,
    base_surface=None,
) -> None:
    """Draw simple roadside lamps on visible urban roads."""
    import pygame
    global _street_light_last_debug_log_ms
    cache_zoom = _static_cache_zoom(px_per_m)

    hour = (game_time_seconds / 3600.0) % 24.0
    sun_altitude, sunrise_minutes, sunset_minutes = solar_altitude_and_events(
        game_time_seconds, latitude, longitude
    )
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    darkness = 1.0 - twilight
    street_light_brightness = int(45.0 + 190.0 * min(1.0, (darkness - 0.25) / 0.75))
    street_lighting_enabled = darkness > 0.25
    if not street_lighting_enabled:
        common._street_light_frame_world_positions = []
        if _render_logger.isEnabledFor(logging.DEBUG):
            now_ms = pygame.time.get_ticks()
            if now_ms - _street_light_last_debug_log_ms >= 1000:
                _render_logger.debug(
                    "Street lights: off time=%02d:%02d sun_altitude=%.2f sunrise=%s sunset=%s brightness=%d",
                    int(hour),
                    int((hour % 1.0) * 60.0),
                    sun_altitude,
                    _format_solar_time(sunrise_minutes),
                    _format_solar_time(sunset_minutes),
                    0,
                )
                _street_light_last_debug_log_ms = now_ms
        return
    road_cache_signature = tuple(
        (
            getattr(way, "osm_id", None),
            len(way.points_m),
            way.points_m[0] if way.points_m else None,
            way.points_m[-1] if way.points_m else None,
            getattr(way, "half_width_m", 0.0),
            getattr(way, "lit", None),
        )
        for way in ways
    )
    cache_pixel_size = 16
    frame_cache_key = (
        id(ways),
        len(ways),
        id(ways[-1]) if ways else None,
        road_cache_signature,
        id(buildings),
        round(camx * cache_zoom / cache_pixel_size),
        round(camy * cache_zoom / cache_pixel_size),
        cache_zoom,
        round(darkness * 32.0),
        screen.get_size(),
    )
    global _street_light_frame_cache_key, _street_light_frame_cache_surface
    global _street_light_frame_pool_surface, _street_light_frame_cache_camera
    if (
        frame_cache_key == _street_light_frame_cache_key
        and _street_light_frame_cache_surface is not None
    ):
        cached_camx, cached_camy = _street_light_frame_cache_camera
        offset_x = round((cached_camx - camx) * cache_zoom)
        offset_y = round((camy - cached_camy) * cache_zoom)
        street_light_surface = base_surface
        if street_light_surface is not None:
            street_light_surface = street_light_surface.copy()
            street_light_surface.blit(
                _street_light_frame_pool_surface,
                (offset_x, offset_y),
                special_flags=pygame.BLEND_RGB_ADD,
            )
            street_light_surface.blit(_street_light_frame_cache_surface, (offset_x, offset_y))
            screen.blit(street_light_surface, (0, 0), special_flags=pygame.BLEND_RGB_MAX)
            return
        if _street_light_frame_pool_surface is not None:
            screen.blit(
                _street_light_frame_pool_surface,
                (offset_x, offset_y),
                special_flags=pygame.BLEND_RGB_ADD,
            )
        screen.blit(_street_light_frame_cache_surface, (offset_x, offset_y))
        if _render_logger.isEnabledFor(logging.DEBUG):
            now_ms = pygame.time.get_ticks()
            if now_ms - _street_light_last_debug_log_ms >= 1000:
                _render_logger.debug(
                    "Street lights: cache-hit time=%02d:%02d darkness=%.2f brightness=%d camera=(%.1f,%.1f)",
                    int(hour),
                    int((hour % 1.0) * 60.0),
                    darkness,
                    street_light_brightness,
                    camx,
                    camy,
                )
                _street_light_last_debug_log_ms = now_ms
        return
    px_per_m = cache_zoom
    # Build the lighting layer beyond the visible edge so lamps are ready before entering view.
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 40.0)
    if spatial_grid is not None:
        visible_ways = spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
    else:
        visible_ways = ways

    global _street_light_junction_cache, _street_light_junction_grid_cache, _street_light_building_grid_cache
    building_cache_key = (id(buildings), len(buildings) if buildings else 0, id(buildings[-1]) if buildings else None)
    if _street_light_building_grid_cache is None or _street_light_building_grid_cache[0] != building_cache_key:
        building_grid = {}
        for building in buildings or ():
            bbox = getattr(building, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            cell_size = STREET_LIGHT_BUILDING_DISTANCE_M
            min_cell_x = math.floor((bbox[0] - cell_size) / cell_size)
            max_cell_x = math.floor((bbox[2] + cell_size) / cell_size)
            min_cell_y = math.floor((bbox[1] - cell_size) / cell_size)
            max_cell_y = math.floor((bbox[3] + cell_size) / cell_size)
            for cell_x in range(min_cell_x, max_cell_x + 1):
                for cell_y in range(min_cell_y, max_cell_y + 1):
                    building_grid.setdefault((cell_x, cell_y), []).append(building)
        _street_light_building_grid_cache = (building_cache_key, building_grid)
    building_grid = _street_light_building_grid_cache[1]
    cache_key = (id(ways), len(ways), id(ways[-1]) if ways else None, id(buildings))
    if _street_light_junction_cache is None or _street_light_junction_cache[0] != cache_key:
        point_ways = {}
        ways_by_object_id = {id(way): way for way in ways}
        for way in ways:
            if getattr(way, "is_drivable", True):
                for point in way.points_m:
                    key = (round(point[0] / 5.0), round(point[1] / 5.0))
                    point_ways.setdefault(key, set()).add(id(way))
        junction_points = [
            (key[0] * 5.0, key[1] * 5.0)
            for key, junction_way_ids in point_ways.items()
            if len(junction_way_ids) >= 2
            and any(
                _way_should_have_street_lighting(
                    ways_by_object_id[way_id], buildings, (key[0] * 5.0, key[1] * 5.0), building_grid
                )
                for way_id in junction_way_ids
            )
        ]
        _street_light_junction_cache = (cache_key, junction_points)
        junction_grid = {}
        junction_cell_size = 40.0
        for junction_x, junction_y in junction_points:
            cell = (math.floor(junction_x / junction_cell_size), math.floor(junction_y / junction_cell_size))
            junction_grid.setdefault(cell, []).append((junction_x, junction_y))
        _street_light_junction_grid_cache = (cache_key, junction_grid)
    else:
        junction_points = _street_light_junction_cache[1]
    junction_grid = _street_light_junction_grid_cache[1]
    light_layer = (
        _reusable_alpha_surface(pygame, "street_light_layer", screen.get_size())
        if street_lighting_enabled
        else None
    )
    common._street_light_frame_world_positions = []
    global _street_light_geometry_cache_key, _street_light_geometry_cache
    global _street_light_way_lit_cache_key, _street_light_way_lit_cache
    geometry_cache_key = (
        id(ways),
        len(ways),
        id(ways[-1]) if ways else None,
        tuple(
            (
                getattr(way, "osm_id", None),
                len(way.points_m),
                way.points_m[0] if way.points_m else None,
                way.points_m[-1] if way.points_m else None,
                getattr(way, "half_width_m", 0.0),
                getattr(way, "lit", None),
            )
            for way in ways
        ),
        id(buildings),
        len(buildings) if buildings else 0,
        id(buildings[-1]) if buildings else None,
    )
    if geometry_cache_key != _street_light_way_lit_cache_key:
        way_lit_cache = {}
        for way in ways:
            if not getattr(way, "is_drivable", True) or len(way.points_m) < 2:
                way_lit_cache[id(way)] = []
                continue
            if _way_has_street_lighting(way):
                way_lit_cache[id(way)] = [True] * (len(way.points_m) - 1)
                continue
            if getattr(way, "lit", None) == "no" or getattr(way, "highway", "") not in {
                "primary", "primary_link", "secondary", "secondary_link",
                "tertiary", "tertiary_link", "unclassified", "residential",
                "living_street", "service",
            }:
                way_lit_cache[id(way)] = [False] * (len(way.points_m) - 1)
                continue
            segment_lighting = []
            for start, end in zip(way.points_m, way.points_m[1:]):
                samples = (start, end, ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5))
                segment_lighting.append(
                    any(_point_is_near_building(sample, buildings, building_grid) for sample in samples)
                )
            way_lit_cache[id(way)] = segment_lighting
        _street_light_way_lit_cache_key = geometry_cache_key
        _street_light_way_lit_cache = way_lit_cache
    if geometry_cache_key != _street_light_geometry_cache_key:
        cached_lamps = []
        lamp_spacing = STREET_LIGHT_SPACING_M
        junction_cell_size = 40.0
        for way in ways:
            if (
                not getattr(way, "is_drivable", True)
                or (
                    not _way_has_street_lighting(way)
                    and getattr(way, "highway", "") not in {
                        "primary", "primary_link", "secondary", "secondary_link",
                        "tertiary", "tertiary_link", "unclassified", "residential",
                        "living_street", "service",
                    }
                )
                or len(way.points_m) < 2
            ):
                continue
            distance_to_lamp = 0.0
            segment_lengths = getattr(way, "segment_lengths", ())
            for segment_index, (start, end) in enumerate(zip(way.points_m, way.points_m[1:])):
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                segment_length = (
                    segment_lengths[segment_index]
                    if segment_index < len(segment_lengths)
                    else math.hypot(dx, dy)
                )
                if segment_length < 1.0:
                    continue
                while distance_to_lamp <= segment_length:
                    fraction = distance_to_lamp / segment_length
                    lamp_x = start[0] + dx * fraction
                    lamp_y = start[1] + dy * fraction
                    normal_x = -dy / segment_length
                    normal_y = dx / segment_length
                    edge_distance = getattr(way, "half_width_m", 4.0) + 1.0
                    segment_lighting = _street_light_way_lit_cache.get(id(way), ())
                    if segment_index < len(segment_lighting) and segment_lighting[segment_index]:
                        for side in (-1.0, 1.0):
                            world_x = lamp_x + normal_x * edge_distance * side
                            world_y = lamp_y + normal_y * edge_distance * side
                            candidate_ways = (
                                spatial_grid.ways_in_rect(
                                    world_x - 1.0, world_y - 1.0,
                                    world_x + 1.0, world_y + 1.0,
                                )
                                if spatial_grid is not None
                                else ways
                            )
                            if any(
                                getattr(candidate, "is_drivable", True)
                                and any(
                                    dist_point_to_segment(
                                        world_x, world_y,
                                        first[0], first[1], second[0], second[1],
                                    ) <= getattr(candidate, "half_width_m", 3.0)
                                    for first, second in zip(
                                        candidate.points_m, candidate.points_m[1:]
                                    )
                                )
                                for candidate in candidate_ways
                            ):
                                continue
                            junction_cell_x = math.floor(world_x / junction_cell_size)
                            junction_cell_y = math.floor(world_y / junction_cell_size)
                            if any(
                                (world_x - junction_x) ** 2 + (world_y - junction_y) ** 2
                                < STREET_LIGHT_JUNCTION_CLEARANCE_M * STREET_LIGHT_JUNCTION_CLEARANCE_M
                                for cell_x in (junction_cell_x - 1, junction_cell_x, junction_cell_x + 1)
                                for cell_y in (junction_cell_y - 1, junction_cell_y, junction_cell_y + 1)
                                for junction_x, junction_y in junction_grid.get((cell_x, cell_y), ())
                            ):
                                continue
                            road_direction = math.atan2(-normal_y * side, -normal_x * side)
                            pool_radius_m = edge_distance + getattr(way, "half_width_m", 4.0) + 1.0
                            cached_lamps.append((world_x, world_y, road_direction, pool_radius_m))
                    distance_to_lamp += lamp_spacing
                distance_to_lamp -= segment_length
        _street_light_geometry_cache_key = geometry_cache_key
        _street_light_geometry_cache = cached_lamps

    lamp_centers = []
    lamp_directions = []
    lamp_pool_radii = []
    visible_way_count = visible_road_count if visible_road_count is not None else len(ways)
    common._street_light_frame_world_positions = []
    for world_x, world_y, road_direction, pool_radius_m in _street_light_geometry_cache:
        if len(lamp_centers) >= MAX_VISIBLE_STREET_LIGHTS:
            break
        if not (vminx <= world_x <= vmaxx and vminy <= world_y <= vmaxy):
            continue
        screen_x, screen_y = world_to_screen(
            world_x, world_y, camx, camy, px_per_m, screen_w, screen_h
        )
        lamp_center = (int(screen_x), int(screen_y))
        lamp_radius = max(1, int(px_per_m * 0.28))
        lamp_color = STREET_LIGHT_SHADE_COLOR
        pygame.draw.circle(screen, lamp_color, lamp_center, lamp_radius)
        lamp_centers.append(lamp_center)
        lamp_directions.append(road_direction)
        lamp_pool_radii.append(pool_radius_m)
        common._street_light_frame_world_positions.append((world_x, world_y))
    if light_layer is not None:
        lamp_radius = max(1, int(px_per_m * 0.28))
        shade_radius = lamp_radius // 3
        pool_add_layer = _reusable_alpha_surface(
            pygame, "street_light_pool_add_layer", screen.get_size()
        )
        for lamp_center, road_direction, lamp_pool_radius_m in zip(
            lamp_centers, lamp_directions, lamp_pool_radii
        ):
            pool_radius = max(lamp_radius + 2, int(lamp_pool_radius_m * px_per_m))
            sector_points = [lamp_center]
            for step in range(STREET_LIGHT_POOL_STEPS + 1):
                angle = (
                    road_direction
                    - STREET_LIGHT_POOL_HALF_ANGLE
                    + step * (2.0 * STREET_LIGHT_POOL_HALF_ANGLE / STREET_LIGHT_POOL_STEPS)
                )
                sector_points.append(
                    (
                        int(lamp_center[0] + math.cos(angle) * pool_radius),
                        int(lamp_center[1] - math.sin(angle) * pool_radius),
                    )
                )
            pygame.draw.polygon(pool_add_layer, (*STREET_LIGHT_POOL_ADD_COLOR, 255), sector_points)
            pygame.draw.circle(light_layer, STREET_LIGHT_CORE_COLOR, lamp_center, lamp_radius)
            if shade_radius:
                pygame.draw.circle(light_layer, STREET_LIGHT_SHADE_COLOR, lamp_center, shade_radius)
            pygame.draw.circle(light_layer, STREET_LIGHT_CORE_COLOR[:3], lamp_center, lamp_radius)
        _street_light_frame_cache_key = frame_cache_key
        _street_light_frame_cache_surface = light_layer
        _street_light_frame_pool_surface = pool_add_layer
        _street_light_frame_cache_camera = (camx, camy)
        if base_surface is not None:
            street_light_surface = base_surface.copy()
            street_light_surface.blit(pool_add_layer, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
            street_light_surface.blit(light_layer, (0, 0))
            screen.blit(street_light_surface, (0, 0), special_flags=pygame.BLEND_RGB_MAX)
        else:
            screen.blit(pool_add_layer, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
            screen.blit(light_layer, (0, 0))
        if _render_logger.isEnabledFor(logging.DEBUG):
            now_ms = pygame.time.get_ticks()
            if now_ms - _street_light_last_debug_log_ms >= 1000:
                _render_logger.debug(
                    "Street lights: rendered time=%02d:%02d sun_altitude=%.2f sunrise=%s sunset=%s roads=%d lamps=%d glows=%d darkness=%.2f brightness=%d",
                    int(hour),
                    int((hour % 1.0) * 60.0),
                    sun_altitude,
                    _format_solar_time(sunrise_minutes),
                    _format_solar_time(sunset_minutes),
                    visible_way_count,
                    len(lamp_centers),
                    0,
                    darkness,
                    street_light_brightness,
                )
                _street_light_last_debug_log_ms = now_ms


class TireTrail:
    """One continuous run of tire-track points (a single skid/dirt-trail
    event - see main.py's track_sequence). Keeps its own running bounding
    box so draw_tire_tracks can reject a whole trail with one cheap check
    instead of touching every one of its points - a session's accumulated
    tracks can number in the thousands, and most of them are nowhere near
    the current viewport at any given moment."""

    __slots__ = ("is_grass", "points", "min_x", "min_y", "max_x", "max_y")

    def __init__(self, is_grass: bool, x: float, y: float, heading: float, intensity: float) -> None:
        self.is_grass = is_grass
        self.points: List[Tuple[float, float, float, float]] = [(x, y, heading, intensity)]
        self.min_x = self.max_x = x
        self.min_y = self.max_y = y

    def add(self, x: float, y: float, heading: float, intensity: float) -> None:
        self.points.append((x, y, heading, intensity))
        if x < self.min_x:
            self.min_x = x
        elif x > self.max_x:
            self.max_x = x
        if y < self.min_y:
            self.min_y = y
        elif y > self.max_y:
            self.max_y = y


def draw_tire_tracks(
    screen,
    trails: List[TireTrail],
    camx: float,
    camy: float,
    grass: bool,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    viewport_bounds=None,
) -> None:
    """Draw persistent tire marks either on grass or on paved roads.

    Each mark's `intensity` (0..1, see physics.skidmark_intensity) fades it
    from barely-visible toward full-black rather than an invisible/solid
    binary switch (SKIDMARK.md section 22.9) - a real skid darkens
    gradually as slip worsens, it doesn't snap into existence."""
    import pygame

    faint_color = (150, 138, 118) if grass else (110, 110, 110)
    dark_color = (105, 68, 38) if grass else (28, 28, 28)
    width = max(3, int((0.75 if grass else 0.24) * px_per_m))

    if viewport_bounds is not None:
        vminx, vminy, vmaxx, vmaxy = viewport_bounds

    for trail in trails:
        if trail.is_grass != grass:
            continue
        if viewport_bounds is not None and (
            trail.max_x < vminx or trail.min_x > vmaxx or trail.max_y < vminy or trail.min_y > vmaxy
        ):
            continue
        previous_tires = None
        for track_x, track_y, heading, intensity in trail.points:
            if viewport_bounds is not None and not (vminx <= track_x <= vmaxx and vminy <= track_y <= vmaxy):
                previous_tires = None
                continue
            center_x, center_y = world_to_screen(track_x, track_y, camx, camy, px_per_m, screen_w, screen_h)
            side_x = -math.sin(heading)
            side_y = math.cos(heading)
            current_tires = [
                (
                    int(center_x + side_x * side * 0.72 * px_per_m),
                    int(center_y + side_y * side * 0.72 * px_per_m),
                )
                for side in (-1.0, 1.0)
            ]
            if previous_tires is not None:
                color = tuple(
                    int(faint + (dark - faint) * intensity) for faint, dark in zip(faint_color, dark_color)
                )
                for previous_tire, current_tire in zip(previous_tires, current_tires):
                    pygame.draw.line(screen, color, previous_tire, current_tire, width)
            previous_tires = current_tires


def draw_vomit_puddles(screen, puddles, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw persistent passenger sickness spots beside the taxi route."""
    import pygame

    for puddle_x, puddle_y in puddles:
        x, y = world_to_screen(puddle_x, puddle_y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
        radius_x = max(3, int(1.2 * px_per_m))
        radius_y = max(2, int(0.7 * px_per_m))
        pygame.draw.ellipse(
            screen,
            (105, 115, 62),
            (x - radius_x, y - radius_y, radius_x * 2, radius_y * 2),
        )


def draw_roadworks(
    screen,
    roadworks,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw temporary barriers and warning cones over roadwork sections."""
    import pygame

    for work in roadworks:
        start = world_to_screen(work.start[0], work.start[1], camx, camy, px_per_m, screen_w, screen_h)
        end = world_to_screen(work.end[0], work.end[1], camx, camy, px_per_m, screen_w, screen_h)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        normal_x = -dy / length
        normal_y = dx / length
        barrier_width = max(2, int(getattr(work.way, "half_width_m", 4.0) * px_per_m))
        for point in (start, end):
            if work.lane_closed:
                barrier_start = point
                barrier_end = (
                    int(point[0] + normal_x * barrier_width),
                    int(point[1] + normal_y * barrier_width),
                )
            else:
                barrier_start = (
                    int(point[0] - normal_x * barrier_width),
                    int(point[1] - normal_y * barrier_width),
                )
                barrier_end = (
                    int(point[0] + normal_x * barrier_width),
                    int(point[1] + normal_y * barrier_width),
                )
            pygame.draw.line(
                screen,
                (235, 190, 35),
                barrier_start,
                barrier_end,
                max(2, int(2 * px_per_m)),
            )
        step_count = max(2, int(length / max(18.0, 25.0 * px_per_m)))
        for index in range(step_count + 1):
            fraction = index / step_count
            cone_x = start[0] + dx * fraction
            cone_y = start[1] + dy * fraction
            if work.lane_closed:
                cone_x += normal_x * barrier_width * 0.5
                cone_y += normal_y * barrier_width * 0.5
            cone_radius = max(2, int(0.35 * px_per_m))
            cone_center = (int(cone_x), int(cone_y))
            pygame.draw.polygon(
                screen,
                (245, 105, 25),
                [
                    (cone_center[0], cone_center[1] - cone_radius * 2),
                    (cone_center[0] - cone_radius, cone_center[1] + cone_radius),
                    (cone_center[0] + cone_radius, cone_center[1] + cone_radius),
                ],
            )
            pygame.draw.line(
                screen,
                (255, 220, 120),
                (cone_center[0] - cone_radius // 2, cone_center[1]),
                (cone_center[0] + cone_radius // 2, cone_center[1]),
                max(1, cone_radius // 2),
            )


def draw_curbs(
    screen,
    curbs: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw raised kerbstone lines (OSM barrier=kerb) as a thin dark-grey edge."""
    import pygame

    if not curbs:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 10.0)
    visible_curbs = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else curbs
    )
    thickness = max(1, int(0.15 * px_per_m))
    for curb in visible_curbs:
        bb = getattr(curb, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        points = curb.points_m
        if len(points) < 2:
            continue
        # A curb can run continuously for kilometers along a road, so
        # (like draw_railways) only walk the segments that actually cross
        # the viewport instead of converting the way's entire point list
        # through world_to_screen every frame regardless of visibility.
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            dx, dy = x1 - x0, y1 - y0
            seg_len = math.hypot(dx, dy)
            if seg_len < 1e-6:
                continue
            ux, uy = dx / seg_len, dy / seg_len
            if _segment_viewport_t_range(x0, y0, ux, uy, seg_len, vminx, vminy, vmaxx, vmaxy) is None:
                continue
            s0 = world_to_screen(x0, y0, camx, camy, px_per_m, screen_w, screen_h)
            s1 = world_to_screen(x1, y1, camx, camy, px_per_m, screen_w, screen_h)
            pygame.draw.line(screen, (55, 55, 52), s0, s1, thickness)


RAILWAY_RAIL_COLOR = (150, 145, 135)  # steel rail
RAILWAY_TIE_COLOR = (90, 65, 45)  # wooden sleeper
RAILWAY_BALLAST_COLOR = (108, 100, 92)  # crushed-rock bed under a bridge deck
_RAILWAY_GAUGE_M = 1.435  # standard gauge
_RAILWAY_TIE_SPACING_M = 2.0
_RAILWAY_TIE_LENGTH_M = 2.6
_RAILWAY_BRIDGE_DECK_MARGIN_M = 0.4  # deck edge beyond the tie ends


def draw_railways(
    screen,
    railways: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    only_bridges: Optional[bool] = None,
) -> None:
    """Draw rail lines (OSM railway=rail/light_rail/tram/...) as two steel
    rails over periodic wooden sleepers, like draw_curbs but track-styled.
    A track marked is_bridge (OSM bridge=yes/viaduct/movable, or a positive
    layer) also gets a solid ballast-bed fill the full deck width (rails
    and ties alone are thin lines with real gaps between them - not
    enough to actually cover whatever's underneath) plus a pair of
    guardrail-colored deck edges on top of that fill - the same cue
    draw_ways uses for road bridges - so it reads as a structure spanning
    whatever's below it instead of track painted on the ground.

    only_bridges filters which tracks this call draws: None (default) draws
    everything; True/False draws only bridge/only ground-level tracks. main.py
    calls this twice per frame with True and False - ground-level track is
    drawn early, in the same pass as roads, so a car crossing it at grade
    still renders on top like any other road marking; a bridge track is
    drawn again in a *later* pass, after cars/pedestrians, so anything
    actually underneath the bridge gets covered the way a real elevated
    structure would cover it - not left showing through it."""
    import pygame

    if not railways:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 10.0)
    visible_railways = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else railways
    )
    if only_bridges is not None:
        visible_railways = [rw for rw in visible_railways if bool(getattr(rw, "is_bridge", False)) == only_bridges]
    rail_thickness = max(1, int(0.08 * px_per_m))
    tie_thickness = max(1, int(0.18 * px_per_m))
    half_gauge = _RAILWAY_GAUGE_M / 2.0
    half_tie = _RAILWAY_TIE_LENGTH_M / 2.0
    half_deck = half_tie + _RAILWAY_BRIDGE_DECK_MARGIN_M
    deck_edge_width = max(2, round(px_per_m * 0.15))
    ballast_width = max(1, round(2.0 * half_deck * px_per_m))
    # Ground-level track and a rail bridge over a road/river/valley look
    # identical without this - both are just two thin rails over sparse
    # sleepers, at the same z-order as whatever's underneath (see
    # is_bridge on Railway/Way in osm/models.py). A solid ballast-bed fill
    # the full deck width, drawn *before* the rails/ties/edges so they
    # still show as detail on top of it, is what actually makes a bridge
    # opaque - the rails and ties alone are thin lines with gaps between
    # them, which (main.py's only_bridges=True late pass notwithstanding)
    # still let most of whatever's underneath show through.
    show_bridge_decks = px_per_m > 1.5

    for rw in visible_railways:
        bb = getattr(rw, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        points = rw.points_m
        if len(points) < 2:
            continue

        # bbox above only culls the whole way - a real rail line can run for
        # kilometers (a yard's sidings, a long corridor), so a way that just
        # clips the viewport corner would otherwise still walk its entire
        # length generating a sleeper tie every 2m, almost all of them
        # off-screen (measured: one dense rail-yard viewport pulled in 17
        # ways totaling 8.7km of track - over 4000 ties - for a 162x100m
        # visible area). A single *segment* can itself be long enough to
        # have the same problem (one endpoint inside the viewport, the
        # other kilometers away) - so ties are bounded to each segment's
        # actual on-screen t-range, not its full length. The tie phase
        # (next_tie) still advances continuously across the whole way so
        # ties stay aligned wherever the next visible stretch is.
        dist_along = 0.0
        next_tie = 0.0
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            dx, dy = x1 - x0, y1 - y0
            seg_len = math.hypot(dx, dy)
            if seg_len < 1e-6:
                continue
            ux, uy = dx / seg_len, dy / seg_len
            nx, ny = -uy, ux
            t_range = _segment_viewport_t_range(x0, y0, ux, uy, seg_len, vminx, vminy, vmaxx, vmaxy)
            target = dist_along + seg_len
            if t_range is not None:
                t_lo, t_hi = t_range
                if rw.is_bridge and show_bridge_decks:
                    lo_x, lo_y = x0 + ux * t_lo, y0 + uy * t_lo
                    hi_x, hi_y = x0 + ux * t_hi, y0 + uy * t_hi
                    s0 = world_to_screen(lo_x, lo_y, camx, camy, px_per_m, screen_w, screen_h)
                    s1 = world_to_screen(hi_x, hi_y, camx, camy, px_per_m, screen_w, screen_h)
                    pygame.draw.line(screen, RAILWAY_BALLAST_COLOR, s0, s1, ballast_width)
                for offset in (-half_gauge, half_gauge):
                    s0 = world_to_screen(x0 + nx * offset, y0 + ny * offset, camx, camy, px_per_m, screen_w, screen_h)
                    s1 = world_to_screen(x1 + nx * offset, y1 + ny * offset, camx, camy, px_per_m, screen_w, screen_h)
                    pygame.draw.line(screen, RAILWAY_RAIL_COLOR, s0, s1, rail_thickness)
                if rw.is_bridge and show_bridge_decks:
                    lo_x, lo_y = x0 + ux * t_lo, y0 + uy * t_lo
                    hi_x, hi_y = x0 + ux * t_hi, y0 + uy * t_hi
                    for offset in (-half_deck, half_deck):
                        s0 = world_to_screen(lo_x + nx * offset, lo_y + ny * offset, camx, camy, px_per_m, screen_w, screen_h)
                        s1 = world_to_screen(hi_x + nx * offset, hi_y + ny * offset, camx, camy, px_per_m, screen_w, screen_h)
                        pygame.draw.line(screen, BRIDGE_GUARDRAIL_COLOR, s0, s1, deck_edge_width)
                window_lo = dist_along + t_lo
                window_hi = dist_along + t_hi
                if next_tie < window_lo:
                    steps = math.ceil((window_lo - next_tie) / _RAILWAY_TIE_SPACING_M)
                    next_tie += steps * _RAILWAY_TIE_SPACING_M
                while next_tie <= window_hi:
                    t = next_tie - dist_along
                    tx, ty = x0 + ux * t, y0 + uy * t
                    s0 = world_to_screen(tx - nx * half_tie, ty - ny * half_tie, camx, camy, px_per_m, screen_w, screen_h)
                    s1 = world_to_screen(tx + nx * half_tie, ty + ny * half_tie, camx, camy, px_per_m, screen_w, screen_h)
                    pygame.draw.line(screen, RAILWAY_TIE_COLOR, s0, s1, tie_thickness)
                    next_tie += _RAILWAY_TIE_SPACING_M
            # Advance the tie phase past whatever of this segment is left
            # (fully off-screen, or the off-screen tail beyond t_hi) in
            # closed form - never iterate tie-by-tie over distance that
            # isn't going to be drawn.
            if next_tie <= target:
                steps = math.floor((target - next_tie) / _RAILWAY_TIE_SPACING_M) + 1
                next_tie += steps * _RAILWAY_TIE_SPACING_M
            dist_along += seg_len


RAILING_COLOR = (150, 145, 130)


def draw_railings(
    screen,
    railings: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw fence/handrail lines (OSM barrier=fence/railing) - visual only,
    dashed like draw_construction_fences but in a neutral (non-hazard) color."""
    if not railings:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 10.0)
    visible_railings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else railings
    )
    thickness = max(1, int(0.12 * px_per_m))
    for railing in visible_railings:
        bb = getattr(railing, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(railing.points_m) < 2:
            continue
        common._draw_dashed_polyline(
            screen, railing.points_m, camx, camy, px_per_m, screen_w, screen_h,
            RAILING_COLOR, thickness, vminx, vminy, vmaxx, vmaxy, dash_m=0.8, gap_m=0.4,
        )


def draw_crossings(
    screen,
    crossings: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw Finnish zebra pedestrian crossings (suojatiet) with white road stripes aligned to road geometry."""
    import pygame

    if not crossings:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    visible_crossings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else crossings
    )
    for c in visible_crossings:
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


# Darker than any color road_color_for_way can return (SURFACE_COLORS and
# LEGACY_HIGHWAY_COLORS both included; the darkest is motorway/trunk's
# legacy fallback at (58, 58, 60)) - reads as a shadowed raised bump
# regardless of what the road underneath is paved with, without needing
# the specific Way a bump snapped to at render time (only its color would
# be needed; not worth the extra field/coupling for a fixed, always-correct
# darkening).
SPEED_BUMP_COLOR = (45, 42, 40)


def draw_speed_bumps(
    screen,
    speed_bumps: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw speed bumps/tables/cushions as a solid darker bar across the
    road - same "bar across the road" geometry as draw_crossings, just
    filled instead of striped, and typically narrower along the road."""
    import pygame

    if not speed_bumps:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 20.0)

    visible_bumps = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else speed_bumps
    )
    # Real-world lengths along the direction of travel - a "table" is a
    # flat-topped platform (often also a raised crossing), noticeably
    # longer than a rounded "bump" or a narrower "cushion".
    length_m_by_kind = {"table": 2.2, "bump": 0.6, "cushion": 0.4, "hump": 0.6}
    for b in visible_bumps:
        bx, by = getattr(b, "x", 0.0), getattr(b, "y", 0.0)
        if not (vminx <= bx <= vmaxx and vminy <= by <= vmaxy):
            continue

        sx, sy = world_to_screen(bx, by, camx, camy, px_per_m, screen_w, screen_h)
        road_angle = getattr(b, "direction_angle", None) or 0.0
        width_m = getattr(b, "width_m", 3.5)
        length_m = length_m_by_kind.get(getattr(b, "kind", "bump"), 0.6)

        u_along_x, u_along_y = math.cos(road_angle), -math.sin(road_angle)
        u_across_x, u_across_y = -u_along_y, u_along_x

        half_len_x = u_along_x * (length_m * px_per_m / 2.0)
        half_len_y = u_along_y * (length_m * px_per_m / 2.0)
        half_wid_x = u_across_x * (width_m * px_per_m / 2.0)
        half_wid_y = u_across_y * (width_m * px_per_m / 2.0)

        corners = [
            (sx - half_len_x - half_wid_x, sy - half_len_y - half_wid_y),
            (sx + half_len_x - half_wid_x, sy + half_len_y - half_wid_y),
            (sx + half_len_x + half_wid_x, sy + half_len_y + half_wid_y),
            (sx - half_len_x + half_wid_x, sy - half_len_y + half_wid_y),
        ]
        pygame.draw.polygon(screen, SPEED_BUMP_COLOR, corners)


def draw_traffic_lights(
    screen,
    traffic_lights: List,
    sim_time: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw traffic signal posts and active lights."""
    import pygame

    global _traffic_light_surface_cache

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    visible_traffic_lights = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else traffic_lights
    )
    for tl in visible_traffic_lights:
        if not getattr(tl, "renderable", True):
            continue
        if not (vminx <= tl.x <= vmaxx and vminy <= tl.y <= vmaxy):
            continue

        cx, cy = world_to_screen(tl.x, tl.y, camx, camy, px_per_m, screen_w, screen_h)
        state = tl.get_state(sim_time)

        # Colors for 3 lamps (dim when off, bright with glow when on)
        # "all-red" isn't part of the normal red -> red+yellow -> green ->
        # yellow sequence (SignalGroup's all_red_duration defaults to 0),
        # but treat it as red defensively rather than lighting nothing -
        # every lamp going dark for a beat reads as a broken traffic light,
        # not a red one.
        is_red = state in ("red", "red+yellow", "all-red")
        is_yellow = state in ("yellow", "red+yellow")
        is_green = state == "green"

        r_col = (255, 30, 30) if is_red else (60, 10, 10)
        y_col = (255, 210, 0) if is_yellow else (60, 50, 0)
        g_col = (40, 240, 60) if is_green else (10, 50, 15)

        lamp_r = 2
        rotation = 90.0 - math.degrees(tl.direction_angle or 0.0)
        cache_key = (id(tl), state, round(rotation, 3), px_per_m)
        rotated = _traffic_light_surface_cache.get(cache_key)
        if rotated is None:
            signal_surface = pygame.Surface((7, 18), pygame.SRCALPHA)
            signal_surface.fill((15, 15, 15, 255))
            pygame.draw.rect(signal_surface, (70, 70, 70), signal_surface.get_rect(), width=1, border_radius=2)
            for y, color, active in ((4, r_col, is_red), (9, y_col, is_yellow), (14, g_col, is_green)):
                if active:
                    pygame.draw.circle(signal_surface, (*color, 90), (3, y), 4)
                pygame.draw.circle(signal_surface, color, (3, y), lamp_r)
            rotated = pygame.transform.rotate(signal_surface, rotation)
            _traffic_light_surface_cache[cache_key] = rotated
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

    global _taxi_sign_text
    if _taxi_sign_text is None:
        sign_font = pygame.font.Font(None, 11)
        _taxi_sign_text = sign_font.render("TAXI", True, (20, 20, 20))

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
        screen.blit(_taxi_sign_text, _taxi_sign_text.get_rect(center=inner_sign.center))


def draw_bus_stops(
    screen,
    bus_stops: List[BusStop],
    ways: List[Way],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw roadside bus bays and small road-aligned shelters from OSM stops."""
    import pygame

    global _bus_stop_geometry_cache, _bus_stop_font_cache, _bus_stop_label_cache

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 35.0)
    cache_key = (id(bus_stops), len(bus_stops), id(ways), len(ways), id(spatial_grid))
    if _bus_stop_geometry_cache is None or _bus_stop_geometry_cache[0] != cache_key:
        road_ways = [way for way in ways if way.is_drivable and len(way.points_m) >= 2]
        stop_geometry = []
        for stop in bus_stops:
            nearest = None
            candidate_ways = (
                spatial_grid.ways_in_rect(stop.x - 45.0, stop.y - 45.0, stop.x + 45.0, stop.y + 45.0)
                if spatial_grid is not None
                else road_ways
            )
            for way in candidate_ways:
                if not way.is_drivable or len(way.points_m) < 2:
                    continue
                if getattr(way, "layer", 0) != getattr(stop, "layer", 0):
                    continue
                for start, end in zip(way.points_m, way.points_m[1:]):
                    dx = end[0] - start[0]
                    dy = end[1] - start[1]
                    length_sq = dx * dx + dy * dy
                    if length_sq <= 1e-9:
                        continue
                    fraction = max(0.0, min(1.0, ((stop.x - start[0]) * dx + (stop.y - start[1]) * dy) / length_sq))
                    projected = (start[0] + fraction * dx, start[1] + fraction * dy)
                    distance_sq = (stop.x - projected[0]) ** 2 + (stop.y - projected[1]) ** 2
                    if nearest is None or distance_sq < nearest[0]:
                        length = math.sqrt(length_sq)
                        nearest = (distance_sq, projected, (dx / length, dy / length), way.half_width_m)
            if nearest is None or nearest[0] > 45.0 * 45.0:
                stop_geometry.append(None)
                continue

            _, projected, tangent, half_width = nearest
            normal = (-tangent[1], tangent[0])
            side_sign = 1.0 if (stop.x - projected[0]) * normal[0] + (stop.y - projected[1]) * normal[1] >= 0.0 else -1.0
            stop_geometry.append((stop, projected, tangent, half_width, (normal[0] * side_sign, normal[1] * side_sign)))
        _bus_stop_geometry_cache = (cache_key, stop_geometry)

    font_size = max(8, min(32, round(2.0 * px_per_m)))
    bus_font = _bus_stop_font_cache.get(font_size)
    if bus_font is None:
        bus_font = pygame.font.Font(None, font_size)
        _bus_stop_font_cache[font_size] = bus_font

    for geometry in _bus_stop_geometry_cache[1]:
        if geometry is None:
            continue
        stop, projected, tangent, half_width, normal = geometry
        if not (vminx <= stop.x <= vmaxx and vminy <= stop.y <= vmaxy):
            continue
        bay_half_length = 14.0
        bay_outer_half_length = 10.0
        bay_outer = half_width + 2.2
        bay_points = [
            (projected[0] - tangent[0] * bay_half_length + normal[0] * half_width, projected[1] - tangent[1] * bay_half_length + normal[1] * half_width),
            (projected[0] + tangent[0] * bay_half_length + normal[0] * half_width, projected[1] + tangent[1] * bay_half_length + normal[1] * half_width),
            (projected[0] + tangent[0] * bay_outer_half_length + normal[0] * bay_outer, projected[1] + tangent[1] * bay_outer_half_length + normal[1] * bay_outer),
            (projected[0] - tangent[0] * bay_outer_half_length + normal[0] * bay_outer, projected[1] - tangent[1] * bay_outer_half_length + normal[1] * bay_outer),
        ]
        pygame.draw.polygon(screen, (82, 82, 78), [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for x, y in bay_points])

        shelter_center = (projected[0] + normal[0] * (half_width + 3.2), projected[1] + normal[1] * (half_width + 3.2))
        if stop.shelter:
            shelter_length = 5.0
            shelter_width = 2.0
            shelter_points = [
                (shelter_center[0] - tangent[0] * shelter_length / 2 - normal[0] * shelter_width / 2, shelter_center[1] - tangent[1] * shelter_length / 2 - normal[1] * shelter_width / 2),
                (shelter_center[0] + tangent[0] * shelter_length / 2 - normal[0] * shelter_width / 2, shelter_center[1] + tangent[1] * shelter_length / 2 - normal[1] * shelter_width / 2),
                (shelter_center[0] + tangent[0] * shelter_length / 2 + normal[0] * shelter_width / 2, shelter_center[1] + tangent[1] * shelter_length / 2 + normal[1] * shelter_width / 2),
                (shelter_center[0] - tangent[0] * shelter_length / 2 + normal[0] * shelter_width / 2, shelter_center[1] - tangent[1] * shelter_length / 2 + normal[1] * shelter_width / 2),
            ]
            shelter_screen = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for x, y in shelter_points]
            pygame.draw.polygon(screen, (190, 190, 180), shelter_screen)
            pygame.draw.lines(screen, (45, 45, 42), True, shelter_screen, max(1, int(px_per_m * 0.25)))
        label_angle = round(-math.degrees(math.atan2(tangent[1], tangent[0])))
        label_key = (font_size, label_angle)
        label = _bus_stop_label_cache.get(label_key)
        if label is None:
            label = pygame.transform.rotate(bus_font.render("BUS", True, (25, 25, 25)), label_angle)
            _bus_stop_label_cache[label_key] = label
        label_center = world_to_screen(shelter_center[0], shelter_center[1], camx, camy, px_per_m, screen_w, screen_h)
        screen.blit(label, label.get_rect(center=label_center))


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
