import argparse
import cProfile
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

from .geo import clamp, dist_point_to_segment, meters_to_latlon
from .audio import AudioManager
from .config import (
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
from .career import (
    CAREER_SCORE_LIMIT,
    career_path,
    gig_odometer_path,
    load_career,
    load_career_distance,
    load_gig_odometer,
    save_career,
    save_gig_odometer,
)
from .localization import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, normalize_language, tr
from .osm import (
    BBOX_PRESETS,
    CITY_CENTERS,
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
    save_osm_cache,
)
from .physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    MAX_SPEED,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    Car,
    SpatialWayGrid,
    get_current_road_at_car,
    is_car_fully_in_water,
    is_on_road,
    is_point_on_parking_space,
    reset_trip,
    respawn_car,
    update_car_physics,
)
from .render import (
    FPS,
    PX_PER_M,
    SCREEN_H,
    SCREEN_W,
    draw_buildings,
    draw_bus_stops,
    draw_car,
    draw_cyclists,
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
    default_hud_layout,
    draw_tutorial_screen,
    draw_labels,
    draw_loading_screen,
    draw_navigation_route,
    draw_npc_cars,
    draw_npc_popup,
    draw_logical_intersections,
    draw_npc_spatial_grid,
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


CITY_MENU_KEYS = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _city_menu_index(key: int, city_count: int) -> Optional[int]:
    """Return the city index for a menu shortcut key."""
    index = next(
        (index for index, shortcut in enumerate(CITY_MENU_KEYS)
         if key in (getattr(pygame, f"K_{shortcut.lower()}"),
                    getattr(pygame, f"K_KP{shortcut}") if shortcut.isdigit() else -1)),
        None,
    )
    if index is None:
        return None
    return index if index < city_count else None
from .pedestrian import CyclistManager, Pedestrian, PedestrianManager, PlayerPedestrian
from .residents import ResidentManager
from .police import PoliceManager, place_speed_cameras
from .roadworks import create_roadworks
from .taxi import TaxiManager, TaxiState
from .traffic import MAX_TRAFFIC_COUNT, TrafficManager, recommended_traffic_count, traffic_count_for_zoom
from .world_cache import WorldCacheManager, clear_world_cache
from .performance import FrameProfiler

# Maintain BBOX constant for backward compatibility
BBOX = DEFAULT_BBOX

logger = logging.getLogger(__name__)
RAGE_SHOUTS = ("PRKL!", "STNA!", "VTTU!", "HLVT!", "KRPÄ!", "KSPÄ!", "PSKA!")
RAGE_DISTANCE_TO_FULL_M = 400.0
RAGE_SHOUT_COST = 0.25


def _screenshot_directory() -> str:
    if sys.platform.startswith("win"):
        home_dir = os.getenv("USERPROFILE") or os.path.expanduser("~")
        return os.path.join(home_dir, "Pictures", "TheRoadRageTrip")
    return os.path.abspath("screenshots")


def _respawn_allowed(on_foot: bool) -> bool:
    """Only allow taxi respawn while the driver is in the taxi."""
    return not on_foot


def _write_debug_snapshot(
    path: str,
    car: Car,
    taxi_mgr,
    auto_fetch_manager,
    args,
    bbox,
    viewport_bounds,
    camx: float,
    camy: float,
    px_per_m: float,
    current_way,
    ways,
    waters,
    buildings,
    sceneries,
    places,
    taxi_stops,
    traffic_lights,
    crossings,
    elements_count: int,
    traffic_mgr,
    pedestrian_mgr,
    cyclist_mgr,
    spatial_grid,
    map_sync_stage: int,
    chosen_city: str,
    camera_city_name,
    game_mode: str,
    on_foot: bool,
) -> None:
    minx, miny, maxx, maxy = auto_fetch_manager.get_bounds()
    now = time.time()
    taxi_scalars = {
        key: value
        for key, value in vars(taxi_mgr).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    passenger = taxi_mgr.current_passenger
    data = {
        "timestamp_ns": time.time_ns(),
        "car": asdict(car),
        "taxi": {
            "state": taxi_mgr.state,
            "scalar_properties": taxi_scalars,
            "current_passenger": asdict(passenger) if passenger is not None else None,
            "offer_count": len(taxi_mgr.offers),
            "tree_effect_count": len(taxi_mgr.tree_effects),
            "fallen_tree_count": len(taxi_mgr.fallen_trees),
            "vomit_puddle_count": len(taxi_mgr.vomit_puddles),
        },
        "world": {
            "city": chosen_city,
            "camera_city": camera_city_name,
            "game_mode": game_mode,
            "initial_bbox": list(bbox),
            "current_bounds": list(auto_fetch_manager.get_bounds()),
            "viewport_bounds": list(viewport_bounds),
            "camera": {"x": camx, "y": camy, "px_per_m": px_per_m},
            "feature_counts": {
                "elements_loaded": elements_count,
                "ways": len(ways),
                "waters": len(waters),
                "buildings": len(buildings),
                "sceneries": len(sceneries),
                "places": len(places),
                "taxi_stops": len(taxi_stops),
                "traffic_lights": len(traffic_lights),
                "crossings": len(crossings),
                "traffic_npcs": len(traffic_mgr.npcs),
                "pedestrians": len(pedestrian_mgr.pedestrians),
                "cyclists": len(cyclist_mgr.cyclists),
            },
            "current_way": {
                "name": getattr(current_way, "name", None),
                "highway": getattr(current_way, "highway", None),
                "layer": getattr(current_way, "layer", None),
                "speed_limit_kmh": getattr(current_way, "speed_limit_kmh", None),
            } if current_way is not None else None,
            "spatial_grid": {"indexed_way_count": spatial_grid.indexed_way_count},
            "map_sync_stage": map_sync_stage,
            "on_foot": on_foot,
        },
        "auto_fetch": {
            "configured_enabled": bool(args.auto_fetch),
            "call_enabled": True,
            "margin_m": args.fetch_margin,
            "tile_size_m": args.fetch_tile_size,
            "build_in_process": bool(args.build_in_process),
            "manager_enabled_state": not auto_fetch_manager.get_fetching(),
            "is_fetching": auto_fetch_manager.get_fetching(),
            "progress": auto_fetch_manager.get_progress(),
            "last_trigger_reason": auto_fetch_manager.get_trigger_reason(),
            "last_fetch_time": auto_fetch_manager.last_fetch_time,
            "seconds_since_last_fetch": (
                now - auto_fetch_manager.last_fetch_time
                if auto_fetch_manager.last_fetch_time
                else None
            ),
            "cooldown_s": auto_fetch_manager.cooldown_s,
            "dead_end_count": len(auto_fetch_manager.dead_ends),
            "dead_ends": auto_fetch_manager.dead_ends,
            "known_dead_end": {
                direction: auto_fetch_manager.is_known_dead_end(car.x, car.y, direction)
                for direction in ("west", "east", "south", "north")
            },
            "distance_to_edges_m": {
                "west": car.x - minx,
                "east": maxx - car.x,
                "south": car.y - miny,
                "north": maxy - car.y,
            },
            "within_margin": {
                "west": car.x < minx + args.fetch_margin,
                "east": car.x > maxx - args.fetch_margin,
                "south": car.y < miny + args.fetch_margin,
                "north": car.y > maxy - args.fetch_margin,
            },
        },
    }
    with open(path, "w", encoding="utf-8") as debug_file:
        json.dump(data, debug_file, ensure_ascii=False, indent=2, default=str)


def parse_args(config=None, city_names=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="The Road Rage Trip (OSM PoC)")
    game = config["game"] if config else {}
    map_config = config["map"] if config else {}
    traffic_config = config["traffic"] if config else {}
    p.add_argument("--bbox", type=str, default=game.get("bbox") or None, help="south,west,north,east (lat/lon)")
    p.add_argument(
        "--preset",
        type=str,
        choices=city_names or list(BBOX_PRESETS.keys()),
        default=game.get("preset") or None,
        help="Named bounding box preset (e.g., oulu, helsinki, tampere, espoo)",
    )
    p.add_argument("--no-menu", action="store_true", default=game.getboolean("no_menu", fallback=False), help="Skip interactive city menu")
    p.add_argument("--force-refresh", action="store_true", default=game.getboolean("force_refresh", fallback=False), help="Force refresh from Overpass (ignore cache)")
    p.add_argument("--use-sample", action="store_true", default=game.getboolean("use_sample", fallback=False), help="Use bundled sample OSM data and skip Overpass")
    p.add_argument("--px-per-m", type=float, default=game.getfloat("px_per_m", fallback=9.0), help="Initial pixels per meter (zoom)")
    p.add_argument("--log-level", type=str, default=game.get("log_level", "INFO"), help="Logging level (DEBUG/INFO/WARNING)")
    p.add_argument("--no-cache", action="store_true", default=game.getboolean("no_cache", fallback=False), help="Disable cache usage (treated like force-refresh)")

    # Auto-fetching nearby map tiles when the car approaches the bbox edge
    p.add_argument("--no-auto-fetch", dest="auto_fetch", action="store_false", default=map_config.getboolean("auto_fetch", fallback=True), help="Disable on-demand map expansion")
    p.add_argument(
        "--fetch-margin",
        type=float,
        default=map_config.getfloat("fetch_margin", fallback=350.0),
        help="Distance in meters from bbox edge that triggers auto-fetch",
    )
    p.add_argument("--fetch-tile-size", type=float, default=map_config.getfloat("fetch_tile_size", fallback=2500.0), help="Meters to expand when auto-fetching")
    p.add_argument(
        "--build-in-process",
        action="store_true",
        default=map_config.getboolean("build_in_process", fallback=True),
        help="Build auto-fetched map data outside the gameplay process",
    )
    p.add_argument(
        "--traffic-count",
        type=int,
        default=get_optional_int(config, "traffic", "traffic_count") if config else None,
        help="Target number of NPC cars (default: scales with available streets, capped at 50)",
    )
    p.add_argument(
        "--parking-density",
        type=float,
        default=traffic_config.getfloat("parking_density", fallback=0.5),
        help="Fraction of regular NPC cars spawned in existing OSM parking spaces",
    )
    p.add_argument("--pedestrian-count", type=int, default=traffic_config.getint("pedestrian_count", fallback=60), help="Target number of pedestrians")
    p.add_argument("--cyclist-count", type=int, default=traffic_config.getint("cyclist_count", fallback=8), help="Target number of cyclists")

    return p.parse_args()


def configure_logging(level: Optional[str] = None, file_logging: bool = False) -> None:
    lvl = os.getenv("LOG_LEVEL", level or "INFO").upper()
    log_level = getattr(logging, lvl, logging.INFO)
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    handlers[0].setFormatter(logging.Formatter(log_format))
    if file_logging:
        file_handler = logging.FileHandler("roadragetrip.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    logging.basicConfig(level=log_level, handlers=handlers, force=True)


def _menu_item_at_y(pos_y: int, start_y: int, item_h: int, gap_y: int, count: int) -> Optional[int]:
    for index in range(count):
        item_y = start_y + index * (item_h + gap_y)
        if item_y <= pos_y <= item_y + item_h:
            return index
    return None


def _city_item_at(pos: Tuple[int, int], city_count: int, screen_w: int) -> Optional[int]:
    cols = 2
    rows = (city_count + cols - 1) // cols
    item_w, item_h = 320, 42
    gap_x, gap_y = 24, 10
    total_w = cols * item_w + (cols - 1) * gap_x
    start_x, start_y = (screen_w - total_w) // 2, 115
    x, y = pos
    col = (x - start_x) // (item_w + gap_x)
    row = (y - start_y) // (item_h + gap_y)
    if not (0 <= col < cols and 0 <= row < rows):
        return None
    item_x = start_x + col * (item_w + gap_x)
    item_y = start_y + row * (item_h + gap_y)
    if item_x <= x <= item_x + item_w and item_y <= y <= item_y + item_h:
        index = col * rows + row
        return index if index < city_count else None
    return None


def _city_horizontal_index(index: int, direction: int, city_count: int) -> int:
    rows = (city_count + 1) // 2
    return (index + direction * rows) % city_count


def _city_refresh_at(pos: Tuple[int, int], screen_w: int, screen_h: int, city_count: int) -> bool:
    cols = 2
    rows = (city_count + cols - 1) // cols
    item_h = 42
    gap_y = 10
    checkbox_rect = pygame.Rect(screen_w // 2 - 150, 115 + rows * (item_h + gap_y) + 12, 22, 22)
    return checkbox_rect.collidepoint(pos)


def _city_edit_at(pos: Tuple[int, int], screen_w: int, screen_h: int, city_count: int) -> bool:
    rows = (city_count + 1) // 2
    top = 115 + rows * 52 + 12 + 38
    return pygame.Rect(screen_w // 2 - 150, top, 300, 36).collidepoint(pos)


def _pause_item_at(pos: Tuple[int, int], option_count: int, screen_w: int, screen_h: int) -> Optional[int]:
    panel_w = min(420, screen_w - 40)
    panel_h = min(screen_h - 40, max(280, 110 + option_count * 56))
    panel_x, panel_y = (screen_w - panel_w) // 2, (screen_h - panel_h) // 2
    item_w, item_h = 340, 44
    item_x = panel_x + (panel_w - item_w) // 2
    if not (item_x <= pos[0] <= item_x + item_w):
        return None
    return _menu_item_at_y(pos[1], panel_y + 80, item_h, 12, option_count)


def _city_editor_suggestion_at(pos: Tuple[int, int], suggestion_count: int, screen_w: int, screen_h: int) -> Optional[int]:
    rows = 5
    input_y = 72 + rows * 46 + 20
    input_rect = (screen_w // 2 - 250, input_y, 500, 42)
    if not (input_rect[0] <= pos[0] <= input_rect[0] + input_rect[2] and input_rect[1] <= pos[1] <= input_rect[1] + input_rect[3] + 8):
        return None
    index = (pos[1] - input_rect[1] - input_rect[3] - 8) // 34
    return index if 0 <= index < suggestion_count else None


def _city_editor_item_at(pos: Tuple[int, int], city_count: int, screen_w: int) -> Optional[int]:
    cols = 2
    rows = (city_count + cols - 1) // cols
    item_w, item_h, gap_x, gap_y = 300, 38, 20, 8
    start_x, start_y = (screen_w - (2 * item_w + gap_x)) // 2, 72
    x, y = pos
    col = (x - start_x) // (item_w + gap_x)
    row = (y - start_y) // (item_h + gap_y)
    if not (0 <= col < cols and 0 <= row < rows):
        return None
    item_x = start_x + col * (item_w + gap_x)
    item_y = start_y + row * (item_h + gap_y)
    if item_x <= x <= item_x + item_w and item_y <= y <= item_y + item_h:
        index = col * rows + row
        return index if index < city_count else None
    return None


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
    while True:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    return True
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit(0)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                screen_w, screen_h = screen.get_size()
                ok_rect = pygame.Rect(screen_w // 2 - button_width - 10, screen_h // 2 + 55, button_width, button_height)
                cancel_rect = pygame.Rect(screen_w // 2 + 10, screen_h // 2 + 55, button_width, button_height)
                if ok_rect.collidepoint(event.pos):
                    return True
                if cancel_rect.collidepoint(event.pos):
                    pygame.quit()
                    sys.exit(0)

        screen_w, screen_h = screen.get_size()
        screen.fill((18, 24, 32))
        title = font.render(tr(language, "outdated_cache_title"), True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(screen_w // 2, screen_h // 2 - 80)))
        message = message_font.render(tr(language, "outdated_cache_message"), True, (210, 220, 230))
        screen.blit(message, message.get_rect(center=(screen_w // 2, screen_h // 2 - 25)))
        ok_rect = pygame.Rect(screen_w // 2 - button_width - 10, screen_h // 2 + 55, button_width, button_height)
        cancel_rect = pygame.Rect(screen_w // 2 + 10, screen_h // 2 + 55, button_width, button_height)
        for rect, key, color in (
            (ok_rect, "ok", (55, 135, 85)),
            (cancel_rect, "cancel", (125, 65, 65)),
        ):
            pygame.draw.rect(screen, color, rect, border_radius=4)
            label = button_font.render(tr(language, key), True, (255, 255, 255))
            screen.blit(label, label.get_rect(center=rect.center))
        pygame.display.flip()


def main() -> None:
    config = load_config()
    overpass_endpoints = get_overpass_endpoints(config)
    configure_user_agent(config.get("game", "user_agent_id"))
    city_centers, bbox_presets = cities_from_config(config)
    args = parse_args(config, city_names=list(bbox_presets))
    configure_logging(args.log_level, file_logging=config.getboolean("game", "file_logging", fallback=False))
    roadworks_enabled = config.getboolean("game", "roadworks_enabled", fallback=False)
    bus_stops_enabled = config.getboolean("game", "bus_stops", fallback=False)

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    try:
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "roadragetrip_icon.png")
        pygame.display.set_icon(pygame.image.load(icon_path).convert_alpha())
    except (OSError, pygame.error):
        logger.warning("Game icon could not be loaded")
    pygame.display.set_caption("The Road Rage Trip (OSM PoC)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)
    small_font = pygame.font.SysFont(None, 18)

    language = normalize_language(config.get("game", "language", fallback=""))
    if not config.get("game", "language", fallback="").strip():
        language = choose_language(screen, font, clock)
        config.set("game", "language", language)
        save_config(config)

    if has_outdated_osm_cache():
        confirm_outdated_cache(screen, font, clock, language)
        clear_osm_cache()

    audio = AudioManager(
        master_volume=config.getfloat("audio", "master_volume", fallback=1.0),
        music_volume=config.getfloat("audio", "music_volume", fallback=0.2),
        effects_volume=config.getfloat("audio", "effects_volume", fallback=1.0),
        comments_enabled=config.getboolean("audio", "comments_enabled", fallback=True),
        speech_min_interval=config.getfloat("speech", "min_interval", fallback=5.0),
        speech_max_interval=config.getfloat("speech", "max_interval", fallback=20.0),
    )

    # Outer game loop to support picking new starting city without restarting process
    app_running = True
    active_city_name = None
    game_mode = "gig_driver"
    career_file = career_path(CONFIG_PATH)
    gig_odometer_file = gig_odometer_path(CONFIG_PATH)
    career = None
    return_to_main_menu = False
    force_refresh = args.force_refresh

    while app_running:
        cities_list = list(city_centers.keys())
        selected_city_idx = 0
        city_summary = None

        # Show city selection menu if no explicit CLI override or when requested from pause menu
        if active_city_name is not None or (
            not args.bbox
            and not args.preset
            and not args.use_sample
            and not args.no_menu
            or return_to_main_menu
        ):
            return_to_main_menu = False
            if active_city_name is None:
                mode_selected = 0 if game_mode == "career" else 1
                choosing_mode = True
                while choosing_mode:
                    clock.tick(30)
                    for ev in pygame.event.get():
                        if ev.type == pygame.QUIT:
                            pygame.quit()
                            sys.exit(0)
                        if ev.type == pygame.MOUSEMOTION:
                            hovered = _menu_item_at_y(ev.pos[1], 270, 30, 30, 4)
                            if hovered is not None:
                                mode_selected = hovered
                            continue
                        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                            hovered = _menu_item_at_y(ev.pos[1], 270, 30, 30, 4)
                            if hovered is not None:
                                mode_selected = hovered
                                if mode_selected == 2:
                                    completed = bool(load_career(career_file, len(cities_list))["completed"])
                                    save_career(career_file, 0, completed=completed)
                                    mode_selected = 0
                                elif mode_selected == 3:
                                    clear_osm_cache()
                                    clear_world_cache()
                                    mode_selected = 0
                                else:
                                    choosing_mode = False
                            continue
                        if ev.type != pygame.KEYDOWN:
                            continue
                        if ev.key == pygame.K_ESCAPE:
                            pygame.quit()
                            sys.exit(0)
                        if ev.key in (pygame.K_UP, pygame.K_LEFT):
                            mode_selected = (mode_selected - 1) % 3
                        elif ev.key in (pygame.K_DOWN, pygame.K_RIGHT):
                            mode_selected = (mode_selected + 1) % 3
                        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                            if mode_selected == 2:
                                completed = bool(load_career(career_file, len(cities_list))["completed"])
                                save_career(career_file, 0, completed=completed)
                                mode_selected = 0
                            elif mode_selected == 3:
                                clear_osm_cache()
                                clear_world_cache()
                                mode_selected = 0
                            else:
                                choosing_mode = False
                        elif ev.key in (pygame.K_1, pygame.K_KP1):
                            mode_selected = 0
                            choosing_mode = False
                        elif ev.key in (pygame.K_2, pygame.K_KP2):
                            mode_selected = 1
                            choosing_mode = False
                        elif ev.key in (pygame.K_3, pygame.K_KP3):
                            completed = bool(load_career(career_file, len(cities_list))["completed"])
                            save_career(career_file, 0, completed=completed)
                            mode_selected = 0
                        elif ev.key in (pygame.K_4, pygame.K_KP4):
                            clear_osm_cache()
                            clear_world_cache()
                            mode_selected = 0
                    draw_mode_selection_menu(screen, font, mode_selected, SCREEN_W, SCREEN_H, language)
                    pygame.display.flip()
                game_mode = "career" if mode_selected == 0 else "gig_driver"

            career = load_career(career_file, len(cities_list)) if game_mode == "career" else None
            if career is not None and not career["completed"]:
                city_centers, bbox_presets = default_city_configuration()
                cities_list = list(city_centers)
                career = load_career(career_file, len(cities_list))
            if career is not None:
                selected_city_idx = len(cities_list) - 1 - int(career["city_index"])
            if active_city_name is not None and active_city_name in cities_list:
                selected_city_idx = cities_list.index(active_city_name)
            in_menu = game_mode != "career"
            intro_until = pygame.time.get_ticks() + 1000
            while in_menu:
                clock.tick(30)
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit(0)
                    elif ev.type == pygame.MOUSEMOTION:
                        hovered = _city_item_at(ev.pos, len(cities_list), SCREEN_W)
                        if hovered is not None:
                            selected_city_idx = hovered
                    elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                        if _city_refresh_at(ev.pos, SCREEN_W, SCREEN_H, len(cities_list)):
                            force_refresh = not force_refresh
                            continue
                        if _city_edit_at(ev.pos, SCREEN_W, SCREEN_H, len(cities_list)):
                            cities_list, selected_city_idx = edit_city_list(
                                screen, font, clock, config, cities_list,
                                selected_city_idx, language,
                            )
                            city_centers, bbox_presets = cities_from_config(config)
                            continue
                        hovered = _city_item_at(ev.pos, len(cities_list), SCREEN_W)
                        if hovered is not None:
                            selected_city_idx = hovered
                            in_menu = False
                    elif ev.type == pygame.KEYDOWN:
                        if ev.key == pygame.K_ESCAPE:
                            pygame.quit()
                            sys.exit(0)
                        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                            in_menu = False
                        elif ev.key == pygame.K_UP:
                            selected_city_idx = (selected_city_idx - 1) % len(cities_list)
                        elif ev.key == pygame.K_DOWN:
                            selected_city_idx = (selected_city_idx + 1) % len(cities_list)
                        elif ev.key == pygame.K_f:
                            force_refresh = not force_refresh
                        elif ev.key == pygame.K_e:
                            cities_list, selected_city_idx = edit_city_list(
                                screen, font, clock, config, cities_list,
                                selected_city_idx, language,
                            )
                            city_centers, bbox_presets = cities_from_config(config)
                        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                            direction = 1 if ev.key == pygame.K_RIGHT else -1
                            selected_city_idx = _city_horizontal_index(
                                selected_city_idx, direction, len(cities_list)
                            )
                        else:
                            idx = _city_menu_index(ev.key, len(cities_list))
                            if idx is not None:
                                selected_city_idx = idx
                                in_menu = False

                if pygame.time.get_ticks() < intro_until:
                    draw_loading_screen(screen, font, 1.0, "Ready", SCREEN_W, SCREEN_H, show_details=False)
                else:
                    draw_city_selection_menu(
                        screen, font, cities_list, selected_city_idx, SCREEN_W, SCREEN_H, language,
                        force_refresh=force_refresh,
                    )
                pygame.display.flip()

            chosen_city = cities_list[selected_city_idx]
            camera_city_name = chosen_city
            bbox = bbox_presets.get(chosen_city.lower(), DEFAULT_BBOX)
            logger.info("Selected starting city: %s (bbox: %s)", chosen_city, bbox)
        else:
            preset_key = args.preset.lower() if args.preset else "oulu"
            chosen_city = args.preset or preset_key
            camera_city_name = chosen_city
            bbox = bbox_presets.get(preset_key, DEFAULT_BBOX)
            if args.bbox:
                try:
                    parts = [float(p.strip()) for p in args.bbox.split(",")]
                    if len(parts) == 4:
                        bbox = (parts[0], parts[1], parts[2], parts[3])
                except Exception:
                    logger.warning("Invalid bbox provided, using default preset (%s)", preset_key)

        sun_latitude, sun_longitude = city_centers.get(
            chosen_city,
            ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0),
        )
        logger.info(
            "Solar model: date=2026-08-31 city=%s latitude=%.6f longitude=%.6f",
            chosen_city,
            sun_latitude,
            sun_longitude,
        )

        last_progress_draw = 0.0

        def on_load_progress(fraction: float, message: str) -> None:
            nonlocal last_progress_draw
            if threading.current_thread() is not threading.main_thread():
                return
            now = time.monotonic()
            if fraction < 1.0 and now - last_progress_draw < 0.1:
                return
            draw_loading_screen(screen, font, fraction, message)
            pygame.display.flip()
            last_progress_draw = now
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)

        on_load_progress(0.05, "Initializing scenery engine...")

        def on_build_progress(fraction: float, message: str) -> None:
            # Map construction is only part of startup; reserve final progress for manager setup.
            on_load_progress(min(0.9, fraction * 0.9), message)

        # Load map
        try:
            elements_count = 0
            world_cache = WorldCacheManager(
                cache_ttl=float(os.getenv("OSM_CACHE_TTL", 24 * 3600)),
                fetch_func=lambda fetch_bbox, **fetch_kwargs: fetch_osm_ways(
                    fetch_bbox, endpoints=overpass_endpoints, progress_callback=on_load_progress,
                    **fetch_kwargs
                ),
                build_func=lambda raw: build_ways(
                    raw, progress_callback=on_build_progress, include_bus_stops=bus_stops_enabled
                ),
            )
            area_id = world_cache.area_id(bbox)
            if args.use_sample:
                on_load_progress(0.2, "Loading bundled offline sample data...")
                elements = load_local_sample()
                if elements is None:
                    raise Exception("No local sample file found")
                logger.info("Using local sample (via --use-sample)")
                on_load_progress(0.5, f"Loaded {len(elements)} sample elements")
                elements_count = len(elements)
                res = build_ways(
                    elements, progress_callback=on_build_progress, include_bus_stops=bus_stops_enabled
                )
            else:
                res = world_cache.load_area(
                    area_id, bbox, force_refresh=force_refresh or args.no_cache,
                )
            crossings = getattr(res, "crossings", [])
            stop_signs = getattr(res, "stop_signs", [])
            yield_signs = getattr(res, "yield_signs", [])
            if len(res) == 8:
                ways, waters, buildings, sceneries, places, bounds, traffic_lights, crossings = res
            elif len(res) == 7:
                ways, waters, buildings, sceneries, places, bounds, traffic_lights = res
            else:
                ways, waters, buildings, sceneries, places, bounds = res[:6]
                traffic_lights = getattr(res, "traffic_lights", [])
                yield_signs = getattr(res, "yield_signs", [])
        except Exception as e:
            logger.error("Failed to load OSM data: %s", e)
            sys.exit(1)

        if not ways and not waters and not buildings and not sceneries and not places:
            logger.error("No map features found in bbox. Try a different bbox.")
            sys.exit(1)

        minx, miny, maxx, maxy = bounds
        taxi_stops = getattr(res, "taxi_stops", [])
        bus_stops = getattr(res, "bus_stops", [])
        parking_spaces = getattr(res, "parking_spaces", [])
        roadworks, roadwork_lights = create_roadworks(ways) if roadworks_enabled else ([], [])
        traffic_lights.extend(roadwork_lights)
        logger.info(
            "Created %d random roadworks (%d temporary lights), enabled=%s",
            len(roadworks),
            len(roadwork_lights),
            roadworks_enabled,
        )
        on_load_progress(0.92, "Preparing road index...")
        # Spatial index for fast O(1) road collision detection
        spatial_grid = SpatialWayGrid()
        spatial_grid.rebuild(ways)
        building_grid = SpatialWayGrid()
        building_grid.rebuild(buildings)
        scenery_grid = SpatialWayGrid()
        scenery_grid.rebuild(sceneries)
        water_grid = SpatialWayGrid()
        water_grid.rebuild(waters)
        crossing_grid = SpatialWayGrid()
        crossing_grid.rebuild(crossings)
        traffic_light_grid = SpatialWayGrid()
        traffic_light_grid.rebuild(traffic_lights)

        # Spawn car on a road near center (avoiding water)
        car = Car(x=(minx + maxx) / 2, y=(miny + maxy) / 2, heading=0.0, speed=0.0)
        if ways:
            respawn_car(car, ways, near_center=True, bounds=bounds, waters=waters, taxi_stops=taxi_stops)
        career_total_distance_m = None
        if career is not None:
            career_total_distance_m = load_career_distance(career_file)
            car.odometer_m = career_total_distance_m
        else:
            car.odometer_m = load_gig_odometer(gig_odometer_file)
            if car.odometer_m == 0.0:
                car.odometer_m = float(random.randint(100000, 600000))
                save_gig_odometer(gig_odometer_file, car.odometer_m)

        # Initialize Taxi Manager for game mode
        on_load_progress(0.94, "Preparing taxi missions...")
        residents = ResidentManager(city_name=chosen_city)
        residents.set_city_center_m((minx + maxx) / 2.0, (miny + maxy) / 2.0)
        city_center = city_centers.get(chosen_city)
        if city_center is not None:
            residents.set_city_center_latlon(*city_center)
        taxi_mgr = TaxiManager(
            ways,
            places=places,
            buildings=buildings,
            taxi_stops=taxi_stops,
            language=language,
            resident_manager=residents,
        )
        speed_cameras = place_speed_cameras(
            ways,
            bounds,
            camera_city_name,
            seed=random.randrange(2**32),
        )
        logger.info("Placed %d hidden speed cameras", len(speed_cameras))
        # Initialize autonomous Traffic Manager for NPC cars
        on_load_progress(0.96, "Preparing traffic...")
        traffic_count = args.traffic_count
        if traffic_count is None:
            traffic_count = recommended_traffic_count(ways)
        traffic_count = max(0, min(MAX_TRAFFIC_COUNT, traffic_count))
        base_traffic_count = traffic_count
        enable_two_wheelers = config["experimental"].getboolean("enable_two_wheelers", fallback=False)
        logger.info("Target NPC traffic: %d cars for %d road ways", traffic_count, len(ways))
        traffic_mgr = TrafficManager(
            ways,
            target_count=traffic_count,
            traffic_lights=traffic_lights,
            stop_signs=stop_signs,
            yield_signs=yield_signs,
            crossings=crossings,
            parking_spaces=parking_spaces,
            parking_density=args.parking_density,
            roadworks=roadworks,
            enable_two_wheelers=enable_two_wheelers,
            residents=residents,
            buildings=buildings,
            sceneries=sceneries,
        )
        police_mgr = PoliceManager(
            traffic_mgr, car.x, car.y, buildings=buildings, building_grid=building_grid, count=0
        )

        # Initialize autonomous Pedestrian Manager
        on_load_progress(0.98, "Preparing pedestrians...")
        pedestrian_mgr = PedestrianManager(
            ways,
            target_count=args.pedestrian_count,
            traffic_lights=traffic_lights,
            crossings=crossings,
            logical_intersections=traffic_mgr.logical_intersections,
            traffic_vehicles=traffic_mgr.npcs,
            traffic_manager=traffic_mgr,
            residents=traffic_mgr.residents,
            venue_buildings=buildings,
        )
        # Cyclists are disabled until their traffic interactions are complete.
        cyclist_mgr = CyclistManager(ways, target_count=0, traffic_lights=traffic_lights)
        player_pedestrian = PlayerPedestrian(
            car.x - math.sin(car.heading) * getattr(car, "width_m", 1.8) * 0.85
            + math.cos(car.heading) * getattr(car, "length_m", 4.0) * 0.2,
            car.y + math.cos(car.heading) * getattr(car, "width_m", 1.8) * 0.85
            + math.sin(car.heading) * getattr(car, "length_m", 4.0) * 0.2,
            heading=car.heading,
        )
        player_pedestrian.is_player = True
        base_pedestrian_count = pedestrian_mgr.target_count
        base_cyclist_count = 0

        # Prepare transformer for meters->latlon display
        try:
            from pyproj import Transformer

            transformer_to_ll = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
        except Exception:
            transformer_to_ll = None
            logger.debug("pyproj not available; lat/lon display disabled")

        # Auto fetch manager (background)
        on_load_progress(0.99, "Starting game...")
        auto_fetch_manager = AutoFetchManager(
            ways,
            bounds,
            transformer_to_ll,
            waters=waters,
            buildings=buildings,
            sceneries=sceneries,
            places=places,
            traffic_lights=traffic_lights,
            stop_signs=stop_signs,
            crossings=crossings,
            parking_spaces=parking_spaces,
            logical_intersections=getattr(res, "logical_intersections", []),
            yield_signs=yield_signs,
            fetch_func=lambda fetch_bbox: fetch_osm_ways(fetch_bbox, endpoints=overpass_endpoints),
            build_func=build_ways,
            build_in_process=args.build_in_process,
            world_cache_manager=world_cache,
        )
        on_load_progress(1.0, "Ready")
        logger.info("Entering gameplay loop")

        label_mode = 0
        show_debug_hud = False
        speed_limiter_enabled = True
        red_light_assist_enabled = False
        show_compass = False
        show_navigation = False
        navigation_route = None
        navigation_target_key = None
        navigation_route_dirty = False
        phone_open = False
        rage_shout_timer = 0.0
        rage_shout_text = RAGE_SHOUTS[0]
        rage_power = 0.0
        hud_layout = default_hud_layout(SCREEN_W, SCREEN_H)
        hud_rects = {}
        hud_dragging = None
        hud_drag_offset = (0, 0)
        selected_resident_id = None
        selected_npc = None
        running = True
        current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True)
        min_px_per_m = minimum_px_per_m_for_viewport_width(screen_w=SCREEN_W, margin_m=30.0)
        zoom_target = max(
            min_px_per_m,
            args.px_per_m if args.px_per_m is not None else 9.0,
        )
        px_per_m = max(min_px_per_m, zoom_target * 0.75)
        zoom_elapsed = 0.0
        zoom_duration = 3.0
        game_time_seconds = 18.0 * 60.0 * 60.0
        solar_time_bucket = None
        camx, camy = car.x, car.y
        first_gameplay_frame = True
        awaiting_start = True
        start_warmup_remaining = 1.5
        start_hint_remaining = 0.0
        slow_check_elapsed = 0.0
        taxi_waiter_elapsed = 0.0
        last_zoom_scale = None
        tire_tracks = []
        last_track_position = None
        track_sequence = 0
        last_track_surface = None
        map_sync_stage = 0
        water_elapsed = 0.0
        visible_road_count_elapsed = 0.0
        visible_road_count = 0
        on_foot = True
        saved_gig_fares = taxi_mgr.completed_fares
        render_profile_last_log = time.perf_counter()
        render_profile_times = {}
        runtime_profiler = cProfile.Profile()
        runtime_profile_active = False
        frame_profiler = FrameProfiler()
        clock.tick()  # Reset clock timer to avoid large dt on first frame

        while running:
            dt = min(clock.tick_busy_loop(FPS) / 1000.0, 0.1)  # Precise pacing; clamp lag spikes for physics safety
            frame_profiler.begin_frame()
            if awaiting_start:
                start_warmup_remaining = max(0.0, start_warmup_remaining - dt)
            elif start_hint_remaining > 0.0:
                start_hint_remaining = max(0.0, start_hint_remaining - dt)
            time_scale = 1.0 if taxi_mgr.current_passenger else 60.0
            game_time_seconds = (game_time_seconds + dt * time_scale) % (24.0 * 60.0 * 60.0)
            current_solar_bucket = int(game_time_seconds // (15.0 * 60.0))
            if current_solar_bucket != solar_time_bucket:
                car_latitude, car_longitude = meters_to_latlon(car.x, car.y, transformer_to_ll)
                if car_latitude is not None and car_longitude is not None:
                    sun_latitude, sun_longitude = car_latitude, car_longitude
                solar_time_bucket = current_solar_bucket
                logger.debug(
                    "Solar position updated: time=%02d:%02d latitude=%.6f longitude=%.6f",
                    int(game_time_seconds // 3600.0),
                    int((game_time_seconds % 3600.0) // 60.0),
                    sun_latitude,
                    sun_longitude,
                )
            if first_gameplay_frame:
                logger.info("Gameplay frame: start")

            frame_events = pygame.event.get()
            frame_profiler.set_metric("events", len(frame_events))
            for event in frame_events:
                if event.type == pygame.QUIT:
                    running = False
                    app_running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    clicked_hud = False
                    for element_name in ("rage", "speedometer", "meters"):
                        element_rect = hud_rects.get(element_name)
                        if element_rect and element_rect.collidepoint(event.pos):
                            element_x, element_y = hud_layout[element_name]
                            hud_dragging = element_name
                            hud_drag_offset = (event.pos[0] - element_x, event.pos[1] - element_y)
                            clicked_hud = True
                            break
                    if not clicked_hud:
                        selected_npc = None
                        for npc in traffic_mgr.npcs:
                            if getattr(npc, "is_police", False) or getattr(npc, "is_on_foot", False):
                                continue
                            npc_x, npc_y = world_to_screen(
                                npc.x, npc.y, camx, camy, px_per_m, SCREEN_W, SCREEN_H
                            )
                            hit_radius = max(
                                12.0,
                                math.hypot(
                                    getattr(npc, "length_m", 4.0),
                                    getattr(npc, "width_m", 1.8),
                                ) * px_per_m * 0.5,
                            )
                            if math.hypot(event.pos[0] - npc_x, event.pos[1] - npc_y) <= hit_radius:
                                selected_npc = npc
                                selected_resident_id = None
                                break
                        if selected_npc is not None:
                            continue
                        visible_pedestrians = pedestrian_mgr.pedestrians + [
                            npc for npc in traffic_mgr.npcs if getattr(npc, "is_on_foot", False)
                        ] + ([player_pedestrian] if on_foot else [])
                        selected_resident_id = resident_at_screen_position(
                            visible_pedestrians,
                            traffic_mgr.residents,
                            event.pos,
                            camx,
                            camy,
                            px_per_m=px_per_m,
                            screen_w=SCREEN_W,
                            screen_h=SCREEN_H,
                        )
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    hud_dragging = None
                elif event.type == pygame.MOUSEMOTION and hud_dragging:
                    hud_layout[hud_dragging] = (
                        event.pos[0] - hud_drag_offset[0],
                        event.pos[1] - hud_drag_offset[1],
                    )
                elif event.type == pygame.KEYDOWN:
                    if awaiting_start:
                        if start_warmup_remaining > 0.0:
                            continue
                        awaiting_start = False
                        start_hint_remaining = 8.0
                        continue
                    if event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                        time_delta = 60.0 * 60.0 if event.key == pygame.K_PAGEUP else -60.0 * 60.0
                        game_time_seconds = (game_time_seconds + time_delta) % (24.0 * 60.0 * 60.0)
                        logger.debug(
                            "Game time adjusted: delta=%+.1fh time=%02d:%02d",
                            time_delta / 3600.0,
                            int(game_time_seconds // 3600.0),
                            int((game_time_seconds % 3600.0) // 60.0),
                        )
                    elif event.key == pygame.K_F12:
                        screenshot_dir = _screenshot_directory()
                        os.makedirs(screenshot_dir, exist_ok=True)
                        screenshot_id = time.time_ns()
                        screenshot_path = os.path.join(screenshot_dir, f"screenshot_{screenshot_id}.png")
                        pygame.image.save(screen, screenshot_path)
                        debug_path = os.path.join(screenshot_dir, f"screenshot_{screenshot_id}.json")
                        screenshot_viewport = get_viewport_bounds(
                            camx, camy, px_per_m=px_per_m, margin_m=30.0
                        )
                        _write_debug_snapshot(
                            debug_path, car, taxi_mgr, auto_fetch_manager, args, bbox,
                            screenshot_viewport, camx, camy, px_per_m, current_way, ways,
                            waters, buildings, sceneries, places, taxi_stops,
                            traffic_lights, crossings, elements_count, traffic_mgr,
                            pedestrian_mgr, cyclist_mgr, spatial_grid, map_sync_stage,
                            chosen_city, camera_city_name, game_mode, on_foot,
                        )
                        logger.info("Screenshot saved to %s", screenshot_path)
                        logger.info("Runtime debug snapshot saved to %s", debug_path)
                    elif event.key == pygame.K_F9:
                        if runtime_profile_active:
                            runtime_profiler.disable()
                            runtime_profile_active = False
                            logger.info("Runtime profiler stopped; press F10 to save profile")
                        else:
                            runtime_profiler.enable()
                            runtime_profile_active = True
                            logger.info("Runtime profiler started")
                    elif event.key == pygame.K_F10:
                        if runtime_profile_active:
                            runtime_profiler.disable()
                            runtime_profile_active = False
                        profile_dir = _screenshot_directory()
                        os.makedirs(profile_dir, exist_ok=True)
                        profile_path = os.path.join(profile_dir, f"profile_{time.time_ns()}.prof")
                        runtime_profiler.dump_stats(profile_path)
                        logger.info("Runtime profile saved to %s", profile_path)
                    elif event.key == pygame.K_p:
                        phone_open = not phone_open
                    elif event.key == pygame.K_c:
                        show_compass = not show_compass
                    elif event.key == pygame.K_n:
                        show_navigation = not show_navigation
                        logger.info(
                            "Navigation toggled: enabled=%s target=%s route_points=%s",
                            show_navigation,
                            bool(taxi_mgr.get_current_target()),
                            len(navigation_route) if navigation_route else 0,
                        )
                        if not show_navigation:
                            navigation_route = None
                            navigation_target_key = None
                    elif event.key == pygame.K_f:
                        if not on_foot:
                            length_m = getattr(car, "length_m", 4.0)
                            width_m = getattr(car, "width_m", 1.8)
                            left_x = -math.sin(car.heading)
                            left_y = math.cos(car.heading)
                            player_pedestrian.x = (
                                car.x
                                + math.cos(car.heading) * length_m * 0.2
                                + left_x * width_m * 0.85
                            )
                            player_pedestrian.y = (
                                car.y
                                + math.sin(car.heading) * length_m * 0.2
                                + left_y * width_m * 0.85
                            )
                            player_pedestrian.heading = car.heading
                            car.speed = 0.0
                            car.engine_on = False
                            on_foot = True
                            audio.play("car-door-open")
                        elif math.hypot(player_pedestrian.x - car.x, player_pedestrian.y - car.y) <= 3.0:
                            on_foot = False
                            start_hint_remaining = 0.0
                            car.speed = 0.0
                            car.engine_on = True
                            audio.play("car-door-open")
                    elif event.key == pygame.K_SPACE and not phone_open:
                        if rage_power >= RAGE_SHOUT_COST:
                            traffic_mgr.rage_shout(car)
                            police_mgr.scare()
                            audio.play_driver_line("rage", language)
                            audio.play("carhorn_takes", volume=0.45)
                            rage_power -= RAGE_SHOUT_COST
                            rage_shout_timer = 5.0
                            rage_shout_text = random.choice(RAGE_SHOUTS)
                    elif phone_open:
                        if event.key == pygame.K_ESCAPE:
                            phone_open = False
                        elif event.key == pygame.K_x:
                            taxi_mgr.reject_offer()
                        elif event.key in (pygame.K_1, pygame.K_KP1, pygame.K_2, pygame.K_KP2, pygame.K_3, pygame.K_KP3):
                            offer_index = {
                                pygame.K_1: 0, pygame.K_KP1: 0,
                                pygame.K_2: 1, pygame.K_KP2: 1,
                                pygame.K_3: 2, pygame.K_KP3: 2,
                            }[event.key]
                            if taxi_mgr.accept_offer(offer_index, car.x, car.y):
                                phone_open = False
                    elif event.key == pygame.K_ESCAPE:
                        if selected_npc is not None:
                            selected_npc = None
                            continue
                        if selected_resident_id is not None:
                            selected_resident_id = None
                            continue
                        # Pause menu with options: Continue Game, Change City, Exit Game
                        pause_options = [
                            tr(language, "continue"), tr(language, "help"), tr(language, "settings_menu"),
                            tr(language, "change_city"), tr(language, "main_menu"), tr(language, "exit"),
                        ]
                        pause_selected = 0
                        is_paused = True

                        while is_paused:
                            clock.tick(30)
                            for p_ev in pygame.event.get():
                                if p_ev.type == pygame.QUIT:
                                    pygame.quit()
                                    sys.exit(0)
                                elif p_ev.type == pygame.MOUSEMOTION:
                                    hovered = _pause_item_at(p_ev.pos, len(pause_options), SCREEN_W, SCREEN_H)
                                    if hovered is not None:
                                        pause_selected = hovered
                                elif p_ev.type == pygame.MOUSEBUTTONDOWN and p_ev.button == 1:
                                    hovered = _pause_item_at(p_ev.pos, len(pause_options), SCREEN_W, SCREEN_H)
                                    if hovered is not None:
                                        pause_selected = hovered
                                        p_ev = pygame.event.Event(
                                            pygame.KEYDOWN,
                                            {"key": pygame.K_RETURN},
                                        )
                                    else:
                                        continue
                                if p_ev.type == pygame.KEYDOWN:
                                    if p_ev.key == pygame.K_ESCAPE:
                                        is_paused = False
                                    elif p_ev.key == pygame.K_UP:
                                        pause_selected = (pause_selected - 1) % len(pause_options)
                                    elif p_ev.key == pygame.K_DOWN:
                                        pause_selected = (pause_selected + 1) % len(pause_options)
                                    elif p_ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                                        if pause_selected == 0:
                                            # Continue Game
                                            is_paused = False
                                        elif pause_selected == 1:
                                            show_help = True
                                            while show_help:
                                                clock.tick(30)
                                                for h_ev in pygame.event.get():
                                                    if h_ev.type == pygame.QUIT:
                                                        pygame.quit()
                                                        sys.exit(0)
                                                    if h_ev.type == pygame.KEYDOWN and h_ev.key in (pygame.K_ESCAPE, pygame.K_F1):
                                                        show_help = False
                                                draw_tutorial_screen(screen, font, SCREEN_W, SCREEN_H, language)
                                                pygame.display.flip()
                                        elif pause_selected == 2:
                                            settings_selected = 0
                                            endpoint_text = config.get("map", "overpass_endpoints", fallback="")
                                            in_settings = True
                                            while in_settings:
                                                clock.tick(30)
                                                for s_ev in pygame.event.get():
                                                    if s_ev.type == pygame.QUIT:
                                                        pygame.quit()
                                                        sys.exit(0)
                                                    if s_ev.type == pygame.MOUSEMOTION:
                                                        hovered = _menu_item_at_y(s_ev.pos[1], 170, 32, 26, 7)
                                                        if hovered is not None:
                                                            settings_selected = hovered
                                                        continue
                                                    if s_ev.type == pygame.MOUSEBUTTONDOWN and s_ev.button == 1:
                                                        hovered = _menu_item_at_y(s_ev.pos[1], 170, 32, 26, 7)
                                                        if hovered is not None:
                                                            settings_selected = hovered
                                                        continue
                                                    if s_ev.type != pygame.KEYDOWN:
                                                        continue
                                                    if s_ev.key == pygame.K_ESCAPE:
                                                        in_settings = False
                                                    elif settings_selected == 6 and s_ev.key == pygame.K_BACKSPACE:
                                                        endpoint_text = endpoint_text[:-1]
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif settings_selected == 6 and s_ev.key == pygame.K_DELETE:
                                                        endpoint_text = ""
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif settings_selected == 6 and s_ev.key == pygame.K_RETURN:
                                                        save_config(config)
                                                    elif settings_selected == 6 and s_ev.unicode and s_ev.unicode.isprintable():
                                                        endpoint_text += s_ev.unicode
                                                        config.set("map", "overpass_endpoints", endpoint_text)
                                                        overpass_endpoints = get_overpass_endpoints(config)
                                                        save_config(config)
                                                    elif s_ev.key == pygame.K_UP:
                                                        settings_selected = (settings_selected - 1) % 7
                                                    elif s_ev.key == pygame.K_DOWN:
                                                        settings_selected = (settings_selected + 1) % 7
                                                    elif s_ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                                                        delta = 0.05 if s_ev.key == pygame.K_RIGHT else -0.05
                                                        if settings_selected == 0:
                                                            language = SUPPORTED_LANGUAGES[(SUPPORTED_LANGUAGES.index(language) + (1 if delta > 0 else -1)) % 2]
                                                        elif settings_selected in (1, 2, 3):
                                                            key = ("master_volume", "music_volume", "effects_volume")[settings_selected - 1]
                                                            value = max(0.0, min(1.0, config.getfloat("audio", key) + delta))
                                                            config.set("audio", key, f"{value:.2f}")
                                                            audio.set_volume(key.removesuffix("_volume"), value)
                                                        elif settings_selected == 4:
                                                            enabled = not config.getboolean("audio", "comments_enabled", fallback=True)
                                                            config.set("audio", "comments_enabled", str(enabled).lower())
                                                            audio.set_comments_enabled(enabled)
                                                        elif settings_selected == 5:
                                                            enabled = not config.getboolean("audio", "subtitles_enabled", fallback=True)
                                                            config.set("audio", "subtitles_enabled", str(enabled).lower())
                                                        config.set("game", "language", language)
                                                        taxi_mgr.set_language(language)
                                                        save_config(config)
                                                draw_settings_menu(screen, font, language, config.getfloat("audio", "master_volume"), config.getfloat("audio", "music_volume"), config.getfloat("audio", "effects_volume"), config.getboolean("audio", "comments_enabled", fallback=True), config.getboolean("audio", "subtitles_enabled", fallback=True), endpoint_text, settings_selected, SCREEN_W, SCREEN_H)
                                                pygame.display.flip()
                                        elif pause_selected == 3:
                                            # Change City
                                            is_paused = False
                                            running = False
                                            active_city_name = cities_list[selected_city_idx]
                                        elif pause_selected == 4:
                                            # Return to main menu
                                            is_paused = False
                                            running = False
                                            active_city_name = None
                                            return_to_main_menu = True
                                        elif pause_selected == 5:
                                            # Exit Game
                                            pygame.quit()
                                            sys.exit(0)

                            # Redraw current frame beneath pause overlay
                            draw_pause_menu(screen, font, pause_options, pause_selected, SCREEN_W, SCREEN_H, language)
                            pygame.display.flip()

                        # Reset clock after unpausing to prevent sudden dt physics jumps
                        clock.tick()
                    elif event.key == pygame.K_F1:
                        show_help = True
                        while show_help:
                            clock.tick(30)
                            for h_ev in pygame.event.get():
                                if h_ev.type == pygame.QUIT:
                                    pygame.quit()
                                    sys.exit(0)
                                if h_ev.type == pygame.KEYDOWN and h_ev.key in (pygame.K_ESCAPE, pygame.K_F1):
                                    show_help = False
                            draw_tutorial_screen(screen, font, SCREEN_W, SCREEN_H, language)
                            pygame.display.flip()
                        clock.tick()
                    elif event.key == pygame.K_F2:
                        hud_layout = default_hud_layout(screen.get_width(), screen.get_height())
                    elif event.key == pygame.K_F3:
                        show_debug_hud = not show_debug_hud
                        frame_profiler.enabled = show_debug_hud
                        logger.info("Debug HUD %s", "enabled" if show_debug_hud else "disabled")
                    elif event.key == pygame.K_r:
                        if not _respawn_allowed(on_foot):
                            logger.info("Respawn ignored while driver is walking outside taxi")
                        else:
                            respawn_car(car, ways, waters=waters, taxi_stops=taxi_stops)
                            camx, camy = car.x, car.y
                            taxi_mgr.handle_respawn(car.x, car.y)
                    elif event.key == pygame.K_HOME:
                        if not _respawn_allowed(on_foot):
                            logger.info("Debug respawn ignored while driver is walking outside taxi")
                        else:
                            respawn_car(
                                car,
                                ways,
                                bounds=auto_fetch_manager.get_bounds(),
                                waters=waters,
                                near_edge=True,
                            )
                            camx, camy = car.x, car.y
                            taxi_mgr.handle_respawn(car.x, car.y)
                            logger.info("Debug respawn near bbox edge: car=(%.1f, %.1f)", car.x, car.y)
                    elif event.key == pygame.K_x:
                        taxi_mgr.discard_mission(car.x, car.y)
                        logger.info("Passenger fare discarded by player")
                    elif event.key == pygame.K_t:
                        reset_trip(car)
                        logger.info("Trip meter reset to 0 m")
                    elif event.key == pygame.K_u:
                        hud_layout = default_hud_layout(screen.get_width(), screen.get_height())
                        logger.info("HUD layout reset to default")
                    elif event.key == pygame.K_l:
                        label_mode = (label_mode + 1) % 3
                        logger.info("Label mode %d", label_mode)
                    elif event.key == pygame.K_k:
                        car.lane_assist_enabled = not car.lane_assist_enabled
                        logger.info("Lane assist %s", "enabled" if car.lane_assist_enabled else "disabled")
                    elif event.key == pygame.K_v:
                        speed_limiter_enabled = not speed_limiter_enabled
                        logger.info("Speed limiter %s", "enabled" if speed_limiter_enabled else "disabled")
                    elif event.key == pygame.K_b:
                        red_light_assist_enabled = not red_light_assist_enabled
                        logger.info("Red light assist %s", "enabled" if red_light_assist_enabled else "disabled")
                    elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                        px_per_m = max(min_px_per_m, px_per_m * 1.1)
                    elif event.key == pygame.K_MINUS:
                        px_per_m = max(min_px_per_m, px_per_m * 0.9)

            if first_gameplay_frame:
                logger.info("Gameplay frame: events complete")

            if not running:
                break

            if phone_open:
                dt = 0.0
            slow_check_elapsed += dt
            taxi_waiter_elapsed += dt
            visible_road_count_elapsed += dt
            rage_shout_timer = max(0.0, rage_shout_timer - dt)

            if zoom_elapsed < zoom_duration:
                zoom_elapsed = min(zoom_duration, zoom_elapsed + dt)
                progress = zoom_elapsed / zoom_duration
                eased = progress * progress * (3.0 - 2.0 * progress)
                px_per_m = max(
                    min_px_per_m,
                    px_per_m + (zoom_target - px_per_m) * eased,
                )

            zoom_scale = max(px_per_m, zoom_target)
            if last_zoom_scale is None or abs(zoom_scale - last_zoom_scale) > 0.001:
                traffic_mgr.set_target_count(traffic_count_for_zoom(base_traffic_count, zoom_scale), car)
                pedestrian_mgr.set_target_count(
                    traffic_count_for_zoom(base_pedestrian_count, zoom_scale, minimum=20),
                    car,
                )
                last_zoom_scale = zoom_scale
            cyclist_mgr.set_target_count(0, car)

            keys = pygame.key.get_pressed()
            if on_foot:
                forward_input = float(keys[pygame.K_w] or keys[pygame.K_UP]) - float(
                    keys[pygame.K_s] or keys[pygame.K_DOWN]
                )
                steer_input = float(keys[pygame.K_a] or keys[pygame.K_LEFT]) - float(
                    keys[pygame.K_d] or keys[pygame.K_RIGHT]
                )
                sprinting = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
                walking_speed = 8.0 if sprinting else 4.0
                if forward_input > 0.0:
                    player_pedestrian.speed = min(
                        walking_speed, player_pedestrian.speed + ACCEL * dt
                    )
                elif forward_input < 0.0:
                    player_pedestrian.speed = max(
                        -walking_speed, player_pedestrian.speed - BRAKE * dt
                    )
                elif player_pedestrian.speed > 0.0:
                    player_pedestrian.speed = max(0.0, player_pedestrian.speed - FRICTION * dt)
                else:
                    player_pedestrian.speed = min(0.0, player_pedestrian.speed + FRICTION * dt)

                if abs(player_pedestrian.speed) > 0.05 and abs(steer_input) > 0.01:
                    steer_effective = STEER_RATE / (
                        1.0 + abs(player_pedestrian.speed) * STEER_SPEED_FACTOR
                    )
                    player_pedestrian.heading += (
                        steer_input
                        * steer_effective
                        * dt
                        * (1.0 if player_pedestrian.speed >= 0.0 else -1.0)
                    )
                player_pedestrian.x += math.cos(player_pedestrian.heading) * player_pedestrian.speed * dt
                player_pedestrian.y += math.sin(player_pedestrian.heading) * player_pedestrian.speed * dt
            immobilized = taxi_mgr.tree_wait_timer > 0.0
            throttle = 0.0 if on_foot or immobilized else (1.0 if keys[pygame.K_w] or keys[pygame.K_UP] else 0.0)
            brake = 0.0 if on_foot or immobilized else (1.0 if keys[pygame.K_s] or keys[pygame.K_DOWN] else 0.0)
            steer_left = 0.0 if on_foot else (1.0 if keys[pygame.K_a] or keys[pygame.K_LEFT] else 0.0)
            steer_right = 0.0 if on_foot else (1.0 if keys[pygame.K_d] or keys[pygame.K_RIGHT] else 0.0)

            current_way = get_current_road_at_car(
                car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way
            )
            speed_limit_mps = None
            if speed_limiter_enabled and current_way:
                speed_limit_mps = current_way.speed_limit_kmh / 3.6
            red_light_limit_mps = None
            nearby_traffic_lights = traffic_mgr._nearby_traffic_lights(car.x, car.y)
            if red_light_assist_enabled:
                red_light_limit_mps = taxi_mgr.get_red_light_assist_speed_limit(
                    car, nearby_traffic_lights, traffic_mgr.sim_time
                )
            if red_light_limit_mps is not None:
                speed_limit_mps = (
                    red_light_limit_mps
                    if speed_limit_mps is None
                    else min(speed_limit_mps, red_light_limit_mps)
                )

            previous_position = (car.x, car.y)
            previous_speed = car.speed
            # Off-road driving is allowed at a reduced speed.
            if not on_foot:
                with frame_profiler.section("physics"):
                    update_car_physics(
                        car, throttle, brake, steer_left, steer_right, dt,
                        ways=ways, spatial_grid=spatial_grid,
                        block_offroad=False, speed_limit_mps=speed_limit_mps,
                        nearby_vehicles=traffic_mgr.npcs, parking_spaces=parking_spaces,
                    )
                car.braking = brake > 0.0 and car.speed > 0.05
                midpoint = (
                    (previous_position[0] + car.x) * 0.5,
                    (previous_position[1] + car.y) * 0.5,
                )
                entered_roadwork = any(
                    not work.contains(*previous_position, margin_m=2.0)
                    and (
                        work.contains(*midpoint, margin_m=2.0)
                        or work.contains(car.x, car.y, margin_m=2.0)
                    )
                    for work in roadworks
                )
                if entered_roadwork:
                    car.x, car.y = previous_position
                    car.speed = 0.0
                    taxi_mgr.notification_msg = tr(language, "roadwork_blocked")
                    taxi_mgr.notification_timer = 2.5
                else:
                    current_way = get_current_road_at_car(
                        car,
                        ways=ways,
                        spatial_grid=spatial_grid,
                        car_roads_only=True,
                        current_way=current_way,
                    )
                in_water = not entered_roadwork and is_car_fully_in_water(
                    car, waters, current_way=current_way
                )
                if in_water:
                    water_elapsed = min(10.0, water_elapsed + dt)
                    taxi_mgr.notification_msg = (
                        f"{tr(language, 'water_timer')}: {max(0.0, 10.0 - water_elapsed):.1f} s"
                    )
                    taxi_mgr.notification_timer = 0.2
                    if water_elapsed >= 10.0:
                        respawn_car(car, ways, waters=waters, taxi_stops=taxi_stops)
                        taxi_mgr.handle_respawn(car.x, car.y)
                        taxi_mgr.notification_msg = tr(language, "water_driving")
                        taxi_mgr.notification_timer = 1.5
                        water_elapsed = 0.0
                else:
                    water_elapsed = 0.0
            if immobilized:
                car.speed = 0.0
            movement_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
            audio.update_acceleration(
                abs(car.speed) > 0.5 and (throttle > 0.0 or brake > 0.0)
            )
            audio.update_comments(dt)
            driven_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
            road_limit_mps = current_way.speed_limit_kmh / 3.6 if current_way else None
            if road_limit_mps is not None and driven_distance > 0.0 and abs(car.speed) <= road_limit_mps + 0.01:
                rage_power = min(1.0, rage_power + driven_distance / RAGE_DISTANCE_TO_FULL_M)
            if abs(car.speed) * 3.6 < 10.0 and taxi_mgr.sees_red_light(
                car, nearby_traffic_lights, traffic_mgr.sim_time
            ):
                rage_power = min(1.0, rage_power + 0.05 * dt)
            if first_gameplay_frame:
                logger.info("Gameplay frame: physics complete")

            with frame_profiler.section("collisions"):
                building_crash = taxi_mgr.check_building_collision(
                    car, buildings, traffic_mgr.sim_time, previous_position, ways=ways
                )
                tree_crash = taxi_mgr.check_tree_collision(
                    car, sceneries, traffic_mgr.sim_time, previous_position
                )
            if building_crash or tree_crash:
                audio.play("car-crash", volume=0.7)
                audio.play_driver_line("collision", language)
            if first_gameplay_frame:
                logger.info("Gameplay frame: collision checks complete")

            # Dynamic lookahead camera offset in vehicle driving direction
            # Look ahead proportionally to car speed and heading, clamped to a percentage of viewport so car remains visible
            max_lead_screen_px = min(SCREEN_W, SCREEN_H) * 0.25
            max_lead_m = max_lead_screen_px / max(0.01, px_per_m)
            lead_distance_m = min(max_lead_m, max(0.0, abs(car.speed) * 0.8))

            focus_x = player_pedestrian.x if on_foot else car.x
            focus_y = player_pedestrian.y if on_foot else car.y
            target_camx = focus_x + math.cos(car.heading) * lead_distance_m
            target_camy = focus_y + math.sin(car.heading) * lead_distance_m

            # Smooth camera lerp
            cam_lerp_factor = min(1.0, 4.0 * dt)
            camx += (target_camx - camx) * cam_lerp_factor
            camy += (target_camy - camy) * cam_lerp_factor

            viewport_bounds = get_viewport_bounds(camx, camy, px_per_m=px_per_m, margin_m=30.0)

            # Update taxi missions & pickups
            previous_taxi_state = taxi_mgr.state
            previous_passenger = taxi_mgr.current_passenger
            previous_nausea_warning_timer = (
                previous_passenger.nausea_warning_timer if previous_passenger is not None else 0.0
            )
            previous_nausea_resolved = (
                previous_passenger.nausea_resolved if previous_passenger is not None else False
            )
            with frame_profiler.section("taxi"):
                taxi_mgr.update(car, dt, game_time_seconds=game_time_seconds)
            vomited_passenger = taxi_mgr.take_vomited_passenger(car)
            if vomited_passenger is not None:
                audio.play_passenger_line("Nyt alkaa jo helpottaa.", vomited_passenger.gender, language, vomited_passenger.name)
                passenger_pedestrian = pedestrian_mgr.spawn_pedestrian_at(
                    vomited_passenger.ped_x,
                    vomited_passenger.ped_y,
                    heading=vomited_passenger.ped_heading,
                )
                if passenger_pedestrian is not None:
                    pedestrian_mgr.pedestrians.append(passenger_pedestrian)
            current_passenger = taxi_mgr.current_passenger
            if (
                current_passenger is not None
                and not previous_nausea_resolved
                and current_passenger.nausea_resolved
            ):
                audio.play_passenger_line("Nyt alkaa jo helpottaa.", current_passenger.gender, language, current_passenger.name)
            if (
                current_passenger is not None
                and previous_nausea_warning_timer <= 0.0
                and current_passenger.nausea_warning_timer > 0.0
            ):
                audio.play_passenger_line_for_situation("nausea", current_passenger.gender, language, current_passenger.name)
                audio.play_passenger_line(
                    "Voisitko pysähtyä hetkeksi, tarvitsen raitista ilmaa.",
                    current_passenger.gender,
                    language,
                    current_passenger.name,
                )
            audio.update_passenger_speech(
                taxi_mgr.current_passenger is not None
                and taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF,
                taxi_mgr.current_passenger.gender if taxi_mgr.current_passenger else "woman",
                language,
                dt,
                taxi_mgr.current_passenger.name if taxi_mgr.current_passenger else None,
            )
            if (
                previous_taxi_state == TaxiState.CLIENT_WALKING_TO_CAR
                and taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF
            ):
                audio.play_passenger_line_for_situation(
                    "pickup", taxi_mgr.current_passenger.gender if taxi_mgr.current_passenger else "woman", language,
                    taxi_mgr.current_passenger.name if taxi_mgr.current_passenger else None,
                )
                audio.play_driver_line("pickup", language)
                audio.play("car-door-open")
            elif (
                previous_taxi_state == TaxiState.DRIVING_TO_DROPOFF
                and previous_passenger is not None
                and taxi_mgr.current_passenger is None
                and vomited_passenger is None
            ):
                audio.play_passenger_line_for_situation("dropoff", previous_passenger.gender, language, previous_passenger.name)
                audio.play_driver_line("dropoff", language)
                audio.play("car-door-open")
                passenger_pedestrian = pedestrian_mgr.spawn_pedestrian_at(
                    car.x + math.sin(car.heading) * 1.8,
                    car.y - math.cos(car.heading) * 1.8,
                    heading=car.heading,
                )
                if passenger_pedestrian is not None:
                    pedestrian_mgr.pedestrians.append(passenger_pedestrian)
            if career is None and taxi_mgr.completed_fares > saved_gig_fares:
                save_gig_odometer(gig_odometer_file, car.odometer_m)
                saved_gig_fares = taxi_mgr.completed_fares
            if career is not None and taxi_mgr.total_score >= CAREER_SCORE_LIMIT:
                career_index = int(career["city_index"])
                career_total_score = int(career["total_score"]) + taxi_mgr.total_score
                next_city_index = career_index + 1
                if next_city_index >= len(cities_list):
                    save_career(
                        career_file, career_index, career_total_score, completed=True,
                        total_distance_m=car.odometer_m,
                    )
                    city_summary = (chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, None, career_total_score)
                    logger.info("Career completed in Helsinki")
                    running = False
                else:
                    save_career(
                        career_file, next_city_index, career_total_score,
                        total_distance_m=car.odometer_m,
                    )
                    next_city = list(reversed(cities_list))[next_city_index]
                    active_city_name = next_city
                    city_summary = (chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, next_city, career_total_score)
                    logger.info("Career advanced to %s", active_city_name)
                    running = False
            if taxi_mgr.check_car_collision(
                car, traffic_mgr.nearby_npcs_at(car.x, car.y), traffic_mgr.sim_time
            ):
                audio.play("car-crash", volume=0.8)
                audio.play_driver_line("collision", language)
                rage_power = 0.0
                for npc in traffic_mgr.nearby_npcs_at(car.x, car.y):
                    if getattr(npc, "crashed_timer", 0.0) <= 0.0:
                        continue
                    traffic_mgr._crash_npc(npc, crashed_timer=npc.crashed_timer)
            was_wrong_way = taxi_mgr.wrong_way_duration > 0.0
            if slow_check_elapsed >= 0.1:
                slow_check_dt = slow_check_elapsed
                slow_check_elapsed = 0.0
                if taxi_mgr.check_wrong_way_violation(car, slow_check_dt, ways=ways, spatial_grid=spatial_grid):
                    if not was_wrong_way:
                        audio.play_driver_line("wrong_way", language)
                if taxi_mgr.check_speed_cameras(car, speed_cameras):
                    audio.play_driver_line("speed_camera", language)
            # Update autonomous traffic NPCs and pedestrians
            with frame_profiler.section("traffic"):
                traffic_mgr.update(
                    car, dt, viewport_bounds=viewport_bounds,
                    pedestrians=pedestrian_mgr.pedestrians,
                    cyclists=cyclist_mgr.cyclists, police_cars=police_mgr.cars,
                )
            for crashed_npc, crash_x, crash_y, curse_text in traffic_mgr.take_crashed_npc_events():
                crashed_pedestrian = pedestrian_mgr.spawn_pedestrian_at(
                    crash_x,
                    crash_y,
                    heading=crashed_npc.heading,
                    resident_id=crashed_npc.owner_id,
                )
                if crashed_pedestrian is not None:
                    crashed_pedestrian.curse_timer = 2.0
                    crashed_pedestrian.curse_text = curse_text
                    pedestrian_mgr.pedestrians.append(crashed_pedestrian)
            police_stopping = police_mgr.update(car, current_way, dt)
            if police_stopping:
                audio.play_driver_line("police_chase", language)
                car.speed = 0.0
                if police_mgr.collect_penalty(car, current_way):
                    taxi_mgr.total_score -= 300
                    taxi_mgr.notification_msg = tr(language, "police_stop", penalty=300)
                    taxi_mgr.notification_timer = 4.0
                    logger.info("Police traffic stop: -300 pts")
            audio.update_police_siren(
                any(npc.pursuing and not npc.penalty_given for npc in police_mgr.cars)
            )
            if not taxi_mgr.current_passenger and taxi_waiter_elapsed >= 0.2:
                taxi_waiter_elapsed = 0.0
                pedestrian_mgr.ensure_taxi_stop_waiter(taxi_stops, car, viewport_bounds=viewport_bounds)
            with frame_profiler.section("pedestrians"):
                pedestrian_mgr.update(
                    car, dt, viewport_bounds=viewport_bounds,
                    game_time_seconds=game_time_seconds,
                )
            frame_profiler.set_metric("visible_npcs", sum(
                viewport_bounds[0] <= npc.x <= viewport_bounds[2]
                and viewport_bounds[1] <= npc.y <= viewport_bounds[3]
                for npc in traffic_mgr.npcs
            ))
            frame_profiler.set_metric("visible_pedestrians", sum(
                viewport_bounds[0] <= ped.x <= viewport_bounds[2]
                and viewport_bounds[1] <= ped.y <= viewport_bounds[3]
                for ped in pedestrian_mgr.pedestrians
            ))
            frame_profiler.set_metric("active_residents", len(traffic_mgr.residents.residents))
            frame_profiler.set_metric(
                "world_cache_operations",
                sum(not future.done() for future in getattr(world_cache, "_futures", {}).values()),
            )
            traffic_mgr.let_taxi_pick_up_waiter(taxi_stops, pedestrian_mgr.pedestrians, dt)
            waiting_pedestrian = taxi_mgr.check_waiting_pickup(car, pedestrian_mgr.pedestrians, dt)
            if waiting_pedestrian is not None:
                pedestrian_mgr.pedestrians.remove(waiting_pedestrian)

            # Keep road logic on car roads, but recognize pedestrian ways as paved surfaces.
            surface_way = get_current_road_at_car(
                car,
                ways=ways,
                spatial_grid=spatial_grid,
                car_roads_only=False,
            )
            current_way = get_current_road_at_car(car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way)
            on_road = current_way is not None
            is_grass = surface_way is None and not is_point_on_parking_space(car.x, car.y, parking_spaces)
            is_skidding = brake > 0.0 and abs(previous_speed) > 4.0 and abs(steer_left - steer_right) > 0.01
            if movement_distance > 0.0 and (is_skidding or (is_grass and abs(car.speed) > 1.0)):
                if last_track_position is None or is_grass != last_track_surface:
                    track_sequence += 1
                if last_track_position is None or math.hypot(car.x - last_track_position[0], car.y - last_track_position[1]) >= 1.0:
                    tire_tracks.append((car.x, car.y, car.heading, is_grass, track_sequence))
                    last_track_position = (car.x, car.y)
                    last_track_surface = is_grass
                    if len(tire_tracks) > 4000:
                        del tire_tracks[:500]
            else:
                last_track_position = None
                last_track_surface = None
            current_road_name = getattr(current_way, "name", None) if current_way else None
            if not current_road_name and current_way:
                current_road_name = getattr(current_way, "highway", "Road").replace("_", " ").title()

            # Auto-fetch map tiles when approaching bounds (if enabled)
            if args.auto_fetch:
                started = auto_fetch_manager.start_if_needed(
                    car,
                    True,
                    args.fetch_margin,
                    args.fetch_tile_size,
                    current_way=current_way,
                )
                if started:
                    logger.info(
                        "Triggered background auto-fetch (%s) at car=(%.1f, %.1f), speed=%.1f m/s, heading=%.2f rad, bounds=%s",
                        auto_fetch_manager.get_trigger_reason(),
                        car.x,
                        car.y,
                        car.speed,
                        car.heading,
                        auto_fetch_manager.get_bounds(),
                    )
                if (
                    (
                        len(ways) != spatial_grid.indexed_way_count
                        or len(buildings) != building_grid.indexed_way_count
                        or len(sceneries) != scenery_grid.indexed_way_count
                        or len(waters) != water_grid.indexed_way_count
                        or len(crossings) != crossing_grid.indexed_way_count
                        or len(traffic_lights) != traffic_light_grid.indexed_way_count
                    )
                    and map_sync_stage == 0
                ):
                    map_sync_stage = 1

                if map_sync_stage == 1:
                    spatial_grid.rebuild(ways)
                    building_grid.rebuild(buildings)
                    scenery_grid.rebuild(sceneries)
                    water_grid.rebuild(waters)
                    crossing_grid.rebuild(crossings)
                    traffic_light_grid.rebuild(traffic_lights)
                    map_sync_stage = 2
                elif map_sync_stage == 2:
                    taxi_mgr.sync_map_data(ways, places=places, buildings=buildings)
                    map_sync_stage = 3
                elif map_sync_stage == 3:
                    traffic_mgr.sync_map_data(
                        ways,
                        traffic_lights=traffic_lights,
                        stop_signs=stop_signs,
                        crossings=crossings,
                        buildings=buildings,
                        sceneries=sceneries,
                    )
                    map_sync_stage = 4
                elif map_sync_stage == 4:
                    pedestrian_mgr.sync_map_data(ways, traffic_lights=traffic_lights)
                    pedestrian_mgr.set_venue_buildings(buildings)
                    map_sync_stage = 5
                elif map_sync_stage == 5:
                    cyclist_mgr.sync_map_data(ways, traffic_lights=traffic_lights)
                    map_sync_stage = 0
                    navigation_route_dirty = True
            current_target = taxi_mgr.get_current_target()
            if show_navigation and current_target:
                target_key = (id(current_target), current_target.x, current_target.y)
                route_deviation = False
                if navigation_route and len(navigation_route) >= 2:
                    route_deviation = min(
                        dist_point_to_segment(car.x, car.y, start[0], start[1], end[0], end[1])
                        for start, end in zip(navigation_route, navigation_route[1:])
                    ) > 35.0
                if target_key != navigation_target_key or navigation_route_dirty or route_deviation:
                    route_layer = getattr(current_way, "layer", None) if current_way else None
                    navigation_route = traffic_mgr.plan_route(
                        (car.x, car.y),
                        (current_target.x, current_target.y),
                        layer=route_layer,
                    )
                    logger.info(
                        "Navigation route planned: start=(%.1f, %.1f) target=(%.1f, %.1f) "
                        "layer=%s points=%s",
                        car.x,
                        car.y,
                        current_target.x,
                        current_target.y,
                        route_layer,
                        len(navigation_route) if navigation_route else 0,
                    )
                    navigation_target_key = target_key
                    navigation_route_dirty = False
            elif not current_target:
                navigation_route = None
                navigation_target_key = None
                show_navigation = False
            if first_gameplay_frame:
                logger.info("Gameplay frame: map update complete")

            # Render background and scene
            render_profiler_start = time.perf_counter()
            render_profile_frame_start = time.perf_counter()
            render_profile_stage_start = render_profile_frame_start
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering scenery")
            map_stage_start = time.perf_counter()
            draw_grass_texture(screen, camx, camy, px_per_m)
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_grass"] = render_profile_times.get("map_grass", 0.0) + stage_elapsed
            frame_profiler.record("render:grass", stage_elapsed * 1000.0)
            map_stage_start = time.perf_counter()
            draw_scenery(
                screen,
                sceneries,
                camx,
                camy,
                px_per_m=px_per_m,
                tree_effects=taxi_mgr.tree_effects,
                fallen_trees=taxi_mgr.fallen_trees,
                spatial_grid=scenery_grid,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_scenery"] = render_profile_times.get("map_scenery", 0.0) + stage_elapsed
            frame_profiler.record("render:scenery", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering water")
            map_stage_start = time.perf_counter()
            draw_waters(screen, waters, camx, camy, px_per_m=px_per_m, spatial_grid=water_grid)
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_water"] = render_profile_times.get("map_water", 0.0) + stage_elapsed
            frame_profiler.record("render:water", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering roads")
            map_stage_start = time.perf_counter()
            draw_ways(screen, ways, camx, camy, px_per_m=px_per_m, spatial_grid=spatial_grid)
            draw_parking_spaces(
                screen,
                parking_spaces,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=traffic_mgr._parking_grid,
                grid_cell_size=traffic_mgr._parking_grid_cell_size,
            )
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_roads"] = render_profile_times.get("map_roads", 0.0) + stage_elapsed
            frame_profiler.record("render:roads", stage_elapsed * 1000.0)
            if bus_stops_enabled:
                map_stage_start = time.perf_counter()
                draw_bus_stops(screen, bus_stops, ways, camx, camy, px_per_m=px_per_m, spatial_grid=spatial_grid)
                stage_elapsed = time.perf_counter() - map_stage_start
                render_profile_times["map_bus_stops"] = render_profile_times.get("map_bus_stops", 0.0) + stage_elapsed
                frame_profiler.record("render:bus_stops", stage_elapsed * 1000.0)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering buildings")
            map_stage_start = time.perf_counter()
            draw_buildings(screen, buildings, camx, camy, px_per_m=px_per_m, spatial_grid=building_grid)
            stage_elapsed = time.perf_counter() - map_stage_start
            render_profile_times["map_buildings"] = render_profile_times.get("map_buildings", 0.0) + stage_elapsed
            frame_profiler.record("render:buildings", stage_elapsed * 1000.0)
            render_profile_times["map"] = render_profile_times.get("map", 0.0) + (
                time.perf_counter() - render_profile_stage_start
            )
            render_profile_stage_start = time.perf_counter()
            draw_tire_tracks(
                screen, tire_tracks, camx, camy, grass=False, px_per_m=px_per_m,
                viewport_bounds=viewport_bounds,
            )
            draw_tire_tracks(
                screen, tire_tracks, camx, camy, grass=True, px_per_m=px_per_m,
                viewport_bounds=viewport_bounds,
            )
            draw_roadworks(screen, roadworks, camx, camy, px_per_m=px_per_m)
            if first_gameplay_frame:
                logger.info("Gameplay frame: rendering overlays")
            draw_crossings(screen, crossings, camx, camy, px_per_m=px_per_m, spatial_grid=crossing_grid)
            draw_traffic_lights(
                screen,
                traffic_lights,
                traffic_mgr.sim_time,
                camx,
                camy,
                px_per_m=px_per_m,
                spatial_grid=traffic_light_grid,
            )
            draw_taxi_stops(screen, taxi_stops, camx, camy, px_per_m=px_per_m)
            draw_speed_cameras(
                screen,
                speed_cameras,
                camx,
                camy,
                px_per_m=px_per_m,
                flash_index=taxi_mgr.speed_camera_flash_index,
                flash_active=taxi_mgr.speed_camera_flash_timer > 0.0,
            )
            viewport_minx, viewport_miny, viewport_maxx, viewport_maxy = get_viewport_bounds(
                camx, camy, px_per_m=px_per_m, margin_m=40.0
            )
            light_vehicles = [
                car,
                *(
                    npc for npc in traffic_mgr.npcs
                    if viewport_minx - 45.0 <= npc.x <= viewport_maxx + 45.0
                    and viewport_miny - 45.0 <= npc.y <= viewport_maxy + 45.0
                ),
            ]
            if visible_road_count_elapsed >= 0.1:
                visible_road_count = sum(
                    1
                    for way in spatial_grid.ways_in_rect(
                        viewport_minx, viewport_miny, viewport_maxx, viewport_maxy
                    )
                    if getattr(way, "is_drivable", True)
                )
                visible_road_count_elapsed = 0.0
            render_profile_stage_start = time.perf_counter()
            visible_pedestrians = pedestrian_mgr.pedestrians + [
                npc for npc in traffic_mgr.npcs if getattr(npc, "is_on_foot", False)
            ] + ([player_pedestrian] if on_foot else [])
            draw_pedestrians(
                screen,
                visible_pedestrians,
                camx,
                camy,
                font=small_font,
                px_per_m=px_per_m,
                ways=ways,
                show_debug=show_debug_hud,
                residents=traffic_mgr.residents,
                spatial_grid=spatial_grid,
            )
            draw_cyclists(
                screen,
                cyclist_mgr.cyclists,
                camx,
                camy,
                px_per_m=px_per_m,
                ways=ways,
                spatial_grid=spatial_grid,
            )
            draw_npc_cars(
                screen,
                traffic_mgr.npcs,
                camx,
                camy,
                px_per_m=px_per_m,
                ways=ways,
                spatial_grid=spatial_grid,
                show_debug=show_debug_hud,
                residents=traffic_mgr.residents,
            )
            if show_debug_hud:
                draw_npc_spatial_grid(
                    screen,
                    traffic_mgr._npc_grid,
                    traffic_mgr._npc_grid_cell_size,
                    camx,
                    camy,
                    px_per_m=px_per_m,
                )
                draw_logical_intersections(
                    screen,
                    traffic_mgr.logical_intersections,
                    camx,
                    camy,
                    traffic_mgr.sim_time,
                    px_per_m=px_per_m,
                    intersection_manager=traffic_mgr.intersection_manager,
                )
            if show_navigation:
                draw_navigation_route(screen, navigation_route, camx, camy, px_per_m=px_per_m)
            draw_taxi_target(screen, taxi_mgr, camx, camy, font, px_per_m=px_per_m, language=language)
            if car.engine_on and not on_foot:
                draw_taxi_exhaust(screen, car, camx, camy, px_per_m=px_per_m)
            draw_car(
                screen,
                car,
                camx,
                camy,
                font=font,
                px_per_m=px_per_m,
                ways=ways,
                shout_timer=rage_shout_timer,
                shout_text=rage_shout_text,
                spatial_grid=spatial_grid,
                current_way=current_way,
            )
            if not on_foot:
                draw_taxi_smoke(screen, car, camx, camy, px_per_m=px_per_m, timer=taxi_mgr.taxi_smoke_timer)
            draw_passenger_nausea_bubble(
                screen,
                font,
                car,
                taxi_mgr,
                camx,
                camy,
                px_per_m=px_per_m,
                language=language,
            )
            stage_elapsed = time.perf_counter() - render_profile_stage_start
            render_profile_times["actors"] = render_profile_times.get("actors", 0.0) + stage_elapsed
            frame_profiler.record("render:actors", stage_elapsed * 1000.0)
            render_profile_stage_start = time.perf_counter()

            lighting_start = time.perf_counter()
            sun_altitude, _, _ = solar_altitude_and_events(
                game_time_seconds, sun_latitude, sun_longitude
            )
            daylight_scene = screen.copy() if sun_altitude < -7.5 else None
            draw_day_night_overlay(
                screen,
                game_time_seconds,
                visible_road_count,
                latitude=sun_latitude,
                longitude=sun_longitude,
            )
            draw_vomit_puddles(screen, taxi_mgr.vomit_puddles, camx, camy, px_per_m=px_per_m)
            draw_vomit_puddles(screen, pedestrian_mgr.vomit_puddles, camx, camy, px_per_m=px_per_m)
            draw_street_lights(
                screen,
                ways,
                camx,
                camy,
                game_time_seconds,
                px_per_m=px_per_m,
                spatial_grid=spatial_grid,
                visible_road_count=visible_road_count,
                daylight_surface=daylight_scene,
                latitude=sun_latitude,
                longitude=sun_longitude,
                buildings=buildings,
            )
            draw_headlight_beams(
                screen,
                light_vehicles,
                camx,
                camy,
                game_time_seconds,
                px_per_m=px_per_m,
                daylight_surface=daylight_scene,
                latitude=sun_latitude,
                longitude=sun_longitude,
                npc_vehicles=light_vehicles,
                street_light_positions=None,
                bicycles=cyclist_mgr.cyclists,
                ways=ways,
                spatial_grid=spatial_grid,
                current_way=current_way,
            )
            draw_vehicle_lights(
                screen,
                light_vehicles,
                camx,
                camy,
                px_per_m=px_per_m,
                ways=ways,
                spatial_grid=spatial_grid,
                current_way=current_way,
            )
            if sun_altitude < -7.5:
                draw_pedestrian_reflectors(
                    screen,
                    visible_pedestrians,
                    camx,
                    camy,
                    px_per_m=px_per_m,
                    ways=ways,
                    light_vehicles=[car, *traffic_mgr.npcs],
                    street_light_positions=None,
                )
            stage_elapsed = time.perf_counter() - lighting_start
            render_profile_times["lighting"] = render_profile_times.get("lighting", 0.0) + stage_elapsed
            frame_profiler.record("render:lighting", stage_elapsed * 1000.0)

            # Labels overlay (toggled with 'L')
            if label_mode:
                draw_labels(
                    screen,
                    font,
                    ways,
                    waters,
                    buildings,
                    sceneries,
                    places,
                    camx,
                    camy,
                    px_per_m=px_per_m,
                    spatial_grid=spatial_grid,
                    scenery_grid=scenery_grid,
                    building_grid=building_grid,
                    label_mode=label_mode,
                )
            stage_elapsed = time.perf_counter() - render_profile_stage_start
            render_profile_times["labels"] = render_profile_times.get("labels", 0.0) + stage_elapsed
            frame_profiler.record("render:labels", stage_elapsed * 1000.0)
            render_profile_stage_start = time.perf_counter()

            render_profile_times["frame"] = render_profile_times.get("frame", 0.0) + (
                time.perf_counter() - render_profile_frame_start
            )
            if logger.isEnabledFor(logging.DEBUG) and time.perf_counter() - render_profile_last_log >= 1.0:
                frame_count = max(1, int(render_profile_times.pop("count", 0)))
                timing_ms = {
                    stage: total * 1000.0 / frame_count
                    for stage, total in render_profile_times.items()
                    if not stage.startswith("map_")
                }
                logger.debug(
                    "Render profile: fps=%.1f avg_ms=%s ways=%d buildings=%d labels=%s",
                    clock.get_fps(),
                    ",".join(f"{stage}={duration:.1f}" for stage, duration in timing_ms.items()),
                    len(ways),
                    len(buildings),
                    label_mode,
                )
                logger.debug(
                    "Map render profile: %s",
                    ",".join(
                        f"{stage.removeprefix('map_')}={duration * 1000.0 / frame_count:.1f}"
                        for stage, duration in render_profile_times.items()
                        if stage.startswith("map_")
                    ),
                )
                render_profile_times.clear()
                render_profile_last_log = time.perf_counter()
            render_profile_times["count"] = render_profile_times.get("count", 0) + 1

            # Draw HUD and compass
            current_target = taxi_mgr.get_current_target()
            target_coords = (current_target.x, current_target.y) if current_target else None
            current_limit_kmh = getattr(current_way, "speed_limit_kmh", None) if current_way else None

            draw_hud(
                screen,
                font,
                car,
                on_road,
                len(ways),
                px_per_m,
                transformer_to_ll,
                is_auto_fetching=(args.auto_fetch and auto_fetch_manager.get_fetching()),
                show_labels=bool(label_mode),
                auto_fetch_progress=auto_fetch_manager.get_progress(),
                taxi_mgr=taxi_mgr,
                current_road_name=current_road_name,
                speed_limit_kmh=current_limit_kmh,
                speed_limiter_enabled=speed_limiter_enabled,
                red_light_assist_enabled=red_light_assist_enabled,
                show_compass=show_compass,
                rage_power=rage_power,
                language=language,
                career_total_distance_m=car.odometer_m if career is not None else None,
                water_time_remaining=(10.0 - water_elapsed) if water_elapsed > 0.0 else None,
                game_time_seconds=game_time_seconds,
                game_time_realtime=taxi_mgr.current_passenger is not None,
                comment_text=audio.comment_text,
                comment_speaker=audio.comment_speaker,
                comment_speaker_name=audio.comment_speaker_name,
                subtitles_enabled=config.getboolean("audio", "subtitles_enabled", fallback=True),
                fps=clock.get_fps(),
                show_debug_hud=show_debug_hud,
                hud_layout=hud_layout,
                hud_rects=hud_rects,
            )
            if phone_open:
                draw_phone_offers(screen, taxi_mgr, font, small_font, SCREEN_W, SCREEN_H, language, car=car)
            if show_compass:
                draw_compass(screen, car, SCREEN_W - 64, 145, 28, font, target_pos=target_coords)
            if selected_resident_id is not None:
                draw_resident_popup(
                    screen,
                    small_font,
                    traffic_mgr.residents.get(selected_resident_id),
                    traffic_mgr.residents,
                    SCREEN_W,
                    SCREEN_H,
                )
            if selected_npc is not None:
                draw_npc_popup(screen, small_font, selected_npc, traffic_mgr.residents, SCREEN_W)
            if awaiting_start:
                draw_game_start_overlay(screen, font, chosen_city, SCREEN_W, SCREEN_H)
            elif start_hint_remaining > 0.0 and on_foot:
                draw_game_start_hint(screen, font, SCREEN_W)

            if first_gameplay_frame:
                logger.info("Gameplay frame: flipping display")
            frame_profiler.record(
                "rendering", (time.perf_counter() - render_profiler_start) * 1000.0
            )
            frame_profiler.end_frame()
            draw_frame_profiler(
                screen, small_font, frame_profiler,
                len(traffic_mgr.npcs), len(pedestrian_mgr.pedestrians),
            )
            pygame.display.flip()
            if first_gameplay_frame:
                logger.info("Gameplay frame: complete")
                first_gameplay_frame = False

        if career is not None and city_summary is None:
            save_career(
                career_file,
                int(career["city_index"]),
                int(career["total_score"]),
                bool(career["completed"]),
                total_distance_m=car.odometer_m,
            )
        elif career is None:
            save_gig_odometer(gig_odometer_file, car.odometer_m)

        if city_summary is not None:
            summary_city, summary_score, summary_fares, summary_next_city, summary_career_total = city_summary
            showing_summary = True
            while showing_summary:
                clock.tick(30)
                for summary_event in pygame.event.get():
                    if summary_event.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit(0)
                    if summary_event.type == pygame.KEYDOWN and summary_event.key in (
                        pygame.K_RETURN, pygame.K_KP_ENTER
                    ):
                        showing_summary = False
                draw_city_summary(
                    screen, font, summary_city, summary_score, summary_fares, summary_next_city,
                    summary_career_total, SCREEN_W, SCREEN_H, language,
                )
                pygame.display.flip()
            if summary_next_city is None:
                app_running = False

    auto_fetch_manager.shutdown()
    audio.close()
    pygame.quit()


if __name__ == "__main__":
    main()
