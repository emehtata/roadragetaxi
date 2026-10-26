"""The per-tick gameplay simulation the server runs.

``advance_simulation`` is one tick: physics, collisions, camera follow,
and the taxi/NPC/traffic/pedestrian manager updates. Player input
crosses the boundary as a plain ``PlayerCommand``, not raw key state;
map streaming lives in server/map_sync.py. History:
``docs/architecture/archive/simulation-rendering.md``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Tuple

from .career import CAREER_SCORE_LIMIT, save_career, save_gig_odometer
from .fuel import (
    FULL_TANK_TOLERANCE_L,
    Refueling,
    fuel_station_price_cents,
    nearest_fuel_station,
    update_car_fuel,
)
from .localization import tr
from .map_level import SURFACE_LEVEL
from .physics import (
    ACCEL,
    BRAKE,
    FRICTION,
    STEER_RATE,
    STEER_SPEED_FACTOR,
    get_current_road_at_car,
    is_car_colliding_with_bridge_edge,
    is_car_fully_in_water,
    SINK_S,
    pull_car_inside_bridge_edge,
    respawn_car,
    update_car_physics,
    water_sinks_car,
    water_ahead_speed_limit,
)
from .station_passengers import StationPassengerView, track_checker
from .taxi import TaxiState
from .viewport import get_viewport_bounds

RAGE_DISTANCE_TO_FULL_M = 400.0
RAGE_GAIN_SCALE = 1.0 / 3.0


RAGE_SHOUTS = ("PRKL!", "STNA!", "VTTU!", "HLVT!", "KRPÄ!", "KSPÄ!", "PSKA!")
RAGE_SHOUT_COST = 0.25
RAGE_SHOUT_DURATION_S = 5.0


@dataclass
class PlayerCommand:
    """Everything the current frame's player input contributes to the
    simulation tick - built from the client's input by the server before crossing into ``advance_simulation``."""

    throttle: float = 0.0
    brake: float = 0.0
    steer_left: float = 0.0
    steer_right: float = 0.0
    forward: float = 0.0  # on-foot forward(+)/back(-), -1..1
    turn: float = 0.0  # on-foot turn left(+)/right(-), -1..1
    sprint: bool = False
    # Session toggles (K/V/B keys) - continuously reported rather than
    # edge-triggered, since the client already tracks their current
    # on/off state locally exactly like it tracks on_foot today.
    speed_limiter_enabled: bool = True
    red_light_assist_enabled: bool = False
    lane_assist_enabled: bool = False
    refuel: bool = False
    engine_on: Optional[bool] = None
    road_rage: bool = False  # SPACE: one press (the server counts presses like refuel)
    respawn: bool = False
    home: bool = False  # H: choose this yard as home / respawn at home (one press)
    cancel_ride: bool = False
    reset_trip: bool = False


@dataclass
class SimulationFrameResult:
    """The handful of scalars that change during a tick and that the
    server still needs afterward. Every
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
    rage_shout: Optional[str] = None  # an accepted SPACE this tick: the shout to show for RAGE_SHOUT_DURATION_S


def walk_blocked_by_walls(x: float, y: float, step_x: float, step_y: float, blocked) -> Tuple[float, float]:
    """The on-foot player's next position: walls block, the player slides
    along them; someone already inside (e.g. spawned in) walks out freely."""
    if not blocked(x + step_x, y + step_y) or blocked(x, y):
        return x + step_x, y + step_y
    if not blocked(x + step_x, y):
        return x + step_x, y
    if not blocked(x, y + step_y):
        return x, y + step_y
    return x, y


def _roadwork_bars(work, x: float, y: float) -> bool:
    """Where a roadwork stops the taxi: all of a generated or closed one,
    only the closed lane of a live one with a lane closed."""
    return work.contains(x, y, margin_m=2.0) if work.blocks else work.in_closed_lane(x, y, margin_m=2.0)


def _provoke_rival(brawls, npc_manager, player_pedestrian, sim_time: float) -> None:
    """On foot, a shout at a stopped rival taxi's driver: they get out to fight."""
    from .competitor_taxis import is_competitor
    from .protocol import LOCAL_PLAYER_ID
    from .taxi_brawls import NPC, PLAYER, PROVOKE_REACH_M, PROVOKE_TAUNT, provoke
    near = [v for v in npc_manager.nearby_vehicles_at(player_pedestrian.x, player_pedestrian.y, PROVOKE_REACH_M)
            if is_competitor(v) and npc_manager.drivers.get(v.vehicle_id) is not None]
    if not near:
        return
    rival = min(near, key=lambda v: math.hypot(v.x - player_pedestrian.x, v.y - player_pedestrian.y))
    provoke(rival, PROVOKE_TAUNT, sim_time)
    brawls.report("provoke", (PLAYER, LOCAL_PLAYER_ID), (NPC, rival.vehicle_id), ("provoke", rival.vehicle_id, int(sim_time)))


