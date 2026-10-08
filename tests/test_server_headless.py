"""client-server-02.md step 18: the server works without any client
connected, with no graphical environment required."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SDL_VIDEODRIVER") not in (None, "dummy"),
    reason="requires a headless-safe SDL driver",
)


def _build_server(tmp_path, monkeypatch, extra=()):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    argv = ["prog", "--use-sample", "--no-menu", "--no-historical-weather", *extra]
    monkeypatch.setattr(sys, "argv", argv)
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.server import SimulationServer

    args, config = parse_server_args()
    return SimulationServer(args, config)


def test_server_builds_and_ticks_with_no_client_connected(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    assert server._chunks_index._encoded == {}  # distant chunks are encoded lazily, not on startup
    for _ in range(30):
        server.tick(1.0 / 30.0)
    assert server._tick == 30


def test_server_never_opens_a_graphical_display(tmp_path, monkeypatch):
    import pygame

    # Patch set_mode itself (not pygame.display.get_surface(), which is
    # shared global state another test module's own real display could
    # leave set) - this is only ever true if the server code path never
    # calls it, regardless of what else is running in the same process.
    monkeypatch.setattr(pygame.display, "set_mode", lambda *a, **k: pytest.fail("server opened a display"))
    server = _build_server(tmp_path, monkeypatch)
    for _ in range(5):
        server.tick(1.0 / 30.0)


def test_game_time_advances(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    start = server._game_time_seconds
    for _ in range(30):
        server.tick(1.0 / 30.0)
    assert server._game_time_seconds != start


def test_traffic_lights_advance_via_sim_time(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    start = server.world.traffic_mgr.sim_time
    for _ in range(10):
        server.tick(1.0 / 30.0)
    assert server.world.traffic_mgr.sim_time > start


def test_weather_state_is_available(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    assert hasattr(server.world.weather, "weather_type")
    assert hasattr(server.world.weather, "wetness")


def test_npc_and_pedestrian_population_advance(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    for _ in range(10):
        server.tick(1.0 / 30.0)
    # Just confirms the managers are live, wired objects (not stubs) that
    # advance_simulation is actually driving - not asserting specific
    # counts, which depend on the bundled sample map's size.
    assert isinstance(server.world.npc_manager.vehicles, list)
    assert isinstance(server.world.pedestrian_mgr.pedestrians, list)


def test_player_commands_reach_the_simulation(tmp_path, monkeypatch):
    from theroadragetrip import protocol, transport
    from theroadragetrip.simulation import PlayerCommand

    server = _build_server(tmp_path, monkeypatch)
    server.start("127.0.0.1", 0)
    connection = transport.connect(server.host, server.port)
    import time
    time.sleep(0.1)

    connection.send(protocol.build_command_message(PlayerCommand(), interact=True, seq=1))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server._on_foot is False  # the interact command got the player into the car

    connection.send(protocol.build_command_message(PlayerCommand(throttle=1.0, engine_on=True), interact=False, seq=2))
    time.sleep(0.05)
    start_x = server.car.x
    for _ in range(20):
        server.tick(1.0 / 30.0)
    assert server.car.x != start_x

    trip_before_reset = server.car.trip_m
    connection.send(protocol.build_command_message(
        PlayerCommand(lane_assist_enabled=True, reset_trip=True), interact=False, seq=3,
    ))
    time.sleep(0.05)
    server.tick(1.0 / 30.0)
    assert server.car.lane_assist_enabled is True
    assert server.car.trip_m < trip_before_reset  # this tick's coasting distance follows the reset
    connection.close()


def test_engine_stays_off_after_entering_until_started():
    """Getting in doesn't start the engine and getting out doesn't stop it;
    only E (the engine_on command) does."""
    import types
    from theroadragetrip.physics import Car
    from theroadragetrip.simulation import apply_enter_exit_vehicle

    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0, engine_on=False)
    pedestrian = types.SimpleNamespace(x=1.0, y=0.0, heading=0.0)
    from theroadragetrip.server import NullAudio

    audio = NullAudio()
    assert apply_enter_exit_vehicle(car, pedestrian, True, audio) is False
    assert car.engine_on is False

    # Jumping out with F (no E first) leaves a running engine idling.
    car.engine_on = True
    assert apply_enter_exit_vehicle(car, pedestrian, False, audio) is True
    assert car.engine_on is True


def _state(server):
    from theroadragetrip import protocol

    return protocol.build_state_message(
        tick=server._tick, world=server.world, car=server.car, on_foot=server._on_foot,
        player_pedestrian=server.world.player_pedestrian, game_time_seconds=server._game_time_seconds,
        camx=server._camx, camy=server._camy, rage_power=server._rage_power, water_elapsed=server._water_elapsed,
        current_way=server._current_way, language="en",
    )["state"]


def test_train_state_omits_the_unused_label():
    from types import SimpleNamespace

    from theroadragetrip import protocol

    train = SimpleNamespace(state="RUNNING", current_speed_mps=12.0,
                            vehicles=lambda: [(1.0, 2.0, 0.5, 20.0, "locomotive")])
    assert set(protocol._train_to_dict(train)) == {"id", "state", "speed", "cars"}


def test_road_name_and_limit_follow_the_way_under_the_taxi(tmp_path, monkeypatch):
    """godot-11: Pygame's HUD rules - the OSM name, else the highway type;
    no road (and no limit) off-road."""
    from types import SimpleNamespace

    server = _build_server(tmp_path, monkeypatch)
    assert _state(server)["road"] == {"name": None, "speed_limit_kmh": None, "layer": 0, "bridge": False}
    server._current_way = SimpleNamespace(name="Isokatu", highway="primary", speed_limit_kmh=40, layer=1, is_bridge=True)
    assert _state(server)["road"] == {"name": "Isokatu", "speed_limit_kmh": 40, "layer": 1, "bridge": True}
    server._current_way = SimpleNamespace(name="", highway="living_street", speed_limit_kmh=None)
    assert _state(server)["road"] == {"name": "Living Street", "speed_limit_kmh": None, "layer": 0, "bridge": False}


def test_speed_camera_notice_is_flagged_while_its_timer_runs(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    taxi_mgr = server.world.taxi_mgr
    assert _state(server)["taxi"]["speed_camera_notice"] is False
    taxi_mgr.speed_camera_notice_timer, taxi_mgr.speed_camera_notice_msg = 4.0, "Speed camera!"
    taxi_mgr.notification_msg, taxi_mgr.notification_timer = "Speed camera!", 4.0
    assert _state(server)["taxi"]["speed_camera_notice"] is True
    taxi_mgr.update(server.car, 4.1)  # the timer runs out: the message goes with it
    assert _state(server)["taxi"]["speed_camera_notice"] is False


def test_a_lightning_strike_sends_its_flash_and_one_thunder(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    weather = server.world.weather
    weather.update = lambda *args, **kwargs: None  # no weather of its own: the strike below is the only one
    server.tick(1.0 / 30.0)
    assert _state(server)["weather"]["lightning_intensity"] == 0.0
    weather.lightning_event_id += 1
    weather.lightning_intensity = 1.0
    sent = []
    server._broadcast_state = lambda **kwargs: sent.extend(kwargs["events"])
    for _ in range(5):
        server.tick(1.0 / 30.0)
    thunders = [e for e in sent if e.get("group") == "weather.thunder"]
    assert len(thunders) == 1  # once per strike, not every tick
    assert _state(server)["weather"]["lightning_intensity"] == 1.0


def test_traffic_light_phases_name_posts_in_the_chunks(tmp_path, monkeypatch):
    """godot-12: every phase in `state` belongs to a post some chunk carries."""
    server = _build_server(tmp_path, monkeypatch)
    light = server.world.traffic_mgr.traffic_lights[0]
    walker = server.world.player_pedestrian  # on foot at the start: phases follow the walker
    walker.x, walker.y = light.x, light.y
    phases = _state(server)["traffic_lights"]
    assert phases, "the sample map has traffic lights"
    posts = {str(post["id"]) for cid in server._chunks_index._chunks for post in server._chunks_index.message(cid)["traffic_lights"]}
    assert set(phases) <= posts
    assert set(phases.values()) <= {"green", "yellow", "red", "red+yellow", "all-red"}


def test_the_calendar_is_the_one_clock_and_carries_the_sun(tmp_path, monkeypatch):
    """godot-14: the server's GameCalendar drives game time, the date and the
    sun the client draws night from."""
    from datetime import datetime

    from theroadragetrip.calendar import solar_altitude_and_events_on

    server = _build_server(tmp_path, monkeypatch)
    assert server._game_time_seconds == server.calendar.time_seconds == 18 * 3600.0
    server.calendar.current = datetime(2026, 6, 21, 13, 0)  # midsummer noon in Oulu
    noon = server.calendar_state()
    assert noon["date"] == "2026-06-21" and noon["darkness"] == 0.0 and noon["sun_altitude_deg"] > 40.0
    server.calendar.current = datetime(2026, 12, 21, 20, 0)  # midwinter evening
    night = server.calendar_state()
    assert night["darkness"] == 1.0 and night["sun_altitude_deg"] < -12.0
    altitude, _, _ = solar_altitude_and_events_on(server.calendar.date, server.calendar.time_seconds,
                                                  server.world.sun_latitude, server.world.sun_longitude)
    assert night["sun_altitude_deg"] == round(altitude, 2)  # the real model, not a copy

    # Advancing: 60 game seconds per real second without a fare; past midnight the date and season move on.
    server.calendar.current = datetime(2026, 11, 30, 23, 59, 30)
    server.tick(1.0)
    assert server.calendar.current == datetime(2026, 12, 1, 0, 0, 30) and server._game_time_seconds == 30.0
    assert server.calendar_state()["time_scale"] == 60.0 and server.world.weather.season == server.calendar.season
    assert _state(server)["game_time_seconds"] == 30.0


def test_darkness_boundaries():
    from theroadragetrip.calendar import darkness_for_sun_altitude

    assert darkness_for_sun_altitude(6.0) == 0.0 and darkness_for_sun_altitude(30.0) == 0.0  # full day from 6 degrees up
    assert darkness_for_sun_altitude(-3.0) == 0.5  # halfway through dusk
    assert darkness_for_sun_altitude(-12.0) == 1.0 and darkness_for_sun_altitude(-40.0) == 1.0  # full night


def test_the_calendar_crosses_the_wire(tmp_path, monkeypatch):
    from theroadragetrip import protocol

    server = _build_server(tmp_path, monkeypatch)
    message = protocol.build_state_message(
        tick=1, world=server.world, car=server.car, on_foot=True, player_pedestrian=server.world.player_pedestrian,
        game_time_seconds=server._game_time_seconds, camx=0.0, camy=0.0, rage_power=0.0, water_elapsed=0.0,
        calendar=server.calendar_state())
    assert protocol.decode(protocol.encode(message))["state"]["calendar"] == server.calendar_state()
    old = protocol.build_state_message(  # a caller without a calendar (old server code): the field is just null
        tick=1, world=server.world, car=server.car, on_foot=True, player_pedestrian=server.world.player_pedestrian,
        game_time_seconds=0.0, camx=0.0, camy=0.0, rage_power=0.0, water_elapsed=0.0)
    assert old["state"]["calendar"] is None


def test_the_server_places_street_lights_as_pygame_does(tmp_path, monkeypatch):
    """godot-15: the same placement render/roads.py runs per view, once over the map."""
    from theroadragetrip.render import roads

    server = _build_server(tmp_path, monkeypatch)
    lights = server.world.street_light_points
    assert lights, "the sample map has lit roads"
    xs = [x for x, *_ in lights]; ys = [y for _, y, *_ in lights]
    work = roads._snapshot_street_light_job("t", (min(xs) - 50, min(ys) - 50, max(xs) + 50, max(ys) + 50), server.world.ways,
                                            None, server.world.buildings, None, server.world.street_lamps, server.world.street_lamp_grid)
    while not roads._advance_street_light_prep(work):
        pass
    while not roads._advance_street_light_placement(work):
        pass
    assert sorted(work["lamps"]) == sorted(lights)
    sent = [light for cid in server._chunks_index._chunks for light in server._chunks_index.message(cid)["street_lights"]]
    assert len(sent) == len(lights)  # every light in exactly one chunk


def test_the_season_weights_come_from_the_calendar(tmp_path, monkeypatch):
    from datetime import datetime

    server = _build_server(tmp_path, monkeypatch)
    server.calendar.current = datetime(2026, 1, 15, 12, 0)
    winter = server.calendar_state()["season"]
    server.calendar.current = datetime(2026, 7, 15, 12, 0)
    summer = server.calendar_state()["season"]
    assert winter[0] > 0.9 and summer[2] > 0.9  # [winter, spring, summer, autumn]
    look = server.calendar.seasonal_appearance
    assert summer == [round(w * 20.0) / 20.0 for w in (look.winter, look.spring, look.summer, look.autumn)]


def test_tyre_marks_flash_and_level_in_the_state(tmp_path, monkeypatch):
    """godot-16: per tick, the taxi's map level, its tyre mark (as main() decides
    it) and the flashing speed camera."""
    server = _build_server(tmp_path, monkeypatch)
    assert _state(server)["player"]["map_level"] == 0 and _state(server)["tire_mark"] is None
    assert _state(server)["speed_camera_flash"] is None
    server.world.taxi_mgr.speed_camera_flash_timer, server.world.taxi_mgr.speed_camera_flash_index = 0.35, 3
    assert _state(server)["speed_camera_flash"] == 3
    server._on_foot = False
    server.car.skid_amount = 1.0  # hard slip on asphalt or whatever is under the taxi
    assert server._tyre_mark(previous=(server.car.x - 1.0, server.car.y)) is not None
    assert server._tyre_mark(previous=(server.car.x, server.car.y)) is None  # not moving: nothing laid


def test_the_running_fare_crosses_the_wire(tmp_path, monkeypatch):
    """godot-final-03: the mission bar's live values, straight from TaxiManager.
    The meter's three are null until the meter starts (Pygame shows them only then)."""
    import json
    from datetime import datetime

    from theroadragetrip import protocol

    server = _build_server(tmp_path, monkeypatch)
    taxi = server.world.taxi_mgr
    taxi.fare_started_at = None
    taxi.elapsed_time = 0.0
    state = _state(server)["taxi"]
    assert state["elapsed_time"] == 0.0  # zero is sent, not omitted
    assert state["live_fare_cents"] is None and state["fare_distance_m"] is None and state["passenger_happiness"] is None

    taxi.fare_started_at = datetime(2026, 10, 6, 18, 0)
    taxi.elapsed_time, taxi.live_fare_cents, taxi.fare_distance_m, taxi.passenger_happiness = 61.5, 1234, 2345.6, 0.0
    state = _state(server)["taxi"]
    assert (state["elapsed_time"], state["live_fare_cents"], state["fare_distance_m"], state["passenger_happiness"]) == (61.5, 1234, 2345.6, 0.0)
    taxi.live_fare_cents, taxi.fare_distance_m, taxi.passenger_happiness = 0, 0.0, 100.0  # boundaries
    wire = json.loads(protocol.encode({"type": "state", "state": _state(server)}).decode())["state"]["taxi"]
    assert (wire["live_fare_cents"], wire["fare_distance_m"], wire["passenger_happiness"]) == (0, 0.0, 100.0)


