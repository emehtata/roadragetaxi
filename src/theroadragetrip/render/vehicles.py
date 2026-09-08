from . import common
from .roads import STREET_LIGHT_SHADE_COLOR
from .common import (
    SCREEN_W,
    SCREEN_H,
    FPS,
    PX_PER_M,
    CACHE_PADDING_PX,
    STATIC_ZOOM_STEP,
    SOLAR_UPDATE_INTERVAL_SECONDS,
    GAME_DATE,
    FINLAND_SUMMER_TIME_OFFSET,
    DEFAULT_SUN_LATITUDE,
    DEFAULT_SUN_LONGITUDE,
    _solar_position_cache,
    _reusable_alpha_surfaces,
    _smoke_surface_cache,
    _render_logger,
    _pending_static_rebuilds,
    _static_rebuilds_this_frame,
    invalidate_static_caches,
    begin_static_cache_frame,
    _allow_static_rebuild,
    _blit_stale_static_cache,
    _static_cache_zoom,
    _reusable_alpha_surface,
    _smoke_surface,
    solar_altitude_and_events,
    _format_solar_time,
    _get_game_version,
    _draw_version,
    world_to_screen,
    asphalt_texture_tile_size,
    road_color_for_way,
    road_render_priority,
    get_viewport_bounds,
    minimum_px_per_m_for_viewport_width,
    _covered_by_higher_road,
    _vehicle_is_on_bridge,
    GAME_VERSION,
)
import math
import logging
import os
import random
import subprocess
import time
from datetime import date
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import List, Optional, Tuple

from shapely.geometry import LineString
from shapely.ops import unary_union

from ..geo import clip_polygon_to_rect, compute_bbox, dist_point_to_segment, meters_to_latlon, point_in_polygon
from ..osm import Building, BusStop, Place, Scenery, TaxiStop, Water, Way
from ..physics import Car, MAX_SPEED, is_point_on_road
from ..taxi import TaxiManager, TaxiState
from ..localization import tr


MAX_VISIBLE_NPC_COUNT = 17
_cyclist_sprite = None
_motorcycle_sprite = None
_moped_sprite = None
_two_wheeler_tinted_sprites = {}
_two_wheeler_render_cache = {}
_npc_vehicle_sprite_cache = {}
_npc_debug_font = None
_cyclist_tinted_sprites = {}


def _tinted_two_wheeler_sprite(sprite, color, cache_key):
    import pygame

    cache_key = (cache_key, tuple(color))
    cached_sprite = _two_wheeler_tinted_sprites.get(cache_key)
    if cached_sprite is not None:
        return cached_sprite

    tinted_sprite = sprite.copy()
    for pixel_x in range(tinted_sprite.get_width()):
        for pixel_y in range(tinted_sprite.get_height()):
            red, green, blue, alpha = tinted_sprite.get_at((pixel_x, pixel_y))
            if alpha == 0 or max(red, green, blue) - min(red, green, blue) <= 25:
                continue
            brightness = (red + green + blue) / (3.0 * 255.0)
            tinted_sprite.set_at(
                (pixel_x, pixel_y),
                (*[min(255, int(channel * (0.65 + brightness * 0.55))) for channel in color], alpha),
            )

    _two_wheeler_tinted_sprites[cache_key] = tinted_sprite
    return tinted_sprite


def _npc_vehicle_sprite(pygame, length_px: float, width_px: float, color, angle: float, is_taxi: bool):
    angle_index = round((angle % (2.0 * math.pi)) / (2.0 * math.pi) * 24.0) % 24
    cache_key = (
        round(length_px),
        round(width_px),
        tuple(color),
        angle_index,
        is_taxi,
    )
    cached = _npc_vehicle_sprite_cache.get(cache_key)
    if cached is not None:
        return cached

    margin = 3
    base_width = max(8, round(length_px)) + margin * 2
    base_height = max(6, round(width_px)) + margin * 2
    base = pygame.Surface((base_width, base_height), pygame.SRCALPHA)
    center_x, center_y = base_width * 0.5, base_height * 0.5
    half_length = length_px * 0.5
    half_width = width_px * 0.5
    body = [
        (center_x + half_length, center_y + half_width),
        (center_x + half_length, center_y - half_width),
        (center_x - half_length, center_y - half_width),
        (center_x - half_length, center_y + half_width),
    ]
    pygame.draw.polygon(base, color, body)
    pygame.draw.polygon(base, (20, 20, 20), body, 1)
    if length_px >= 6.0:
        cabin_half_length = length_px * 0.225
        cabin_half_width = half_width * 0.75
        cabin = [
            (center_x + cabin_half_length, center_y + cabin_half_width),
            (center_x + cabin_half_length, center_y - cabin_half_width),
            (center_x - cabin_half_length * 1.8, center_y - cabin_half_width),
            (center_x - cabin_half_length * 1.8, center_y + cabin_half_width),
        ]
        pygame.draw.polygon(base, (30, 35, 45), cabin)
    if is_taxi and length_px >= 6.0:
        sign = pygame.Rect(round(center_x - 4), round(center_y - half_width - 2), 8, 3)
        pygame.draw.rect(base, (240, 220, 20), sign)
        pygame.draw.rect(base, (30, 30, 30), sign, 1)

    rotated = pygame.transform.rotate(base, -angle_index * 360.0 / 24.0)
    _npc_vehicle_sprite_cache[cache_key] = rotated
    return rotated


