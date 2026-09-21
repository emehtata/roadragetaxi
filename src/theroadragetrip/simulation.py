"""The per-tick gameplay simulation, kept independent of Pygame.

``advance_simulation`` is the extracted "update phase" of ``main()``'s
gameplay loop (physics, collisions, camera follow, and the taxi/NPC/
traffic/pedestrian manager updates). It is moved here verbatim from
``main/__init__.py`` so it can be called without a display - by tests, by
``--headless`` mode, and eventually by an alternate (non-Pygame) client or
a server. See ``docs/architecture/simulation-rendering.md``.

This module must never import pygame, directly or indirectly. Player
input crosses the boundary as a plain ``PlayerCommand``, not raw key
state; the rendering/HUD phase and the map/tile-streaming pipeline stay
in ``main()`` since they own genuinely Pygame- or client-only concerns
(loading-screen event pumping, HUD dragging, debug overlays).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .career import CAREER_SCORE_LIMIT, save_career, save_gig_odometer
from .localization import tr
from .physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    get_current_road_at_car,
    is_car_colliding_with_bridge_edge,
    is_car_fully_in_water,
    pull_car_inside_bridge_edge,
    respawn_car,
    update_car_physics,
)
from .taxi import TaxiState

RAGE_DISTANCE_TO_FULL_M = 400.0


@dataclass
class PlayerCommand:
    """Everything the current frame's player input contributes to the
    simulation tick - built from raw key state by ``main()`` (or a future
    non-Pygame client) before crossing into ``advance_simulation``."""

    throttle: float = 0.0
    brake: float = 0.0
    steer_left: float = 0.0
    steer_right: float = 0.0
    forward: float = 0.0  # on-foot forward(+)/back(-), -1..1
    turn: float = 0.0  # on-foot turn left(+)/right(-), -1..1
    sprint: bool = False
    # Session toggles (V/B keys) - continuously reported rather than
    # edge-triggered, since the client already tracks their current
    # on/off state locally exactly like it tracks on_foot today.
    speed_limiter_enabled: bool = True
    red_light_assist_enabled: bool = False


@dataclass
class SimulationFrameResult:
    """The handful of scalars that change during a tick and that ``main()``
    still needs afterward for rendering, HUD, or outer-loop control. Every
    other effect of a tick (car/pedestrian/manager state) is mutated in
    place on the objects already passed in."""

    camx: float
    camy: float
    current_way: object
    movement_distance: float
    water_elapsed: float
    rage_power: float
    bridge_edge_crash_cooldown: float
    slow_check_elapsed: float
    taxi_waiter_elapsed: float
    saved_gig_fares: int
    viewport_bounds: tuple
    should_stop: bool = False
    city_summary: Optional[tuple] = None
    next_active_city_name: Optional[str] = None


def apply_enter_exit_vehicle(car, player_pedestrian, on_foot: bool, audio) -> bool:
    """The 'F' key's get-in/get-out-of-the-car action - authoritative
    gameplay logic (a distance check gates re-entry), so it belongs on
    the simulation side of the boundary, not decided by a client. Moved
    verbatim from main()'s event handler. Returns the new on_foot value."""
    if not on_foot:
        length_m = getattr(car, "length_m", 4.0)
        width_m = getattr(car, "width_m", 1.8)
        left_x = -math.sin(car.heading)
        left_y = math.cos(car.heading)
        player_pedestrian.x = (
            car.x + math.cos(car.heading) * length_m * 0.2 + left_x * width_m * 0.85
        )
        player_pedestrian.y = (
            car.y + math.sin(car.heading) * length_m * 0.2 + left_y * width_m * 0.85
        )
        player_pedestrian.heading = car.heading
        car.speed = 0.0
        car.engine_on = False
        audio.play("car-door-open")
        return True
    elif math.hypot(player_pedestrian.x - car.x, player_pedestrian.y - car.y) <= 3.0:
        car.speed = 0.0
        car.engine_on = True
        audio.play("car-door-open")
        return False
    return on_foot


def _rage_from_speeding(
    rage_power: float, speed_mps: float, road_limit_mps: Optional[float], driven_distance_m: float,
) -> float:
    """Speeding builds rage; driving within the limit calms it back down -
    both at the same rate (RAGE_DISTANCE_TO_FULL_M of speeding fills the
    meter, the same distance under the limit empties it). No current road
    (unknown limit) leaves rage unchanged either way."""
    if road_limit_mps is None or driven_distance_m <= 0.0:
        return rage_power
    delta = driven_distance_m / RAGE_DISTANCE_TO_FULL_M
    if abs(speed_mps) > road_limit_mps + 0.01:
        return min(1.0, rage_power + delta)
    return max(0.0, rage_power - delta)