def test_the_pump_in_refuelling_range_sends_its_price(tmp_path, monkeypatch):
    """godot-final-03: the gauge's "G: REFUEL" price is the nearest pump within
    the refuelling range - the same lookup and price refuelling charges."""
    from types import SimpleNamespace

    from theroadragetrip.fuel import FUEL_STATION_RANGE_M, fuel_station_price_cents, nearest_fuel_station
    from theroadragetrip.simulation import PlayerCommand

    server = _build_server(tmp_path, monkeypatch)
    car = server.car
    far = SimpleNamespace(kind="fuel", x=car.x + FUEL_STATION_RANGE_M + 0.5, y=car.y, id=11)
    server.world.scenery_objects = [o for o in getattr(server.world, "scenery_objects", ()) if getattr(o, "kind", None) != "fuel"] + [far]
    assert _state(server)["taxi"]["fuel_station_price_cents"] is None  # 8.5 m: out of range

    near = SimpleNamespace(kind="fuel", x=car.x + 3.0, y=car.y, id=12)
    nearer = SimpleNamespace(kind="fuel", x=car.x, y=car.y + 2.0, id=13)
    server.world.scenery_objects += [near, nearer]
    assert fuel_station_price_cents(near) != fuel_station_price_cents(nearer)  # so the choice shows
    price = _state(server)["taxi"]["fuel_station_price_cents"]
    assert nearest_fuel_station(server.world.scenery_objects, car.x, car.y) is nearer
    assert price == fuel_station_price_cents(nearer)

    # Refuelling charges exactly that price.
    server._on_foot = False
    car.speed, car.fuel_l = 0.0, car.fuel_capacity_l - 10.0
    server.world.taxi_mgr.balance_cents = 100_000
    server._latest_command = PlayerCommand()
    server._pending_refuels = 1
    server.tick(1.0 / 30.0)
    assert 100_000 - server.world.taxi_mgr.balance_cents == pytest.approx(10.0 * price, abs=2)


