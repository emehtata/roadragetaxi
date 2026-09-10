"""The Road Rage Trip rendering package.

Split from a single monolithic render.py into per-concern submodules
(common cache/geometry helpers, then one module per visual layer). This
__init__ re-exports every function and constant that was previously
importable from ``theroadragetrip.render`` so existing call sites
(``from .render import X`` / ``from theroadragetrip.render import X``)
keep working unchanged. A handful of purely-internal mutable render
caches (frame-cache surfaces, sprite caches, etc.) are intentionally not
re-exported here since they are reassigned at runtime by their owning
submodule; nothing outside this package ever imported them directly.
"""

from .common import (
    CACHE_PADDING_PX,
    DEFAULT_SUN_LATITUDE,
    DEFAULT_SUN_LONGITUDE,
    FINLAND_SUMMER_TIME_OFFSET,
    FPS,
    GAME_DATE,
    GAME_VERSION,
    LEGACY_HIGHWAY_COLORS,
    PX_PER_M,
    SCREEN_H,
    SCREEN_W,
    SOLAR_UPDATE_INTERVAL_SECONDS,
    STATIC_ZOOM_STEP,
    SURFACE_COLORS,
    _allow_static_rebuild,
    _blit_stale_static_cache,
    _covered_by_higher_road,
    _draw_version,
    _format_solar_time,
    _get_game_version,
    _pending_static_rebuilds,
    _render_logger,
    _reusable_alpha_surface,
    _reusable_alpha_surfaces,
    _smoke_surface,
    _smoke_surface_cache,
    _solar_position_cache,
    _static_cache_zoom,
    _vehicle_is_on_bridge,
    asphalt_texture_tile_size,
    begin_static_cache_frame,
    get_viewport_bounds,
    invalidate_static_caches,
    invalidate_static_caches_for_camera_jump,
    minimum_px_per_m_for_viewport_width,
    road_color_for_way,
    road_render_priority,
    solar_altitude_and_events,
    world_to_screen,
)

from .scenery import (
    CONSTRUCTION_FENCE_COLOR,
    SCENERY_COLORS,
    SCENERY_OBJECT_COLORS,
    TREE_CROWN_COLORS,
    _draw_scenery_uncached,
    draw_construction_fences,
    draw_grass_texture,
    draw_parking_spaces,
    draw_scenery,
    draw_scenery_objects,
    draw_trees,
)

from .waters import (
    _draw_waters_uncached,
    draw_waters,
)

from .buildings import (
    BUILDING_ROOF_COLORS,
    BUILDING_WALL_COLORS,
    COMMERCIAL_AMENITIES,
    COMMERCIAL_BUILDING_TYPES,
    DOOR_TOP_V_RATIO,
    FINNISH_BUILDING_COLOR_NAMES,
    MAX_BUILDING_DEPTH_PX,
    MAX_BUILDING_SIGN_FONT_SIZE,
    MAX_BUILDING_SIGN_HEIGHT_M,
    MAX_BUILDING_SIGN_WIDTH_M,
    MIN_BUILDING_SIGN_DEPTH_PX,
    MIN_BUILDING_SIGN_WIDTH_PX,
    SIGN_CATEGORY_BY_VENUE_TYPE,
    SIGN_THEME_DEFAULT,
    SIGN_THEMES,
    _building_colors_from_name,
    _building_is_commercial,
    _building_sign_anchor,
    _building_sign_angle,
    _building_sign_corners,
    _building_sign_foreshorten,
    _building_sign_surface,
    _building_sign_surface_cache,
    _building_sign_theme,
    _building_visual_plan,
    _building_visual_plan_cache,
    _building_window_story_count,
    _draw_buildings_uncached,
    _visible_building_edges,
    draw_buildings,
)

from .roads import (
    MAX_VISIBLE_STREET_LIGHTS,
    STREET_LIGHT_BUILDING_DISTANCE_M,
    STREET_LIGHT_CORE_COLOR,
    STREET_LIGHT_JUNCTION_CLEARANCE_M,
    STREET_LIGHT_POOL_ADD_COLOR,
    STREET_LIGHT_POOL_HALF_ANGLE,
    STREET_LIGHT_POOL_STEPS,
    STREET_LIGHT_SHADE_COLOR,
    STREET_LIGHT_SPACING_M,
    SPEED_BUMP_COLOR,
    RAILING_COLOR,
    RAILWAY_RAIL_COLOR,
    RAILWAY_TIE_COLOR,
    TireTrail,
    _point_is_near_building,
    _street_light_glow_cache,
    _way_has_street_lighting,
    _way_should_have_street_lighting,
    draw_bus_stops,
    draw_crossings,
    draw_curbs,
    draw_railings,
    draw_railways,
    draw_roadworks,
    draw_speed_bumps,
    draw_speed_cameras,
    draw_street_lights,
    draw_taxi_stops,
    draw_tire_tracks,
    draw_traffic_lights,
    draw_vomit_puddles,
    draw_ways,
)

