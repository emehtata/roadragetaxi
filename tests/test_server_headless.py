"""client-server-02.md step 18: the server works without any client
connected, with no graphical environment required."""

import sys

import pytest


def _build_server(tmp_path, monkeypatch, extra=()):
    argv = ["prog", "--use-sample", "--no-menu", "--no-historical-weather", *extra]
    monkeypatch.setattr(sys, "argv", argv)
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.server import SimulationServer

    args, config = parse_server_args()
    return SimulationServer(args, config)


def test_startup_progress_reaches_the_render_chunk_stage(tmp_path, monkeypatch):
    import json

    status = tmp_path / "startup.json"
    _build_server(tmp_path, monkeypatch, ["--startup-progress", str(status)])
    report = json.loads(status.read_text())
    assert report["stage"] == "chunks"
    assert report["history"] == ["starting", "world", "weather", "lights", "chunks"]
    assert "buildings" in report["detail"]


@pytest.mark.parametrize("hour,minute,second,expected", [(17, 0, 0, True), (18, 0, 0, True),
                                                       (20, 29, 59, True), (20, 30, 0, False), (23, 0, 0, False)])
def test_match_day_notice_excludes_finished_games(tmp_path, monkeypatch, hour, minute, second, expected):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import Mock

    server = _build_server(tmp_path, monkeypatch)
    server.calendar.current = datetime(2026, 10, 17, hour, minute, second)
    game = SimpleNamespace(start=datetime(2026, 10, 17, 18), home_team="Kärpät", away_team="Sport", venue_name="Arena")
    server.world.arena_crowds = SimpleNamespace(schedule_on=lambda day: [game])
    notices = []
    monkeypatch.setattr(server, "_notify", lambda *args: notices.append(args))
    connection = Mock()
    server._on_client_connect(connection)
    assert bool(notices) == expected
    assert server._game_day_notice_shown
    server._on_client_connect(connection)
    assert len(notices) == int(expected)  # do not repeat the notice on reconnect


def test_group_fare_mass_and_cancellation_release_everyone_once(tmp_path, monkeypatch):
    from theroadragetrip.taxi import TaxiPassenger, TaxiState, TaxiTarget

    server = _build_server(tmp_path, monkeypatch)
    taxi = server.world.taxi_mgr
    parent = taxi.residents.create(age=40)
    child = taxi.residents.create(age=9)
    child.parent_ids = {parent.resident_id}
    pickup = TaxiTarget(server.car.x, server.car.y, "Pickup")
    dropoff = TaxiTarget(server.car.x + 1000, server.car.y, "Dropoff")
    party = TaxiPassenger("Parent", pickup, dropoff, resident_id=parent.resident_id, weight_kg=80,
                         boarded=True, nausea_delay=float("inf"))
    party.companions = [TaxiPassenger("Child", pickup, dropoff, resident_id=child.resident_id,
                                     weight_kg=30, boarded=True, nausea_delay=float("inf"))]
    taxi.current_passenger = party
    taxi.state = TaxiState.DRIVING_TO_DROPOFF
    monkeypatch.setattr(taxi, "generate_offers", lambda *a, **kw: [])
    server.tick(1 / 30)
    assert server.car.passenger_mass_kg == 110
    released = []
    monkeypatch.setattr(server.world.pedestrian_mgr, "spawn_pedestrian_at",
                        lambda *a, **kw: released.append(kw["resident_id"]))
    taxi.discard_mission(server.car.x, server.car.y)
    server.tick(1 / 30)
    server.tick(1 / 30)
    assert sorted(released) == sorted([parent.resident_id, child.resident_id])
    assert server.car.passenger_mass_kg == 0