def apply_enter_exit_vehicle(car, player_pedestrian, on_foot: bool, audio, taxi_mgr=None, pedestrians=()) -> bool:
    """The 'F' key's get-in/get-out-of-the-car action - authoritative
    gameplay logic (a distance check gates re-entry), so it belongs on
    the simulation side of the boundary, not decided by a client. On foot by a pre-booked rail
    customer, F greets them instead (they stay a pedestrian and walk to
    the taxi). Returns the new on_foot value."""
    if on_foot and taxi_mgr is not None and taxi_mgr.greet_booked_passenger(
        player_pedestrian, car, pedestrians,
    ) is not None:
        audio.play_group("gameplay.meet_greet")
        return on_foot
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
        car.speed = 0.0  # the engine keeps running (idling) until E turns it off
        audio.play_group("vehicle.door_open")
        return True
    elif math.hypot(player_pedestrian.x - car.x, player_pedestrian.y - car.y) <= 3.0:
        car.speed = 0.0
        audio.play_group("vehicle.door_open")  # getting in: the door opens (passengers boarding get door_close)
        return False
    return on_foot


def passenger_steps_out(pedestrian_mgr, passenger, x: float, y: float, heading: float) -> None:
    """The taxi passenger walks on from (x, y) as the same resident - not a
    stranger (reported: a woman dropped off became a man)."""
    for index, member in enumerate(passenger.members):
        member.boarded = False
        member.is_walking_to_car = False
        pedestrian = pedestrian_mgr.spawn_pedestrian_at(x + math.cos(heading) * index * 0.6,
                                                      y + math.sin(heading) * index * 0.6,
                                                      heading=heading, resident_id=member.resident_id)
        if pedestrian is not None:
            pedestrian_mgr.pedestrians.append(pedestrian)


def remove_boarded_rail_walker(taxi_mgr, pedestrian_mgr) -> None:
    """A greeted rail customer walked to the taxi as their own pedestrian;
    once they have boarded, that pedestrian leaves the world."""
    booking = getattr(taxi_mgr.current_passenger, "rail_booking", None)
    if booking is not None and booking.passenger.pedestrian is not None:
        walker, booking.passenger.pedestrian = booking.passenger.pedestrian, None
        if walker in pedestrian_mgr.pedestrians:
            pedestrian_mgr.pedestrians.remove(walker)


def _rage_from_speeding(
    rage_power: float, speed_mps: float, road_limit_mps: Optional[float], driven_distance_m: float,
) -> float:
    """Speeding builds rage; driving within the limit calms it back down.
    Positive gain is scaled separately so calming remains responsive. No
    current road (unknown limit) leaves rage unchanged either way."""
    if road_limit_mps is None or driven_distance_m <= 0.0:
        return rage_power
    delta = driven_distance_m / RAGE_DISTANCE_TO_FULL_M
    if abs(speed_mps) > road_limit_mps + 0.01:
        return min(1.0, rage_power + delta * RAGE_GAIN_SCALE)
    return max(0.0, rage_power - delta)