def test_the_navigation_route_crosses_the_wire(tmp_path, monkeypatch):
    """godot-final-04: state.navigation.points - the server's cached route,
    world metres, unchanged through encode/decode; discrete under interpolation."""
    import json

    from theroadragetrip import protocol

    server = _build_server(tmp_path, monkeypatch)
    server.world.taxi_mgr.current_passenger = None
    server.tick(1.0 / 30.0)
    assert server.navigation.points == [] and _state(server)["navigation"] == {"points": []}  # no caller value: empty, never missing
    car = server.car
    points = [[1.25, -2.5], [100.0, 3.75], [250.5, 3.75]]
    server.navigation.points = points  # what a finished route publishes
    message = protocol.build_state_message(
        tick=1, world=server.world, car=car, on_foot=False, player_pedestrian=server.world.player_pedestrian,
        game_time_seconds=0.0, camx=0.0, camy=0.0, rage_power=0.0, water_elapsed=0.0,
        navigation={"points": server.navigation.points})
    wire = protocol.decode(protocol.encode(message))
    assert wire["state"]["navigation"]["points"] == points  # a new client's first state carries the cached route
    other = json.loads(json.dumps(wire["state"]))
    other["navigation"] = {"points": [[0.0, 0.0], [9.0, 9.0]]}
    blended = protocol.interpolate_state(wire["state"], other, 0.5)
    assert blended["navigation"]["points"] == [[0.0, 0.0], [9.0, 9.0]]  # the newest route, never a blend