def test_sinking_is_cancelled_when_current_geometry_is_dry(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    server._on_foot = False
    server._water_elapsed = 4.99  # a previous map tile incorrectly reported water
    server.world.waters = []
    origin = (server.car.x, server.car.y)
    server.tick(1 / 30)
    assert server._water_elapsed == 0
    assert (server.car.x, server.car.y) == origin  # no erroneous water respawn


def test_sinking_continues_when_the_car_really_is_in_open_water(tmp_path, monkeypatch):
    from theroadragetrip.osm import Water
    from datetime import datetime

    server = _build_server(tmp_path, monkeypatch)
    server.calendar.current = datetime(2026, 9, 30, 19)
    server._on_foot = False
    server._water_elapsed = 1
    server.car.x = server.car.y = 1_000_000  # outside the sample's roads and obstacles
    x, y = server.car.x, server.car.y
    server.world.waters = [Water([(x - 20, y - 20), (x + 20, y - 20), (x + 20, y + 20),
                                  (x - 20, y + 20), (x - 20, y - 20)], "river", True)]
    server.tick(1 / 30)
    assert server._water_elapsed > 1


def test_server_builds_and_ticks_with_no_client_connected(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    assert server.world.speed_cameras == []
    assert server._chunks_index._encoded == {}  # distant chunks are encoded lazily, not on startup
    for _ in range(30):
        server.tick(1.0 / 30.0)
    assert server._tick == 30
    assert server.world.speed_cameras == []


def test_runtime_camera_is_sent_to_loaded_clients_with_stable_id(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from theroadragetrip.map_chunks import cell_of, chunk_id
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.osm import Way

    server = _build_server(tmp_path, monkeypatch)
    x, y = server.car.x, server.car.y
    server.world.spatial_grid = SpatialWayGrid([
        Way([(x + 600, y), (x + 1600, y)], "primary", 4),
    ])
    server._camera_spawner.remaining_s = 0
    # Capture only sends for a camera's loaded chunk, not all clients/chunks.
    sent = []
    class Connection:
        def send(self, message):
            sent.append(message)
    connection = Connection()
    loaded = {chunk_id(*cell_of(x + offset, y - 5)) for offset in range(500, 1801, 100)}
    server._client_chunks = {connection: (loaded, None)}
    server._update_speed_cameras(1 / 30)
    assert len(server.world.speed_cameras) == 1
    camera = server.world.speed_cameras[0]
    cid = chunk_id(*cell_of(camera.x, camera.y))
    assert server._chunks_index.message(cid)["speed_cameras"][0][0] == 0
    assert sent == [server._chunks_index.encoded(cid)]
    server.car.x += 4000
    server.world.spatial_grid = SpatialWayGrid([
        Way([(x + 4600, y), (x + 5600, y)], "primary", 4),
    ])
    server._camera_spawner.remaining_s = 0
    server._update_speed_cameras(1 / 30)
    assert len(server.world.speed_cameras) == 2
    second = server.world.speed_cameras[1]
    second_cid = chunk_id(*cell_of(second.x, second.y))
    assert server._chunks_index.message(second_cid)["speed_cameras"][0][0] == 1
    assert server._chunks_index.message(cid)["speed_cameras"][0][0] == 0
    assert len(sent) == 1  # the second camera's chunk isn't loaded by this client
    # Existing-camera IDs survive the next creation and an in-flight map build
    # cannot race an append into the index it is replacing.
    server._map_streamer = SimpleNamespace(hold=True)
    server._camera_spawner.remaining_s = 0
    server._update_speed_cameras(1000)
    assert server.world.speed_cameras == [camera, second]


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


def test_moving_tractor_clears_road_snow_and_reports_it_to_client(tmp_path, monkeypatch):
    from theroadragetrip.npc import place_parked_npc
    from theroadragetrip.weather import WeatherType

    server = _build_server(tmp_path, monkeypatch)
    weather = server.world.weather
    weather._automatic = False
    weather.weather_type = WeatherType.CLEAR
    weather.road_snow = 3.0
    tractor = place_parked_npc(999, (server.car.x, server.car.y), None, vehicle_type="tractor")
    tractor.way = server.world.ways[0]
    tractor.car.speed = 1.0
    manager = server.world.npc_manager
    manager.vehicles[:] = [tractor]
    manager.drivers[tractor.vehicle_id] = object()
    monkeypatch.setattr(manager, "update", lambda *args, **kwargs: None)

    server.tick(1.0 / 30.0)

    assert manager.snowy  # ploughs stay active after the snowfall stops
    assert weather.plowed_cells
    wire = _state(server)["weather"]
    assert wire["road_snow"] == 3.0
    assert wire["plowed_cells"][0][2] == 3.0


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


def test_ilokapina_blocks_taxi_requires_paid_rage_and_syncs_phone_notice(tmp_path, monkeypatch):
    from theroadragetrip.osm import Way
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.protests import ProtestGroup
    from theroadragetrip.simulation import PlayerCommand

    server = _build_server(tmp_path, monkeypatch, ["--npc-vehicle-count", "0", "--pedestrian-count", "0"])
    road = Way([(1_000_000, 1_000_000), (1_002_000, 1_000_000)], "primary", 7)
    server.world.ways = [road]
    server.world.spatial_grid = SpatialWayGrid([road])
    car = server.car
    car.x, car.y, car.heading, car.speed = 1_000_100, 999_998, 0, 210/3.6
    car.engine_on = True
    server._current_way, server._on_foot = road, False
    group = ProtestGroup(1, road, car.x+6, 1_000_000, 0, 24, 0)
    manager = server.world.protests
    manager.settings.enabled = False
    manager.groups = [group]
    server._latest_command = PlayerCommand(throttle=1, speed_limiter_enabled=False)
    start = car.x
    server.tick(0.5)
    assert car.x == start and car.speed == 0  # swept movement, not endpoint-only collision
    assert group.state == "SITTING"
    server._rage_power, server._pending_road_rages = 0.1, 1
    server.tick(1/30)
    assert group.state == "SITTING"
    server._rage_power, server._pending_road_rages = 1, 1
    server.tick(1/30)
    assert group.state == "ALARMED" and server._rage_power < 0.8
    server._latest_command = PlayerCommand(throttle=0, speed_limiter_enabled=False)
    for _ in range(150):
        server.tick(1/30)
    assert group.state == "CLEARED"
    state = _state(server)
    assert state["protest_active"] and state["protests"][0]["state"] == "CLEARED"
    assert len(state["protests"][0]["members"]) == 24
    assert _state(server)["protests"] == state["protests"]  # late join gets full current state
    server._latest_command = PlayerCommand(throttle=1, speed_limiter_enabled=False)
    for _ in range(90):
        server.tick(1/30)
    assert car.x > group.x + 8
    manager.groups.clear()
    assert not _state(server)["protest_active"]


def test_unfinished_garage_cannot_swallow_taxi_at_speed(tmp_path, monkeypatch):
    from theroadragetrip.level_transitions import close_garage_roads
    from theroadragetrip.osm import LevelConnector, Way
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.simulation import PlayerCommand
    from theroadragetrip.world_loader import level_structures

    server = _build_server(tmp_path, monkeypatch, ["--npc-vehicle-count", "0", "--pedestrian-count", "0"])
    road = Way([(1_000_000, 1_000_000), (1_000_200, 1_000_000)], "service", 4, osm_id=1)
    ramp = Way([(1_000_200, 1_000_000), (1_000_230, 1_000_000)], "service", 4, osm_id=2, level="0;-2")
    entrance = LevelConnector("node", 10, "parking_entrance", 1_000_200, 1_000_000, road_osm_ids=(1, 2))
    server.world.ways = [road, ramp]
    close_garage_roads(server.world.ways)
    server.world.spatial_grid = SpatialWayGrid(server.world.ways)
    for key, value in level_structures(server.world.ways, [], [entrance]).items():
        setattr(server.world, key, value)
    car = server.car
    car.x, car.y, car.heading, car.speed = 1_000_190, 1_000_000, 0, 210/3.6
    car.engine_on = True
    server._on_foot, server._current_way = False, road
    server._latest_command = PlayerCommand(throttle=1, speed_limiter_enabled=False)
    server.tick(0.5)
    assert car.x == 1_000_190 and car.speed == 0 and car.map_level == 0
    assert "not available" in server.world.taxi_mgr.notification_msg
    car.map_level = -2
    server.tick(1/30)
    assert car.map_level == 0  # discard stale underground mode while support is disabled


def test_client_view_reaches_tick_and_discards_only_unseen_ambient_state(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from theroadragetrip.protocol import LOCAL_PLAYER_ID

    server = _build_server(tmp_path, monkeypatch)
    x, y = server.car.x, server.car.y
    view = [x - 100, y - 70, x + 100, y + 70]
    connection = Mock()
    connection.is_closed = False
    connection.try_recv_all.return_value = [{"type": "command", "player_id": LOCAL_PLAYER_ID,
                                            "command": {"view_bounds": view}}]
    server._clients.append(connection)
    server._apply_incoming_messages()
    assert server._visible_bounds() == tuple(view)
    connection.try_recv_all.return_value = []
    pedestrians = server.world.pedestrian_mgr
    near = pedestrians.spawn_pedestrian_at(x, y, 0)
    far = pedestrians.spawn_pedestrian_at(x, y, 0)
    assert near is not None and far is not None
    far.x, far.y = x + 2000, y + 2000
    pedestrians.add_pedestrian(near)
    pedestrians.add_pedestrian(far)
    server.world.taxi_mgr.vomit_puddles[:] = [(x, y), (x + 2000, y + 2000)]
    server.tick(1 / 30)
    assert near in pedestrians.pedestrians and far not in pedestrians.pedestrians
    assert server.world.taxi_mgr.vomit_puddles == [(x, y)]
    server._server_time += 3
    assert server._visible_bounds() is None  # stale view cannot constrain a legacy/headless tick


def test_vomit_puddles_reach_godot(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    server.world.taxi_mgr.vomit_puddles.append((server.car.x + 1.0, server.car.y))
    server.world.pedestrian_mgr.vomit_puddles.append((server.car.x - 1.0, server.car.y))
    server.world.pedestrian_mgr.vomit_footprints.append((server.car.x, server.car.y, 0.5))
    assert _state(server)["vomit_puddles"] == [
        [server.car.x + 1.0, server.car.y], [server.car.x - 1.0, server.car.y],
    ]
    assert _state(server)["vomit_footprints"] == [[server.car.x, server.car.y, 0.5]]


def test_train_state_omits_the_unused_label():
    from types import SimpleNamespace

    from theroadragetrip import protocol

    train = SimpleNamespace(state="RUNNING", current_speed_mps=12.0,
                            vehicles=lambda: [(1.0, 2.0, 0.5, 20.0, "locomotive")])
    assert set(protocol._train_to_dict(train)) == {"id", "state", "speed", "cars"}


def test_road_name_and_limit_follow_the_way_under_the_taxi(tmp_path, monkeypatch):
    """godot-11: the HUD's road name - the OSM name, else the highway type;
    no road (and no limit) off-road."""
    from types import SimpleNamespace

    server = _build_server(tmp_path, monkeypatch)
    assert _state(server)["road"] == {"name": None, "speed_limit_kmh": None, "layer": 0, "bridge": False}
    server._current_way = SimpleNamespace(name="Isokatu", highway="primary", speed_limit_kmh=40, layer=1, is_bridge=True)
    assert _state(server)["road"] == {"name": "Isokatu", "speed_limit_kmh": 40, "layer": 1, "bridge": True}
    server._current_way = SimpleNamespace(name="", highway="living_street", speed_limit_kmh=None)
    assert _state(server)["road"] == {"name": "Living Street", "speed_limit_kmh": None, "layer": 0, "bridge": False}


def test_speed_camera_detects_a_fast_drive_on_the_first_tick(tmp_path, monkeypatch):
    import math
    from theroadragetrip.police import SpeedCamera

    server = _build_server(tmp_path, monkeypatch, ["--npc-vehicle-count", "0", "--pedestrian-count", "0"])
    server._on_foot = False
    server._slow_check_elapsed = 0.0
    car = server.car
    car.engine_on = True
    car.speed = 200 / 3.6
    server.world.speed_cameras = [SpeedCamera(
        car.x + 20 * math.cos(car.heading), car.y + 20 * math.sin(car.heading), car.heading, 50, None,
        layer=car.layer, map_level=car.map_level,
    )]
    before = server.world.taxi_mgr.total_score
    server.tick(1 / 30)
    assert server.world.taxi_mgr.total_score == before - 300
    assert server.world.taxi_mgr.speed_camera_flash_index == 0
    assert server.world.taxi_mgr.speed_camera_notice_timer > 0
    server.tick(1 / 30)
    assert server.world.taxi_mgr.total_score == before - 300


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


def test_the_driver_on_foot_turns_on_the_spot(tmp_path, monkeypatch):
    from theroadragetrip.simulation import PlayerCommand

    server = _build_server(tmp_path, monkeypatch)
    walker = server.world.player_pedestrian  # on foot at the start
    start = (walker.x, walker.y, walker.heading)
    server._latest_command = PlayerCommand(turn=1.0)
    for _ in range(10):
        server.tick(1.0 / 30.0)
    assert walker.heading != start[2] and (walker.x, walker.y) == start[:2]


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


def test_holidays_follow_the_server_calendar(tmp_path, monkeypatch):
    from datetime import datetime

    server = _build_server(tmp_path, monkeypatch)
    server.calendar.current = datetime(2026, 12, 31, 23, 59, 59)
    assert server.calendar_state()["holidays"]["fireworks"]
    server.calendar.advance(2)
    assert server.calendar_state()["holidays"]["fireworks"]
    server.calendar.current = datetime(2027, 1, 1, 2)
    assert not any(server.calendar_state()["holidays"].values())




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


def test_measured_snow_depth_decides_the_snow_cover(tmp_path, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace

    server = _build_server(tmp_path, monkeypatch)
    server.calendar.current = datetime(2026, 1, 15, 12, 0)
    depth = {"cm": 0.0}
    server.weather_history = SimpleNamespace(get=lambda moment: SimpleNamespace(snow_depth_cm=depth["cm"]))
    assert server.calendar_state()["season"][0] == 0.0  # a snowless January: bare ground
    depth["cm"] = 30.0
    assert server.calendar_state()["season"][0] == 1.0
    server.calendar.current = datetime(2026, 10, 10, 12, 0)  # early snow in October
    assert server.calendar_state()["season"][0] == 1.0


def test_tyre_marks_flash_and_level_in_the_state(tmp_path, monkeypatch):
    """godot-16: per tick, the taxi's map level, its tyre mark and the flashing speed camera."""
    server = _build_server(tmp_path, monkeypatch)
    assert _state(server)["player"]["map_level"] == 0 and _state(server)["tire_mark"] is None
    assert _state(server)["speed_camera_flash"] is None
    server.world.taxi_mgr.speed_camera_flash_timer, server.world.taxi_mgr.speed_camera_flash_index = 0.35, 3
    assert _state(server)["speed_camera_flash"] == 3
    server._on_foot = False
    server.world.weather.wetness = 0.0  # a dry road (an autumn start may begin in rain, the road wet)
    server.car.skid_amount = 1.0  # hard slip on asphalt or whatever is under the taxi
    assert server._tyre_mark(previous=(server.car.x - 1.0, server.car.y)) is None  # no gray cornering/acceleration trail
    server.car.braking = True
    mark = server._tyre_mark(previous=(server.car.x - 1.0, server.car.y))
    assert mark is not None and mark["kind"] == "rubber" and mark["intensity"] == 1.0
    assert server._tyre_mark(previous=(server.car.x, server.car.y)) is None  # not moving: nothing laid


def test_normal_driving_leaves_tracks_on_snowy_roads_but_not_plowed_roads(tmp_path, monkeypatch):
    server = _build_server(tmp_path, monkeypatch)
    server._on_foot = False
    road = server.world.ways[0]
    server.car.x, server.car.y = road.points_m[0]
    server.car.speed = 2.0
    server.car.skid_amount = 0.0
    weather = server.world.weather
    weather.road_snow = 3.0
    previous = (server.car.x - 1.0, server.car.y)
    assert server._tyre_mark(previous) == {"kind": "snow", "intensity": 1.0, "front": True}
    assert server._tyre_mark((server.car.x, server.car.y)) is None
    weather.plow_road((server.car.x, server.car.y), (server.car.x, server.car.y))
    assert server._tyre_mark(previous) is None
    server.car.map_level = -1
    weather.plowed_cells.clear()
    assert server._tyre_mark(previous) is None


def test_the_running_fare_crosses_the_wire(tmp_path, monkeypatch):
    """godot-final-03: the mission bar's live values, straight from TaxiManager.
    The meter's three are null until the meter starts."""
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
    server._on_foot = True
    car.speed, car.fuel_l = 0.0, car.fuel_capacity_l - 10.0
    car.engine_on = False
    server.world.player_pedestrian.x, server.world.player_pedestrian.y = car.x, car.y
    server.world.taxi_mgr.balance_cents = 100_000
    server._latest_command = PlayerCommand()
    server._pending_refuels = 1
    server.tick(1.0 / 30.0)
    assert car.fuel_l == pytest.approx(car.fuel_capacity_l - 10.0 + 0.5 / 30.0)
    assert 100_000 - server.world.taxi_mgr.balance_cents == pytest.approx(0.5 / 30.0 * price, abs=1)


def test_the_navigation_route_crosses_the_wire(tmp_path, monkeypatch):
    """godot-final-04: state.navigation.points - the server's cached route,
    world metres, unchanged through encode/decode."""

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


def test_road_rage_is_the_simulations_and_runs_once_per_press(tmp_path, monkeypatch):
    """godot-final-05: SPACE is the simulation's - cost 0.25, the 0.45 horn,
    a shout for 5 s and arcade clearance once; nothing below 0.25."""

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
    at = (server.car.x, server.car.y, server.car.heading, server.world.traffic_mgr.sim_time)  # as the tick starts (the press before the step)
    server.tick(1.0 / 30.0)
    assert server._rage_power == pytest.approx(0.0, abs=0.01)
    assert [e for e in sent[-1] if e.get("group") == "vehicle.horn"] == [{"type": "sound", "group": "vehicle.horn"}]
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == () and kwargs == {"sim_time": at[3]}
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


@pytest.mark.parametrize("rage", [False, True])
def test_210_kmh_shout_clears_a_close_npc_before_the_collision_pass(tmp_path, monkeypatch, rage):
    from theroadragetrip.npc import NPCState, NPCVehicle
    from theroadragetrip.osm import Way
    from theroadragetrip.physics import Car, SpatialWayGrid
    from theroadragetrip.simulation import PlayerCommand

    server = _build_server(tmp_path, monkeypatch)
    # Isolated road, clear of the sample map's buildings, water and signals.
    road = Way([(1_000_000, 1_000_000), (1_002_000, 1_000_000)], "primary", 7)
    server.world.ways = [road]
    server.world.spatial_grid = SpatialWayGrid([road])
    server.car.x, server.car.y, server.car.heading = 1_000_100, 999_998, 0
    server.car.speed = 210 / 3.6
    server.car.engine_on = True
    server._current_way = road
    server._on_foot = False
    vehicle = NPCVehicle(12345, Car(server.car.x + 5, server.car.y, 0, 0), state=NPCState.WAITING)
    manager = server.world.npc_manager
    manager.vehicles = [vehicle]
    manager.drivers.clear()
    manager._previous_player_pose = server.car.x, server.car.y, server.car.heading
    manager.rebuild_spatial_grid()
    server._latest_command = PlayerCommand(throttle=1, speed_limiter_enabled=False)
    server._rage_power = 1 if rage else 0
    server._pending_road_rages = 1
    server.tick(1 / 30)
    if rage:
        assert vehicle.vehicle_id in manager.road_rage.held
        assert vehicle.state != NPCState.CRASHED
        assert server.world.taxi_mgr.taxi_smoke_timer == 0
        assert not manager.accidents
    else:
        assert vehicle.state == NPCState.CRASHED


def test_weather_audio_facts_cross_the_wire(tmp_path, monkeypatch):
    """godot-final-06: is_thunderstorm and the gust-adjusted wind vector,
    straight from WeatherSystem; nothing else new (no particles, ripples,
    splashes, volumes or a made-up precipitation intensity)."""
    import json

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
                          "source", "temperature_c", "road_snow", "plowed_cells", "cloud_cover"}
    for vector in ((0.0, 0.0), (3.25, -7.5), (-12.0, 4.0), (float("nan"), float("inf"))):
        monkeypatch.setattr(type(weather), "wind_vector_mps", property(lambda self, v=vector: v))  # restored after the test
        wire = json.loads(json.dumps(_state(server)["weather"]))["wind_vector_mps"]
        assert wire == [v if v == v and abs(v) != float("inf") else 0.0 for v in vector]


def test_historical_weather_drives_the_servers_weather_and_temperature(tmp_path, monkeypatch, caplog):
    """Historical weather on the server: the FMI hour replaces the
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
            return HourlyWeather(temperature_c=-3.5, precipitation_mm=2.0, wawa=71,
                                 wind_speed_mps=6.5, wind_from_deg=225.0, snow_depth_cm=2.0)

        def source_at(self, moment):
            return "observed"

    server.weather_history = FakeHistory()
    import logging
    with caplog.at_level(logging.INFO, logger="theroadragetrip.server"):
        server.tick(1.0 / 30.0)
        server.tick(1.0 / 30.0)
        forecast = server._forecast()
    assert sum("FMI weather now" in record.message for record in caplog.records) == 1
    assert any("FMI weather " in record.message for record in caplog.records)
    weather = _state(server)["weather"]
    assert weather["source"] == "observed" and weather["temperature_c"] == -3.5
    assert server.world.weather.weather_type == WeatherType.SNOW
    assert forecast[0]["wind_speed_mps"] == 6.5 and forecast[0]["wind_from_deg"] == 225.0
    assert forecast[0]["snow_depth_cm"] == 2.0


def test_start_time_starts_the_calendar_clamped_to_a_year_back(tmp_path, monkeypatch):
    """The gig start picker's time via --start-time."""
    from datetime import date, datetime, timedelta

    picked = (datetime.now() - timedelta(days=40)).replace(hour=7, minute=15, second=0, microsecond=0)
    server = _build_server(tmp_path, monkeypatch, ["--start-time", picked.isoformat()])
    assert server.calendar.current == picked
    assert _build_server(tmp_path, monkeypatch, ["--start-time", "2001-02-03T04:05"]).calendar.current.date() >= date.today() - timedelta(days=366)


def test_missing_current_weather_uses_previous_cache_until_exact_hour_arrives(tmp_path, monkeypatch, caplog):
    from types import SimpleNamespace
    from theroadragetrip.weather_history import HourlyWeather, game_time_to_utc_hour

    server = _build_server(tmp_path, monkeypatch)
    previous = HourlyWeather(temperature_c=7, wawa=61)
    calls = []
    def fallback(moment):
        calls.append(moment)
        return int(game_time_to_utc_hour(moment)) - 1, previous
    history = SimpleNamespace(request=lambda *a: None, get=lambda moment: None, previous=fallback)
    server.weather_history = history
    with caplog.at_level("WARNING"):
        for _ in range(2):
            seen = server._update_outside()
            server.world.weather.update(0.001, 0, outside_temperature_c=7, observed=seen)
    assert len(calls) == 1
    assert server.world.weather.weather_type.value == "rain"
    assert sum("using cached" in r.message for r in caplog.records) == 1
    current = HourlyWeather(temperature_c=7, wawa=0, source="forecast")
    history.get = lambda moment: current
    seen = server._update_outside()
    assert seen == current
    server.world.weather.update(0.001, 0, outside_temperature_c=7, observed=seen)
    assert server.world.weather.weather_type.value == "clear"


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
    """The start sign: the city and a 24-hour forecast,
    now and every 6 hours; the engine starts off (E after getting in)."""
    from theroadragetrip import protocol

    server = _build_server(tmp_path, monkeypatch)
    forecast = server.start_forecast
    assert len(forecast) == 5 and forecast[0]["source"] == "generated"
    assert all(set(line) == {"time", "temperature_c", "weather", "source", "wind_speed_mps", "wind_from_deg", "snow_depth_cm"}
               for line in forecast)
    assert all(line["time"].endswith(":00") for line in forecast)
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



def test_the_server_places_its_street_lights_with_the_placement_job(tmp_path, monkeypatch):
    """godot-15: street_lights.py's placement, run once over the map."""
    from theroadragetrip import street_lights as roads

    server = _build_server(tmp_path, monkeypatch)
    lights = server.world.street_light_points
    assert lights, "the sample map has lit roads"
    xs = [x for x, *_ in lights]; ys = [y for _, y, *_ in lights]
    work = roads._snapshot_street_light_job("t", (min(xs) - 50, min(ys) - 50, max(xs) + 50, max(ys) + 50), server.world.ways,
                                            None, server.world.buildings, None, server.world.street_lamps, server.world.street_lamp_grid,
                                            server.world.parking_spaces)
    while not roads._advance_street_light_prep(work):
        pass
    while not roads._advance_street_light_placement(work):
        pass
    assert sorted(work["lamps"]) == sorted(lights)
    sent = [light for cid in server._chunks_index._chunks for light in server._chunks_index.message(cid)["street_lights"]]
    assert len(sent) == len(lights)  # every light in exactly one chunk
