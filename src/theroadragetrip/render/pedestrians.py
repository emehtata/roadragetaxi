from . import common
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


STREET_LIGHT_REFLECTOR_RADIUS_M = 10.0


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
    show_debug: bool = False,
    residents=None,
    spatial_grid=None,
) -> None:
    """Draw pedestrians as small top-down characters and comic cursing bubbles."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)

    for ped in pedestrians:
        if getattr(ped, "state", "walking") in {"entering_building", "in_building"}:
            continue
        if not (vminx <= ped.x <= vmaxx and vminy <= ped.y <= vmaxy):
            continue
        if _covered_by_higher_road(
            ped.x,
            ped.y,
            getattr(ped, "layer", getattr(ped.way, "layer", 0)),
            ways,
            spatial_grid=spatial_grid,
        ):
            continue

        cx, cy = world_to_screen(ped.x, ped.y, camx, camy, px_per_m, screen_w, screen_h)
        radius_px = max(4.0, getattr(ped, "radius_m", 0.45) * px_per_m)

        if show_debug:
            route = getattr(ped, "route", None) or ()
            route_points = [
                world_to_screen(point[0], point[1], camx, camy, px_per_m, screen_w, screen_h)
                for point in route
            ]
            if len(route_points) >= 2:
                pygame.draw.lines(screen, (245, 210, 70), False, route_points, 1)
            destination = getattr(ped, "destination", None)
            if destination is not None:
                destination_screen = world_to_screen(
                    destination[0], destination[1], camx, camy, px_per_m, screen_w, screen_h
                )
                pygame.draw.circle(screen, (70, 230, 130), destination_screen, 4, 1)
            if font:
                crossing = getattr(ped, "crossing", None)
                crossing_id = getattr(crossing, "id", None) if crossing is not None else "-"
                resident = residents.get(getattr(ped, "resident_id", None)) if residents is not None else None
                resident_name = (
                    "Pelaaja"
                    if getattr(ped, "is_player", False)
                    else f"{resident.first_name} {resident.surname}" if resident is not None else "Unknown"
                )
                debug_text = font.render(
                    f"{resident_name} {getattr(ped, 'state', 'walking')} L{getattr(ped, 'lod_level', 0)} C{crossing_id}",
                    True,
                    (255, 255, 255),
                )
                screen.blit(debug_text, (int(cx + radius_px + 3), int(cy - radius_px - 2)))

        heading_x = math.cos(ped.heading)
        heading_y = -math.sin(ped.heading)
        side_x = -heading_y
        side_y = heading_x

        # Shadow, legs, body, and head make direction readable without a detached marker.
        pygame.draw.ellipse(
            screen,
            (20, 20, 20),
            (int(cx - radius_px * 0.8), int(cy + radius_px * 0.35),
             max(2, int(radius_px * 1.6)), max(2, int(radius_px * 0.65))),
        )
        appearance = getattr(ped, "appearance", None)
        if getattr(ped, "animation_state", "walking") == "fallen":
            pygame.draw.ellipse(
                screen,
                getattr(appearance, "clothing", None) or ped.color,
                (int(cx - radius_px * 1.15), int(cy - radius_px * 0.35),
                 max(3, int(radius_px * 2.3)), max(3, int(radius_px * 0.7))),
            )
            pygame.draw.circle(
                screen,
                getattr(appearance, "head", (238, 185, 145)),
                (int(cx + radius_px * 1.0), int(cy - radius_px * 0.1)),
                max(2, int(radius_px * 0.35)),
            )
            continue
        leg_color = getattr(appearance, "legs", (35, 35, 45))
        gait = math.sin(getattr(ped, "animation_time", 0.0) * 10.0) if getattr(ped, "animation_state", "walking") == "walking" else 0.0
        leg_start_x = cx - heading_x * radius_px * 0.15
        leg_start_y = cy - heading_y * radius_px * 0.15 + radius_px * 0.45
        for leg_side in (-1, 1):
            leg_end_x = leg_start_x + side_x * radius_px * (0.42 * leg_side + gait * 0.10 * leg_side) + heading_x * radius_px * 0.12
            leg_end_y = leg_start_y + side_y * radius_px * (0.42 * leg_side + gait * 0.10 * leg_side) + heading_y * radius_px * 0.12 + radius_px * 0.45
            pygame.draw.line(
                screen, leg_color,
                (int(leg_start_x), int(leg_start_y)),
                (int(leg_end_x), int(leg_end_y)),
                max(1, int(radius_px * 0.28)),
            )

        pygame.draw.ellipse(
            screen,
            (20, 20, 20),
            (int(cx - radius_px * 0.72), int(cy - radius_px * 0.35),
             max(2, int(radius_px * 1.44)), max(2, int(radius_px * 1.55))),
        )
        pygame.draw.ellipse(
            screen,
            getattr(appearance, "clothing", None) or ped.color,
            (int(cx - radius_px * 0.58), int(cy - radius_px * 0.22),
             max(2, int(radius_px * 1.16)), max(2, int(radius_px * 1.25))),
        )

        head_x = cx + heading_x * radius_px * 0.6
        head_y = cy + heading_y * radius_px * 0.6
        pygame.draw.circle(screen, getattr(appearance, "hair", (20, 20, 20)), (int(head_x), int(head_y)), max(2, int(radius_px * 0.48)))
        pygame.draw.circle(screen, getattr(appearance, "head", (238, 185, 145)), (int(head_x), int(head_y)), max(1, int(radius_px * 0.35)))

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


def resident_at_screen_position(
    pedestrians: List,
    residents,
    pos: Tuple[int, int],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> Optional[int]:
    """Return the nearest clickable resident at a screen position."""
    best_id = None
    best_distance = float("inf")
    for pedestrian in pedestrians:
        if getattr(pedestrian, "state", "walking") in {"entering_building", "in_building"}:
            continue
        resident_id = getattr(pedestrian, "resident_id", None)
        if resident_id is None or residents.get(resident_id) is None:
            continue
        screen_x, screen_y = world_to_screen(
            pedestrian.x, pedestrian.y, camx, camy, px_per_m, screen_w, screen_h
        )
        distance = math.hypot(pos[0] - screen_x, pos[1] - screen_y)
        hit_radius = max(10.0, getattr(pedestrian, "radius_m", 0.45) * px_per_m)
        if distance <= hit_radius and distance < best_distance:
            best_id = resident_id
            best_distance = distance
    return best_id


def draw_resident_popup(
    screen,
    font,
    resident,
    residents=None,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    pedestrian=None,
) -> None:
    """Draw selected resident details above the gameplay view."""
    import pygame

    if resident is None:
        return
    popup_width, popup_height = 420, 268
    popup_rect = pygame.Rect(screen_w - popup_width - 24, 24, popup_width, popup_height)
    shade = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    shade.fill((12, 20, 30, 242))
    screen.blit(shade, popup_rect.topleft)
    pygame.draw.rect(screen, (105, 205, 255), popup_rect, width=2, border_radius=6)
    birth_date = getattr(resident, "birth_date", None)
    birth_text = birth_date.isoformat() if birth_date is not None else "-"
    vehicle_count = len(getattr(resident, "vehicle_ids", ()))
    residents = residents or {}

    def names_for(ids) -> str:
        names = [
            f"{person.first_name} {person.surname}".strip()
            for person_id in ids
            if (person := residents.get(person_id)) is not None
        ]
        return ", ".join(names) or "-"

    lines = (
        f"Resident #{resident.resident_id}",
        f"{resident.first_name} {resident.surname}".strip(),
        f"Sukupuoli: {resident.gender or '-'}",
        f"Syntynyt: {birth_text}",
        f"Tila: {getattr(resident, 'mode', '-')}",
        f"Promillet: {getattr(pedestrian, 'blood_alcohol_promille', 0.0):.2f} ‰",
        f"Ajoneuvoja: {vehicle_count}",
        f"Vanhemmat: {names_for(getattr(resident, 'parent_ids', ())) }",
        f"Lapset: {names_for(getattr(resident, 'child_ids', ())) }",
    )
    for index, text in enumerate(lines):
        color = (245, 250, 255) if index == 0 else (205, 220, 232)
        text_surface = font.render(text, True, color)
        screen.blit(text_surface, (popup_rect.x + 16, popup_rect.y + 14 + index * 26))


def draw_npc_popup(screen, font, npc, residents, screen_w: int = SCREEN_W) -> None:
    """Draw vehicle details and the residents currently associated with it."""
    import pygame

    if npc is None:
        return
    popup_width, popup_height = 420, 210
    popup_rect = pygame.Rect(screen_w - popup_width - 24, 24, popup_width, popup_height)
    shade = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    shade.fill((12, 20, 30, 242))
    screen.blit(shade, popup_rect.topleft)
    pygame.draw.rect(screen, (255, 190, 80), popup_rect, width=2, border_radius=6)

    occupant_ids = set()
    for attribute in ("occupant_ids", "passenger_ids"):
        occupant_ids.update(getattr(npc, attribute, ()) or ())
    if getattr(npc, "current_driver_id", None) is not None:
        occupant_ids.add(npc.current_driver_id)
    occupants = [
        f"{person.first_name} {person.surname}".strip()
        for resident_id in occupant_ids
        if (person := residents.get(resident_id)) is not None
    ]
    owner = residents.get(getattr(npc, "owner_id", None)) if residents is not None else None
    owner_name = f"{owner.first_name} {owner.surname}".strip() if owner is not None else "-"
    vehicle_name = getattr(npc, "vehicle_type", "car")
    speed_kmh = abs(getattr(npc, "speed", 0.0)) * 3.6
    lines = (
        "NPC-ajoneuvo",
        f"Tyyppi: {vehicle_name}",
        f"Tila: {getattr(npc, 'state', '-')}",
        f"Nopeus: {speed_kmh:.0f} km/h",
        f"Omistaja: {owner_name}",
        f"Henkilöt kyydissä: {', '.join(occupants) or '-'}",
    )
    for index, text in enumerate(lines):
        color = (245, 250, 255) if index == 0 else (205, 220, 232)
        screen.blit(font.render(text, True, color), (popup_rect.x + 16, popup_rect.y + 14 + index * 32))


def draw_pedestrian_reflectors(
    screen,
    pedestrians: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    light_vehicles: Optional[List] = None,
    street_light_positions: Optional[List[Tuple[float, float]]] = None,
) -> None:
    """Draw a bright nighttime reflector point on visible pedestrians."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)
    street_light_positions = (
        common._street_light_frame_world_positions
        if street_light_positions is None
        else street_light_positions
    )

    def is_lit(pedestrian) -> bool:
        for vehicle in light_vehicles or ():
            vehicle_x = getattr(vehicle, "x", None)
            vehicle_y = getattr(vehicle, "y", None)
            heading = getattr(vehicle, "heading", None)
            if vehicle_x is None or vehicle_y is None or heading is None:
                continue
            delta_x = pedestrian.x - vehicle_x
            delta_y = pedestrian.y - vehicle_y
            forward_distance = delta_x * math.cos(heading) + delta_y * math.sin(heading)
            if not 0.0 < forward_distance <= 15.0:
                continue
            lateral_distance = abs(-delta_x * math.sin(heading) + delta_y * math.cos(heading))
            if lateral_distance <= 1.5 + forward_distance * 0.35:
                return True
        return any(
            (pedestrian.x - light_x) ** 2 + (pedestrian.y - light_y) ** 2 <= STREET_LIGHT_REFLECTOR_RADIUS_M ** 2
            for light_x, light_y in street_light_positions
        )

    for ped in pedestrians:
        if not (vminx <= ped.x <= vmaxx and vminy <= ped.y <= vmaxy):
            continue
        if is_lit(ped):
            continue
        cx, cy = world_to_screen(ped.x, ped.y, camx, camy, px_per_m, screen_w, screen_h)
        pygame.draw.circle(screen, (255, 255, 245), (int(cx), int(cy)), max(1, int(px_per_m * 0.35)))
