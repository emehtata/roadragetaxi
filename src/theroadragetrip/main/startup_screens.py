import argparse
import cProfile
import concurrent.futures
import json
import logging
import math
import os
import random
import sys
import threading
import time
from dataclasses import asdict
from typing import Optional, Tuple

import pygame

from ..geo import clamp, dist_point_to_segment, meters_to_latlon
from ..audio import AudioManager
from ..config import (
    CONFIG_PATH,
    city_suggestions,
    cities_from_config,
    default_city_configuration,
    get_optional_int,
    get_overpass_endpoints,
    load_city_catalog,
    load_config,
    replace_city_in_config,
    save_config,
)
from ..career import (
    CAREER_SCORE_LIMIT,
    career_path,
    gig_odometer_path,
    load_career,
    load_career_distance,
    load_gig_odometer,
    save_career,
    save_gig_odometer,
)
from ..localization import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, normalize_language, tr
from ..osm import (
    BBOX_PRESETS,
    DEFAULT_BBOX,
    DEFAULT_OVERPASS_ENDPOINTS,
    DEFAULT_ROAD_HALF_WIDTH_M,
    HIGHWAY_HALF_WIDTH,
    AutoFetchManager,
    Building,
    BusStop,
    Place,
    Scenery,
    TaxiStop,
    TrafficLight,
    Water,
    Way,
    build_ways,
    clear_osm_cache,
    configure_user_agent,
    fetch_osm_ways,
    has_outdated_osm_cache,
    load_local_sample,
    load_osm_cache,
    remove_trees_under_roads,
    save_osm_cache,
)
from ..physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    MAX_SPEED,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    Car,
    SpatialWayGrid,
    get_current_road_at_car,
    is_car_colliding_with_bridge_edge,
    is_car_fully_in_water,
    is_on_road,
    is_point_on_parking_space,
    reset_trip,
    respawn_car,
    pull_car_inside_bridge_edge,
    update_car_physics,
)
from .menu_input import (
    _city_editor_item_at,
    _city_editor_suggestion_at,
    _menu_item_at_y,
)
from ..render import (
    FPS,
    PX_PER_M,
    SCREEN_H,
    SCREEN_W,
    draw_buildings,
    draw_bus_stops,
    draw_car,
    draw_city_selection_menu,
    draw_game_start_hint,
    draw_game_start_overlay,
    draw_city_editor,
    draw_city_summary,
    draw_mode_selection_menu,
    draw_compass,
    draw_crossings,
    draw_day_night_overlay,
    draw_grass_texture,
    draw_headlight_beams,
    draw_hud,
    draw_frame_profiler,
    begin_static_cache_frame,
    invalidate_static_caches,
    default_hud_layout,
    draw_tutorial_screen,
    draw_labels,
    draw_loading_screen,
    draw_navigation_route,
    draw_logical_intersections,
    draw_pause_menu,
    draw_parking_spaces,
    draw_settings_menu,
    draw_pedestrians,
    draw_pedestrian_reflectors,
    draw_resident_popup,
    resident_at_screen_position,
    draw_phone_offers,
    draw_scenery,
    draw_street_lights,
    draw_taxi_smoke,
    draw_passenger_nausea_bubble,
    draw_taxi_exhaust,
    draw_speed_cameras,
    draw_taxi_stops,
    draw_taxi_target,
    draw_tire_tracks,
    draw_vehicle_lights,
    draw_vomit_puddles,
    draw_traffic_lights,
    draw_waters,
    draw_ways,
    draw_roadworks,
    get_viewport_bounds,
    minimum_px_per_m_for_viewport_width,
    solar_altitude_and_events,
    world_to_screen,
)


logger = logging.getLogger(__name__)


def edit_city_list(screen, font, clock, config, cities_list: list[str], selected_idx: int, language: str) -> tuple[list[str], int]:
    catalog = load_city_catalog()
    editor_idx = selected_idx
    query = ""
    suggestion_idx = 0
    editing = True
    pygame.key.start_text_input()
    try:
        while editing:
            clock.tick(30)
            suggestions = city_suggestions(query, catalog=catalog)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    city_idx = _city_editor_item_at(ev.pos, len(cities_list), SCREEN_W)
                    if city_idx is not None:
                        editor_idx = city_idx
                        query = ""
                        suggestion_idx = 0
                        continue
                    picked_idx = _city_editor_suggestion_at(ev.pos, len(suggestions), SCREEN_W, SCREEN_H)
                    if picked_idx is not None:
                        selected_name = suggestions[picked_idx]
                        latitude, longitude = catalog[selected_name]
                        replace_city_in_config(config, editor_idx, selected_name, latitude, longitude)
                        save_config(config)
                        cities_list = list(cities_from_config(config)[0])
                        editing = False
                        continue
                if ev.type != pygame.KEYDOWN:
                    continue
                if ev.key == pygame.K_ESCAPE:
                    editing = False
                elif ev.key == pygame.K_BACKSPACE:
                    query = query[:-1]
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and suggestions:
                    selected_name = suggestions[suggestion_idx]
                    latitude, longitude = catalog[selected_name]
                    replace_city_in_config(config, editor_idx, selected_name, latitude, longitude)
                    save_config(config)
                    cities_list = list(cities_from_config(config)[0])
                    editing = False
                elif ev.key == pygame.K_UP and suggestions:
                    suggestion_idx = (suggestion_idx - 1) % len(suggestions)
                elif ev.key == pygame.K_DOWN and suggestions:
                    suggestion_idx = (suggestion_idx + 1) % len(suggestions)
                elif ev.unicode and ev.unicode.isprintable():
                    query += ev.unicode
                    suggestion_idx = 0
            draw_city_editor(
                screen, font, cities_list, editor_idx, query, suggestions, suggestion_idx,
                SCREEN_W, SCREEN_H, language,
            )
            pygame.display.flip()
    finally:
        pygame.key.stop_text_input()
    return cities_list, min(editor_idx, max(0, len(cities_list) - 1))