def advance_simulation(
    dt: float,
    command: PlayerCommand,
    car,
    world,
    *,
    on_foot: bool,
    player_pedestrian,
    camx: float,
    camy: float,
    px_per_m: float,
    current_way,
    game_time_seconds: float,
    speed_limiter_enabled: bool,
    red_light_assist_enabled: bool,
    npc_follow: bool,
    screen_w: int,
    screen_h: int,
    physics_mode,
    weather,
    bridge_edge_crash_cooldown: float,
    rage_power: float,
    water_elapsed: float,
    language: str,
    audio,
    frame_profiler,
    slow_check_elapsed: float,
    taxi_waiter_elapsed: float,
    saved_gig_fares: int,
    career,
    career_file,
    gig_odometer_file,
    chosen_city,
    cities_list,
) -> SimulationFrameResult:
    """Run one gameplay tick: physics, collisions, camera follow, and the
    taxi/NPC/traffic/pedestrian manager updates. Extracted verbatim from
    ``main()``'s inline update phase - see module docstring."""

    ways = world.ways
    spatial_grid = world.spatial_grid
    parking_spaces = world.parking_spaces
    scenery_grid = world.scenery_grid
    roadworks = world.roadworks
    waters = world.waters
    taxi_stops = world.taxi_stops
    curbs = world.curbs
    curb_grid = world.curb_grid
    speed_bumps = world.speed_bumps
    buildings = world.buildings
    sceneries = world.sceneries
    residents = world.residents
    npcs = world.npcs
    npc_manager = world.npc_manager
    taxi_mgr = world.taxi_mgr
    traffic_mgr = world.traffic_mgr
    pedestrian_mgr = world.pedestrian_mgr
    building_grid = world.building_grid
    speed_cameras = world.speed_cameras
    places = world.places

    if on_foot:
        forward_input = command.forward
        steer_input = command.turn
        sprinting = command.sprint
        walking_speed = 8.0 if sprinting else 4.0
        if forward_input > 0.0:
            player_pedestrian.speed = min(walking_speed, player_pedestrian.speed + ACCEL * dt)
        elif forward_input < 0.0:
            player_pedestrian.speed = max(-walking_speed, player_pedestrian.speed - BRAKE * dt)
        elif player_pedestrian.speed > 0.0:
            player_pedestrian.speed = max(0.0, player_pedestrian.speed - FRICTION * dt)
        else:
            player_pedestrian.speed = min(0.0, player_pedestrian.speed + FRICTION * dt)

        if abs(player_pedestrian.speed) > 0.05 and abs(steer_input) > 0.01:
            steer_effective = STEER_RATE / (1.0 + abs(player_pedestrian.speed) * STEER_SPEED_FACTOR)
            player_pedestrian.heading += (
                steer_input * steer_effective * dt * (1.0 if player_pedestrian.speed >= 0.0 else -1.0)
            )
        player_pedestrian.x += math.cos(player_pedestrian.heading) * player_pedestrian.speed * dt
        player_pedestrian.y += math.sin(player_pedestrian.heading) * player_pedestrian.speed * dt

    immobilized = taxi_mgr.tree_wait_timer > 0.0
    throttle = 0.0 if on_foot or immobilized else command.throttle
    brake = 0.0 if on_foot or immobilized else command.brake
    steer_left = 0.0 if on_foot else command.steer_left
    steer_right = 0.0 if on_foot else command.steer_right

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
            red_light_limit_mps if speed_limit_mps is None else min(speed_limit_mps, red_light_limit_mps)
        )

    previous_position = (car.x, car.y)
    # Off-road driving is allowed at a reduced speed.
    if not on_foot:
        with frame_profiler.section("physics"):
            update_car_physics(
                car, throttle, brake, steer_left, steer_right, dt,
                ways=ways, spatial_grid=spatial_grid,
                block_offroad=False, speed_limit_mps=speed_limit_mps,
                nearby_vehicles=[], parking_spaces=parking_spaces,
                scenery_grid=scenery_grid,
                current_way=current_way, physics_mode=physics_mode,
                wetness=weather.road_grip_wetness,
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
                car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, current_way=current_way,
            )
        in_water = not entered_roadwork and is_car_fully_in_water(car, waters, current_way=current_way)
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
    audio.update_acceleration(abs(car.speed) > 0.5 and (throttle > 0.0 or brake > 0.0))
    audio.update_comments(dt)
    driven_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
    road_limit_mps = current_way.speed_limit_kmh / 3.6 if current_way else None
    rage_power = _rage_from_speeding(rage_power, car.speed, road_limit_mps, driven_distance)
    if abs(car.speed) * 3.6 < 10.0 and taxi_mgr.sees_red_light(car, nearby_traffic_lights, traffic_mgr.sim_time):
        rage_power = min(1.0, rage_power + 0.05 * dt)
    if car.is_sliding:
        # Adrenaline from a hard, tire-losing-grip corner feeds the rage
        # meter too, same as speeding does.
        rage_power = min(1.0, rage_power + 0.15 * dt)

    taxi_mgr.update_passenger_happiness(dt, car.speed, road_limit_mps, car.is_sliding)

    with frame_profiler.section("collisions"):
        building_crash = taxi_mgr.check_building_collision(
            car, buildings, traffic_mgr.sim_time, previous_position, ways=ways
        )
        tree_crash = taxi_mgr.check_tree_collision(car, sceneries, traffic_mgr.sim_time, previous_position, ways=ways)
        fence_crash = taxi_mgr.check_fence_collision(car, sceneries, traffic_mgr.sim_time, previous_position)
        taxi_mgr.check_curb_bump(car, curbs, previous_position, traffic_mgr.sim_time, curb_grid=curb_grid)
        taxi_mgr.check_speed_bump(car, speed_bumps, previous_position, traffic_mgr.sim_time)
        bridge_edge_crash = is_car_colliding_with_bridge_edge(car, current_way, ways=ways)
        if bridge_edge_crash:
            pull_car_inside_bridge_edge(car, current_way)
            # Bounce away from the rail so a held throttle cannot keep the
            # car pinned against the same bridge edge.
            car.speed = -max(2.5, min(abs(car.speed), 6.0))
            taxi_mgr.taxi_smoke_timer = max(taxi_mgr.taxi_smoke_timer, 5.0)
            if bridge_edge_crash_cooldown <= 0.0:
                bridge_edge_crash_cooldown = 3.0
                taxi_mgr.total_score -= 200
                taxi_mgr.adjust_passenger_happiness(-30.0)
                taxi_mgr.notification_msg = tr(language, "bridge_crash", penalty=200)
                taxi_mgr.notification_timer = 3.5
    if building_crash or tree_crash or fence_crash or bridge_edge_crash:
        audio.play("car-crash", volume=0.7)
        audio.play_driver_line("collision", language)

    # Dynamic lookahead camera offset in vehicle driving direction. Look
    # ahead proportionally to car speed and heading, clamped to a
    # percentage of viewport so car remains visible.
    max_lead_screen_px = min(screen_w, screen_h) * 0.25
    max_lead_m = max_lead_screen_px / max(0.01, px_per_m)

    # F6 debug follow: same lookahead/lerp camera behavior, just aimed at
    # the NPC instead of the player.
    following_npc = npc_follow and npcs
    focus_heading = npcs[0].heading if following_npc else car.heading
    focus_speed = npcs[0].speed if following_npc else car.speed
    focus_x = npcs[0].x if following_npc else (player_pedestrian.x if on_foot else car.x)
    focus_y = npcs[0].y if following_npc else (player_pedestrian.y if on_foot else car.y)
    lead_distance_m = min(max_lead_m, max(0.0, abs(focus_speed) * 0.8))
    target_camx = focus_x + math.cos(focus_heading) * lead_distance_m
    target_camy = focus_y + math.sin(focus_heading) * lead_distance_m

    # Smooth camera lerp
    cam_lerp_factor = min(1.0, 4.0 * dt)
    camx += (target_camx - camx) * cam_lerp_factor
    camy += (target_camy - camy) * cam_lerp_factor

    viewport_bounds = _viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, margin_m=30.0)

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
    with frame_profiler.section("npc"):
        npc_manager.update(
            dt, car.x, car.y, residents, traffic_mgr, ways,
            spatial_grid=spatial_grid, parking_spaces=parking_spaces,
            sceneries=sceneries, buildings=buildings,
            curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
            viewport_bounds=viewport_bounds,
            player_car=car, pedestrian_mgr=pedestrian_mgr,
        )
    vomited_passenger = taxi_mgr.take_vomited_passenger(car)
    if vomited_passenger is not None:
        audio.play_passenger_line("Nyt alkaa jo helpottaa.", vomited_passenger.gender, language, vomited_passenger.name)
        passenger_pedestrian = pedestrian_mgr.spawn_pedestrian_at(
            vomited_passenger.ped_x, vomited_passenger.ped_y, heading=vomited_passenger.ped_heading,
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
            current_passenger.gender, language, current_passenger.name,
        )
    audio.update_passenger_speech(
        taxi_mgr.current_passenger is not None and taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF,
        taxi_mgr.current_passenger.gender if taxi_mgr.current_passenger else "woman",
        language, dt,
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

    should_stop = False
    city_summary = None
    next_active_city_name = None
    if career is None and taxi_mgr.completed_fares > saved_gig_fares:
        save_gig_odometer(gig_odometer_file, car.odometer_m)
        saved_gig_fares = taxi_mgr.completed_fares
    if career is not None and taxi_mgr.total_score >= CAREER_SCORE_LIMIT:
        career_index = int(career["city_index"])
        career_total_score = int(career["total_score"]) + taxi_mgr.total_score
        next_city_index = career_index + 1
        if next_city_index >= len(cities_list):
            save_career(career_file, career_index, career_total_score, completed=True, total_distance_m=car.odometer_m)
            city_summary = (chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, None, career_total_score)
            should_stop = True
        else:
            save_career(career_file, next_city_index, career_total_score, total_distance_m=car.odometer_m)
            next_city = list(reversed(cities_list))[next_city_index]
            next_active_city_name = next_city
            city_summary = (
                chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, next_city, career_total_score,
            )
            should_stop = True

    was_wrong_way = taxi_mgr.wrong_way_duration > 0.0
    if slow_check_elapsed >= 0.1:
        slow_check_dt = slow_check_elapsed
        slow_check_elapsed = 0.0
        if taxi_mgr.check_wrong_way_violation(car, slow_check_dt, ways=ways, spatial_grid=spatial_grid):
            if not was_wrong_way:
                audio.play_driver_line("wrong_way", language)
        taxi_mgr.check_pedestrian_way_violation(car, slow_check_dt, ways=ways, spatial_grid=spatial_grid)
        if taxi_mgr.check_speed_cameras(car, speed_cameras):
            audio.play_driver_line("speed_camera", language)
    # Advance signals and taxi-world time; no autonomous vehicle update.
    with frame_profiler.section("traffic"):
        traffic_mgr.advance_time(dt)
    if not taxi_mgr.current_passenger and taxi_waiter_elapsed >= 0.2:
        taxi_waiter_elapsed = 0.0
        pedestrian_mgr.ensure_taxi_stop_waiter(taxi_stops, car, viewport_bounds=viewport_bounds)
    with frame_profiler.section("pedestrians"):
        pedestrian_mgr.update(car, dt, viewport_bounds=viewport_bounds, game_time_seconds=game_time_seconds)
    traffic_mgr.let_taxi_pick_up_waiter(taxi_stops, pedestrian_mgr.pedestrians, dt)
    waiting_pedestrian = taxi_mgr.check_waiting_pickup(car, pedestrian_mgr.pedestrians, dt)
    if waiting_pedestrian is not None:
        pedestrian_mgr.pedestrians.remove(waiting_pedestrian)

    return SimulationFrameResult(
        camx=camx,
        camy=camy,
        current_way=current_way,
        movement_distance=movement_distance,
        water_elapsed=water_elapsed,
        rage_power=rage_power,
        bridge_edge_crash_cooldown=bridge_edge_crash_cooldown,
        slow_check_elapsed=slow_check_elapsed,
        taxi_waiter_elapsed=taxi_waiter_elapsed,
        saved_gig_fares=saved_gig_fares,
        viewport_bounds=viewport_bounds,
        should_stop=should_stop,
        city_summary=city_summary,
        next_active_city_name=next_active_city_name,
    )


def _viewport_bounds(
    camx: float, camy: float, px_per_m: float, screen_w: int, screen_h: int, margin_m: float,
) -> tuple:
    """Local copy of render.common.get_viewport_bounds's formula, kept here
    so this module never imports the (Pygame-touching) render package."""
    half_w_m = (screen_w / 2.0) / max(0.01, px_per_m) + margin_m
    half_h_m = (screen_h / 2.0) / max(0.01, px_per_m) + margin_m
    return (camx - half_w_m, camy - half_h_m, camx + half_w_m, camy + half_h_m)