def test_road_rage_is_the_simulations_and_runs_once_per_press(tmp_path, monkeypatch):
    """godot-final-05: SPACE moved from Pygame's event loop into the shared
    simulation - cost 0.25, the 0.45 horn, a shout for 5 s, the nearest
    driver ahead provoked once; nothing below 0.25."""
    import json
    from pathlib import Path

    from theroadragetrip import protocol
    from theroadragetrip.simulation import RAGE_SHOUTS, PlayerCommand

    server = _build_server(tmp_path, monkeypatch)
    calls = []
    real_trigger = server.world.npc_manager.trigger_road_rage
    monkeypatch.setattr(server.world.npc_manager, "trigger_road_rage",
                        lambda *a, **k: calls.append((a, k)) or real_trigger(*a, **k))
    server._on_foot = False
    server.car.speed = 0.0
    server._latest_command = PlayerCommand()

    sent = []
    real_broadcast = server._broadcast_state
    monkeypatch.setattr(server, "_broadcast_state", lambda **k: sent.append(k.get("events") or []) or real_broadcast(**k))

    server._rage_power = 0.2  # below the cost: nothing at all
    server._pending_road_rages = 1
    server.tick(1.0 / 30.0)
    assert calls == [] and server._road_rage is None and not any(e.get("group") == "vehicle.horn" for e in sent[-1])
    assert server._rage_power == pytest.approx(0.2, abs=0.01)

    server._rage_power = 0.25  # exactly the cost: accepted, down to zero
    server._pending_road_rages = 1
    at = (server.car.x, server.car.y, server.car.heading, server.world.traffic_mgr.sim_time)  # as the tick starts (main(): the press before the step)
    server.tick(1.0 / 30.0)
    assert server._rage_power == pytest.approx(0.0, abs=0.01)
    assert [e for e in sent[-1] if e.get("group") == "vehicle.horn"] == [{"type": "sound", "group": "vehicle.horn"}]
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == at[:3] and kwargs == {"sim_time": at[3]}
    shout = _state(server)  # no road_rage passed: the builder's default
    state = protocol.build_state_message(
        tick=1, world=server.world, car=server.car, on_foot=False, player_pedestrian=server.world.player_pedestrian,
        game_time_seconds=0.0, camx=0.0, camy=0.0, rage_power=0.0, water_elapsed=0.0, road_rage=server._road_rage)["state"]
    assert state["road_rage"]["text"] in RAGE_SHOUTS and state["road_rage"]["timer"] == 5.0
    assert shout["road_rage"] is None

    for _ in range(30):  # the press is not replayed; the shout counts down in real time
        server.tick(1.0 / 30.0)
    assert len(calls) == 1 and server._road_rage["timer"] == pytest.approx(4.0, abs=0.01)
    for _ in range(130):
        server.tick(1.0 / 30.0)
    assert server._road_rage is None  # expired and cleared, never negative

    server._rage_power = 0.6  # two distinct presses, two actions on two ticks
    server._pending_road_rages = 2
    server.tick(1.0 / 30.0)
    server.tick(1.0 / 30.0)
    server.tick(1.0 / 30.0)
    assert len(calls) == 3 and server._rage_power == pytest.approx(0.1, abs=0.01)
    assert sum(1 for events in sent[-3:] for e in events if e.get("group") == "vehicle.horn") == 2

    wire = protocol.decode(protocol.encode({"type": "state", "version": protocol.PROTOCOL_VERSION, "state": state}))
    later = json.loads(json.dumps(wire["state"]))
    later["road_rage"] = None
    assert protocol.interpolate_state(wire["state"], later, 0.5)["road_rage"] is None  # discrete: the newest
    main_source = Path(protocol.__file__).with_name("main").joinpath("__init__.py").read_text(encoding="utf-8")
    assert "trigger_road_rage" not in main_source and "RAGE_SHOUT_COST" not in main_source  # Pygame only queues the press now