from .vehicles import (
    MAX_VISIBLE_NPC_COUNT,
    _cyclist_tinted_sprites,
    _draw_vehicle,
    _draw_vehicle_lights,
    _draw_vehicle_outline,
    _npc_vehicle_sprite,
    _npc_vehicle_sprite_cache,
    _tinted_cyclist_sprite,
    _tinted_two_wheeler_sprite,
    _two_wheeler_render_cache,
    _two_wheeler_tinted_sprites,
    draw_car,
    draw_cyclists,
    draw_headlight_beams,
    draw_logical_intersections,
    draw_npc_cars,
    draw_npc_spatial_grid,
    draw_passenger_nausea_bubble,
    draw_police_cars,
    draw_taxi_exhaust,
    draw_taxi_smoke,
    draw_vehicle_lights,
)

from .pedestrians import (
    STREET_LIGHT_REFLECTOR_RADIUS_M,
    draw_npc_popup,
    draw_pedestrian_reflectors,
    draw_pedestrians,
    draw_resident_popup,
    resident_at_screen_position,
)

from .labels import (
    DISTRICT_PLACE_KINDS,
    _draw_labels_uncached,
    _label_surface_cache,
    draw_labels,
)

from .weather import (
    RAIN_COLOR,
    draw_rain,
)

from .navigation import (
    draw_compass,
    draw_navigation_route,
    draw_taxi_target,
)

from .hud import (
    _day_night_overlay_cache,
    _draw_analog_speedometer,
    _load_rage_face_frames,
    _rage_face_path,
    default_hud_layout,
    draw_day_night_overlay,
    draw_frame_profiler,
    draw_g_force_meter,
    draw_hud,
    draw_phone_offers,
)

from .menus import (
    _loading_image_path,
    draw_city_editor,
    draw_city_selection_menu,
    draw_city_summary,
    draw_game_start_hint,
    draw_game_start_overlay,
    draw_help_screen,
    draw_loading_screen,
    draw_mode_selection_menu,
    draw_pause_menu,
    draw_settings_menu,
    draw_tutorial_screen,
)


# A handful of private module-level caches are reassigned at runtime by
# their owning submodule (frame-cache surfaces, sprite caches, etc.). The
# original monolithic render.py exposed these as live module attributes;
# module __getattr__ (PEP 562) preserves that for `theroadragetrip.render.<name>`
# access (some tests reach into these directly) without snapshotting a stale
# value at package-import time.
_REBOUND_ATTR_MODULES = {
    "_asphalt_texture_source": "roads",
    "_asphalt_texture_tile": "roads",
    "_asphalt_texture_tile_size": "roads",
    "_building_frame_cache_camera": "common",
    "_building_frame_cache_key": "common",
    "_building_frame_cache_surface": "common",
    "_building_sign_font_cache": "buildings",
    "_bus_stop_font_cache": "roads",
    "_bus_stop_geometry_cache": "roads",
    "_bus_stop_label_cache": "roads",
    "_cyclist_sprite": "vehicles",
    "_grass_frame_cache_camera": "common",
    "_grass_frame_cache_key": "common",
    "_grass_frame_cache_surface": "common",
    "_grass_texture_tile": "scenery",
    "_label_frame_cache_camera": "common",
    "_label_frame_cache_key": "common",
    "_label_frame_cache_surface": "common",
    "_loading_image": "menus",
    "_moped_sprite": "vehicles",
    "_motorcycle_sprite": "vehicles",
    "_npc_debug_font": "vehicles",
    "_rage_face_frames": "hud",
    "_road_frame_cache_camera": "common",
    "_road_frame_cache_key": "common",
    "_road_frame_cache_surface": "common",
    "_scenery_frame_cache_camera": "common",
    "_scenery_frame_cache_key": "common",
    "_scenery_frame_cache_surface": "common",
    "_speedometer_font": "hud",
    "_speedometer_label_font": "hud",
    "_static_rebuilds_this_frame": "common",
    "_street_light_building_grid_cache": "roads",
    "_street_light_frame_cache_camera": "roads",
    "_street_light_frame_cache_key": "roads",
    "_street_light_frame_cache_surface": "roads",
    "_street_light_frame_pool_surface": "roads",
    "_street_light_frame_world_positions": "common",
    "_street_light_geometry_cache": "roads",
    "_street_light_geometry_cache_key": "roads",
    "_street_light_junction_cache": "roads",
    "_street_light_junction_grid_cache": "roads",
    "_street_light_last_debug_log_ms": "roads",
    "_street_light_way_lit_cache": "roads",
    "_street_light_way_lit_cache_key": "roads",
    "_taxi_sign_text": "roads",
    "_traffic_light_surface_cache": "roads",
    "_water_frame_cache_camera": "common",
    "_water_frame_cache_key": "common",
    "_water_frame_cache_surface": "common",
}


def __getattr__(name):
    module_name = _REBOUND_ATTR_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    return getattr(importlib.import_module(f".{module_name}", __name__), name)