def choose_language(screen, font, clock, current_language: str = "fi") -> str:
    """Show the first-run language chooser."""
    import pygame

    selected = SUPPORTED_LANGUAGES.index(normalize_language(current_language))
    while True:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.MOUSEMOTION:
                hovered = _menu_item_at_y(event.pos[1], 280, 24, 31, len(SUPPORTED_LANGUAGES))
                if hovered is not None:
                    selected = hovered
                continue
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                hovered = _menu_item_at_y(event.pos[1], 280, 24, 31, len(SUPPORTED_LANGUAGES))
                if hovered is not None:
                    return SUPPORTED_LANGUAGES[hovered]
                continue
            if event.type != pygame.KEYDOWN:
                continue
            if event.key in (pygame.K_LEFT, pygame.K_UP):
                selected = (selected - 1) % len(SUPPORTED_LANGUAGES)
            elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                selected = (selected + 1) % len(SUPPORTED_LANGUAGES)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                return SUPPORTED_LANGUAGES[selected]
            elif pygame.K_1 <= event.key <= pygame.K_9:
                index = event.key - pygame.K_1
                if index < len(SUPPORTED_LANGUAGES):
                    return SUPPORTED_LANGUAGES[index]

        language = SUPPORTED_LANGUAGES[selected]
        screen.fill((18, 24, 32))
        title = font.render(tr(language, "select_language"), True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(screen.get_width() // 2, 180)))
        for index, code in enumerate(SUPPORTED_LANGUAGES):
            color = (255, 215, 95) if index == selected else (210, 220, 230)
            label = font.render(f"{index + 1}. {LANGUAGE_NAMES[code]}", True, color)
            screen.blit(label, label.get_rect(center=(screen.get_width() // 2, 280 + index * 55)))
        hint = pygame.font.SysFont(None, 18).render(tr(language, "language_hint"), True, (150, 175, 195))
        screen.blit(hint, hint.get_rect(center=(screen.get_width() // 2, screen.get_height() - 80)))
        pygame.display.flip()


def confirm_outdated_cache(screen, font, clock, language: str) -> bool:
    """Ask before removing cache data created by an older release."""
    button_font = pygame.font.SysFont(None, 22)
    message_font = pygame.font.SysFont(None, 24)
    button_width, button_height = 130, 42
    selected = 0  # 0 = OK, 1 = Cancel - matches the other menus' selected-item highlight
    while True:
        clock.tick(30)
        screen_w, screen_h = screen.get_size()
        ok_rect = pygame.Rect(screen_w // 2 - button_width - 10, screen_h // 2 + 55, button_width, button_height)
        cancel_rect = pygame.Rect(screen_w // 2 + 10, screen_h // 2 + 55, button_width, button_height)

        def activate(index: int) -> bool:
            if index == 0:
                return True
            pygame.quit()
            sys.exit(0)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.MOUSEMOTION:
                if ok_rect.collidepoint(event.pos):
                    selected = 0
                elif cancel_rect.collidepoint(event.pos):
                    selected = 1
                continue
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                    selected = 1 - selected
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    return activate(selected)
                elif event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit(0)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if ok_rect.collidepoint(event.pos):
                    return activate(0)
                if cancel_rect.collidepoint(event.pos):
                    return activate(1)

        screen.fill((18, 24, 32))
        title = font.render(tr(language, "outdated_cache_title"), True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(screen_w // 2, screen_h // 2 - 80)))
        message = message_font.render(tr(language, "outdated_cache_message"), True, (210, 220, 230))
        screen.blit(message, message.get_rect(center=(screen_w // 2, screen_h // 2 - 25)))
        for index, (rect, key, color) in enumerate((
            (ok_rect, "ok", (55, 135, 85)),
            (cancel_rect, "cancel", (125, 65, 65)),
        )):
            pygame.draw.rect(screen, color, rect, border_radius=4)
            if index == selected:
                # Same selected-item accent color as the mode/pause menus.
                pygame.draw.rect(screen, (255, 215, 95), rect, width=3, border_radius=4)
            label = button_font.render(tr(language, key), True, (255, 255, 255))
            screen.blit(label, label.get_rect(center=rect.center))
        pygame.display.flip()