def test_weather_audio_facts_cross_the_wire(tmp_path, monkeypatch):
    """godot-final-06: is_thunderstorm and the gust-adjusted wind vector,
    straight from WeatherSystem; nothing else new (no particles, ripples,
    splashes, volumes or a made-up precipitation intensity)."""
    import json

    from theroadragetrip import protocol
    from theroadragetrip.weather import WeatherType

    server = _build_server(tmp_path, monkeypatch)
    weather = server.world.weather
    for kind in (WeatherType.CLEAR, WeatherType.RAIN, WeatherType.SLUSH, WeatherType.SNOW):
        weather.weather_type = kind
        assert _state(server)["weather"]["weather_type"] == kind.value
    weather.is_thunderstorm = True
    state = _state(server)["weather"]
    assert state["is_thunderstorm"] is True
    assert state["wind_vector_mps"] == [round(v, 3) for v in weather.wind_vector_mps]
    assert set(state) == {"weather_type", "wetness", "lightning_intensity", "is_thunderstorm", "wind_vector_mps",
                          "source", "temperature_c"}
    for vector in ((0.0, 0.0), (3.25, -7.5), (-12.0, 4.0), (float("nan"), float("inf"))):
        monkeypatch.setattr(type(weather), "wind_vector_mps", property(lambda self, v=vector: v))  # restored after the test
        wire = json.loads(json.dumps(_state(server)["weather"]))["wind_vector_mps"]
        assert wire == [v if v == v and abs(v) != float("inf") else 0.0 for v in vector]