def _tinted_cyclist_sprite(sprite, color):
    import pygame

    cache_key = tuple(color)
    cached_sprite = _cyclist_tinted_sprites.get(cache_key)
    if cached_sprite is not None:
        return cached_sprite

    tinted_sprite = sprite.copy()
    for pixel_x in range(tinted_sprite.get_width()):
        for pixel_y in range(tinted_sprite.get_height()):
            red, green, blue, alpha = tinted_sprite.get_at((pixel_x, pixel_y))
            is_blue_clothing = blue > red and blue > green
            is_yellow_clothing = red > 200 and 130 <= green <= 210 and blue < 100
            if alpha == 0 or not (is_blue_clothing or is_yellow_clothing):
                continue
            brightness = (red + green + blue) / (3.0 * 255.0)
            tinted_sprite.set_at(
                (pixel_x, pixel_y),
                (*[min(255, int(channel * (0.65 + brightness * 0.55))) for channel in color], alpha),
            )

    _cyclist_tinted_sprites[cache_key] = tinted_sprite
    return tinted_sprite


def draw_taxi_smoke(screen, car: Car, camx: float, camy: float, px_per_m: float = PX_PER_M, timer: float = 0.0) -> None:
    """Draw the same animated crash smoke used for NPC cars."""
    if timer <= 0.0:
        return
    import pygame

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
    length_m = getattr(car, "length_m", 4.0)
    length_px = max(5.0, length_m * px_per_m)
    t = 5.0 - timer
    fx = math.cos(car.heading)
    fy = -math.sin(car.heading)
    rx = math.sin(car.heading)
    ry = math.cos(car.heading)
    front_cx = cx + fx * (length_px * 0.4)
    front_cy = cy + fy * (length_px * 0.4)
    for puff_idx in range(4):
        offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
        drift = math.sin(t * 3.0 + puff_idx) * (4.0 * offset_t)
        puff_x = front_cx + rx * drift
        puff_y = front_cy + ry * drift - offset_t * 14.0
        radius = int(3.0 + offset_t * 5.0)
        alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
        smoke_surf = _smoke_surface(pygame, radius, alpha)
        screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_taxi_exhaust(screen, car: Car, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw four animated smoke puffs behind the taxi as exhaust."""
    import pygame

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
    length_px = max(5.0, getattr(car, "length_m", 4.0) * px_per_m)
    t = pygame.time.get_ticks() / 1000.0
    fx = math.cos(car.heading)
    fy = -math.sin(car.heading)
    rx = math.sin(car.heading)
    ry = math.cos(car.heading)
    rear_cx = cx - fx * (length_px * 0.4)
    rear_cy = cy - fy * (length_px * 0.4)
    for puff_idx in range(4):
        offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
        trail_distance = offset_t * 14.0
        puff_x = rear_cx - fx * trail_distance
        puff_y = rear_cy - fy * trail_distance - offset_t * 3.0
        drift = math.sin(t * 3.0 + puff_idx) * (2.0 * offset_t)
        puff_x += rx * drift
        puff_y += ry * drift
        radius = int(3.0 + offset_t * 5.0)
        alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
        smoke_surf = _smoke_surface(pygame, radius, alpha)
        screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_passenger_nausea_bubble(
    screen,
    font,
    car: Car,
    taxi_mgr: Optional[TaxiManager],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    language: str = "fi",
) -> None:
    """Draw a speech bubble above the taxi during nausea warning."""
    import pygame

    passenger = taxi_mgr.current_passenger if taxi_mgr is not None else None
    if (
        passenger is None
        or taxi_mgr.state != TaxiState.DRIVING_TO_DROPOFF
        or passenger.nausea_warning_timer <= 0.0
    ):
        return

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m)
    text_surface = font.render(tr(language, "passenger_nausea_bubble"), True, (210, 35, 35))
    text_width, text_height = text_surface.get_size()
    bubble_width, bubble_height = text_width + 18, text_height + 10
    bubble_x = cx - bubble_width // 2
    bubble_y = cy - max(34, int(2.5 * px_per_m)) - bubble_height

    bubble_surface = pygame.Surface((bubble_width, bubble_height), pygame.SRCALPHA)
    pygame.draw.rect(
        bubble_surface,
        (255, 255, 255, 245),
        (0, 0, bubble_width, bubble_height),
        border_radius=7,
    )
    pygame.draw.rect(
        bubble_surface,
        (210, 35, 35, 255),
        (0, 0, bubble_width, bubble_height),
        width=2,
        border_radius=7,
    )
    bubble_surface.blit(text_surface, (9, 5))
    screen.blit(bubble_surface, (bubble_x, bubble_y))
    pygame.draw.polygon(
        screen,
        (255, 255, 255),
        [(cx - 7, bubble_y + bubble_height), (cx + 7, bubble_y + bubble_height), (cx, bubble_y + bubble_height + 8)],
    )
    pygame.draw.line(screen, (210, 35, 35), (cx - 7, bubble_y + bubble_height), (cx, bubble_y + bubble_height + 8), 2)
    pygame.draw.line(screen, (210, 35, 35), (cx, bubble_y + bubble_height + 8), (cx + 7, bubble_y + bubble_height), 2)


def draw_headlight_beams(
    screen,
    vehicles,
    camx: float,
    camy: float,
    game_time_seconds: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    daylight_surface=None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
    npc_vehicles=None,
    street_light_positions=None,
    bicycles=None,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
    current_way=None,
) -> None:
    """Draw lightweight forward-facing headlight beams for visible vehicles at night."""
    import pygame

    sun_altitude, _, _ = solar_altitude_and_events(game_time_seconds, latitude, longitude)
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    darkness = 1.0 - twilight
    if darkness <= 0.25:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    beam_mask = _reusable_alpha_surface(pygame, "headlight_beam_mask", screen.get_size())
    beam_length = 15.0 * px_per_m
    beam_near = 1.0 * px_per_m
    beam_width = 4.5 * px_per_m
    crossing_offset = 3.0 * px_per_m
    long_beam_length = beam_length * 3.0
    oncoming_detection_distance = 45.0
    street_light_radius = 22.0
    active_street_light_positions = (
        common._street_light_frame_world_positions
        if street_light_positions is None
        else street_light_positions
    )
    npc_ids = {id(vehicle) for vehicle in npc_vehicles or ()}
    bicycle_ids = {id(bicycle) for bicycle in bicycles or ()}

    def draw_beam(origin, near_edge, far_edge, tip, cap_center, cap_radius):
        pygame.draw.polygon(
            beam_mask,
            (255, 255, 255, 255),
            [
                (int(origin[0]), int(origin[1])),
                (int(near_edge[0]), int(near_edge[1])),
                (int(far_edge[0]), int(far_edge[1])),
                (int(tip[0]), int(tip[1])),
            ],
        )
        pygame.draw.circle(
            beam_mask,
            (255, 255, 255, 255),
            (int(cap_center[0]), int(cap_center[1])),
            max(1, int(cap_radius)),
        )

    def has_oncoming_vehicle(vehicle, x: float, y: float, heading: float) -> bool:
        forward_x = math.cos(heading)
        forward_y = math.sin(heading)
        for other in vehicles:
            if other is vehicle:
                continue
            other_x = getattr(other, "x", None)
            other_y = getattr(other, "y", None)
            other_heading = getattr(other, "heading", None)
            if other_x is None or other_y is None or other_heading is None:
                continue
            delta_x = other_x - x
            delta_y = other_y - y
            distance = math.hypot(delta_x, delta_y)
            if distance <= 0.1 or distance > oncoming_detection_distance:
                continue
            ahead = (delta_x * forward_x + delta_y * forward_y) / distance
            other_forward_x = math.cos(other_heading)
            other_forward_y = math.sin(other_heading)
            opposing = forward_x * other_forward_x + forward_y * other_forward_y
            if ahead > 0.2 and opposing < -0.5:
                return True
        return False

    def is_near_street_light(x: float, y: float) -> bool:
        return any(
            (x - light_x) ** 2 + (y - light_y) ** 2 <= (street_light_radius ** 2)
            for light_x, light_y in active_street_light_positions
        )

    drawn = 0
    for vehicle in [*vehicles, *(bicycles or ())]:
        if drawn >= 80:
            break
        x = getattr(vehicle, "x", None)
        y = getattr(vehicle, "y", None)
        heading = getattr(vehicle, "heading", None)
        if x is None or y is None or heading is None or not (vminx <= x <= vmaxx and vminy <= y <= vmaxy):
            continue
        vehicle_layer = getattr(vehicle, "layer", getattr(getattr(vehicle, "way", None), "layer", 0))
        active_way = current_way if vehicle is vehicles[0] else None
        if not _vehicle_is_on_bridge(vehicle, active_way) and _covered_by_higher_road(
            x, y, vehicle_layer, ways, spatial_grid
        ):
            continue
        cx, cy = world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
        forward_x = math.cos(heading)
        forward_y = -math.sin(heading)
        right_x = math.sin(heading)
        right_y = math.cos(heading)
        is_bicycle = id(vehicle) in bicycle_ids
        beam_length_for_vehicle = 6.0 * px_per_m if is_bicycle else beam_length
        if (
            not is_bicycle
            and id(vehicle) in npc_ids
            and not is_near_street_light(x, y)
            and not has_oncoming_vehicle(vehicle, x, y, heading)
        ):
            beam_length_for_vehicle = long_beam_length
        vehicle_width = max(3.0, getattr(vehicle, "width_m", 1.8) * px_per_m)
        if is_bicycle:
            vehicle_width = max(2.0, getattr(vehicle, "radius_m", 0.6) * px_per_m)
        headlight_offset = vehicle_width * 0.35
        bicycle_front_offset = 0.7 * px_per_m if is_bicycle else beam_near
        front_x = cx + forward_x * (bicycle_front_offset + max(0.0, vehicle_width * 0.55))
        front_y = cy + forward_y * (bicycle_front_offset + max(0.0, vehicle_width * 0.55))
        if is_bicycle:
            origin_x = front_x
            origin_y = front_y
            tip_x = cx + forward_x * beam_length_for_vehicle
            tip_y = cy + forward_y * beam_length_for_vehicle
            near_spread = min(0.20 * px_per_m, vehicle_width * 0.20)
            far_width = 0.80 * px_per_m
            near_left_x = origin_x - right_x * near_spread
            near_left_y = origin_y - right_y * near_spread
            near_right_x = origin_x + right_x * near_spread
            near_right_y = origin_y + right_y * near_spread
            far_left_x = tip_x - right_x * far_width
            far_left_y = tip_y - right_y * far_width
            far_right_x = tip_x + right_x * far_width
            far_right_y = tip_y + right_y * far_width
            draw_beam(
                (near_left_x, near_left_y),
                (near_right_x, near_right_y),
                (far_right_x, far_right_y),
                (far_left_x, far_left_y),
                (tip_x, tip_y),
                far_width,
            )
            drawn += 1
            continue
        for side in (-1.0, 1.0):
            side_x = right_x * side
            side_y = right_y * side
            origin_x = front_x + side_x * headlight_offset
            origin_y = front_y + side_y * headlight_offset
            tip_shift = crossing_offset if side < 0.0 else crossing_offset * 0.75
            tip_x = cx + forward_x * beam_length_for_vehicle + right_x * tip_shift
            tip_y = cy + forward_y * beam_length_for_vehicle + right_y * tip_shift
            near_spread = min(beam_width * 0.08, vehicle_width * 0.10)
            far_width = beam_width * 1.7
            near_x = origin_x + side_x * near_spread
            near_y = origin_y + side_y * near_spread
            far_x = tip_x + side_x * far_width
            far_y = tip_y + side_y * far_width
            cap_x = tip_x + side_x * far_width * 0.5
            cap_y = tip_y + side_y * far_width * 0.5
            draw_beam(
                (origin_x, origin_y),
                (near_x, near_y),
                (far_x, far_y),
                (tip_x, tip_y),
                (cap_x, cap_y),
                far_width * 0.5,
            )
        drawn += 1
    if drawn:
        if daylight_surface is not None:
            restored_daylight = _reusable_alpha_surface(pygame, "headlight_restored_daylight", screen.get_size())
            restored_daylight.blit(daylight_surface, (0, 0))
            restored_daylight.blit(beam_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            screen.blit(restored_daylight, (0, 0))
    lamp_radius = max(1, int(px_per_m * 0.28))
    for light_x, light_y in active_street_light_positions:
        if not (vminx <= light_x <= vmaxx and vminy <= light_y <= vmaxy):
            continue
        lamp_center = world_to_screen(light_x, light_y, camx, camy, px_per_m, screen_w, screen_h)
        pygame.draw.circle(screen, STREET_LIGHT_SHADE_COLOR, (int(lamp_center[0]), int(lamp_center[1])), lamp_radius)


def _draw_vehicle_lights(
    screen,
    cx: float,
    cy: float,
    heading: float,
    length_px: float,
    width_px: float,
    turn_signal: str = "",
    turn_signal_elapsed: float = 0.0,
    braking: bool = False,
    reversing: bool = False,
) -> None:
    import pygame

    fx = math.cos(heading)
    fy = -math.sin(heading)
    rx = math.sin(heading)
    ry = math.cos(heading)
    hl = length_px / 2.0
    hw = width_px / 2.0
    light_inset = hw * 0.7
    light_r = max(1.2, width_px * 0.18)
    def draw_light_rectangle(color, light, length, width):
        half_length = length * 0.5
        half_width = width * 0.5
        corners = [
            (light[0] + fx * half_length + rx * half_width, light[1] + fy * half_length + ry * half_width),
            (light[0] + fx * half_length - rx * half_width, light[1] + fy * half_length - ry * half_width),
            (light[0] - fx * half_length - rx * half_width, light[1] - fy * half_length - ry * half_width),
            (light[0] - fx * half_length + rx * half_width, light[1] - fy * half_length + ry * half_width),
        ]
        pygame.draw.polygon(screen, color, corners)

    front_right = (cx + fx * (hl - 0.5) + rx * light_inset, cy + fy * (hl - 0.5) + ry * light_inset)
    front_left = (cx + fx * (hl - 0.5) - rx * light_inset, cy + fy * (hl - 0.5) - ry * light_inset)
    rear_right = (cx - fx * (hl - 0.5) + rx * light_inset, cy - fy * (hl - 0.5) + ry * light_inset)
    rear_left = (cx - fx * (hl - 0.5) - rx * light_inset, cy - fy * (hl - 0.5) - ry * light_inset)
    # Keep the lamp span inside the vehicle's side edge.
    light_length = min(width_px * 0.25, max(1.0, light_r * 2.4))
    light_width = min(length_px * 0.08, max(1.0, light_r * 0.75))
    for light in (front_right, front_left):
        draw_light_rectangle((255, 255, 230), light, light_width, light_length)
    for light in (rear_right, rear_left):
        brake_scale = 1.2 if braking else 1.0
        draw_light_rectangle(
            (255, 0, 0) if braking else (230, 30, 30),
            light,
            light_width * brake_scale,
            light_length * brake_scale,
        )
    if reversing:
        reverse_r = max(1.0, light_r * 0.65)
        reverse_x = (rear_right[0] + rear_left[0]) * 0.5
        reverse_y = (rear_right[1] + rear_left[1]) * 0.5
        draw_light_rectangle((245, 245, 235), (reverse_x, reverse_y), reverse_r, light_length * 0.65)
    turn_signal_on = turn_signal and (turn_signal_elapsed % 0.9 < 0.45)
    if turn_signal_on:
        signal_side = 1.0 if turn_signal == "right" else -1.0
        for signal_x, signal_y in (
            (
                cx + fx * (hl - 0.5) + rx * (light_inset * signal_side),
                cy + fy * (hl - 0.5) + ry * (light_inset * signal_side),
            ),
            (
                cx - fx * (hl - 0.5) + rx * (light_inset * signal_side),
                cy - fy * (hl - 0.5) + ry * (light_inset * signal_side),
            ),
        ):
            draw_light_rectangle((255, 170, 20), (signal_x, signal_y), light_width, light_length)


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
    door_open_progress: float = 0.0,
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

    if is_taxi and door_open_progress > 0.0:
        # Driver-side front door swings outward from the left side of the taxi.
        door_progress = max(0.0, min(1.0, door_open_progress))
        door_center = (cx + fx * hl * 0.2 - rx * hw, cy + fy * hl * 0.2 - ry * hw)
        door_half_length = max(2.0, hl * 0.22)
        door_inner_front = (
            door_center[0] + fx * door_half_length,
            door_center[1] + fy * door_half_length,
        )
        door_inner_rear = (
            door_center[0] - fx * door_half_length,
            door_center[1] - fy * door_half_length,
        )
        door_swing = width_px * 0.95 * door_progress
        door_outer_front = (
            door_inner_front[0] - rx * door_swing,
            door_inner_front[1] - ry * door_swing,
        )
        door_outer_rear = (
            door_inner_rear[0] - rx * door_swing,
            door_inner_rear[1] - ry * door_swing,
        )
        pygame.draw.polygon(
            screen,
            (245, 205, 45),
            [door_inner_front, door_outer_front, door_outer_rear, door_inner_rear],
        )
        pygame.draw.line(screen, outline_color, door_inner_front, door_outer_front, 1)
        pygame.draw.line(screen, outline_color, door_inner_rear, door_outer_rear, 1)

    _draw_vehicle_lights(screen, cx, cy, heading, length_px, width_px, turn_signal, turn_signal_elapsed)


def _draw_vehicle_outline(screen, cx, cy, heading, length_px, width_px, color=(235, 235, 235)) -> None:
    import pygame

    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    fx, fy = cos_h, -sin_h
    rx, ry = sin_h, cos_h
    half_length = length_px * 0.5
    half_width = width_px * 0.5
    corners = [
        (cx + fx * half_length + rx * half_width, cy + fy * half_length + ry * half_width),
        (cx + fx * half_length - rx * half_width, cy + fy * half_length - ry * half_width),
        (cx - fx * half_length - rx * half_width, cy - fy * half_length - ry * half_width),
        (cx - fx * half_length + rx * half_width, cy - fy * half_length + ry * half_width),
    ]
    outline_width = max(1, round(min(2.0, width_px * 0.1)))
    pygame.draw.lines(screen, color, True, corners, outline_width)


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
    door_open_progress: float = 0.0,
    spatial_grid=None,
    current_way=None,
) -> None:
    """Draw player taxi scaled in meters with headlights and taillights."""
    import pygame

    covered_by_higher_road = not _vehicle_is_on_bridge(car, current_way) and _covered_by_higher_road(
        car.x, car.y, getattr(car, "layer", 0), ways, spatial_grid, current_way
    )
    if covered_by_higher_road:
        cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, screen_w, screen_h)
        _draw_vehicle_outline(
            screen,
            cx,
            cy,
            car.heading,
            max(6.0, getattr(car, "length_m", 4.0) * px_per_m),
            max(3.0, getattr(car, "width_m", 1.8) * px_per_m),
        )
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
        door_open_progress=door_open_progress,
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


def draw_vehicle_lights(
    screen,
    vehicles,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
    current_way=None,
) -> None:
    """Redraw vehicle lamps after night tinting so they remain visible in darkness."""
    for vehicle in vehicles:
        if getattr(vehicle, "is_police", False):
            continue
        vehicle_layer = getattr(vehicle, "layer", getattr(getattr(vehicle, "way", None), "layer", 0))
        active_way = current_way if vehicle is vehicles[0] else None
        if not _vehicle_is_on_bridge(vehicle, active_way) and _covered_by_higher_road(
            vehicle.x, vehicle.y, vehicle_layer, ways, spatial_grid
        ):
            continue
        cx, cy = world_to_screen(vehicle.x, vehicle.y, camx, camy, px_per_m)
        length_px = max(5.0, getattr(vehicle, "length_m", 4.0) * px_per_m)
        width_px = max(2.5, getattr(vehicle, "width_m", 1.8) * px_per_m)
        _draw_vehicle_lights(
            screen,
            cx,
            cy,
            vehicle.heading,
            length_px,
            width_px,
            getattr(vehicle, "turn_signal", ""),
            getattr(vehicle, "turn_signal_elapsed", 0.0),
            braking=getattr(vehicle, "braking", False),
            reversing=getattr(vehicle, "speed", 0.0) < -0.05,
        )


def draw_npc_cars(
    screen,
    npcs: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
    show_debug: bool = False,
    residents=None,
) -> None:
    """Draw autonomous NPC cars scaled in meters with headlights and taillights."""
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    global _motorcycle_sprite, _moped_sprite
    global _npc_debug_font
    import pygame

    if show_debug and _npc_debug_font is None:
        _npc_debug_font = pygame.font.Font(None, 16)
    debug_font = _npc_debug_font

    if _motorcycle_sprite is None:
        _motorcycle_sprite = pygame.image.load(
            os.path.join(os.path.dirname(__file__), "..", "assets", "motorcycle.xpm")
        ).convert_alpha()
    if _moped_sprite is None:
        _moped_sprite = pygame.image.load(
            os.path.join(os.path.dirname(__file__), "..", "assets", "moped.xpm")
        ).convert_alpha()

    visible_npc_count = 0
    for npc in npcs:
        if getattr(npc, "is_police", False) or getattr(npc, "is_on_foot", False):
            continue
        in_view = vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy
        parking_route = getattr(npc, "parking_route", None)
        if not in_view and show_debug and parking_route:
            route_screen = [
                world_to_screen(point[0], point[1], camx, camy, px_per_m, screen_w, screen_h)
                for point in parking_route
            ]
            if len(route_screen) >= 2:
                pygame.draw.lines(screen, (255, 150, 40), False, route_screen, 2)
            continue
        if not in_view:
            continue
        if getattr(npc, "lod_level", 0) >= 2:
            continue
        covered_by_higher_road = not _vehicle_is_on_bridge(npc) and _covered_by_higher_road(
            npc.x,
            npc.y,
            getattr(npc, "layer", getattr(npc.way, "layer", 0)),
            ways,
            spatial_grid,
        )
        if visible_npc_count >= MAX_VISIBLE_NPC_COUNT:
            continue
        visible_npc_count += 1

        cx, cy = world_to_screen(npc.x, npc.y, camx, camy, px_per_m, screen_w, screen_h)
        length_m = getattr(npc, "length_m", 4.0)
        width_m = getattr(npc, "width_m", 1.8)
        length_px = max(5.0, length_m * px_per_m)
        width_px = max(2.5, width_m * px_per_m)

        if covered_by_higher_road:
            _draw_vehicle_outline(screen, cx, cy, npc.heading, length_px, width_px)
            continue

        vehicle_type = getattr(npc, "vehicle_type", "car")
        if vehicle_type in ("motorcycle", "moped"):
            sprite = _motorcycle_sprite if vehicle_type == "motorcycle" else _moped_sprite
            sprite_length = max(6, int(1.8 * px_per_m))
            sprite_width = max(4, int(0.6 * px_per_m))
            fallen_angle = 90.0 if getattr(npc, "fallen", False) else 0.0
            render_angle = round((math.degrees(npc.heading) - 90.0 + fallen_angle) / 15.0) * 15.0
            render_key = (
                vehicle_type,
                tuple(npc.color),
                sprite_width,
                sprite_length,
                render_angle,
            )
            rotated_sprite = _two_wheeler_render_cache.get(render_key)
            if rotated_sprite is None:
                tinted_sprite = _tinted_two_wheeler_sprite(sprite, npc.color, vehicle_type)
                scaled_sprite = pygame.transform.smoothscale(tinted_sprite, (sprite_width, sprite_length))
                rotated_sprite = pygame.transform.rotate(scaled_sprite, render_angle)
                _two_wheeler_render_cache[render_key] = rotated_sprite
            screen.blit(rotated_sprite, rotated_sprite.get_rect(center=(int(cx), int(cy))))
        elif getattr(npc, "lod_level", 0) > 0:
            sprite = _npc_vehicle_sprite(
                pygame,
                length_px,
                width_px,
                npc.color,
                npc.heading,
                getattr(npc, "is_taxi", False),
            )
            screen.blit(sprite, sprite.get_rect(center=(int(cx), int(cy))))
        else:
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

        if show_debug:
            lod_colors = ((70, 220, 100), (240, 190, 60), (230, 90, 80))
            debug_color = lod_colors[min(2, max(0, getattr(npc, "lod_level", 0)))]
            collider_radius = max(length_px, width_px) * 0.5
            pygame.draw.circle(screen, debug_color, (int(cx), int(cy)), max(2, int(collider_radius)), 1)
            if parking_route:
                route_screen = [
                    world_to_screen(point[0], point[1], camx, camy, px_per_m, screen_w, screen_h)
                    for point in parking_route
                ]
                if len(route_screen) >= 2:
                    pygame.draw.lines(screen, (255, 150, 40), False, route_screen, 2)
                target_index = min(
                    max(0, getattr(npc, "parking_route_index", 0)),
                    len(route_screen) - 1,
                )
                target_screen = route_screen[target_index]
                pygame.draw.circle(
                    screen, (255, 220, 80), (int(target_screen[0]), int(target_screen[1])), 4, 1
                )
            else:
                travel_route = getattr(npc, "travel_route", None) or ()
                if len(travel_route) >= 2:
                    route_screen = [
                        world_to_screen(point[0], point[1], camx, camy, px_per_m, screen_w, screen_h)
                        for point in travel_route
                    ]
                    pygame.draw.lines(screen, (100, 220, 255), False, route_screen, 1)
                    destination_screen = route_screen[-1]
                    pygame.draw.circle(
                        screen,
                        (100, 220, 255),
                        (int(destination_screen[0]), int(destination_screen[1])),
                        5,
                        1,
                    )
                pts = getattr(npc.way, "points_m", None)
                target_pt = None
                if pts and getattr(npc, "direction", 1) == 1 and getattr(npc, "segment_idx", 0) + 1 < len(pts):
                    target_pt = pts[npc.segment_idx + 1]
                elif pts and getattr(npc, "direction", 1) == -1 and getattr(npc, "segment_idx", 0) < len(pts):
                    target_pt = pts[npc.segment_idx]
                if target_pt is not None:
                    target_screen = world_to_screen(
                        target_pt[0], target_pt[1], camx, camy, px_per_m, screen_w, screen_h
                    )
                    pygame.draw.line(screen, debug_color, (int(cx), int(cy)),
                                     (int(target_screen[0]), int(target_screen[1])), 1)
            if debug_font is not None:
                waiting_for = getattr(npc, "debug_waiting_for", "")
                debug_state = getattr(npc, "state", "driving")
                if waiting_for and debug_state in {"waiting", "braking"}:
                    debug_state = f"{debug_state} [{waiting_for}]"
                road_type = str(getattr(npc.way, "highway", "unknown"))
                service_type = getattr(npc.way, "service", "")
                if service_type:
                    road_type += f"/{service_type}"
                owner = residents.get(getattr(npc, "owner_id", None)) if residents is not None else None
                owner_name = f"{owner.first_name} {owner.surname}" if owner is not None else "Unknown"
                destination = getattr(npc, "destination", None)
                if destination is not None:
                    destination_distance = math.hypot(npc.x - destination[0], npc.y - destination[1])
                    if getattr(npc, "destination_parking_space_id", None) is not None:
                        destination_text = f"PARKING {npc.destination_parking_space_id} {destination_distance:.0f}m"
                    else:
                        destination_text = f"DEST ({destination[0]:.0f},{destination[1]:.0f}) {destination_distance:.0f}m"
                else:
                    destination_text = "DEST none"
                debug_text = debug_font.render(
                    f"{owner_name} {debug_state} "
                    f"{road_type} L{getattr(npc, 'lod_level', 0)} "
                    f"{getattr(npc, 'speed', 0.0) * 3.6:.0f} km/h {destination_text}",
                    True,
                    debug_color,
                )
                screen.blit(debug_text, (int(cx + collider_radius + 2), int(cy - debug_text.get_height() / 2)))

        # Draw animated smoke puff effect if NPC is disabled from a crash
        crashed_timer = getattr(npc, "crashed_timer", 0.0)
        if crashed_timer > 0.0:
            import pygame
            t = (
                5.0 - crashed_timer
                if math.isfinite(crashed_timer)
                else pygame.time.get_ticks() / 1000.0
            )
            # 3 animated puff particles floating upwards from engine bay
            fx = math.cos(npc.heading)
            fy = -math.sin(npc.heading)
            rx = math.sin(npc.heading)
            ry = math.cos(npc.heading)
            front_cx = cx + fx * (length_px * 0.4)
            front_cy = cy + fy * (length_px * 0.4)
            for puff_idx in range(4):
                offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
                drift = math.sin(t * 3.0 + puff_idx) * (4.0 * offset_t)
                puff_x = front_cx + rx * drift
                puff_y = front_cy + ry * drift - offset_t * 14.0  # drifts upwards
                radius = int(3.0 + offset_t * 5.0)
                alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
                smoke_surf = _smoke_surface(pygame, radius, alpha)
                screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_police_cars(screen, police_cars, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw patrol cars and their blue emergency lights."""
    import pygame

    for police in police_cars:
        cx, cy = world_to_screen(police.x, police.y, camx, camy, px_per_m)
        length_px = max(7.0, 4.3 * px_per_m)
        width_px = max(3.0, 1.9 * px_per_m)
        _draw_vehicle(
            screen,
            cx=cx,
            cy=cy,
            heading=police.heading,
            length_px=length_px,
            width_px=width_px,
            body_color=(235, 235, 240),
            outline_color=(20, 25, 35),
        )
        if getattr(police, "pursuing", False) and not getattr(police, "penalty_given", False):
            right_x = math.sin(police.heading)
            right_y = math.cos(police.heading)
            light_spacing = max(1.5, width_px * 0.32)
            light_radius = max(1.5, min(3.0, width_px * 0.25))
            phase = (pygame.time.get_ticks() // 180) % 2
            left_color = (255, 35, 35) if phase == 0 else (90, 20, 20)
            right_color = (40, 110, 255) if phase == 1 else (20, 45, 110)
            bar_start = (cx - right_x * light_spacing, cy - right_y * light_spacing)
            bar_end = (cx + right_x * light_spacing, cy + right_y * light_spacing)
            pygame.draw.line(screen, (25, 30, 40), bar_start, bar_end, max(2, int(light_radius * 2.2)))
            pygame.draw.circle(screen, left_color, (int(bar_start[0]), int(bar_start[1])), int(light_radius))
            pygame.draw.circle(screen, right_color, (int(bar_end[0]), int(bar_end[1])), int(light_radius))


def draw_npc_spatial_grid(
    screen,
    npc_grid,
    cell_size: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw occupied NPC grid cells for traffic debugging."""
    import pygame

    global _npc_debug_font
    if _npc_debug_font is None:
        _npc_debug_font = pygame.font.Font(None, 16)
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    min_cell_x = math.floor(vminx / cell_size)
    max_cell_x = math.floor(vmaxx / cell_size)
    min_cell_y = math.floor(vminy / cell_size)
    max_cell_y = math.floor(vmaxy / cell_size)
    for cell_x in range(min_cell_x, max_cell_x + 1):
        for cell_y in range(min_cell_y, max_cell_y + 1):
            occupants = npc_grid.get((cell_x, cell_y))
            if not occupants:
                continue
            left, top = world_to_screen(
                cell_x * cell_size, (cell_y + 1) * cell_size,
                camx, camy, px_per_m, screen_w, screen_h,
            )
            right, bottom = world_to_screen(
                (cell_x + 1) * cell_size, cell_y * cell_size,
                camx, camy, px_per_m, screen_w, screen_h,
            )
            rect = pygame.Rect(
                int(left), int(top), max(1, int(right - left)), max(1, int(bottom - top))
            )
            pygame.draw.rect(screen, (80, 180, 255), rect, 1)
            label = _npc_debug_font.render(str(len(occupants)), True, (140, 220, 255))
            screen.blit(label, rect.topleft)


def draw_logical_intersections(
    screen,
    intersections,
    camx: float,
    camy: float,
    current_time: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    intersection_manager=None,
) -> None:
    """Draw cached intersection bounds, approaches, stop lines, and phases."""
    import pygame

    global _npc_debug_font
    if _npc_debug_font is None:
        _npc_debug_font = pygame.font.Font(None, 16)
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    state_colors = {
        "green": (70, 220, 100),
        "yellow": (245, 205, 60),
        "red": (235, 80, 80),
        "all-red": (255, 120, 120),
        "red+yellow": (245, 140, 60),
    }
    for intersection in intersections:
        center_x, center_y = intersection.center
        if not (vminx - intersection.radius_m <= center_x <= vmaxx + intersection.radius_m
                and vminy - intersection.radius_m <= center_y <= vmaxy + intersection.radius_m):
            continue
        center = world_to_screen(center_x, center_y, camx, camy, px_per_m, screen_w, screen_h)
        pygame.draw.circle(screen, (180, 100, 220), center, max(2, int(intersection.radius_m * px_per_m)), 1)
        title = _npc_debug_font.render(
            f"{intersection.intersection_id} A{len(intersection.approaches)}"
            + (
                f" R{len(intersection_manager._reservations.get(intersection.intersection_id, {}))}"
                if intersection_manager is not None else ""
            ),
            True,
            (220, 170, 240),
        )
        screen.blit(title, (int(center[0] + 4), int(center[1] - 12)))
        for approach in intersection.approaches:
            stop_start = world_to_screen(*approach.stop_line[0], camx, camy, px_per_m, screen_w, screen_h)
            stop_end = world_to_screen(*approach.stop_line[1], camx, camy, px_per_m, screen_w, screen_h)
            state = approach.signal_group.get_state(current_time) if approach.signal_group else "green"
            color = state_colors.get(state, (180, 180, 180))
            pygame.draw.line(screen, color, stop_start, stop_end, 2)
            vector_end = (
                center_x + approach.direction_vector[0] * 18.0,
                center_y + approach.direction_vector[1] * 18.0,
            )
            vector_screen = world_to_screen(*vector_end, camx, camy, px_per_m, screen_w, screen_h)
            pygame.draw.line(screen, color, center, vector_screen, 1)
            label = _npc_debug_font.render(
                f"{approach.approach_id} {state} M{','.join(sorted(approach.allowed_movements))}",
                True,
                color,
            )
            screen.blit(label, (int(stop_start[0] + 2), int(stop_start[1] + 2)))


def draw_cyclists(
    screen,
    cyclists: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
) -> None:
    """Draw cyclists as compact riders with bicycle wheels."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)
    for cyclist in cyclists:
        if not (vminx <= cyclist.x <= vmaxx and vminy <= cyclist.y <= vmaxy):
            continue
        if _covered_by_higher_road(
            cyclist.x,
            cyclist.y,
            getattr(cyclist.way, "layer", 0),
            ways,
            spatial_grid=spatial_grid,
        ):
            continue
        cx, cy = world_to_screen(cyclist.x, cyclist.y, camx, camy, px_per_m, screen_w, screen_h)
        global _cyclist_sprite
        if _cyclist_sprite is None:
            _cyclist_sprite = pygame.image.load(
                os.path.join(os.path.dirname(__file__), "..", "assets", "cyclist.xpm")
            ).convert_alpha()
        sprite_scale = max(0.15, px_per_m * 3.2 / _cyclist_sprite.get_width())
        tinted_sprite = _tinted_cyclist_sprite(_cyclist_sprite, cyclist.color)
        sprite = pygame.transform.rotozoom(tinted_sprite, math.degrees(cyclist.heading) - 90.0, sprite_scale)
        screen.blit(sprite, sprite.get_rect(center=(int(cx), int(cy))))