def _tram_obstacles(car, world) -> list:
    """What a tram must not run into (trams.TramManager.update): the taxi
    and NPC cars at their front, middle and back, and pedestrians."""
    points = []
    for vehicle in [car, *getattr(world.npc_manager, "vehicles", ())]:
        half = getattr(vehicle, "length_m", 4.5) / 2.0
        dx, dy = math.cos(vehicle.heading) * half, math.sin(vehicle.heading) * half
        points += [(vehicle.x, vehicle.y), (vehicle.x + dx, vehicle.y + dy), (vehicle.x - dx, vehicle.y - dy)]
    points += [(p.x, p.y) for p in world.pedestrian_mgr.pedestrians]
    return points


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
    outside_temperature_c: float = 15.0,
    now=None,
    view_bounds=None,
    brawl_flee: bool = False,
) -> SimulationFrameResult:
    """Run one gameplay tick: physics, collisions, camera follow, and the
    taxi/NPC/traffic/pedestrian manager updates."""

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
    scenery_objects = getattr(world, "scenery_objects", ())
    residents = world.residents
    npcs = world.npcs
    npc_manager = world.npc_manager
    taxi_mgr = world.taxi_mgr
    traffic_mgr = world.traffic_mgr
    pedestrian_mgr = world.pedestrian_mgr
    building_grid = world.building_grid
    speed_cameras = world.speed_cameras
    places = world.places
    brawls = getattr(world, "taxi_brawls", None)
    brawl_heading = brawls.player_locked() if brawls is not None and on_foot else None
    fighting = brawls is not None and on_foot and brawls.player_engaged()

    if brawl_heading is not None:  # squaring up or knocked down: the brawl holds the player in place
        player_pedestrian.speed = 0.0
        player_pedestrian.heading = brawl_heading
    elif on_foot:
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

        if abs(steer_input) > 0.01:  # a person turns on the spot too, unlike a car
            steer_effective = STEER_RATE / (1.0 + abs(player_pedestrian.speed) * STEER_SPEED_FACTOR)
            player_pedestrian.heading += (
                steer_input * steer_effective * dt * (1.0 if player_pedestrian.speed >= 0.0 else -1.0)
            )
        step_x = math.cos(player_pedestrian.heading) * player_pedestrian.speed * dt
        step_y = math.sin(player_pedestrian.heading) * player_pedestrian.speed * dt
        player_pedestrian.x, player_pedestrian.y = walk_blocked_by_walls(
            player_pedestrian.x, player_pedestrian.y, step_x, step_y, pedestrian_mgr._point_inside_building,
        )

    audio.player_position = (car.x, car.y)  # where the taxi's own sounds come from
    immobilized = taxi_mgr.tree_wait_timer > 0.0 or water_elapsed > 0.0  # sinking: no driving out
    score_at_start = taxi_mgr.total_score
    loud_event = False  # a crash/camera/vomit sound already tells of this tick's lost points
    car.driver_mass_kg = 0.0 if on_foot else 90.0
    taxi_mgr.driver_on_foot = on_foot
    player_pedestrian.name_card = on_foot and taxi_mgr.meet_booking() is not None
    passenger = taxi_mgr.current_passenger
    car.passenger_mass_kg = (
        sum(member.weight_kg for member in passenger.members if member.boarded)
        if passenger is not None and getattr(passenger, "boarded", False)
        else 0.0
    )
    out_of_fuel = car.fuel_l <= 0.0

    if command.engine_on is not None and not on_foot:
        engine_was_on = car.engine_on
        car.engine_on = bool(command.engine_on and not out_of_fuel)
        if car.engine_on != engine_was_on:
            audio.play_group("vehicle.engine_start" if car.engine_on else "vehicle.engine_stop")

    rage_shout = None
    protests = getattr(world, "protests", None)
    if protests is not None:
        protests.update(dt, world, car, now, traffic_mgr.sim_time)
    if command.road_rage and fighting:
        pass  # SPACE in a fight is a punch (taxi_brawls), not a shout
    elif command.road_rage and rage_power >= RAGE_SHOUT_COST:  # SPACE: horn, shout, arcade clearance
        audio.play_driver_line("rage", language)
        audio.play_group("vehicle.horn", 0.45)
        rage_power = max(0.0, rage_power - RAGE_SHOUT_COST)
        rage_shout = random.choice(RAGE_SHOUTS)
        world.npc_manager.trigger_road_rage(sim_time=world.traffic_mgr.sim_time)
        if protests is not None:
            protests.intimidate(car)
        if on_foot and brawls is not None:  # shouting at a rival taxi's driver picks a fight
            _provoke_rival(brawls, world.npc_manager, player_pedestrian, traffic_mgr.sim_time)

    stopped_refueling = command.refuel and getattr(taxi_mgr, "refueling", None) is not None
    if stopped_refueling:
        taxi_mgr.refueling = None
    if command.refuel and not stopped_refueling:
        station = nearest_fuel_station(scenery_objects, car.x, car.y)
        if station is None:
            taxi_mgr.notification_msg = tr(language, "fuel_no_station")
        elif not on_foot or car.engine_on:
            taxi_mgr.notification_msg = tr(language, "fuel_enter_car")
        elif abs(car.speed) > 0.5:
            taxi_mgr.notification_msg = tr(language, "fuel_stop_car")
        elif math.hypot(player_pedestrian.x - car.x, player_pedestrian.y - car.y) > 8.0:
            taxi_mgr.notification_msg = tr(language, "fuel_no_station")
        elif car.fuel_l >= car.fuel_capacity_l - FULL_TANK_TOLERANCE_L:  # idling since the last fill-up still reads as full
            taxi_mgr.notification_msg = tr(language, "fuel_tank_full")
        else:
            price_cents = fuel_station_price_cents(station)
            if taxi_mgr.balance_cents <= 0:
                taxi_mgr.notification_msg = tr(language, "fuel_no_money")
            else:
                if getattr(taxi_mgr, "refueling", None) is None:
                    taxi_mgr.refueling = Refueling(price_cents)
                audio.play_group("taxi.refuel")
        taxi_mgr.notification_timer = 4.0
    fueling = getattr(taxi_mgr, "refueling", None)
    if fueling is not None:
        station = nearest_fuel_station(scenery_objects, car.x, car.y)
        if (not on_foot or car.engine_on or abs(car.speed) > 0.5 or station is None
                or math.hypot(player_pedestrian.x - car.x, player_pedestrian.y - car.y) > 8.0):
            taxi_mgr.refueling = None
        else:
            fueling.advance(car, taxi_mgr, dt)
            taxi_mgr.notification_msg = tr(language, "fuel_purchased", liters=fueling.liters, cost=fueling.paid_cents / 100.0)
            taxi_mgr.notification_timer = 4.0
            if car.fuel_l >= car.fuel_capacity_l - 1e-9 or taxi_mgr.balance_cents <= 0:
                taxi_mgr.refueling = None
    throttle = 0.0 if on_foot or immobilized or out_of_fuel or not car.engine_on else command.throttle
    brake = 0.0 if on_foot or immobilized else command.brake
    steer_left = 0.0 if on_foot else command.steer_left
    steer_right = 0.0 if on_foot else command.steer_right

    # The player drives on its own map level's road network (garage-05.md):
    # the surface one, or the level's - never the surface as a fallback.
    # NPCs below keep the surface network.
    if not getattr(world.level_transitions, "enabled", True):
        car.map_level = SURFACE_LEVEL
    on_surface = car.map_level == SURFACE_LEVEL
    if on_surface:
        drive_ways, drive_grid = ways, spatial_grid
    else:
        drive_ways, drive_grid = world.level_roads.network(car.map_level)
    current_way = get_current_road_at_car(
        car, ways=drive_ways, spatial_grid=drive_grid, car_roads_only=True, current_way=current_way
    )
    if not on_foot:
        npc_manager.road_rage.update(npc_manager, car, traffic_mgr.sim_time, drive_ways, drive_grid, current_way)
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

    # Soft streaming boundary: ease off near tiles still being fetched
    # instead of blocking the game behind a loading screen.
    auto_fetch_manager = getattr(world, "auto_fetch_manager", None)
    if auto_fetch_manager is not None and not on_foot:
        streaming_cap_mps = auto_fetch_manager.streaming_speed_cap_mps(
            car.x, car.y, math.cos(car.heading) * car.speed, math.sin(car.heading) * car.speed,
        )
        if streaming_cap_mps is not None:
            speed_limit_mps = streaming_cap_mps if speed_limit_mps is None else min(speed_limit_mps, streaming_cap_mps)

    # Safety brake before open water straight ahead, off-road only: a shore road's
    # bends point at the water without leaving the road (surface only: levels have none).
    # Braking from a standstill reverses: that backs away from the shore, never capped.
    if on_surface and not on_foot and waters and current_way is None and not (brake > 0.0 and car.speed <= 0.5):
        water_limit_mps = water_ahead_speed_limit(car, waters, now.month if now is not None else None, drive_grid)
        if water_limit_mps is not None:
            speed_limit_mps = water_limit_mps if speed_limit_mps is None else min(speed_limit_mps, water_limit_mps)
            if car.speed > water_limit_mps + 0.5:  # too close for the gentle limit: brake hard
                throttle, brake = 0.0, 1.0

    previous_position = (car.x, car.y)
    approach_way = current_way  # the road the car drove along into this frame's movement
    # Off-road driving is allowed at a reduced speed.
    if not on_foot:
        with frame_profiler.section("physics"):
            update_car_physics(
                car, throttle, brake, steer_left, steer_right, dt,
                ways=drive_ways, spatial_grid=drive_grid,
                block_offroad=False, speed_limit_mps=speed_limit_mps,
                # Ground types and parking bays carry no level: surface only.
                nearby_vehicles=[], parking_spaces=parking_spaces if on_surface else [],
                scenery_grid=scenery_grid if on_surface else None,
                current_way=current_way, physics_mode=physics_mode,
                wetness=weather.road_grip_wetness,
                black_ice=weather.road_ice_fraction,
                wind=weather.wind_vector_mps,
                fields_frozen=getattr(world, "fields_frozen", False),
            )
        car.braking = brake > 0.0 and car.speed > 0.05
        if world.level_transitions.blocks_entry(car, previous_position, approach_way):
            car.x, car.y = previous_position
            car.speed = 0.0
            taxi_mgr.notification_msg = tr(language, "garage_closed")
            taxi_mgr.notification_timer = 2.5
        if protests is not None and protests.blocks_movement(car, previous_position):
            car.x, car.y = previous_position
            car.speed = 0.0
        midpoint = (
            (previous_position[0] + car.x) * 0.5,
            (previous_position[1] + car.y) * 0.5,
        )
        live = getattr(world, "live_roadworks", None)
        entered_roadwork = on_surface and any(  # roadworks sit on surface roads
            not _roadwork_bars(work, *previous_position)
            and (_roadwork_bars(work, *midpoint) or _roadwork_bars(work, car.x, car.y))
            for work in (list(roadworks) + (live.zones if live is not None else []))
        )
        audio.on_rise("roadwork", entered_roadwork, "gameplay.roadwork_blocked")
        if entered_roadwork:
            car.x, car.y = previous_position
            car.speed = 0.0
            taxi_mgr.notification_msg = tr(language, "roadwork_blocked")
            taxi_mgr.notification_timer = 2.5
        else:
            current_way = get_current_road_at_car(
                car, ways=drive_ways, spatial_grid=drive_grid, car_roads_only=True, current_way=current_way,
            )
        # Driving through a parking entrance may change the player's map
        # level (garage-08.md); everything level-aware follows car.map_level.
        if world.level_transitions.update(car, previous_position, approach_way) is not None:
            on_surface = car.map_level == SURFACE_LEVEL
            drive_ways, drive_grid = (
                (ways, spatial_grid) if on_surface else world.level_roads.network(car.map_level)
            )
            current_way = get_current_road_at_car(
                car, ways=drive_ways, spatial_grid=drive_grid, car_roads_only=True,
            )
        # water_elapsed: seconds the taxi has been sinking (0: afloat or on ice)
        if water_elapsed > 0.0 and (not on_surface or not is_car_fully_in_water(car, waters, current_way)):
            water_elapsed = 0.0  # streamed geometry can correct a false water overlap
        elif water_elapsed == 0.0 and on_surface and not entered_roadwork and water_sinks_car(
                car, waters, current_way, now.month if now is not None else None, dt):
            water_elapsed = dt
            audio.play_group("vehicle.water_splash")
        elif water_elapsed > 0.0:
            water_elapsed += dt
        if water_elapsed > 0.0:
            car.speed = 0.0  # the HUD counts down from water_elapsed
            if water_elapsed >= SINK_S:
                respawn_car(car, ways, waters=waters, taxi_stops=taxi_stops)
                taxi_mgr.handle_respawn(car.x, car.y)
                taxi_mgr.notification_msg = tr(language, "water_driving")
                taxi_mgr.notification_timer = 1.5
                water_elapsed = 0.0
    if immobilized:
        car.speed = 0.0
    movement_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
    audio.update_engine(car.engine_on and not on_foot, car.speed, throttle)
    audio.set_loop("engine_idle", "vehicle.engine_idle", 0.45 if car.engine_on and abs(car.speed) <= 0.5 else 0.0)
    # Tyre squeal (vehicle.tire_squeal on car.is_sliding) is off for now: too annoying in play.
    audio.on_rise("brake", brake > 0.0 and abs(car.speed) > 8.0, "vehicle.brake_hard", 0.7)
    audio.update_comments(dt)
    driven_distance = math.hypot(car.x - previous_position[0], car.y - previous_position[1])
    fuel_emptied = update_car_fuel(
        car,
        driven_distance,
        abs(car.speed),
        throttle,
        brake,
        acceleration_mps2=max(0.0, car.raw_forward_g * 9.81),
        elapsed_seconds=dt,
        outside_temperature_c=outside_temperature_c,
    )
    if fuel_emptied:
        audio.play_group("vehicle.fuel_empty")
        taxi_mgr.notification_msg = tr(language, "fuel_empty")
        taxi_mgr.notification_timer = 4.0
    road_limit_mps = current_way.speed_limit_kmh / 3.6 if current_way else None
    live_limit = world.live_roadworks.speed_limit_at(car.x, car.y) if getattr(world, "live_roadworks", None) else None
    if live_limit is not None and road_limit_mps is not None:  # a live roadwork's limit (digitraffic_road)
        road_limit_mps = min(road_limit_mps, live_limit / 3.6)
    rage_power = _rage_from_speeding(rage_power, car.speed, road_limit_mps, driven_distance)
    if abs(car.speed) * 3.6 < 10.0 and taxi_mgr.sees_red_light(car, nearby_traffic_lights, traffic_mgr.sim_time):
        rage_power = min(1.0, rage_power + 0.05 * RAGE_GAIN_SCALE * dt)
    if car.is_sliding:
        # Adrenaline from a hard, tire-losing-grip corner feeds the rage
        # meter too, same as speeding does.
        rage_power = min(1.0, rage_power + 0.15 * RAGE_GAIN_SCALE * dt)

    taxi_mgr.update_passenger_happiness(dt, car.speed, road_limit_mps, car.is_sliding)

    with frame_profiler.section("collisions"):
        # Level-aware (garage-06.md): buildings carry map_level and are
        # filtered per candidate in check_building_collision; trees, fences,
        # curbs and speed bumps have no level data, so they're surface-only
        # and not checked off the surface (their indexes stay untouched).
        # Road-overlap exemptions use the player's own level's roads.
        building_crash = taxi_mgr.check_building_collision(
            car, buildings, traffic_mgr.sim_time, previous_position, ways=drive_ways,
            current_way=current_way,
        )
        fallen_before = len(taxi_mgr.fallen_trees)
        tree_crash = on_surface and taxi_mgr.check_tree_collision(
            car, sceneries, traffic_mgr.sim_time, previous_position, ways=drive_ways
        )
        if len(taxi_mgr.fallen_trees) > fallen_before:
            audio.play_group("collision.tree_fall")
        fence_crash = on_surface and taxi_mgr.check_fence_collision(car, sceneries, traffic_mgr.sim_time, previous_position)
        fence_group = "collision.fence"
        if not fence_crash and on_surface:
            fence_crash = taxi_mgr.check_barrier_collision(
                car, getattr(world, "railings", ()), traffic_mgr.sim_time, previous_position, current_way)
            fence_group = taxi_mgr.barrier_sound
        tram_crash = on_surface and taxi_mgr.check_tram_collision(
            car, getattr(world, "tram_mgr", None), traffic_mgr.sim_time, previous_position)
        # Bollards and lamp posts are OSM nodes without a level: surface only.
        post_crash = on_surface and taxi_mgr.check_post_collision(
            car, scenery_objects, traffic_mgr.sim_time, previous_position
        )
        if on_surface and taxi_mgr.check_curb_bump(car, curbs, previous_position, traffic_mgr.sim_time, curb_grid=curb_grid):
            audio.play_group("vehicle.curb_bump", min(1.0, 0.3 + abs(car.speed) / 10.0))
        if on_surface and taxi_mgr.check_speed_bump(car, speed_bumps, previous_position, traffic_mgr.sim_time):
            audio.play_group("vehicle.speed_bump", min(1.0, 0.3 + abs(car.speed) / 12.0))
        bridge_edge_crash = is_car_colliding_with_bridge_edge(car, current_way, ways=drive_ways)
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
    # Once per impact (the checks stay true every frame the car touches).
    crashed = any([
        audio.on_rise("crash_building", building_crash, "collision.building", 0.8),
        audio.on_rise("crash_tree", tree_crash, "collision.tree", 0.8),
        audio.on_rise("crash_fence", fence_crash, fence_group, 0.8),
        audio.on_rise("crash_tram", tram_crash, "collision.building", 0.9),  # a heavy steel body
        audio.on_rise("crash_post", post_crash, "collision.guardrail", 0.8),  # a metal pole
        audio.on_rise("crash_guardrail", bridge_edge_crash, "collision.guardrail", 0.8),
    ])
    if crashed:
        loud_event = True
        audio.play_driver_line("collision", language)
    audio.set_loop("steam", "vehicle.damaged_steam", 0.35 if taxi_mgr.taxi_smoke_timer > 0.0 else 0.0)

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

    viewport_bounds = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, margin_m=30.0)
    ambient_bounds = None
    if view_bounds is not None:
        from .viewport import simulation_bounds
        viewport_bounds = (view_bounds[0] - 30, view_bounds[1] - 30, view_bounds[2] + 30, view_bounds[3] + 30)
        ambient_bounds = simulation_bounds(view_bounds, car.x, car.y, car.speed, car.heading)

    # Trains: timetable trains, their passengers and pre-bookings follow the
    # game clock (`now`, a datetime); presentation (drawing, train sounds,
    # station announcements) stays with the client.
    railway_mgr = getattr(world, "railway_mgr", None)
    if railway_mgr is not None and now is not None:
        with frame_profiler.section("trains"):
            if railway_mgr.passenger_view is None:
                railway_mgr.associate_taxi_stands(taxi_mgr.taxi_stops)  # existing stands only
                railway_mgr.passenger_view = StationPassengerView(
                    pedestrian_mgr, on_track=track_checker(world.railway_grid),
                )
            railway_mgr.view_point = (camx, camy)
            railway_mgr.update(dt, dt * (1.0 if taxi_mgr.has_active_job() else 60.0), now)
    tram_mgr = getattr(world, "tram_mgr", None)
    if tram_mgr is not None and tram_mgr.has_track:
        with frame_profiler.section("trams"):
            tram_mgr.update(dt, (camx, camy), viewport_bounds, _tram_obstacles(car, world))

    # Update taxi missions & pickups
    previous_taxi_state = taxi_mgr.state
    previous_passenger = taxi_mgr.current_passenger
    previous_nausea_warning_timer = (
        previous_passenger.nausea_warning_timer if previous_passenger is not None else 0.0
    )
    previous_nausea_resolved = (
        previous_passenger.nausea_resolved if previous_passenger is not None else False
    )
    offers_before = len(taxi_mgr.offers)
    fares_before = taxi_mgr.completed_fares
    vomited_before = previous_passenger is not None and previous_passenger.nausea_vomited
    with frame_profiler.section("taxi"):
        taxi_mgr.update(car, dt, game_time_seconds=game_time_seconds)
    party_released = any(party is previous_passenger for party in taxi_mgr.released_parties)
    for party in taxi_mgr.released_parties:
        x, y = (car.x, car.y) if party.boarded else (party.ped_x, party.ped_y)
        passenger_steps_out(pedestrian_mgr, party, x, y, car.heading)
    taxi_mgr.released_parties.clear()
    if len(taxi_mgr.offers) > offers_before:
        audio.play_group("ui.new_offer")
    if taxi_mgr.completed_fares > fares_before:
        audio.play_group("taxi.payment")
    if previous_passenger is not None and previous_passenger.nausea_vomited and not vomited_before:
        audio.play_group("passenger.vomit")
        loud_event = True
    with frame_profiler.section("npc"):
        if ambient_bounds is not None:
            from .viewport import in_bounds
            party = taxi_mgr.current_passenger
            protected = [member.resident_id for member in party.members] if party is not None else []
            npc_manager.discard_outside(ambient_bounds, residents, pedestrian_mgr, protected)
            pedestrian_mgr.discard_outside(ambient_bounds, protected)
            taxi_mgr.vomit_puddles[:] = [p for p in taxi_mgr.vomit_puddles if in_bounds(ambient_bounds, p[0], p[1], 2.0)]
        traffic_mgr.stop_signs = getattr(world, "stop_signs", ())
        traffic_mgr.yield_signs = getattr(world, "yield_signs", ())
        npc_manager.clock = now
        npc_manager.bus_stops = getattr(world, "bus_stops", ())  # the bus lines' stops (bus_lines.py)
        npc_manager.snowy = weather.weather_type.value == "snow" or weather.road_snow > 0.1
        plough_positions = {v.vehicle_id: (v.x, v.y) for v in npc_manager.vehicles
                            if v.vehicle_type == "tractor" and v.vehicle_id in npc_manager.drivers}
        npc_manager.update(
            dt, car.x, car.y, residents, traffic_mgr, ways,
            spatial_grid=spatial_grid, parking_spaces=parking_spaces,
            sceneries=sceneries, buildings=buildings,
            curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
            viewport_bounds=viewport_bounds,
            player_car=car, pedestrian_mgr=pedestrian_mgr,
            current_way=current_way,
            active_bounds=ambient_bounds,
        )
        if npc_manager.snowy:
            for vehicle in npc_manager.vehicles:
                start = plough_positions.get(vehicle.vehicle_id)
                if (start is not None and abs(vehicle.car.speed) > 0.1
                        and vehicle.way is not None and vehicle.car.map_level == SURFACE_LEVEL):
                    weather.plow_road(start, (vehicle.x, vehicle.y))
    for x, y in npc_manager.accidents:
        audio.play_group("collision.vehicle", at=(x, y))
    npc_manager.accidents.clear()
    for at in npc_manager.bus_brakes:
        audio.play_group("vehicle.bus_air_brake", at=at)
    npc_manager.bus_brakes.clear()
    curses = pedestrian_mgr.curses + npc_manager.curses  # bumped NPC drivers curse the same way
    if curses:
        x, y = curses[-1]  # one curse per tick is plenty
        audio.play_group("pedestrian.curse", 0.8, at=(x, y))
        pedestrian_mgr.curses.clear()
        npc_manager.curses.clear()
    vomited_passenger = taxi_mgr.take_vomited_passenger(car)
    if vomited_passenger is not None:
        audio.play_group("passenger.vomit")
        audio.play_passenger_line("Nyt alkaa jo helpottaa.", vomited_passenger.gender, language, vomited_passenger.name)
        passenger_steps_out(pedestrian_mgr, vomited_passenger, vomited_passenger.ped_x, vomited_passenger.ped_y,
                            vomited_passenger.ped_heading)
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
        audio.play_group("vehicle.door_close")  # the passenger is in
        audio.play_group("taxi.meter_start", 0.7)
        remove_boarded_rail_walker(taxi_mgr, pedestrian_mgr)
    elif (
        previous_taxi_state == TaxiState.DRIVING_TO_DROPOFF
        and previous_passenger is not None
        and taxi_mgr.current_passenger is None
        and vomited_passenger is None
        and not party_released
    ):
        audio.play_passenger_line_for_situation("dropoff", previous_passenger.gender, language, previous_passenger.name)
        audio.play_driver_line("dropoff", language)
        audio.play_group("vehicle.door_open")
        passenger_steps_out(pedestrian_mgr, previous_passenger, car.x + math.sin(car.heading) * 1.8,
                            car.y - math.cos(car.heading) * 1.8, car.heading)

    should_stop = False
    city_summary = None
    next_active_city_name = None
    if career is None and taxi_mgr.completed_fares > saved_gig_fares:
        save_gig_odometer(gig_odometer_file, car.odometer_m, car.fuel_l, taxi_mgr.balance_cents)
        saved_gig_fares = taxi_mgr.completed_fares
    if career is not None and taxi_mgr.total_score >= CAREER_SCORE_LIMIT:
        career_index = int(career["city_index"])
        career_total_score = int(career["total_score"]) + taxi_mgr.total_score
        next_city_index = career_index + 1
        if next_city_index >= len(cities_list):
            save_career(
                career_file, career_index, career_total_score, completed=True,
                total_distance_m=car.odometer_m, balance_cents=taxi_mgr.balance_cents,
            )
            city_summary = (chosen_city, taxi_mgr.total_score, taxi_mgr.completed_fares, None, career_total_score)
            should_stop = True
        else:
            save_career(
                career_file, next_city_index, career_total_score,
                total_distance_m=car.odometer_m, balance_cents=taxi_mgr.balance_cents,
            )
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
        if taxi_mgr.check_wrong_way_violation(car, slow_check_dt, ways=drive_ways, spatial_grid=drive_grid):
            if not was_wrong_way:
                audio.play_driver_line("wrong_way", language)
        taxi_mgr.check_pedestrian_way_violation(car, slow_check_dt, ways=drive_ways, spatial_grid=drive_grid)
    if not on_foot and on_surface and taxi_mgr.check_speed_cameras(car, speed_cameras, previous_position=previous_position):
        audio.play_group("gameplay.speed_camera")
        audio.play_driver_line("speed_camera", language)
        loud_event = True
    # Advance signals and taxi-world time; no autonomous vehicle update.
    with frame_profiler.section("traffic"):
        traffic_mgr.advance_time(dt)
    if not taxi_mgr.current_passenger and taxi_waiter_elapsed >= 0.2:
        taxi_waiter_elapsed = 0.0
        pedestrian_mgr.ensure_taxi_stop_waiter(taxi_stops, car, viewport_bounds=viewport_bounds)
    arena_crowds = getattr(world, "arena_crowds", None)
    if now is not None and arena_crowds is not None:
        arena_crowds.update(now, (car.x, car.y))
    pedestrian_mgr.ensure_sports_players(car, viewport_bounds)
    with frame_profiler.section("pedestrians"):
        pedestrian_previous = {id(p): (p.x, p.y) for p in pedestrian_mgr.pedestrians} if protests is not None and protests.groups else {}
        pedestrian_mgr.update(car, dt, viewport_bounds=viewport_bounds, game_time_seconds=game_time_seconds,
                              active_bounds=ambient_bounds)
        if pedestrian_previous:
            protests.block_walkers(pedestrian_mgr.pedestrians, pedestrian_previous)
        pedestrian_mgr.track_vomit(taxi_mgr.vomit_puddles + pedestrian_mgr.vomit_puddles)
    for group_id, at in pedestrian_mgr.sound_events:
        audio.play_group(group_id, at=at)
    pedestrian_mgr.sound_events.clear()
    if on_foot:
        audio.update_footsteps(player_pedestrian.speed, dt, running=command.sprint)
    world.competitor_dispatcher.update(taxi_mgr, npc_manager, dt, brawls, traffic_mgr.sim_time)  # competitors take phone fares
    if brawls is not None:
        from .protocol import LOCAL_PLAYER_ID
        from .taxi_brawls import NPC, PLAYER
        for vehicle_id in npc_manager.taxi_bumps:  # the player bumped a rival: a future player quarrel
            brawls.report("traffic", (PLAYER, LOCAL_PLAYER_ID), (NPC, vehicle_id), ("traffic", vehicle_id, int(traffic_mgr.sim_time)))
        from .taxi_brawls import PlayerView
        passenger = taxi_mgr.current_passenger
        brawls.update(npc_manager, dt, traffic_mgr.sim_time, taxi_stops, now, player_rage=rage_power,
                      player=PlayerView(
                          player_pedestrian.x, player_pedestrian.y, on_foot, car.x, car.y, car.heading,
                          getattr(car, "width_m", 1.8), getattr(car, "map_level", 0),
                          carrying=passenger is not None,
                          strike=bool(command.road_rage and fighting), dodge=bool(command.sprint and fighting),
                          flee=bool(brawl_flee and fighting)))
        if brawls.player_notice:
            taxi_mgr.notification_msg = tr(language, brawls.player_notice)
            taxi_mgr.notification_timer = 4.0
            brawls.player_notice = None
        for group_id, at in brawls.sound_events:
            audio.play_group(group_id, at=at)
        brawls.sound_events.clear()
    npc_manager.taxi_bumps.clear()
    waiting_pedestrian = taxi_mgr.check_waiting_pickup(car, pedestrian_mgr.pedestrians, dt)
    if waiting_pedestrian is not None:
        pedestrian_mgr.pedestrians.remove(waiting_pedestrian)
    # Points lost this tick (wrong way, pedestrian way, cancelled fare ...)
    # with no crash/camera/vomit sound of its own.
    if taxi_mgr.total_score < score_at_start and not loud_event:
        audio.play_group("ui.penalty", 0.6)

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
        rage_shout=rage_shout,
    )