def test_historical_weather_drives_the_servers_weather_and_temperature(tmp_path, monkeypatch):
    """main()'s historical weather on the server: the FMI hour replaces the
    generated precipitation, its temperature reaches the state; off: generated
    weather and the climate's typical temperature."""
    from theroadragetrip.weather import WeatherType
    from theroadragetrip.weather_history import HourlyWeather

    server = _build_server(tmp_path, monkeypatch)
    server.weather_history = None  # off (whatever the local config says)
    server.tick(1.0 / 30.0)
    assert _state(server)["weather"]["source"] == "generated"
    assert isinstance(_state(server)["weather"]["temperature_c"], float)

    class FakeHistory:
        def request(self, start, end):
            pass

        def get(self, moment):
            return HourlyWeather(temperature_c=-3.5, precipitation_mm=2.0, wawa=71)

        def source_at(self, moment):
            return "observed"

    server.weather_history = FakeHistory()
    server.tick(1.0 / 30.0)
    weather = _state(server)["weather"]
    assert weather["source"] == "observed" and weather["temperature_c"] == -3.5
    assert server.world.weather.weather_type == WeatherType.SNOW


def test_start_time_starts_the_calendar_clamped_to_a_year_back(tmp_path, monkeypatch):
    """The gig start picker (Pygame's choose_start_datetime) via --start-time."""
    from datetime import date, datetime, timedelta

    picked = (datetime.now() - timedelta(days=40)).replace(hour=7, minute=15, second=0, microsecond=0)
    server = _build_server(tmp_path, monkeypatch, ["--start-time", picked.isoformat()])
    assert server.calendar.current == picked
    assert _build_server(tmp_path, monkeypatch, ["--start-time", "2001-02-03T04:05"]).calendar.current.date() >= date.today() - timedelta(days=366)


