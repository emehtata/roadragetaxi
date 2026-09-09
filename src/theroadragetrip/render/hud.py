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

from ..geo import clamp, clip_polygon_to_rect, compute_bbox, dist_point_to_segment, meters_to_latlon, point_in_polygon
from ..osm import Building, BusStop, Place, Scenery, TaxiStop, Water, Way
from ..physics import Car, MAX_SPEED, is_point_on_road
from ..taxi import TaxiManager, TaxiState
from ..localization import tr


_day_night_overlay_cache = {}
_rage_face_frames = None
_rage_face_path = os.path.join(os.path.dirname(__file__), "..", "assets", "ragefaceatlas.png")
_speedometer_font = None
_speedometer_label_font = None


def _load_rage_face_frames(pygame):
    global _rage_face_frames
    if _rage_face_frames is not None:
        return _rage_face_frames
    try:
        atlas = pygame.image.load(_rage_face_path).convert()
        atlas_width, atlas_height = atlas.get_size()
        frame_size = (170, 180)
        frames = []
        crop_rects = [(0, 80, 296, 486), (296, 80, 592, 486), (592, 80, 888, 486)]
        crop_rects.extend([(888, 80, 1188, 486), (1188, 80, 1484, 486)])
        crop_rects.extend(
            (column * (atlas_width // 6), 576, (column + 1) * (atlas_width // 6), 990)
            for column in range(6)
        )
        for left, top, right, bottom in crop_rects:
            crop = atlas.subsurface((left, top, right - left, bottom - top))
            scale = min(frame_size[0] / crop.get_width(), frame_size[1] / crop.get_height())
            scaled_size = (round(crop.get_width() * scale), round(crop.get_height() * scale))
            scaled_crop = pygame.transform.smoothscale(crop, scaled_size)
            frame = pygame.Surface(frame_size).convert()
            frame.fill(atlas.get_at((0, 0)))
            frame.blit(
                scaled_crop,
                ((frame_size[0] - scaled_size[0]) // 2, (frame_size[1] - scaled_size[1]) // 2),
            )
            frames.append(frame)
        _rage_face_frames = frames
    except (pygame.error, OSError) as exc:
        _render_logger.warning("Could not load rage face atlas: %s", exc)
        _rage_face_frames = []
    return _rage_face_frames


def default_hud_layout(screen_width: int, screen_height: int) -> dict[str, Tuple[int, int]]:
    return {
        "meters": (10, 10),
        "rage": (screen_width - 190, screen_height - 246),
        "speedometer": (10, screen_height - 180),
    }


def _draw_analog_speedometer(screen, speed_mps: float, position: Tuple[int, int]):
    import pygame

    global _speedometer_font
    global _speedometer_label_font
    if _speedometer_font is None:
        _speedometer_font = pygame.font.SysFont(None, 18)
    if _speedometer_label_font is None:
        _speedometer_label_font = pygame.font.SysFont(None, 14)
    font = _speedometer_font
    label_font = _speedometer_label_font
    width, height = 190, 170
    x, y = position
    center = (x + width // 2, y + 88)
    radius = 68
    pygame.draw.rect(screen, (20, 25, 30, 220), (x, y, width, height), border_radius=4)
    pygame.draw.rect(screen, (130, 140, 150), (x, y, width, height), width=1, border_radius=4)
    pygame.draw.circle(screen, (12, 16, 20), center, radius)
    pygame.draw.circle(screen, (130, 140, 150), center, radius, 2)

    speed_kmh = max(0.0, min(MAX_SPEED * 3.6, speed_mps * 3.6))
    for speed_mark in range(0, 211, 10):
        angle = math.radians(135.0 + speed_mark / 210.0 * 270.0)
        is_major = speed_mark % 20 == 0
        outer_radius = radius - 5
        inner_radius = radius - (18 if is_major else 11)
        outer = (center[0] + math.cos(angle) * outer_radius, center[1] + math.sin(angle) * outer_radius)
        inner = (center[0] + math.cos(angle) * inner_radius, center[1] + math.sin(angle) * inner_radius)
        pygame.draw.line(screen, (235, 220, 170), inner, outer, 3 if is_major else 2)
        if is_major:
            label_center = (
                center[0] + math.cos(angle) * (radius - 25),
                center[1] + math.sin(angle) * (radius - 25),
            )
            label = label_font.render(str(speed_mark), True, (220, 225, 215))
            screen.blit(label, label.get_rect(center=label_center))

    needle_angle = math.radians(135.0 + (speed_kmh / (MAX_SPEED * 3.6)) * 270.0)
    needle_end = (
        center[0] + math.cos(needle_angle) * (radius - 20),
        center[1] + math.sin(needle_angle) * (radius - 20),
    )
    pygame.draw.line(screen, (230, 65, 45), center, needle_end, 4)
    pygame.draw.circle(screen, (240, 220, 170), center, 6)
    speed_text = font.render(f"{speed_kmh:.0f}", True, (240, 240, 240))
    screen.blit(speed_text, speed_text.get_rect(center=(center[0], y + 132)))
    unit_text = font.render("km/h", True, (190, 200, 205))
    screen.blit(unit_text, unit_text.get_rect(center=(center[0], y + 153)))
    return pygame.Rect(x, y, width, height)


def draw_day_night_overlay(
    screen,
    game_time_seconds: float,
    visible_road_count: Optional[int] = None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
) -> None:
    """Tint the game world according to the simulated time of day."""
    import pygame

    sun_altitude, _, _ = solar_altitude_and_events(game_time_seconds, latitude, longitude)
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    alpha = int(115.0 * (1.0 - twilight))
    if visible_road_count is not None and alpha > 0:
        sparse_area = max(0.0, min(1.0, (12.0 - visible_road_count) / 12.0))
        alpha += int(95.0 * sparse_area)
    if alpha <= 0:
        return
    cache_key = (screen.get_size(), alpha)
    overlay = _day_night_overlay_cache.get(cache_key)
    if overlay is None:
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((10, 18, 48, alpha))
        _day_night_overlay_cache[cache_key] = overlay
    screen.blit(overlay, (0, 0))


def draw_phone_offers(
    screen,
    taxi_mgr: TaxiManager,
    font,
    small_font,
    screen_w: int,
    screen_h: int,
    language: str = "fi",
    car: Optional[Car] = None,
) -> None:
    """Draw the in-game phone with selectable taxi offers."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((5, 8, 12, 170))
    screen.blit(overlay, (0, 0))

    phone = pygame.Rect(screen_w // 2 - 250, screen_h // 2 - 250, 500, 500)
    pygame.draw.rect(screen, (18, 22, 28), phone, border_radius=18)
    pygame.draw.rect(screen, (92, 105, 116), phone, width=3, border_radius=18)
    pygame.draw.rect(screen, (38, 48, 57), (phone.x + 180, phone.y + 12, 140, 5), border_radius=2)
    title = font.render(tr(language, "taxi_phone"), True, (245, 220, 110))
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
            distance = (
                math.hypot(car.x - passenger.pickup.x, car.y - passenger.pickup.y)
                if car is not None
                else offer.pickup_distance_m
            )
            distance_text = f"{distance:.0f} m" if distance < 1000 else f"{distance / 1000.0:.2f} km"
            trip_distance = math.hypot(
                passenger.dropoff.x - passenger.pickup.x,
                passenger.dropoff.y - passenger.pickup.y,
            )
            trip_distance_text = (
                f"{trip_distance:.0f} m"
                if trip_distance < 1000
                else f"{trip_distance / 1000.0:.2f} km"
            )
            label = small_font.render(f"[{index + 1}]  {passenger.name}", True, (245, 245, 240))
            pickup = small_font.render(f"{tr(language, 'pickup')}: {passenger.pickup.address}", True, (190, 205, 212))
            dropoff = small_font.render(f"{tr(language, 'to')}: {passenger.dropoff.address}", True, (170, 190, 175))
            dist = small_font.render(
                f"{tr(language, 'distance_client')}: {distance_text} | "
                f"{tr(language, 'distance_trip')}: {trip_distance_text}",
                True,
                (255, 215, 95),
            )
            screen.blit(label, (row.x + 12, row.y + 8))
            screen.blit(pickup, (row.x + 12, row.y + 29))
            screen.blit(dropoff, (row.x + 12, row.y + 48))
            screen.blit(dist, (row.x + 12, row.y + 67))

    hint_text = tr(language, "close_phone")
    if taxi_mgr.offers:
        hint_text += f"  |  {tr(language, 'reject_phone')}"
    hint = small_font.render(hint_text, True, (180, 185, 190))
    screen.blit(hint, hint.get_rect(center=(phone.centerx, phone.bottom - 20)))


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
    show_compass: bool = False,
    rage_power: float = 0.0,
    language: str = "fi",
    career_total_distance_m: Optional[float] = None,
    water_time_remaining: Optional[float] = None,
    game_time_seconds: Optional[float] = None,
    game_time_realtime: bool = False,
    comment_text: Optional[str] = None,
    comment_speaker: str = "driver",
    comment_speaker_name: Optional[str] = None,
    subtitles_enabled: bool = True,
    fps: float = 0.0,
    show_debug_hud: bool = False,
    hud_layout: Optional[dict[str, Tuple[int, int]]] = None,
    hud_rects: Optional[dict[str, object]] = None,
) -> None:
    """Draw speed, trip, odometer, on-road status, current road name, lat/lon, taxi mission bar, notifications."""
    import pygame

    screen_width = screen.get_width()
    screen_height = screen.get_height()
    layout = hud_layout if hud_layout is not None else default_hud_layout(screen_width, screen_height)
    if hud_rects is not None:
        hud_rects.clear()

    lat, lon = meters_to_latlon(car.x, car.y, transformer=transformer_to_ll)
    lat_s = f"{lat:.5f}" if lat is not None else "N/A"
    lon_s = f"{lon:.5f}" if lon is not None else "N/A"

    trip_s = f"{car.trip_m:.0f} m" if car.trip_m < 1000 else f"{car.trip_m / 1000.0:.2f} km"
    odo_s = f"{car.odometer_m / 1000.0:.1f} km"

    labels_status = tr(language, "on" if show_labels else "off")
    lane_assist_status = tr(language, "on" if getattr(car, "lane_assist_enabled", False) else "off")
    speed_limiter_status = tr(language, "on" if speed_limiter_enabled else "off")
    red_light_assist_status = tr(language, "on" if red_light_assist_enabled else "off")
    road_name_s = current_road_name if current_road_name else tr(language, "off_road")
    limit_s = f" [{tr(language, 'limit')}: {speed_limit_kmh} km/h]" if speed_limit_kmh is not None else ""
    assist_s = f" | [{tr(language, 'lane_assist_active')}]" if getattr(car, "lane_assist_active", False) else ""
    hud = (
        f"{tr(language, 'road')}: {road_name_s}{limit_s}{assist_s} | {tr(language, 'trip')}: {trip_s} | {tr(language, 'odometer')}: {odo_s} | "
        f"{tr(language, 'ways')}: {ways_count} | {tr(language, 'zoom_level')}: {px_per_m:.2f} px/m | "
        f"{tr(language, 'latitude')}: {lat_s} {tr(language, 'longitude')}: {lon_s}"
    )
    if show_debug_hud:
        text = font.render(hud, True, (240, 240, 240))
        screen.blit(text, (10, 10))

    if game_time_seconds is not None:
        total_minutes = int(game_time_seconds // 60.0) % (24 * 60)
        clock_text = f"Kello {total_minutes // 60:02d}:{total_minutes % 60:02d}"
        clock_text += " *" if game_time_realtime else ""
        clock_surface = font.render(clock_text, True, (255, 230, 120))
        clock_rect = clock_surface.get_rect(topright=(screen.get_width() - 12, 10))
        screen.blit(clock_surface, clock_rect)

    if speed_limit_kmh is not None:
        sign_center = (screen.get_width() - 48, 76)
        pygame.draw.circle(screen, (255, 210, 0), sign_center, 31)
        pygame.draw.circle(screen, (210, 35, 35), sign_center, 31, 8)
        sign_font = pygame.font.Font(None, 38)
        sign_text = sign_font.render(str(speed_limit_kmh), True, (20, 20, 20))
        screen.blit(sign_text, sign_text.get_rect(center=sign_center))

    if water_time_remaining is not None:
        water_text = font.render(
            f"{tr(language, 'water_timer')}: {water_time_remaining:.1f} s",
            True,
            (255, 235, 90),
        )
        water_rect = water_text.get_rect(center=(screen.get_width() // 2, 78))
        water_bg = pygame.Surface((water_rect.width + 24, water_rect.height + 10), pygame.SRCALPHA)
        water_bg.fill((35, 25, 15, 225))
        screen.blit(water_bg, (water_rect.x - 12, water_rect.y - 5))
        pygame.draw.rect(
            screen,
            (255, 190, 40),
            (water_rect.x - 12, water_rect.y - 5, water_rect.width + 24, water_rect.height + 10),
            2,
            border_radius=4,
        )
        screen.blit(water_text, water_rect)

    if subtitles_enabled and comment_text:
        subtitle_font = pygame.font.SysFont(None, max(22, font.get_height()))
        speaker = comment_speaker_name or tr(language, "driver")
        subtitle_surface = subtitle_font.render(f"{speaker}: {comment_text}", True, (255, 255, 255))
        subtitle_rect = subtitle_surface.get_rect(center=(screen.get_width() // 2, screen.get_height() - 82))
        subtitle_bg = pygame.Surface((subtitle_rect.width + 34, subtitle_rect.height + 16), pygame.SRCALPHA)
        subtitle_bg.fill((0, 0, 0, 205))
        screen.blit(subtitle_bg, (subtitle_rect.x - 17, subtitle_rect.y - 8))
        screen.blit(subtitle_surface, subtitle_rect)

    hint = (
        f"{tr(language, 'controls')}: W/S/A/D = {tr(language, 'drive').lower()} | +/- = {tr(language, 'zoom').lower()} | R = {tr(language, 'respawn').lower()} | X = {tr(language, 'cancel_ride').lower()} | T = {tr(language, 'reset_trip').lower()} | "
        f"L = labels ({labels_status}) | K = lane assist ({lane_assist_status}) | V = limiter ({speed_limiter_status}) | B = red assist ({red_light_assist_status}) | C = {tr(language, 'compass')} ({tr(language, 'on' if show_compass else 'off')}) | Space = {tr(language, 'rage')} | ESC = pause"
    )
    if show_debug_hud:
        hint_t = font.render(hint, True, (220, 220, 220))
        screen.blit(hint_t, (10, 34))


    meter_s = (
        f"{tr(language, 'career_meter')}: {odo_s}   |   "
        f"{tr(language, 'trip_meter')}: {trip_s}"
        if career_total_distance_m is None
        else f"{tr(language, 'career_meter')}: {career_total_distance_m / 1000.0:.1f} km   |   "
        f"{tr(language, 'trip_meter')}: {trip_s}"
    )
    meter_surface = font.render(meter_s, True, (255, 245, 190))
    meter_background = pygame.Surface((meter_surface.get_width() + 20, meter_surface.get_height() + 10), pygame.SRCALPHA)
    meter_background.fill((15, 20, 25, 210))
    meter_x, meter_y = layout["meters"]
    meter_rect = pygame.Rect(meter_x, meter_y, meter_background.get_width(), meter_background.get_height())
    if hud_rects is not None:
        hud_rects["meters"] = meter_rect
    screen.blit(meter_background, (meter_x, meter_y))
    screen.blit(meter_surface, (meter_x + 10, meter_y + 5))

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
            role_text = tr(language, "fare_pickup", name=p.name if p else tr(language, "client"), address=target.address if target else "...") + f" ({dist_s})"
            role_color = (255, 215, 60)
        else:
            cur_speed_kmh = (dist_m / max(1.0, taxi_mgr.elapsed_time)) * 3.6 if taxi_mgr.elapsed_time > 0 else 0.0
            role_text = (
                tr(language, "fare_dropoff", name=p.name if p else tr(language, "client"), address=target.address if target else "...")
                + f" ({dist_s}, {tr(language, 'elapsed_time')}: {taxi_mgr.elapsed_time:.1f}s)"
            )
            role_color = (100, 240, 140)

        # Draw taxi score and stats on top right
        score_text = f"{tr(language, 'score')}: {taxi_mgr.total_score} {tr(language, 'points')} | {tr(language, 'fares')}: {taxi_mgr.completed_fares}"
        score_surf = font.render(score_text, True, (255, 230, 110))
        score_rect = score_surf.get_rect(topright=(SCREEN_W - 140, 10))
        bg_s = pygame.Surface((score_rect.width + 12, score_rect.height + 6), pygame.SRCALPHA)
        bg_s.fill((20, 20, 20, 200))
        screen.blit(bg_s, (score_rect.x - 6, score_rect.y - 3))
        pygame.draw.rect(screen, (220, 180, 50), (score_rect.x - 6, score_rect.y - 3, score_rect.width + 12, score_rect.height + 6), 1, border_radius=3)
        screen.blit(score_surf, score_rect)

        fps_surf = font.render(f"FPS: {fps:.1f}", True, (170, 245, 180))
        fps_rect = fps_surf.get_rect(topright=(SCREEN_W - 10, score_rect.bottom + 8))
        fps_bg = pygame.Surface((fps_rect.width + 12, fps_rect.height + 6), pygame.SRCALPHA)
        fps_bg.fill((20, 30, 25, 220))
        screen.blit(fps_bg, (fps_rect.x - 6, fps_rect.y - 3))
        pygame.draw.rect(screen, (90, 180, 110), (fps_rect.x - 6, fps_rect.y - 3, fps_rect.width + 12, fps_rect.height + 6), 1, border_radius=3)
        screen.blit(fps_surf, fps_rect)

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
            is_speed_camera_notice = (
                getattr(taxi_mgr, "speed_camera_notice_timer", 0.0) > 0.0
                and getattr(taxi_mgr, "speed_camera_notice_msg", "")
            )
            notice_text = (
                taxi_mgr.speed_camera_notice_msg
                if is_speed_camera_notice
                else taxi_mgr.notification_msg
            )
            notif_surf = font.render(notice_text, True, (255, 255, 255))
            notice_center = (SCREEN_W // 2, SCREEN_H // 2) if is_speed_camera_notice else (SCREEN_W // 2, SCREEN_H - 45)
            notif_rect = notif_surf.get_rect(center=notice_center)
            n_bg = pygame.Surface((notif_rect.width + 24, notif_rect.height + 12), pygame.SRCALPHA)
            n_bg.fill((20, 30, 40, 235))
            screen.blit(n_bg, (notif_rect.x - 12, notif_rect.y - 6))
            border_color = (255, 70, 45) if is_speed_camera_notice else (255, 200, 50)
            pygame.draw.rect(screen, border_color, (notif_rect.x - 12, notif_rect.y - 6, notif_rect.width + 24, notif_rect.height + 12), 2, border_radius=5)
            screen.blit(notif_surf, notif_rect)

    # Keep the rage face and meter together in the lower-right corner.
    rage_text = font.render(f"{tr(language, 'rage_meter')}: {rage_power * 100:.0f}%", True, (255, 120, 100))
    rage_faces = _load_rage_face_frames(pygame)
    rage_face = None
    if rage_faces:
        rage_index = min(10, max(0, int(max(0.0, min(1.0, rage_power)) * 10.0)))
        rage_face = rage_faces[rage_index]
    face_width = rage_face.get_width() if rage_face else 0
    face_height = rage_face.get_height() if rage_face else 0
    instrument_width = max(rage_text.get_width(), face_width) + 20
    instrument_height = face_height + rage_text.get_height() + 24
    instrument_x, instrument_y = layout["rage"]
    rage_rect = pygame.Rect(instrument_x, instrument_y, instrument_width, instrument_height)
    if hud_rects is not None:
        hud_rects["rage"] = rage_rect
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
    content_x = instrument_x + (instrument_width - face_width) // 2 if rage_face else instrument_x + 10
    if rage_face:
        screen.blit(rage_face, (content_x, instrument_y + 6))
    rage_y = instrument_y + face_height + 10
    screen.blit(rage_text, (instrument_x + 10, rage_y))
    rage_bar = pygame.Rect(instrument_x + 10, rage_y + rage_text.get_height() + 2, instrument_width - 20, 6)
    pygame.draw.rect(screen, (45, 30, 30), rage_bar)
    pygame.draw.rect(
        screen,
        (220, 55, 35),
        (rage_bar.x, rage_bar.y, int(rage_bar.width * max(0.0, min(1.0, rage_power))), rage_bar.height),
    )

    speedometer_rect = _draw_analog_speedometer(screen, car.speed, layout["speedometer"])
    if hud_rects is not None:
        hud_rects["speedometer"] = speedometer_rect

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

        load_t = font.render(f"{tr(language, 'loading_scenery')} {int(prog * 100)}%", True, (255, 215, 60))
        screen.blit(load_t, (bar_x + bar_w + 10, bar_y - 2))


def draw_frame_profiler(screen, font, profiler, npc_count: int, pedestrian_count: int) -> None:
    """Draw compact frame timing diagnostics when enabled."""
    if not profiler.enabled:
        return
    snapshot = profiler.snapshot()
    lines = [
        f"FRAME {snapshot['frame_ms']:.1f} ms | AVG {snapshot['average_ms']:.1f} ms | FPS {snapshot['fps']:.1f}",
        f"SPIKES {snapshot['spikes']} | culprit {snapshot['spike_subsystem'] or 'none'}",
        f"NPC {npc_count} | pedestrians {pedestrian_count}",
    ]
    lines.extend(
        f"{name}: {value}"
        for name, value in snapshot["metrics"].items()
    )
    lines.extend(f"{name}: {duration:.1f} ms" for name, duration in sorted(snapshot["sections"].items(), key=lambda item: -item[1])[:6])
    y = 58
    for line in lines:
        surface = font.render(line, True, (255, 220, 120))
        screen.blit(surface, (10, y))
        y += surface.get_height() + 2


def draw_g_force_meter(
    screen,
    font,
    forward_g: float,
    lateral_g: float,
    is_sliding: bool = False,
    screen_h: int = SCREEN_H,
    max_g: float = 2.5,
) -> None:
    """Debug-HUD g-force meter: a dot on a crosshair circle, positioned
    beside the speedometer. Forward/back is the vertical axis (accelerating
    up, braking down), left/right is horizontal - the classic racing-
    telemetry layout, so all four directions read at a glance."""
    import pygame

    radius = 60
    center = (210 + radius, screen_h - 180 + radius)
    ring_color = (210, 60, 60) if is_sliding else (130, 140, 150)

    pygame.draw.circle(screen, (20, 25, 30), center, radius)
    pygame.draw.circle(screen, ring_color, center, radius, 2)
    pygame.draw.line(screen, (70, 78, 86), (center[0] - radius, center[1]), (center[0] + radius, center[1]), 1)
    pygame.draw.line(screen, (70, 78, 86), (center[0], center[1] - radius), (center[0], center[1] + radius), 1)
    # A ring at 1g marks the typical dry-asphalt grip limit, for scale.
    pygame.draw.circle(screen, (70, 78, 86), center, int(radius / max_g), 1)

    label_color = (170, 178, 186)
    for text, offset in (
        ("F", (0, -radius - 12)), ("B", (0, radius + 4)),
        ("L", (-radius - 14, -6)), ("R", (radius + 4, -6)),
    ):
        label = font.render(text, True, label_color)
        screen.blit(label, (center[0] + offset[0], center[1] + offset[1]))

    # Screen X grows right (matches "R" = +lateral_g); screen Y grows down,
    # so accelerating (+forward_g) plots upward, hence the minus sign.
    dot_x = center[0] + clamp(lateral_g / max_g, -1.0, 1.0) * radius
    dot_y = center[1] - clamp(forward_g / max_g, -1.0, 1.0) * radius
    dot_color = (255, 90, 70) if is_sliding else (255, 210, 60)
    pygame.draw.circle(screen, dot_color, (int(dot_x), int(dot_y)), 6)

    readout = font.render(f"{math.hypot(forward_g, lateral_g):.2f} g", True, dot_color)
    screen.blit(readout, readout.get_rect(midtop=(center[0], center[1] + radius + 16)))