def test_npc_brake_lamps_when_slowing_or_standing_in_traffic():
    from types import SimpleNamespace

    from theroadragetrip.server import npc_braking

    def npc(speed, state="DRIVING", on_foot=False):
        return SimpleNamespace(speed=speed, state=state, is_on_foot=on_foot)

    dt = 1 / 30
    assert npc_braking(npc(10.0 - 3.0 * dt), 10.0, dt)  # 3 m/s² down
    assert not npc_braking(npc(10.0 - 0.2 * dt), 10.0, dt)  # coasting
    assert not npc_braking(npc(10.0 + 1.0 * dt), 10.0, dt)  # speeding up
    assert npc_braking(npc(0.0), 0.0, dt)  # waiting at a light
    assert not npc_braking(npc(0.0, "PARKED"), 0.0, dt)
    assert not npc_braking(npc(-1.0), -0.5, dt)  # reversing: the reversing lamp, not the brakes
    assert not npc_braking(npc(0.0, on_foot=True), 0.0, dt)


def test_the_world_message_carries_the_start_sign(tmp_path, monkeypatch):
    """main()'s draw_game_start_overlay: the city and a 24-hour forecast,
    now and every 6 hours; the engine starts off (E after getting in)."""
    from theroadragetrip import protocol

    server = _build_server(tmp_path, monkeypatch)
    forecast = server.start_forecast
    assert len(forecast) == 5 and forecast[0]["source"] == "generated"
    assert all(set(line) == {"time", "temperature_c", "weather", "source"} for line in forecast)
    assert forecast[0]["weather"] in ("clear", "rain", "slush", "snow", "thunderstorm")
    message = protocol.build_world_message((0.0, 0.0), 250.0, "p1", "Oulu", forecast)
    assert message["city"] == "Oulu" and message["forecast"] == forecast
    assert server.car.engine_on is False


def test_f12_debug_snapshot_is_written_by_the_server(tmp_path, monkeypatch):
    import json

    server = _build_server(tmp_path, monkeypatch)
    path = tmp_path / "shots" / "screenshot_1.json"
    server._debug_snapshots.append(str(path))
    server.tick(1 / 30)
    data = json.loads(path.read_text())
    assert data and isinstance(data, dict)
