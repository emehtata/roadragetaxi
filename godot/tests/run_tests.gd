## Client unit tests, no server needed:
##   godot --headless --path godot --script res://tests/run_tests.gd
## Exits 1 if any check fails.
extends SceneTree

const Hud := preload("res://hud.gd")
const MapLayer := preload("res://map_layer.gd")
const Instruments := preload("res://instruments.gd")
const EntityLayer := preload("res://entity_layer.gd")
const MapChunk := preload("res://map_chunk.gd")
const Main := preload("res://main.gd")
const NightLayer := preload("res://night_layer.gd")
const Labels := preload("res://labels.gd")
const Detail := preload("res://chunk_detail.gd")
const B25 := preload("res://buildings_25d.gd")
const B3 := preload("res://buildings_3d.gd")
const Perf := preload("res://perf.gd")
const EntityLayer2 := preload("res://entity_layer.gd")

var _failures := 0
var _checks := 0


func check(ok: bool, what: String) -> void:
	_checks += 1
	if not ok:
		_failures += 1
		printerr("FAIL: ", what)


func _state(x: float, heading: float = 0.0, events: Array = []) -> Dictionary:
	return {"player": {"x": x, "y": 0.0, "heading": heading}, "npcs": [], "events": events}


var _ran := false


func _process(_delta: float) -> bool:  # first frame: the tree is live, so nodes get _ready
	if _ran:
		return false
	_ran = true
	MapChunk.build_async = false  # check the buildings right after a chunk loads
	MapChunk.buildings_3d = false  # the legacy 2D renderer's checks; test_buildings_3d switches it on
	test_interpolation()
	test_audio()
	test_hud()
	test_map_chunks()
	test_commands_carry_the_player_id()
	test_phone()
	test_rendering()
	test_drive_input()
	test_meet_road_camera_lightning()
	test_gameplay_points()
	test_obstacles()
	test_day_night()
	test_static_world()
	test_rest_of_static_world()
	test_buildings_2_5d()
	test_buildings_3d()
	test_performance_paths()
	print("%d checks, %d failed" % [_checks, _failures])
	quit(1 if _failures > 0 else 0)
	return false


func test_interpolation() -> void:
	var buffer := StateBuffer.new()
	buffer.delay = 0.1
	check(buffer.sample(0.0).is_empty(), "nothing received: an empty sample, no crash")
	# States 1/30 s apart, each arriving the moment it was made (local == server time).
	check(buffer.push(1, 1.0, _state(0.0), 1.0), "first state accepted")
	check(buffer.push(2, 1.0 + 1.0 / 30.0, _state(10.0), 1.0 + 1.0 / 30.0), "next state accepted")
	var halfway := buffer.sample(1.0 + 1.0 / 60.0 + 0.1)  # render time halfway between them
	check(is_equal_approx(StateBuffer.blend(halfway["a"]["player"], halfway["b"]["player"], halfway["t"]).x, 5.0), "two states interpolate")

	check(not buffer.push(2, 1.0 + 1.0 / 30.0, _state(99.0), 1.1), "a duplicate state is dropped")
	check(not buffer.push(1, 1.0, _state(99.0), 1.1), "an older state is dropped")
	check(buffer.size() == 2, "the buffer is unchanged by them")

	var late := buffer.sample(5.0)  # long after the newest state: hold it, don't extrapolate
	check(late["t"] == 0.0 and late["a"]["player"]["x"] == 10.0, "a missing state holds the newest one")
	check(buffer.underruns == 1 and buffer.underrun_episodes == 1, "and counts an underrun episode")
	buffer.sample(5.1)
	check(buffer.underruns == 2 and buffer.underrun_episodes == 1 and is_equal_approx(buffer.longest_underrun_s, 0.1), "consecutive underrun frames are one episode")
	check(is_equal_approx(buffer.max_arrival_gap_s, 1.0 / 30.0), "the gap between state arrivals is measured")

	# godot-09: at real map coordinates (Oulu: x ~ 428 km, y ~ 7210 km) the
	# blended position must keep centimetres - 32-bit vectors of absolute
	# metres step by 3 cm (x) and 50 cm (y), which shook the world.
	var origin := Vector2(428000.0, 7210000.0)
	var from := {"x": 428491.0, "y": 7210561.0, "heading": 0.0}
	var to := {"x": 428491.1, "y": 7210561.4, "heading": 0.0}
	var smooth := true
	var previous := StateBuffer.blend(from, to, 0.0, origin)
	for step in range(1, 11):
		var here := StateBuffer.blend(from, to, step / 10.0, origin)
		smooth = smooth and absf((here.x - previous.x) - 0.01) < 0.001 and absf((previous.y - here.y) - 0.04) < 0.001
		previous = here
	check(smooth, "blending keeps centimetre steps at Oulu coordinates")
	check(is_equal_approx(StateBuffer.blend(from, from, 0.0, origin).y, -561.0), "blend returns canvas coordinates (y down) relative to the origin")

	# Heading across the +-pi seam turns the short way.
	var near_pi := 3.1
	var heading := lerp_angle(near_pi, -near_pi, 0.5)
	check(absf(absf(heading) - PI) < 0.01, "heading interpolation wraps (got %f)" % heading)
	var p := StateBuffer.blend({"x": 0.0, "y": 0.0, "heading": near_pi}, {"x": 0.0, "y": 0.0, "heading": -near_pi}, 0.5)
	check(absf(absf(p.z) - PI) < 0.01, "entity blend uses the short way round")

	# Server ticks that run late shift the server clock for good (no catch-up):
	# here every 4th tick is 30 ms late, as under load. The render time must
	# keep following, not overtake the newest state between arrivals.
	var slip := StateBuffer.new()
	slip.delay = 0.1
	var behind := 0.0
	for tick in range(1, 121):
		if tick > 30 and tick % 4 == 0:
			behind += 0.03
		var arrived := tick / 30.0 + behind
		slip.push(tick, tick / 30.0, _state(0.0), arrived)
		var next_arrival := (tick + 1) / 30.0 + behind + (0.03 if tick + 1 > 30 and (tick + 1) % 4 == 0 else 0.0)
		var frame := arrived
		while frame < next_arrival:
			slip.sample(frame)
			frame += 1.0 / 150.0
	check(slip.underruns == 0, "server clock slips cause no underrun (got %d frames)" % slip.underruns)

	# godot-08: the render clock never runs backwards, whatever the arrivals
	# do - late, early, bunched - and it still ends up `delay` behind.
	var steady := StateBuffer.new()
	steady.delay = 0.1
	var arrivals := [0.0, 0.0, 0.03, -0.01, 0.025, 0.0, 0.04, -0.02, 0.0, 0.035, 0.01, 0.0]  # lateness per state (s)
	var last_render := -INF
	var backwards := 0
	var frame_at := 0.0
	for tick in range(1, 121):
		var arrived: float = tick / 30.0 + arrivals[tick % arrivals.size()]
		steady.push(tick, tick / 30.0, _state(tick * 1.0), arrived)
		while frame_at < arrived + 1.0 / 30.0:
			var now_render := steady.render_time(frame_at)
			backwards += int(now_render < last_render)
			last_render = now_render
			frame_at += 1.0 / 144.0
	check(backwards == 0, "the render clock is monotonic (%d backward steps)" % backwards)
	check(absf(steady.render_time(frame_at) - steady.target_time(frame_at)) < 0.02, "and converges on its target")

	# Events: handed out once, when the render time reaches their state.
	var events := StateBuffer.new()
	events.delay = 0.1
	events.push(1, 10.0, _state(0.0, 0.0, [{"type": "sound", "group": "vehicle.door_close"}]), 10.0)
	check(events.take_due_events(10.05).is_empty(), "an event waits for the picture to reach its state")
	check(events.take_due_events(10.2).size() == 1, "then it is due")
	check(events.take_due_events(10.3).is_empty(), "and only once")
	events.push(1, 10.0, _state(0.0, 0.0, [{"type": "sound", "group": "vehicle.door_close"}]), 10.4)
	check(events.take_due_events(11.0).is_empty(), "a re-sent state doesn't replay its events")


func test_audio() -> void:
	var audio := AudioManager.new()
	root.add_child(audio)  # _ready loads the config and the game's catalog
	var door := audio.resolve({"type": "sound", "group": "vehicle.door_close"})
	check(door.size() == 1 and door[0]["file"].ends_with(".ogg") and FileAccess.file_exists(door[0]["file"]), "a sound event resolves to an existing file")
	check(door[0].has("at"), "the taxi's own sounds come from the taxi")
	var arrived := audio.resolve({"type": "train_arrived", "at": [100.0, 200.0], "station": "Oulu"})
	check(arrived.size() == 2 and arrived[0]["group"] == "railway.train_brakes" and arrived[0]["at"] == Vector2(100, 200), "train_arrived maps to brakes + doors, placed")
	check(arrived[0]["range"][1] == 150.0, "with the game's hearing range")
	check(audio.bus_for("ui.accept") == "UI" and audio.bus_for("weather.rain") == "Environment", "categories map to buses")
	check(audio.bus_for("ambient.city_day") == "Environment", "the day bed is environment")
	var opened := audio.resolve({"type": "sound", "group": "vehicle.door_open"})
	check(opened.size() == 1 and opened[0]["file"].ends_with(".ogg") and FileAccess.file_exists(opened[0]["file"]), "getting in: the door-open sound exists as OGG")
	check(audio.resolve({"type": "something_new"}).is_empty() and audio.unhandled.get("something_new") == 1, "an unknown event is noted, not played")
	audio.handle_event({"type": "something_new"})  # no crash
	var unloadable: Array = []
	for path in audio.all_files():
		var stream := audio.load_file(path)
		if stream == null or stream.get_length() <= 0.0:
			unloadable.append(path)
	check(audio.all_files().size() >= 120 and unloadable.is_empty(), "Godot loads every catalog sound (%d files; failed: %s)" % [audio.all_files().size(), unloadable])
	var picks: Array = []
	for i in 30:
		picks.append(audio.resolve({"type": "sound", "group": "vehicle.door_open"})[0]["file"])
	var repeats := 0
	for i in range(1, picks.size()):
		repeats += int(picks[i] == picks[i - 1])
	var distinct := {}
	for pick in picks:
		distinct[pick] = true
	check(repeats == 0 and distinct.size() == 3, "door-open variations: all used, never the same twice in a row")
	var before := audio.played
	audio.handle_event({"type": "sound", "group": "vehicle.door_close"})
	check(audio.played == before + 1, "one event plays one sound")
	var beds: Array = []
	for day in 3:  # day, night (loop stopped), day ...
		audio.set_loop("city_day", 0.5)
		audio.set_loop("city_day", 0.4)  # an update, not a restart
		beds.append(audio.loop_files["city_day"])
		audio.set_loop("city_day", 0.0)
	check(audio.loop_starts["city_day"] == 3 and beds[0] != beds[1] and beds[2] == beds[0], "the day bed alternates its two variations on each restart")
	audio.set_loop("engine", 0.5, 1.2)
	check(audio.loop_playing("engine"), "a loop starts")
	audio.set_loop("engine", 0.0)
	check(not audio.loop_playing("engine"), "and stops at volume 0")
	audio.set_loop("damaged_steam", 0.35)
	check(audio.loop_playing("damaged_steam"), "taxi damage starts the steam loop")
	audio.set_loop("damaged_steam", 0.0)
	var steps_before: int = audio.played_groups.get("pedestrian.footsteps", 0)
	audio.update_footsteps(true, Vector2.ZERO)
	audio.update_footsteps(true, Vector2(0.4, 0.0))
	audio.update_footsteps(true, Vector2(0.9, 0.0))
	check(audio.played_groups.get("pedestrian.footsteps", 0) == steps_before + 1, "on-foot distance plays one footstep per stride")
	audio.update_footsteps(false, Vector2.ZERO)
	audio.update_footsteps(true, Vector2(100.0, 100.0))
	check(audio.played_groups.get("pedestrian.footsteps", 0) == steps_before + 1, "entering on foot or teleporting does not make a step")
	audio.set_bus_volume("Game", 0.5)
	check(is_equal_approx(AudioServer.get_bus_volume_db(AudioServer.get_bus_index("Game")), linear_to_db(0.5)), "bus volume")
	audio.free()


func test_hud() -> void:
	var text := Hud.values({
		"on_foot": false, "game_time_seconds": 18.0 * 3600.0 + 5.0 * 60.0,
		"player": {"speed": 13.9, "engine_on": true},
		"weather": {"weather_type": "rain", "wetness": 0.4},
		"taxi": {"balance_cents": 12345, "state": "DROPOFF", "completed_fares": 2, "notification_msg": "Fare paid", "notification_timer": 2.0,
			"current_passenger": {"name": "Aino", "pickup": {"address": "Kauppurienkatu 1"}, "dropoff": {"address": "Rautatientori"}}},
	})
	check(text["money"] == "123.45 €", "money (%s)" % text["money"])
	check(text["speed"] == "50 km/h", "speed (%s)" % text["speed"])
	check(text["clock"] == "18:05", "clock (%s)" % text["clock"])
	check(text["weather"] == "Rain, road 40% wet", "weather (%s)" % text["weather"])
	check(text["fare"] == "Drive Aino to Rautatientori", "fare (%s)" % text["fare"])
	var finnish := Hud.values({"on_foot": true, "taxi": {"completed_fares": 2}, "weather": {"weather_type": "rain", "wetness": 0.4}}, {}, "fi")
	check(finnish["speed"] == "jalan" and finnish["fare"] == "Ei kyytiä – 2 ajettu" and finnish["weather"].begins_with("Sadetta"), "Finnish selection localizes the HUD")
	check(text["notice"] == "Fare paid", "notice")
	var empty := Hud.values({})
	check(empty["money"] == "– €" and empty["clock"] == "--:--" and empty["speed"] == "on foot", "missing fields show placeholders")
	check(Hud.values({"taxi": {"current_passenger": null}})["fare"].begins_with("No fare"), "no passenger")


func test_map_chunks() -> void:
	var map := MapLayer.new()
	root.add_child(map)
	var chunk := {"chunk_id": "1_2", "roads": [{"points": [[0, 0], [10, 0]], "half_width_m": 3.0, "drivable": true}], "railways": [], "waters": [], "buildings": []}
	check(map.add_chunk(chunk), "a chunk loads")
	check(not map.add_chunk(chunk) and map.chunk_count() == 1, "the same chunk isn't loaded twice")
	check(map.add_chunk({"chunk_id": "1_3"}) and map.chunk_count() == 2, "a new area's chunk is added")
	check(map.remove_chunk("1_2") and not map.has_chunk("1_2") and map.chunk_count() == 1, "a distant chunk is removed")
	check(not map.remove_chunk("9_9"), "removing an unknown chunk is harmless")
	map.free()


func test_rendering() -> void:
	const RS := preload("res://render_style.gd")
	const Entities := preload("res://entity_layer.gd")
	const Nav := preload("res://nav_overlay.gd")
	const Instruments := preload("res://instruments.gd")
	const Chunk := preload("res://map_chunk.gd")

	# The job target, as TaxiManager.get_current_target.
	var passenger := {"pickup": {"x": 10.0, "y": 20.0, "address": "A", "radius_m": 12.0}, "dropoff": {"x": 500.0, "y": 0.0, "address": "B", "radius_m": 15.0}}
	check(Entities.current_target({"taxi": {"state": "PICKUP", "current_passenger": passenger}})["address"] == "A", "pickup target while waiting")
	check(Entities.current_target({"taxi": {"state": "WALKING", "current_passenger": passenger}})["is_pickup"], "pickup target while the customer walks over")
	check(Entities.current_target({"taxi": {"state": "DROPOFF", "current_passenger": passenger}})["address"] == "B", "drop-off target with the customer aboard")
	check(Entities.current_target({"taxi": {"state": "PICKUP", "current_passenger": null}}).is_empty(), "no passenger, no target")

	# Turn signals blink as Pygame's elapsed % 0.9 < 0.45.
	check(RS.signal_lit(0.1) and not RS.signal_lit(0.5) and RS.signal_lit(0.95), "turn signal blink phase")

	# Wet roads: darken 90/255 at full wetness, no sheen below 0.15.
	var dry := RS.wet_alphas(0.0)
	var damp := RS.wet_alphas(0.1)
	var soaked := RS.wet_alphas(1.0)
	check(dry[0] == 0.0 and damp[1] == 0.0 and is_equal_approx(soaked[0], 90.0 / 255.0) and is_equal_approx(soaked[1], 12.0 / 255.0), "wet-road overlay strengths")
	check(RS.puddle_strength(0.2, 0.5) == 0.0 and is_equal_approx(RS.puddle_strength(0.75, 0.5), 0.5) and RS.puddle_strength(1.0, 0.5) == 1.0, "puddles appear above their reveal wetness")

	# Puddles: deterministic, inside their chunk only, on drivable roads.
	var roads: Array = []
	for i in 40:
		roads.append({"points": [[i * 12.0, 0.0], [i * 12.0 + 5.0, 400.0]], "half_width_m": 3.0, "drivable": true})
	roads.append({"points": [[0.0, 0.0], [300.0, 300.0]], "half_width_m": 1.0, "drivable": false})
	var bounds := Rect2(0, -500, 500, 500)  # world 0..500 x 0..500, y flipped
	var first: Array = Chunk.puddle_spots(roads, bounds, Vector2.ZERO)
	var again: Array = Chunk.puddle_spots(roads, bounds, Vector2.ZERO)
	# 40 roads of 400 m: a 40 % chance per PUDDLE_STRETCH_M, within 20 % of the expectation.
	var expected := 40 * 400.0 / RS.PUDDLE_STRETCH_M * RS.PUDDLE_CHANCE_PER_WAY
	check(absf(first.size() - expected) < expected * 0.2 and str(first) == str(again), "puddle spots follow road length and are deterministic (%d on 40 x 400 m)" % first.size())
	check(first.all(func(spot): return bounds.has_point(spot["at"])), "puddles only inside their chunk")
	check(Chunk.puddle_spots(roads, Rect2(1000, 1000, 10, 10), Vector2.ZERO).is_empty(), "a road's puddle is drawn by one chunk only")

	# Off-screen arrow on the screen edge, with Pygame's 130 px margin.
	var screen := Vector2(1280, 720)
	check(Nav.edge_point(0.0, screen) == Vector2(1280 - 130, 360), "target to the east: right edge")
	check(Nav.edge_point(PI / 2.0, screen) == Vector2(640, 130), "target to the north: top edge")
	check(not Nav.on_screen(Vector2(10, 300), screen) and Nav.on_screen(Vector2(640, 360), screen), "on-screen test with 30 px border")
	check(Nav.distance_text(350.0) == "350m" and Nav.distance_text(2340.0) == "2.3km", "arrow distance text")

	# Instruments.
	check(Instruments.trip_text(950.0, 12345.0) == "Trip: 950 m · Odometer: 12.3 km" and Instruments.trip_text(1500.0, 0.0).begins_with("Trip: 1.50 km"), "trip and odometer text")
	check(Instruments.trip_text(950.0, 12345.0, "fi") == "Matka: 950 m · Mittari: 12.3 km", "instruments follow the selected language")
	var center := Vector2(100, 100)
	check(Instruments.dial_point(center, 0.0, 10.0).x < 100.0 and Instruments.dial_point(center, 1.0, 10.0).x > 100.0
		and is_equal_approx(Instruments.dial_point(center, 0.5, 10.0).y, 90.0), "fuel needle: E left, F right, half up")
	var faces: Array = Instruments.load_rage_faces(ProjectSettings.globalize_path("res://").path_join(Instruments.RAGE_ATLAS).simplify_path())
	check(faces.size() == 11 and faces[0].get_size().x <= 170.0, "11 rage faces cut from Pygame's atlas")

	# Pygame skips police, drivers on foot and the far LOD band in draw_npc_cars.
	var npc := {"id": 1, "vehicle_type": "car"}
	check(Entities.drawn_as_vehicle(npc) and Entities.drawn_as_vehicle(npc.merged({"lod_level": 1})), "ordinary NPC vehicles are drawn")
	check(not Entities.drawn_as_vehicle(npc.merged({"is_police": true})) and not Entities.drawn_as_vehicle(npc.merged({"is_on_foot": true}))
		and not Entities.drawn_as_vehicle(npc.merged({"lod_level": 2})), "police, drivers on foot and the far LOD band are not")
	check(Entities.is_reversing(-0.051) and not Entities.is_reversing(-0.05) and not Entities.is_reversing(1.0), "signed speed switches the reversing lamp at Pygame's threshold")


func _release(code: Key) -> InputEventKey:
	var event := _key(code)
	event.pressed = false
	return event


func test_drive_input() -> void:
	# godot-08: the accelerator is active exactly while it is held.
	var drive := DriveInput.new()
	check(drive.controls(false)["throttle"] == 0.0, "nothing held: no throttle")
	drive.handle(_key(KEY_W))
	check(drive.controls(false)["throttle"] == 1.0, "W pressed: throttle")
	drive.handle(_release(KEY_W))
	check(drive.controls(false)["throttle"] == 0.0 and not drive.any_held(), "W released: no throttle, nothing left held")
	for i in 5:
		drive.handle(_key(KEY_W))
		drive.handle(_release(KEY_W))
	check(drive.controls(false)["throttle"] == 0.0, "repeated taps leave nothing held")
	drive.handle(_key(KEY_W))
	drive.handle(_key(KEY_UP))
	drive.handle(_release(KEY_W))
	check(drive.controls(false)["throttle"] == 1.0, "the other accelerator key still held")
	drive.handle(_release(KEY_UP))
	drive.handle(_key(KEY_S))
	check(drive.controls(false)["throttle"] == 0.0 and drive.controls(false)["brake"] == 1.0, "release then brake")
	drive.handle(_release(KEY_S))
	drive.handle(_key(KEY_W))
	drive.handle(_key(KEY_A))
	drive.handle(_release(KEY_W))
	var turning := drive.controls(false)
	check(turning["throttle"] == 0.0 and turning["steer_left"] == 1.0, "release W while turning: steering stays, throttle goes")
	drive.handle(_key(KEY_W))
	drive.clear()  # the window lost focus with W and A down: their key-ups never come
	check(drive.controls(false)["throttle"] == 0.0 and drive.controls(false)["steer_left"] == 0.0, "focus lost: nothing held")
	var echo := _key(KEY_W)
	echo.echo = true
	drive.handle(echo)
	check(drive.controls(false)["throttle"] == 0.0, "key-repeat echoes don't press")
	drive.handle(_key(KEY_W))
	var walking := drive.controls(true)
	check(walking["throttle"] == 0.0 and walking["forward"] == 1.0, "on foot, W walks instead of accelerating")
	check(not drive.handle(_key(KEY_P)) and not drive.handle(_key(KEY_F)), "phone and enter keys are not driving keys")


func _key(code: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.pressed = true
	return event


func _offer(id: String, name: String, metres: int = 800, seconds: float = 40.0) -> Dictionary:
	return {"id": id, "kind": "offer", "status": "AVAILABLE", "name": name, "pickup": "Kirkkokatu 4",
		"dropoff": "Rautatientori", "pickup_distance_m": metres, "trip_distance_m": 2300, "time_remaining_s": seconds}


func test_phone() -> void:
	var phone: Phone = preload("res://phone.gd").new()
	root.add_child(phone)
	var sounds: Array = []
	var requests: Array = []
	phone.sound.connect(func(group, variation): sounds.append([group, variation]))
	phone.request.connect(func(action, item_id, request_id): requests.append([action, item_id, request_id]))

	check(not phone.is_open and not phone.visible, "the phone starts closed")
	phone._unhandled_input(_key(KEY_ENTER))
	phone._unhandled_input(_key(KEY_X))
	check(requests.is_empty(), "closed, its keys do nothing")
	phone._unhandled_input(_key(KEY_P))
	check(phone.is_open and phone.visible, "P opens it")
	check(sounds == [["ui.phone_open", 0]], "opening plays ui.phone_open exactly once (%s)" % [sounds])
	phone.open()
	check(sounds.size() == 1, "opening an open phone plays nothing")
	phone._unhandled_input(_key(KEY_P))
	check(not phone.is_open and sounds == [["ui.phone_open", 0], ["ui.phone_open", 1]], "P closes it (Pygame's close variation)")
	phone.open()
	phone._unhandled_input(_key(KEY_ESCAPE))
	check(not phone.is_open, "Esc closes it")
	sounds.clear()

	# No phone key is a driving / taxi / camera key (main.gd, hud hints), so
	# opening, closing or answering can't move or brake the taxi.
	var driving := [KEY_W, KEY_A, KEY_S, KEY_D, KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_SHIFT, KEY_F, KEY_E, KEY_F3, KEY_EQUAL, KEY_MINUS, KEY_KP_ADD, KEY_KP_SUBTRACT]
	var clash := false
	for action in Phone.ACTIONS:
		for code in Phone.ACTIONS[action]:
			clash = clash or code in driving
	check(not clash, "phone keys don't overlap driving controls")

	phone.set_connected(true)
	phone.open()
	phone.show_phone({"busy": false, "items": []})
	check(phone._status.text == "No ride requests right now." and phone._accept.disabled, "no offers: said so, nothing to accept")
	phone.show_phone({"busy": false, "items": [_offer("offer-1", "Aino"), _offer("offer-2", "Eero", 1500)]})
	check(phone._rows.get_child_count() == 2 and phone._rows.get_child(0).text == "[1] Aino", "offers are listed")
	check(phone.selected_id == "offer-1" and phone._details.text.contains("Pickup: Kirkkokatu 4") and phone._details.text.contains("Trip: 2.30 km"), "the first offer's details")
	check(phone._details.text.contains("Fare: unavailable"), "no invented fare")
	phone._unhandled_input(_key(KEY_2))
	check(phone.selected_id == "offer-2" and phone._details.text.contains("To the customer: 1.50 km"), "2 selects the second offer")
	var row_before := phone._rows.get_child(0)
	phone.show_phone({"busy": false, "items": [_offer("offer-1", "Aino", 790, 39.0), _offer("offer-2", "Eero", 1490, 39.0)]})
	check(phone._rows.get_child(0) == row_before and phone._details.text.contains("1.49 km"), "a value update refreshes text without rebuilding rows")

	phone._unhandled_input(_key(KEY_ENTER))
	check(requests == [["accept", "offer-2", 1]], "Enter sends exactly one accept request")
	phone._unhandled_input(_key(KEY_ENTER))
	phone.accept_selected()
	phone.reject_selected()
	check(requests.size() == 1 and phone._accept.disabled, "no second request while waiting for the answer")
	check(phone._rows.get_child(1).text.ends_with("waiting for answer..."), "the pending request shows")
	phone.handle_result({"type": "phone_result", "action": "accept", "item_id": "offer-2", "request_id": 1.0, "ok": false, "reason": "gone"})
	check(phone._status.text == "That request is no longer available." and not phone._accept.disabled, "a refused accept is told, and the row can be answered again")
	phone.accept_selected()
	phone.handle_result({"type": "phone_result", "action": "accept", "item_id": "offer-2", "request_id": 2.0, "ok": true, "reason": ""})
	check(not phone.is_open and phone.pending.is_empty(), "an accepted fare closes the phone")
	phone.show_phone({"busy": true, "items": []})
	phone.open()
	check(phone._status.text == "Finish the current fare first." and phone._rows.get_child_count() == 0, "the simulation's state replaces the rows: busy")

	phone.show_phone({"busy": false, "items": [_offer("offer-3", "Liisa")]})
	phone.accept_selected()
	phone.show_phone({"busy": false, "items": [_offer("offer-4", "Matti")]})  # offer-3 expired meanwhile
	check(phone.pending.is_empty() and phone.selected_id == "offer-4" and phone._rows.get_child_count() == 1, "an expired offer disappears with its pending request")
	phone.show_phone({"busy": false, "items": [{"id": "booking-7", "kind": "booking", "status": "ACCEPTED", "name": "Kaisa", "train": "IC 27",
		"pickup": "Oulu", "arrival": "18:42", "dropoff": "Torikatu 1", "surcharge_cents": 800}]})
	check(phone._rows.get_child(0).text.contains("accepted") and phone._accept.disabled and phone._details.text.contains("+8.00 €"), "a booking's state change shows; an accepted one can't be answered")

	phone.show_phone({"busy": false, "items": [_offer("offer-5", "Olli")]})
	phone.accept_selected()
	requests.clear()
	phone.set_connected(false)
	check(phone.items.is_empty() and phone.pending.is_empty() and phone._accept.disabled and phone._status.text.begins_with("No connection"), "connection loss: stale rows and pending answers cleared, actions off")
	check(not phone.accept_selected() and requests.is_empty(), "no requests without a connection")
	phone.set_connected(true)
	check(phone._status.text == "No ride requests right now.", "reconnected: a fresh, empty phone until the simulation says otherwise")
	check(phone.get_children().size() == 1 and _orphan_timers(phone) == 0, "no leftover timers or nodes")
	phone.free()



func _orphan_timers(node: Node) -> int:
	return node.find_children("*", "Timer", true, false).size()


func test_commands_carry_the_player_id() -> void:
	var line := SimClient.command_line({"throttle": 1.0}, 7, "local_player")
	var message: Dictionary = JSON.parse_string(line)
	check(line.ends_with("\n") and message["type"] == "command" and message["player_id"] == "local_player" and message["seq"] == 7, "commands carry the player id")
	var answer: Dictionary = JSON.parse_string(SimClient.command_line({"throttle": 0.0}, 8, "local_player", {"action": "accept", "item_id": "offer-2", "request_id": 1}))
	check(answer["phone"] == {"action": "accept", "item_id": "offer-2", "request_id": 1.0} and answer["command"]["throttle"] == 0.0, "a phone answer rides on a command with the current controls")
	# godot-final-01: G asks the simulation to refuel (it checks the station, speed, tank and money).
	var refuel := Main.command_for({"throttle": 0.0}, true, false, true)
	check(refuel["refuel"] == true and refuel["interact"] == false and refuel["throttle"] == 0.0, "a G press sends refuel")
	check(Main.command_for({}, true, false, false)["refuel"] == false, "no press, no refuel")
	check(Hud.values({"on_foot": false, "player": {"engine_on": true}})["hint"].contains("G refuel"), "the driving hint names G")
	test_controls_and_economy()
	test_taxi_information()
	test_navigation_route()
	test_label_modes()
	test_road_rage()
	test_weather_presentation()
	test_speech_and_stations()
	# The limit sign (Wikimedia C32-60 / C32-100, Traficom numeral widths), at a digit height of 100.
	var sixty: Array = Instruments.digit_layout("60")
	check(is_equal_approx(sixty[0][1], 55.0 + 37.0 / 3.0) and is_equal_approx(sixty[1] * 3.0, 367.0), "60 as C32-60: 165 + 37 + 165")
	var hundred: Array = Instruments.digit_layout("100")
	check(is_equal_approx(hundred[0][1] * 3.0, 96.0) and is_equal_approx(hundred[0][2] * 3.0, 271.0) and is_equal_approx(hundred[1] * 3.0, 436.0), "100 as C32-100: 1 at 0, zeros at 96 and 271, 436 wide")
	check(Instruments.digit_layout("7")[1] == 47.0 and Instruments.digit_layout("4")[1] == 60.0, "7 and 4 widths (Traficom)")
	for d in "1234567890":
		check(not Instruments.digit_strokes(d).is_empty(), "digit %s has strokes" % d)
	check(Instruments.digit_layout("120")[1] * 3.0 <= 490.0, "120 fits inside the red ring (radius 245)")


## godot-final-07: speech, station announcements, station ambience, the J board.
func test_speech_and_stations() -> void:
	var audio: Node = load("res://audio_manager.gd").new()
	root.add_child(audio)
	var dir := DirAccess.open(audio.package_root.path_join("sounds/driver_chatter"))
	var wav := ""
	for file in dir.get_files():
		if file.ends_with(".wav"):
			wav = file
			break
	var parts := wav.get_basename().split("_")
	var line := {"type": "speech", "speaker": "driver", "speaker_name": null, "gender": parts[0], "language": parts[1], "hash": parts[2],
		"text": "Asiakas kyytiin.", "duration_s": 4.0}
	check(audio.speech_file(line).ends_with("sounds/driver_chatter/" + wav), "a speech event names exactly one existing recording")
	check(audio.speak(line) and audio.speech_player.playing and audio.speech_player.bus == "Game", "it plays on the one voice, the Game bus")
	check(not audio.speak(line) and audio.played_groups["speech"] == 1, "never two lines at once")
	for bad in [line.merged({"hash": "../../etc/passwd"}, true), line.merged({"speaker": "../x"}, true), line.merged({"gender": "x"}, true),
			line.merged({"hash": "00000000deadbeef"}, true), {"type": "speech"}]:
		check(audio.speech_file(bad) == "" or not FileAccess.file_exists(audio.speech_file(bad)), "a malformed or missing recording: nothing (%s)" % str(bad.get("hash")))
	audio.stop_voices()
	check(not audio.speech_player.playing, "stops on disconnect")
	var announcement := {"type": "station_announcement", "clips": ["phrases/attention.ogg", "connectors/pause_medium.ogg", "train_types/intercity.ogg"],
		"at": [10.0, 20.0], "text": "Hyvät matkustajat. InterCity"}
	check(audio.announce(announcement), "an announcement is queued and starts")
	check(audio.announcer.playing and audio._announcing == [audio.package_root.path_join("assets/railway_announcements/connectors/pause_medium.ogg"),
		audio.package_root.path_join("assets/railway_announcements/train_types/intercity.ogg")], "its clips play in order on one player")
	check(audio.announcer.position == MapMath.point(audio.origin, 10.0, 20.0) and audio.announcer.max_distance == 300.0, "from the station, heard to 300 m")
	check(not audio.announce(announcement.merged({"clips": ["../../../secrets.ogg"]}, true)) and not audio.announce(announcement.merged({"clips": ["/abs.ogg"]}, true)), "no clip outside the announcement assets")
	check(audio.announce(announcement) and audio.announcements.size() == 1, "a second one waits its turn, whole")
	audio.announcements[0][0] -= 21000
	audio._announcing.clear()
	audio._next_clip()
	check(audio.announcements.is_empty() and audio._announcing.is_empty(), "one waiting more than 20 s is dropped")
	audio.stop_voices()
	audio.free()

	var hud_scene: Node = load("res://main.tscn").instantiate()
	var hud: Control = hud_scene.get_node("Ui/Hud")
	hud.owner = null
	for child in hud.find_children("*", "", true, false):
		child.owner = hud
	hud.get_parent().remove_child(hud)
	hud_scene.free()
	root.add_child(hud)
	check(Hud.subtitle_text({"speaker": "passenger", "speaker_name": "Aino", "text": "Hei"}) == "Aino: Hei" and Hud.subtitle_text({"speaker": "driver", "text": "Mennään"}) == "Driver: Mennään", "the passenger's name, else the speaker")
	check(Hud.subtitle_text({"speaker": "passenger", "text": ""}) == "" and Hud.subtitle_text({}) == "", "no text: no subtitle")
	hud.show_subtitle({"speaker": "passenger", "speaker_name": "Aino", "text": "Hei", "duration_s": 4.0})
	check(hud._subtitle.visible and hud._subtitle.text == "Aino: Hei", "one subtitle shows")
	var glow_p := PackedVector2Array()
	var glow_c := PackedColorArray()
	var glow_t := PackedInt32Array()
	EntityLayer.lamp_glow(Vector2.ZERO, EntityLayer.BRAKE_GLOW, 0.0, glow_p, glow_c, glow_t)
	check(glow_t.is_empty(), "lamp halos: none by day")
	EntityLayer.lamp_glow(Vector2(5, 5), EntityLayer.BRAKE_GLOW, 1.0, glow_p, glow_c, glow_t)
	check(glow_t.size() == 3 * EntityLayer.GLOW_STEPS and glow_c[0].r > 0.5 and glow_c[1] == Color(0, 0, 0, 1) and is_equal_approx(glow_p[1].distance_to(Vector2(5, 5)), EntityLayer.BRAKE_GLOW[1]), "lamp halos: red at the lamp, nothing at the reach")
	check(EntityLayer.BRAKE_GLOW[1] > EntityLayer.TAIL_GLOW[1] and EntityLayer.BRAKE_GLOW[0].r > EntityLayer.TAIL_GLOW[0].r and EntityLayer.REVERSE_GLOW[1] > EntityLayer.BRAKE_GLOW[1], "brake halos outshine tail lamps; reversing lights the ground behind")
	check(FileAccess.get_file_as_string("res://entity_layer.gd").contains("npc.get(\"braking\", false)"), "NPCs' brake lamps from the server")
	var on_foot_state := {"on_foot": true, "player": {"engine_on": false, "fuel_l": 30.0}, "taxi": {}}
	check(Hud.values(on_foot_state, {"entered_taxi": false})["start_hint"] == "Press F to get into your taxi", "start hint: get in, until the driver first does")
	check(Hud.values(on_foot_state, {"entered_taxi": true})["start_hint"] == "", "start hint: not again once in")
	check(Hud.values({"on_foot": false, "player": {"engine_on": false, "fuel_l": 30.0}, "taxi": {}})["start_hint"] == "Press E to start the engine", "start hint: start the engine")
	check(Hud.values({"on_foot": false, "player": {"engine_on": true, "fuel_l": 30.0}, "taxi": {}})["start_hint"] == "" and Hud.values({"on_foot": false, "player": {"engine_on": false, "fuel_l": 0.0}, "taxi": {}})["start_hint"] == "", "start hint: none running or out of fuel")
	var sign := Main.start_sign({"city": "Sysmä", "forecast": [{"time": "08.10. 18:00", "temperature_c": 8.4, "weather": "clear", "source": "observed"}]}, "en")
	var sign_text := ""
	for label in sign.get_child(0).get_children():
		sign_text += label.text + "\n"
	check(sign_text == "SYSMÄ\nWeather forecast for the next 24 hours\n08.10. 18:00   +8 °C   Clear   (observed)\nPress any key to start\n", "start sign: city, forecast with its source, the prompt")
	sign.free()
	var Instruments := load("res://instruments.gd")
	check(is_equal_approx(Instruments.speed_kmh(-5.0), 18.0) and Instruments.speed_kmh(100.0) == 210.0, "speedometer: |speed| in km/h, up to 210")
	check(is_equal_approx(Instruments.speed_angle(0.0), deg_to_rad(135.0)) and is_equal_approx(Instruments.speed_angle(210.0), deg_to_rad(405.0)), "speedometer: 270 degrees from lower left")
	var Startup := load("res://startup.gd")
	check(Startup.map_source_args("pbf", "") == ["--osm-source", "pbf"] and Startup.map_source_args("pbf", "/maps/fi.osm.pbf") == ["--osm-source", "pbf", "--osm-pbf-path", "/maps/fi.osm.pbf"], "map source: a local .osm.pbf, its path when set")
	check(Startup.map_source_args("overpass", "x") == ["--osm-source", "overpass"] and Startup.map_source_args("", "") == [], "map source: Overpass, or the server's config")
	var today := {"year": 2026, "month": 10, "day": 8}
	check(Startup.clamp_start({"year": 2026, "month": 3, "day": 5, "hour": 7, "minute": 15}, today) == {"year": 2026, "month": 3, "day": 5, "hour": 7, "minute": 15}, "start time: a date in the last year stays")
	check(Startup.clamp_start({"year": 2024, "month": 1, "day": 1, "hour": 7, "minute": 0}, today).year == 2025 and Startup.clamp_start({"year": 2024, "month": 1, "day": 1, "hour": 7, "minute": 0}, today).month == 10, "start time: a year back at most")
	check(Startup.clamp_start({"year": 2026, "month": 12, "day": 24, "hour": 7, "minute": 0}, today).month == 10, "start time: no later than today")
	check(Startup.clamp_start({"year": 2026, "month": 2, "day": 31, "hour": 7, "minute": 0}, today).day == 28, "start time: the day within its month")
	check(Startup.clamp_start({"year": 2025, "month": 2, "day": 28, "hour": 0, "minute": 0}, {"year": 2028, "month": 2, "day": 29}).day == 28, "start time: 29 Feb a year back is the 28th")
	check(Startup.clamp_start({"year": 2027, "month": 2, "day": 28, "hour": 9, "minute": 0}, {"year": 2028, "month": 2, "day": 29}) == {"year": 2027, "month": 2, "day": 28, "hour": 9, "minute": 0}, "start time: the earliest day itself")
	check(Main.screenshot_directory("Windows", "C:/Users/esa") == "C:/Users/esa/Pictures/TheRoadRageTrip", "F12 on Windows: Pictures/TheRoadRageTrip")
	check(Main.screenshot_directory("Linux", "").ends_with("screenshots"), "F12 elsewhere: ./screenshots")
	check(FileAccess.get_file_as_string("res://main.gd").contains("KEY_F12:\n\t\t\t\tsave_screenshot()"), "F12 saves a screenshot")
	hud.size = Vector2(1280, 720)
	hud.show_subtitle({"speaker": "driver", "text": "Nyt mennään kovaa, pidä kiinni", "duration_s": 4.0})
	check(hud._subtitle.size.x > 3.0 * hud._subtitle.size.y, "a subtitle is one horizontal line, not a letter per row")
	hud.show_subtitle({"speaker": "driver", "text": "pitkä rivi ".repeat(30), "duration_s": 4.0})
	check(hud._subtitle.size.x <= 1240.0 and hud._subtitle.size.x > 1000.0 and hud._subtitle.size.y > 50.0, "a line wider than the screen wraps across it")
	hud._subtitle_until = Time.get_ticks_msec() - 1
	hud.show_state({})
	check(not hud._subtitle.visible, "gone after its duration")
	var railway := {"nearest_station": "Oulu", "stations": [{"name": "Oulu", "x": 0.0, "y": 0.0, "waiting": 12}],
		"arrivals": [{"time": "18:02", "train_type": "IC", "number": "28", "origin": "Rovaniemi", "track": "1"}],
		"departures": [{"time": "18:08", "train_type": "IC", "number": "28", "destination": "Helsinki", "track": ""}]}
	check(Hud.next_train_text(railway) == "Oulu\nNext trains:\n18:02 track 1  IC 28 Rovaniemi\nDeparting trains:\n18:08  IC 28 Helsinki", "the J board as draw_next_train")
	var many := railway.duplicate(true)
	for i in 8:
		many["arrivals"].append(railway["arrivals"][0])
	check(Hud.next_train_text(many).count("Rovaniemi") == 5, "five rows at most")
	check(Hud.next_train_text({}) == "" and Hud.next_train_text(null) == "" and Hud.next_train_text({"arrivals": "x"}) == "", "nothing to show: no board")
	hud.show_state({"railway": railway}, {"next_train": true})
	check(hud._board.visible and hud._board.text.begins_with("Oulu"), "J on: the board")
	hud.show_state({"railway": railway}, {"next_train": false})
	check(not hud._board.visible, "J off: gone")
	hud.queue_free()

	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
	var sim: Node = main.get_node("SimClient")
	main._unhandled_input(_key_event(KEY_J))
	main.send({})
	check(main.show_next_train and not sim._last_command.has("next_train") and not sim._last_command.has("j"), "J is local: no command")
	main.phone.is_open = true
	main._unhandled_input(_key_event(KEY_J))
	check(main.show_next_train, "not while the phone is open")
	main.free()
	check(Hud.values({"on_foot": false, "player": {"engine_on": true}})["hint"].contains("J trains"), "the hint names J")

	var range_m := [15.0, 150.0]
	var stations := {"stations": [{"name": "A", "x": 0.0, "y": 0.0, "waiting": 30}, {"name": "B", "x": 40.0, "y": 0.0, "waiting": 6}, {"name": "C", "x": 5.0, "y": 0.0, "waiting": 0}]}
	var crowd: Array = Main.station_ambience(stations, Vector2(100.0, 0.0), range_m)
	check(crowd[1] == Vector2(0, 0) and is_equal_approx(crowd[0], 1.0), "the station heard loudest: busy A at 100 m (1.0 x 0.15) over quiet B at 60 m (0.2 x 0.25)")
	check(Main.station_ambience(stations, Vector2(160.0, 0.0), range_m)[1] == Vector2(40, 0), "A out of earshot (160 m): quiet B")
	check(Main.station_ambience(stations, Vector2(1000.0, 0.0), range_m)[1] == null and Main.station_ambience(stations, Vector2(1000.0, 0.0), range_m)[0] == 0.0, "nobody in earshot: silent")
	check(Main.station_ambience(null, Vector2.ZERO, range_m)[0] == 0.0 and Main.station_ambience({"stations": [{"x": "a"}]}, Vector2.ZERO, range_m)[0] == 0.0, "older or malformed state: silent")
	check(is_equal_approx(Main.heard(Vector2.ZERO, Vector2(30, 0), range_m), 0.5) and Main.heard(Vector2.ZERO, Vector2(150, 0), range_m) == 0.0, "audio.py's distance gain")
	var cfg: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://audio/audio_events.json"))
	check(cfg["loops"]["station_crowd"]["variation"] == 0 and cfg["loops"]["station_luggage"]["variation"] == 1 and cfg["loops"]["station_crowd"]["positional"], "crowd and luggage loops, placed")


## godot-final-06: precipitation, ripples, splashes and weather audio (render/weather.py, weather.py, audio.py).
func test_weather_presentation() -> void:
	var W := preload("res://weather_layer.gd")
	var wx: Node = W.new()
	check(wx.particles.size() == 220 * 3, "a fixed pool of 220 particles")
	check(W.falling({"weather": {"weather_type": "clear"}}) == "" and W.falling({}) == "" and W.falling({"weather": "rain"}) == "", "clear, missing or malformed: nothing falls")
	check(W.falling({"weather": {"weather_type": "rain"}}) == "rain" and W.falling({"weather": {"weather_type": "slush"}}) == "slush" and W.falling({"weather": {"weather_type": "snow"}}) == "snow", "rain, slush, snow")
	for kind in ["rain", "slush", "snow"]:
		wx.kind = kind
		var before := Vector2(wx.particles[0], wx.particles[1])
		var factor: float = wx.particles[2]
		wx.advance_particles(0.01)
		var motion: Vector2 = W.MOTION[kind]
		var moved := Vector2(wx.particles[0], wx.particles[1]) - before
		check(moved.is_equal_approx(Vector2(0.05 * motion.y, 0.9 * motion.x) * factor * 0.01), "%s: Pygame's fall and drift in real seconds" % kind)
	wx.kind = "snow"
	for i in 2000:  # long runs and weather changes: the pool never grows, everything stays on screen
		wx.advance_particles(0.05)
		if i == 1000:
			wx.kind = "rain"
	var inside := true
	for i in 220:
		inside = inside and wx.particles[i * 3] >= 0.0 and wx.particles[i * 3] <= 1.0 and wx.particles[i * 3 + 1] >= 0.0 and wx.particles[i * 3 + 1] <= 1.0
	check(wx.particles.size() == 660 and inside, "recycled in place, in screen fractions")
	wx.kind = ""
	var frozen: PackedFloat32Array = wx.particles.duplicate()
	wx.advance_particles(1.0)
	check(wx.particles == frozen, "clear: no particle work")
	wx.free()

	# The canvas items: one batched draw per primitive, none while clear or underground.
	var sky := CanvasLayer.new()
	var world := Node2D.new()
	world.set_script(null)
	root.add_child(sky)
	root.add_child(world)
	var map := MapLayer.new()
	root.add_child(map)
	var live: Node = W.new()
	root.add_child(live)
	live.setup(sky, map)
	live.precipitation.size = Vector2(1280, 720)
	var rainy := {"weather": {"weather_type": "rain", "wetness": 0.9}, "player": {"speed": 0.0}, "on_foot": false}
	live.update(0.016, rainy, Vector2.ZERO, false)
	check(live.precipitation.visible and live.ripples.visible, "rain: precipitation and ripples on")
	live.update(0.016, rainy, Vector2.ZERO, true)
	check(not live.precipitation.visible and not live.ripples.visible, "underground: no rain, no ripples")
	live.update(0.016, {"weather": {"weather_type": "clear", "wetness": 0.9}, "player": {}, "on_foot": false}, Vector2.ZERO, false)
	check(not live.precipitation.visible and not live.ripples.visible, "wet but clear: puddles stay, no ripples, no particles")
	check(sky.get_child_count() == 1 and map.get_children().filter(func(n): return n == live.ripples or n == live.splash_node).size() == 2, "three canvas items in all, never one per particle")

	# Ripples: deterministic phases, the 2.4 s cycle and 1 s ring.
	var roads := [{"points": [[0.0, 0.0], [30.0, 0.0]], "drivable": true, "half_width_m": 4.0}]
	var spots_a := MapChunk.puddle_spots(roads.duplicate(true), Rect2(), Vector2.ZERO)
	var spots_b := MapChunk.puddle_spots(roads.duplicate(true), Rect2(), Vector2.ZERO)
	check(spots_a == spots_b and (spots_a.is_empty() or spots_a[0].has("phase")), "the same road: the same puddle and ripple phase")
	var spot := {"at": Vector2.ZERO, "radius": 2.0, "reveal": 0.2, "phase": 0.0}
	var ring: Array = W.ripple(spot, 1.0, 0.5)
	check(is_equal_approx(ring[0], 2.0 * (0.25 + 0.85 * 0.5)) and is_equal_approx(ring[1], 150.0 / 255.0 * 0.5), "half-way: 0.675 of the radius, half the alpha")
	check(W.ripple(spot, 1.0, 1.5).is_empty() and not W.ripple(spot, 1.0, 2.4 + 0.2).is_empty(), "1 s of ripple in every 2.4 s")
	check(W.ripple(spot, 0.1, 0.5).is_empty(), "a puddle not showing yet: no ripple")

	# Splashes: edge-triggered on entering a showing puddle at 1 m/s or more.
	var fake := MapChunk.new()
	fake._puddle_spots = [{"at": Vector2(100, 0), "radius": 1.5, "reveal": 0.2, "shape": [], "phase": 0.0}]
	fake._bounds_rect = Rect2(50, -50, 100, 100)
	map._chunks["fake"] = fake
	var drive := func(at: Vector2, speed: float, on_foot := false, under := false):
		live.update(0.016, {"weather": {"weather_type": "rain", "wetness": 0.9}, "player": {"speed": speed, "length_m": 4.4, "width_m": 1.8}, "on_foot": on_foot}, at, under)
	live.splashes.clear()
	drive.call(Vector2(90, 0), 10.0)
	check(live.splashes.is_empty(), "outside the puddle: nothing")
	drive.call(Vector2(99, 0), 10.0)
	check(live.splashes.size() == 1 and is_equal_approx(live.splashes[0][2], 10.0 * 3.6 / 60.0), "entering at 10 m/s: one splash, strength speed km/h / 60")
	drive.call(Vector2(100, 0), 10.0)
	check(live.splashes.size() == 1, "staying inside: no more")
	drive.call(Vector2(120, 0), 10.0)
	drive.call(Vector2(100, 0), 0.5)
	check(live.splashes.size() == 1, "too slow: no splash")
	drive.call(Vector2(120, 0), 10.0)
	drive.call(Vector2(100, 0), 10.0, true)
	drive.call(Vector2(120, 0), 10.0)
	drive.call(Vector2(100, 0), 10.0, false, true)
	check(live.splashes.size() == 1, "on foot or underground: no splash")
	drive.call(Vector2(120, 0), 10.0)
	drive.call(Vector2(100, 0), 10.0)
	check(live.splashes.size() == 2, "out and in again: another")
	check(live.puddle_at(Vector2(100, 0), 2.2, 0.1) == null, "a puddle not showing at this wetness can't be hit")
	var faraway := MapChunk.new()
	faraway._bounds_rect = Rect2(5000, 5000, 500, 500)
	faraway._puddle_spots = [{"at": Vector2(100, 0), "radius": 9.0, "reveal": 0.0}]  # wrongly placed: only found if far chunks were scanned
	map._chunks["faraway"] = faraway
	map._chunks.erase("fake")
	check(live.puddle_at(Vector2(100, 0), 2.2, 0.9) == null, "only chunks around the taxi are looked at")
	map._chunks.erase("faraway")
	var young: Array = W.splash_ring([Vector2.ZERO, 0.0, 1.0])
	var old: Array = W.splash_ring([Vector2.ZERO, 0.25, 0.5])
	check(is_equal_approx(young[0], 0.25) and is_equal_approx(young[1], 200.0 / 255.0), "a splash starts 0.25 m, full alpha")
	check(is_equal_approx(old[0], 0.25 + 0.5 * 1.4 * 0.5) and is_equal_approx(old[1], 200.0 / 255.0 * 0.5 * 0.75), "half-way: grown and faded by its strength")
	live.splashes.clear()
	for i in 45:
		live.spawn_splash(Vector2(i, 0), 1.0)
	check(live.splashes.size() == 40 and live.splashes[0][0] == Vector2(5, 0), "at most 40: the oldest go")
	live.age_splashes(0.5)
	check(live.splashes.is_empty(), "gone after 0.5 s")
	live.free()
	map.free()
	sky.free()
	world.free()
	fake.free()
	faraway.free()

	# Weather audio: main()'s update_ambience formulas.
	var loops := Main.weather_loops({"weather": {"weather_type": "rain", "wetness": 0.5, "is_thunderstorm": true, "wind_vector_mps": [6.0, 8.0]}, "player": {"speed": 15.0}, "on_foot": false})
	check(loops["rain"] == 0.6 and loops["rain_heavy"] == 0.7, "a thunderstorm: rain and heavy rain")
	check(is_equal_approx(loops["wind"], 10.0 / 12.0 * 0.5) and loops["wind_strong"] == 0.0, "10 m/s wind: 0.42, no strong wind yet")
	check(is_equal_approx(loops["wet_tires"], 0.5 * 0.6) and loops["wet_slush"] == 0.0, "wet tyres by wetness x speed / 15")
	var gale := Main.weather_loops({"weather": {"weather_type": "slush", "wetness": 1.0, "wind_vector_mps": [0.0, -20.0]}, "player": {"speed": 30.0}, "on_foot": false})
	check(gale["wind"] == 0.5 and is_equal_approx(gale["wind_strong"], 0.6) and gale["rain_heavy"] == 0.0, "20 m/s: both wind layers full; no storm: no heavy rain")
	check(gale["wet_slush"] == 0.6 and gale["wet_tires"] == 0.0 and gale["rain"] == 0.6, "slush: its own tyre variation, and rain")
	var snow := Main.weather_loops({"weather": {"weather_type": "snow", "wetness": 0.8}, "player": {"speed": 10.0}, "on_foot": true})
	check(snow["rain"] == 0.0 and snow["wet_tires"] == 0.0 and snow["wind"] == 0.0, "snow: no rain loop; on foot: no tyres; no wind field: silent")
	var older := Main.weather_loops({"weather": {"weather_type": "rain", "wetness": "x", "wind_vector_mps": [NAN, 1.0]}})
	check(older["rain"] == 0.6 and older["rain_heavy"] == 0.0 and older["wind"] == 0.0, "an older or malformed state: base rain only")
	var audio: Node = load("res://audio_manager.gd").new()
	audio.load_config("res://audio/audio_events.json")
	var spec: Dictionary = audio._config["loops"]
	check(spec["rain"]["variation"] == 0 and spec["rain_heavy"]["variation"] == 1 and spec["wind_strong"]["variation"] == 1 and spec["wet_slush"]["variation"] == 1 and spec["wet_tires"]["variation"] == 0, "loop variations as audio.py")
	check(spec.has("engine") and spec.has("city_day") and spec.has("train_running"), "the other loops are unchanged")
	audio.free()


## godot-final-05: SPACE sends one road-rage press; the server's shout is drawn above the taxi.
func test_road_rage() -> void:
	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
	var sim: Node = main.get_node("SimClient")
	main.send({})
	check(sim._last_command["road_rage"] == false, "no press: road_rage false")
	main._unhandled_input(_key_event(KEY_SPACE))
	var echo := _key_event(KEY_SPACE)
	echo.echo = true
	main._unhandled_input(echo)  # held: no second press
	main.send({"throttle": 1.0})
	check(sim._last_command["road_rage"] == true and sim._last_command["throttle"] == 1.0, "SPACE rides on the next command with the held input")
	main.send({"throttle": 1.0})
	check(sim._last_command["road_rage"] == false, "sent once; a held key doesn't repeat it")
	main.phone.is_open = true
	main._unhandled_input(_key_event(KEY_SPACE))
	main.send({})
	check(sim._last_command["road_rage"] == false, "not while the phone is open (main())")
	main.phone.is_open = false
	main._unhandled_input(_key_event(KEY_SPACE))
	main._unhandled_input(_key_event(KEY_G))
	main.send({})
	check(sim._last_command["road_rage"] == true and sim._last_command["refuel"] == true, "SPACE and G are independent presses")
	main.summary_shown = true
	main._unhandled_input(_key_event(KEY_SPACE))
	main.send({})
	check(sim._last_command["road_rage"] == false, "not after the career summary")
	main.free()

	check(EntityLayer.shout_for({"road_rage": {"text": "PRKL!", "timer": 3.2}}) == ["PRKL!", 1.0], "the server's text, fully visible")
	check(EntityLayer.shout_for({"road_rage": {"text": "VTTU!", "timer": 0.5}})[1] == 1.0 and is_equal_approx(EntityLayer.shout_for({"road_rage": {"text": "VTTU!", "timer": 0.2}})[1], 0.4), "fades over the last 0.5 s")
	for bad in [{}, {"road_rage": null}, {"road_rage": "PRKL!"}, {"road_rage": {"text": "", "timer": 2.0}}, {"road_rage": {"text": "PRKL!", "timer": 0.0}},
			{"road_rage": {"text": "PRKL!", "timer": -1.0}}, {"road_rage": {"text": "PRKL!", "timer": INF}}, {"road_rage": {"text": "PRKL!", "timer": NAN}}, {"road_rage": {"text": 5, "timer": 2.0}}]:
		check(EntityLayer.shout_for(bad).is_empty(), "no shout from %s" % str(bad))
	var source: String = (EntityLayer as Script).source_code
	var draw := source.substr(source.find("func _draw() -> void:"))
	var taxi_body := draw.find("_vehicle(taxi_at")
	check(taxi_body < draw.find("shout_for(a)") and draw.find("shout_for(a)") < draw.find("drawn_as_vehicle(npc)"), "the shout after the taxi body, before the NPC vehicles (draw_car)")
	check(draw.find("_bubble(taxi_at") > 0 and source.find("draw_set_transform(anchor, 0.0, Vector2.ONE / px_per_m)") > 0, "drawn at the interpolated taxi, in constant screen pixels")
	var audio: Node = load("res://audio_manager.gd").new()
	audio.load_config("res://audio/audio_events.json")
	var horn: Array = audio.resolve({"type": "sound", "group": "vehicle.horn"})
	check(horn.size() == 1 and horn[0]["group"] == "vehicle.horn" and is_equal_approx(horn[0]["volume"], 0.45), "the horn event plays vehicle.horn at Pygame's 0.45")
	audio.free()
	check(Hud.values({"on_foot": false, "player": {"engine_on": true}})["hint"].contains("SPACE road rage"), "the hint names SPACE")


## L cycles the labels as Pygame's label_mode: off (start), street names, everything.
func test_label_modes() -> void:
	var labels: Control = Labels.new()
	check(labels.mode == 0, "labels start off, as in Pygame")
	var l := _key_event(KEY_L)
	l.physical_keycode = KEY_L
	var seen := []
	for i in 3:
		labels._unhandled_input(l)
		seen.append(labels.mode)
	check(seen == [1, 2, 0], "L: streets, all, off again")
	labels.mode = 0
	labels.update_view(Transform2D(), 1, false)
	check(not labels.visible, "mode 0 draws nothing")
	labels.mode = 1
	labels.update_view(Transform2D(), 1, false)
	check(labels.visible, "mode 1 shows the overlay")
	labels.free()
	var candidates := [[0.0, 0.0, "Keskusta", 0], [0.0, 0.0, "Kirkkokatu", 4]]
	var canvas := Transform2D(0.0, Vector2(640, 360)).scaled_local(Vector2(9, 9))
	var font: Font = ThemeDB.fallback_font
	check(Labels.declutter(candidates, canvas, Vector2(1280, 720), font, 1).map(func(p): return p[1]) == ["Kirkkokatu"], "mode 1: only the street name")
	check(Labels.declutter(candidates, canvas, Vector2(1280, 720), font, 2).map(func(p): return p[1]) == ["Keskusta"], "mode 2: everything, by priority (one spot: the district wins)")
	check(Labels.declutter(candidates, canvas, Vector2(1280, 720), font, 0).is_empty(), "mode 0: none")
	var driving := {"on_foot": false, "player": {"engine_on": true}}
	check(Hud.values(driving, {"labels": 1})["hint"].contains("L labels STREETS") and Hud.values(driving)["hint"].contains("L labels OFF"), "the hint names the label mode")


## godot-final-04: the server's route, N to show it (C stays the compass).
func test_navigation_route() -> void:
	var nav: Control = load("res://nav_overlay.gd").new()
	check(not nav.show_route and not nav.show_compass, "N and C start off, as in Pygame")
	var n := _key_event(KEY_N)
	n.physical_keycode = KEY_N
	nav._unhandled_input(n)
	check(nav.show_route and not nav.show_compass, "N shows the route; the compass stays as it was")
	var echo := _key_event(KEY_N)
	echo.physical_keycode = KEY_N
	echo.echo = true
	nav._unhandled_input(echo)
	check(nav.show_route, "a held N (echo) doesn't flip it")
	var c := _key_event(KEY_C)
	c.physical_keycode = KEY_C
	nav._unhandled_input(c)
	check(nav.show_route and nav.show_compass, "C toggles only the compass")
	nav._unhandled_input(n)
	check(not nav.show_route, "N again hides it")
	nav.free()
	var driving := {"on_foot": false, "player": {"engine_on": true}}
	check(Hud.values(driving, {"navigation": true})["hint"].contains("N navigation ON") and Hud.values(driving)["hint"].contains("N navigation OFF"), "the hint reports N")

	var origin := Vector2(100.0, 200.0)
	check(EntityLayer.route_points([[100.0, 200.0], [130.0, 160.0]], origin) == PackedVector2Array([Vector2(0, 0), Vector2(30, 40)]), "world metres through the map origin (y flipped)")
	for bad in [null, [], [[1.0, 2.0]], "x", [[1.0, 2.0], [3.0]], [[1.0, 2.0], ["a", 3.0]], [[1.0, 2.0], [INF, 3.0]], [[1.0, 2.0], [NAN, 3.0]]]:
		check(EntityLayer.route_points(bad, origin).is_empty(), "no line from %s" % str(bad))
	var layer: Node2D = EntityLayer.new()
	layer.origin = origin
	var passenger := {"name": "Aino", "pickup": {"x": 130.0, "y": 160.0, "address": "A", "radius_m": 4.0}, "dropoff": {"x": 0.0, "y": 0.0, "address": "B", "radius_m": 4.0}}
	var state := {"taxi": {"state": "PICKUP", "current_passenger": passenger}, "navigation": {"points": [[100.0, 200.0], [130.0, 160.0]]}}
	check(layer.route_for(state).is_empty(), "N off: nothing drawn")
	layer.show_route = true
	check(layer.route_for(state).size() == 2, "N on: the newest route at once")
	var cached: PackedVector2Array = layer._route_points
	var same := state.duplicate(true)  # the next state: an equal route, parsed anew
	layer.route_for(same)
	check(layer._route_points == cached and layer._route_source == same["navigation"]["points"], "an unchanged route isn't rebuilt")
	var replanned := state.duplicate(true)
	replanned["navigation"]["points"] = [[100.0, 200.0], [100.0, 150.0], [130.0, 160.0]]
	check(layer.route_for(replanned).size() == 3, "a new route replaces the old line")
	check(layer.route_for({"taxi": {"state": "PICKUP"}, "navigation": replanned["navigation"]}).is_empty(), "no target: no route")
	check(layer.route_for(replanned.merged({"navigation": {"points": []}}, true)).is_empty(), "an empty route: nothing")
	check(layer.route_for(replanned.merged({"navigation": null}, true)).is_empty() and layer.route_for({"taxi": replanned["taxi"]}).is_empty(), "null or missing navigation: nothing")
	layer.show_route = false
	check(layer.route_for(replanned).is_empty(), "N off again: gone at once")
	layer.free()
	var source: String = (EntityLayer as Script).source_code
	var draw := source.substr(source.find("func _draw() -> void:"))
	check(draw.find("_pedestrian(") < draw.find("_route(a)") and draw.find("_route(a)") < draw.find("_target(a)") and draw.find("_target(a)") < draw.find("_vehicle("),
		"drawn after the pedestrians, before the target marker and the vehicles")
	var scene: Node = load("res://main.tscn").instantiate()
	var z: int = scene.get_node("EntityLayer").z_index
	scene.free()
	check(z > 7 and z < 11, "the entity layer (z %d) sits above the roads and buildings (z 7), under canopies and rail bridges (z 11)" % z)


## godot-final-03: the running fare in the mission line, the pump price in the gauge.
func test_taxi_information() -> void:
	var passenger := {"name": "Aino", "pickup": {"address": "Kirkkokatu 4"}, "dropoff": {"address": "Rautatientori"}}
	var fare := {"state": "DROPOFF", "current_passenger": passenger, "elapsed_time": 61.6, "live_fare_cents": 1234,
		"fare_distance_m": 2345.6, "passenger_happiness": 49.6}
	check(Hud.values({"taxi": fare})["fare"] == "Drive Aino to Rautatientori · 62 s · meter 12.34 € · 2.35 km · happiness 50%", "a running fare: time, meter, distance, happiness")
	var started := fare.merged({"elapsed_time": 0.0, "live_fare_cents": 0, "fare_distance_m": 0.0, "passenger_happiness": 100.0}, true)
	check(Hud.values({"taxi": started})["fare"].ends_with("· 0 s · meter 0.00 € · 0.00 km · happiness 100%"), "zeroes and the boundaries show as they are")
	check(Hud.values({"taxi": fare.merged({"live_fare_cents": 5}, true)})["fare"].contains("meter 0.05 €"), "a cent-level meter")
	var before := fare.merged({"live_fare_cents": null, "fare_distance_m": null, "passenger_happiness": null}, true)
	check(Hud.values({"taxi": before})["fare"] == "Drive Aino to Rautatientori · 62 s", "before the meter starts: no made-up meter values")
	var old := {"state": "DROPOFF", "current_passenger": passenger}
	check(Hud.values({"taxi": old})["fare"] == "Drive Aino to Rautatientori", "an older server: the plain mission line")
	check(Hud.values({"taxi": fare.merged({"live_fare_cents": "12", "passenger_happiness": [1]}, true)})["fare"] == "Drive Aino to Rautatientori · 62 s · 2.35 km", "malformed values are left out")
	check(Hud.values({"taxi": fare.merged({"state": "PICKUP"}, true)})["fare"] == "Pick up Aino at Kirkkokatu 4", "pickup text unchanged")
	check(Hud.values({"taxi": fare.merged({"state": "WALKING"}, true)})["fare"] == "Aino is walking to the taxi", "walking text unchanged")
	check(Hud.values({"taxi": {"completed_fares": 3, "elapsed_time": 9.0}})["fare"] == "No fare - 3 done", "no passenger: unchanged")

	check(Instruments.price_text({"taxi": {"fuel_station_price_cents": 189}}) == "G: REFUEL  1.89 €/L", "a pump in range: its price from cents")
	check(Instruments.price_text({"taxi": {"fuel_station_price_cents": 300.0}}) == "G: REFUEL  3.00 €/L", "a whole-euro price")
	for none in [{"taxi": {"fuel_station_price_cents": null}}, {"taxi": {}}, {}, {"taxi": {"fuel_station_price_cents": "189"}}, {"taxi": {"fuel_station_price_cents": -5}}]:
		check(Instruments.price_text(none) == "", "no pump, or a bad price %s: no line" % str(none))
	var gauge: Control = Instruments.new()
	root.add_child(gauge)
	gauge.show_state({"player": {"fuel_l": 20.0}, "taxi": {"fuel_station_price_cents": 189}})
	var shown: Array = gauge._shown.duplicate()
	gauge.show_state({"player": {"fuel_l": 20.0}, "taxi": {"fuel_station_price_cents": 245}})
	check(gauge._shown != shown, "another pump: the gauge redraws")
	shown = gauge._shown.duplicate()
	gauge.show_state({"player": {"fuel_l": 20.0}, "taxi": {"fuel_station_price_cents": null}})
	check(gauge._shown != shown and gauge._shown[9] == "", "driving away: the price goes")
	gauge.free()


func _key_event(code: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = code
	event.pressed = true
	return event


## godot-final-02: V/B session toggles, the score, the career city summary.
func test_controls_and_economy() -> void:
	var defaults := Main.command_for({}, true, false, false)
	check(defaults["speed_limiter_enabled"] == true and defaults["red_light_assist_enabled"] == false, "defaults: limiter on, red-light assist off (PlayerCommand's)")
	check(defaults["lane_assist_enabled"] == false and not defaults["respawn"] and not defaults["cancel_ride"] and not defaults["reset_trip"], "the remaining gameplay controls have safe defaults")
	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
	var sim: Node = main.get_node("SimClient")
	main._unhandled_input(_key_event(KEY_V))
	main.send({})
	check(sim._last_command["speed_limiter_enabled"] == false, "V turns the limiter off in the commands")
	main._unhandled_input(_key_event(KEY_B))
	main._unhandled_input(_key_event(KEY_K))
	main._unhandled_input(_key_event(KEY_F))
	main._unhandled_input(_key_event(KEY_G))
	main._unhandled_input(_key_event(KEY_R))
	main._unhandled_input(_key_event(KEY_X))
	main._unhandled_input(_key_event(KEY_T))
	main.send({"throttle": 1.0})
	var pressed: Dictionary = sim._last_command
	check(pressed["red_light_assist_enabled"] == true and pressed["speed_limiter_enabled"] == false and pressed["lane_assist_enabled"] == true, "B/K turn the assists on; the limiter stays off")
	check(pressed["interact"] and pressed["refuel"] and pressed["respawn"] and pressed["cancel_ride"] and pressed["reset_trip"], "F/G/R/X/T ride on the next command")
	main.send({"throttle": 0.0})
	var later: Dictionary = sim._last_command
	check(later["speed_limiter_enabled"] == false and later["red_light_assist_enabled"] == true, "later commands keep both toggles")
	check(later["interact"] == false and later["refuel"] == false, "F and G are sent once")
	check(not later["respawn"] and not later["cancel_ride"] and not later["reset_trip"] and later["lane_assist_enabled"], "R/X/T are sent once; K stays on")
	main._unhandled_input(_key_event(KEY_V))
	main.send({})
	check(sim._last_command["speed_limiter_enabled"] == true, "V again: the limiter back on")
	var driving := {"on_foot": false, "player": {"engine_on": true}}
	check(Hud.values(driving, {"speed_limiter": false, "red_light_assist": true})["hint"].contains("V limiter OFF · B red-light assist ON"), "the hint shows both states")
	check(Hud.values(driving)["hint"].contains("V limiter ON · B red-light assist OFF"), "the hint's defaults match the commands'")

	# Score: the server's number, whatever its sign; a missing one is a placeholder.
	check(Hud.values({"taxi": {"total_score": 1234}})["score"] == "1234", "positive score")
	check(Hud.values({"taxi": {"total_score": 0}})["score"] == "0", "zero score")
	check(Hud.values({"taxi": {"total_score": -250.0}})["score"] == "-250", "negative score (JSON numbers arrive as floats)")
	check(Hud.values({})["score"] == "–" and Hud.values({"taxi": {"total_score": null}})["score"] == "–", "a missing score is safe")

	# The city summary (render/menus.py draw_city_summary).
	var next := Hud.summary_text({"should_stop": true, "city_summary": ["Oulu", 10500, 12, "Tampere", 21000]})
	check(next == "City summary\n\nOulu\nScore: 10500\nFares completed: 12\nNext city: Tampere", "a next-city summary")
	var done := Hud.summary_text({"should_stop": true, "city_summary": ["Helsinki", 10200.0, 9.0, null, 98765.0]})
	check(done.ends_with("Career complete! Helsinki conquered.\nTotal career score: 98765") and done.contains("Helsinki\nScore: 10200"), "the last city: career complete and the total")
	for bad in [null, [], ["Oulu"], [1, 2, 3, 4, 5], "Oulu", ["Oulu", "x", 1, null, 2]]:
		check(Hud.summary_text({"should_stop": true, "city_summary": bad}) == "City summary\n\nThis city is complete.", "malformed summary %s: no made-up values" % str(bad))

	# Shown once should_stop arrives: it covers the UI and no more driving commands go out.
	var base := _state(0.0)
	main._present(base.merged({"should_stop": false, "taxi": {"total_score": 5}}))
	check(not main.summary_shown, "ordinary states: no summary")
	main._present(base.merged({"should_stop": true, "city_summary": ["Oulu", 10500, 12, "Tampere", 21000]}))
	var hud: Control = main.get_node("Ui/Hud")
	check(main.summary_shown and hud._summary.visible and hud._summary.text.contains("Next city: Tampere"), "should_stop shows the summary")
	var others: Array = main.get_node("Ui").get_children().filter(func(n): return n != hud)
	check(others.all(func(n): return not n.visible), "the rest of the game UI is hidden")
	main._present(base.merged({"should_stop": false}))
	check(hud._summary.visible, "it stays: the session is over")
	main._present({})
	check(hud.visible and hud._summary.visible, "no state any more (the server went away): the summary stays")
	sim._last_command = {}
	main._command_timer = 0.0
	main._process(0.1)
	check(sim._last_command.is_empty(), "no driving command after the summary")
	main.free()


## godot-11: the server's meet, road, speed-camera and lightning state.
func test_meet_road_camera_lightning() -> void:
	# Road and limit: the simulation's values, Pygame's wording.
	check(Hud.values({})["road"] == "" and Instruments.speed_limit({}) == 0, "no road field (older server): nothing shown")
	check(Hud.values({"road": {"name": null, "speed_limit_kmh": null}})["road"] == "Road: Off-road", "off-road")
	check(Hud.values({"road": {"name": "Isokatu", "speed_limit_kmh": 40}})["road"] == "Road: Isokatu [Limit: 40 km/h]", "named road with its limit")
	check(Hud.values({"road": {"name": "Living Street", "speed_limit_kmh": null}})["road"] == "Road: Living Street", "unnamed road (highway type) without a limit")
	check(Instruments.speed_limit({"road": {"name": "Isokatu", "speed_limit_kmh": 40}}) == 40, "limit sign value")
	check(Instruments.speed_limit({"road": {"name": "Isokatu", "speed_limit_kmh": null}}) == 0, "no limit known: no sign")

	# Speed camera: only a running notice flagged by the simulation.
	var camera_hit := {"taxi": {"notification_msg": "Speed camera! 12 km/h over -50 pts", "notification_timer": 3.0, "speed_camera_notice": true}}
	check(Hud.values(camera_hit)["notice_camera"], "a camera hit is styled as one")
	check(not Hud.values({"taxi": {"notification_msg": "Fare paid", "notification_timer": 3.0}})["notice_camera"], "an ordinary notice is not")
	camera_hit["taxi"]["notification_timer"] = 0.0
	check(Hud.values(camera_hit)["notice"] == "" and not Hud.values(camera_hit)["notice_camera"], "an expired notice shows nothing")

	# Meet panel: the server's lines while a meet is on, gone after.
	var meet := {"status": "PASSENGER_WAITING", "lines": ["Meet: Aino", "IC57 | Oulu", "Park and get out (F)"],
		"arrow": {"id": 7, "x": 20.0, "y": 40.0, "radius_m": 0.45}}
	check(Hud.values({"meet": meet})["meet"] == "Meet: Aino\nIC57 | Oulu\nPark and get out (F)", "meet panel lines")
	check(Hud.values({"meet": null})["meet"] == "" and Hud.values({})["meet"] == "", "no meet: no panel")
	var scene: Node = load("res://main.tscn").instantiate()
	var hud: Control = scene.get_node("Ui/Hud")
	hud.owner = null
	for child in hud.find_children("*", "", true, false):
		child.owner = hud  # keep the %Unique names resolvable once detached
	hud.get_parent().remove_child(hud)
	scene.free()
	root.add_child(hud)
	hud.show_state({"meet": meet, "taxi": camera_hit["taxi"]})
	check(hud._meet.visible and hud._meet.text.begins_with("Meet: Aino"), "the panel shows")
	hud.show_state({"meet": null})
	check(not hud._meet.visible, "boarded or missed: the panel goes")
	hud.queue_free()

	# Booked-passenger arrow: at the interpolated pedestrian by id, else the sent spot, never without a meet.
	var ped := {"id": 7, "x": 10.0, "y": 0.0, "heading": 0.0}
	var a := {"meet": meet, "pedestrians": [ped]}
	var later := {7: {"id": 7, "x": 20.0, "y": 0.0, "heading": 0.0}}
	check(EntityLayer.booked_arrow_at(a, {}, 0.5, later, Vector2.ZERO) == Vector2(15, 0), "the arrow follows the drawn (interpolated) passenger")
	check(EntityLayer.booked_arrow_at({"meet": meet, "pedestrians": []}, {}, 0.5, {}, Vector2.ZERO) == Vector2(20, -40), "not among the pedestrians: the sent position")
	var train_due := meet.duplicate()
	train_due["arrow"] = null
	check(EntityLayer.booked_arrow_at({"meet": train_due}, {}, 0.0, {}, Vector2.ZERO) == Vector2.INF, "train still due: no arrow")
	check(EntityLayer.booked_arrow_at({"meet": null}, {}, 0.0, {}, Vector2.ZERO) == Vector2.INF, "no meet: no stale arrow")

	# Lightning: the simulation's fading intensity, nothing of Godot's own.
	var none := {"weather": {"lightning_intensity": 0.0}}
	var strike := {"weather": {"lightning_intensity": 1.0}}
	check(EntityLayer.lightning_alpha(none, none, 0.5) == 0.0 and EntityLayer.lightning_alpha({}, {}, 0.5) == 0.0, "no lightning, or an older server: no flash")
	check(is_equal_approx(EntityLayer.lightning_alpha(strike, strike, 0.0), 145.0 / 255.0), "a strike flashes at Pygame's maximum alpha")
	check(is_equal_approx(EntityLayer.lightning_alpha(strike, none, 0.5), 0.5 * 145.0 / 255.0), "the flash fades with the sent intensity")


## godot-12: taxi stands, fuel stations, traffic-light posts and roadworks
## come with their chunk and go with it; the phase is only ever the server's.
func test_gameplay_points() -> void:
	var map := MapLayer.new()
	root.add_child(map)
	map.set_origin(Vector2(1000, 2000))
	var message := {"chunk_id": "2_4", "bounds": [1000, 2000, 1500, 2500], "roads": [], "railways": [], "waters": [], "buildings": [],
		"taxi_stands": [[1020.0, 2040.0]],
		"fuel_stations": [{"x": 1030.0, "y": 2060.0, "angle": 0.5, "is_area": true, "name": "Neste", "price_cents": 189}],
		"traffic_lights": [{"id": 0, "x": 1102.0, "y": 2050.0, "angle": 1.5708}, {"id": 1, "x": 1200.0, "y": 2050.0, "angle": 0.0}],
		"roadworks": [{"start": [1480.0, 2100.0], "end": [1540.0, 2100.0], "lane_closed": true, "half_width_m": 3.5}]}
	message = JSON.parse_string(JSON.stringify(message))  # as the client gets it: every number a float
	check(map.add_chunk(message) and not map.add_chunk(message), "points arrive with their chunk, once")
	var chunk = map._chunks["2_4"]
	check(chunk._px_layers.size() == 2 + 4 and chunk._lights != null, "pumps, boards, roadworks/stands and posts each get one canvas item (besides the tracks and buildings every chunk has)")
	check(MapMath.point(map.origin, 1020.0, 2040.0) == Vector2(20, -40), "a stand sits at its map position relative to the origin")
	check(map.add_chunk({"chunk_id": "0_0"}) and map._chunks["0_0"]._px_layers.size() == 2 and map._chunks["0_0"]._lights == null,
		"a chunk without points adds no point layers (older servers too)")
	check(MapChunk.fuel_board_text(message["fuel_stations"][0]) == "Neste  1.89 €/L", "the board shows the server's price")

	# Phases: lit as sent, unlit when not sent, redrawn only on change.
	check(MapChunk.lamps("green") == [false, false, true] and MapChunk.lamps("red+yellow") == [true, true, false], "lamps by phase")
	check(MapChunk.lamps("all-red") == [true, false, false] and MapChunk.lamps("") == [false, false, false], "all-red reads as red; no phase lights nothing")
	map.set_traffic_lights({"0": "green"})
	check(chunk._phases.get("0") == "green" and chunk._phases.get("1", "") == "", "each post takes the server's phase (a far one none)")
	check(not chunk.set_phases({"0": "green"}), "the same phases don't redraw")
	check(chunk.set_phases({"0": "yellow"}) and chunk._phases["0"] == "yellow", "a changed phase redraws")
	map.set_traffic_lights({"0": "yellow"})
	chunk._process(1.0) if chunk.has_method("_process") else null
	check(chunk._phases["0"] == "yellow" and not chunk.has_method("_process"), "no phase change without the server (no client clock)")

	# Unload and reload: gone, then back once at the same place.
	check(map.remove_chunk("2_4") and not map.has_chunk("2_4"), "points go with their chunk")
	check(map.add_chunk(map_message_copy(message)) and map._chunks["2_4"]._phases.get("0") == "yellow", "reloaded with the current phases")
	check(map.chunk_count() == 2 and not map.add_chunk(message), "no duplicate after a revisit")
	map.set_px_per_m(4.5)
	check(map._chunks["2_4"]._px_per_m == 4.5, "zoom reaches the pixel-sized points")
	map.free()


func map_message_copy(message: Dictionary) -> Dictionary:
	return message.duplicate(true)


## godot-13: trees, construction fences and bollards come and go with their
## chunk; felled trees and knocked posts are the server's state, matched by
## position. (Collision stays on the server: nothing here collides.)
func test_obstacles() -> void:
	var map := MapLayer.new()
	root.add_child(map)
	map.set_origin(Vector2(1000, 2000))
	var message: Dictionary = JSON.parse_string(JSON.stringify({"chunk_id": "2_4", "bounds": [1000, 2000, 1500, 2500],
		"roads": [], "railways": [], "waters": [], "buildings": [],
		"trees": [[1010.0, 2020.0, "pine", 0.25], [1030.0, 2020.0, "birch", 0.8]],
		"construction_fences": [[[1100.0, 2100.0], [1110.0, 2100.0], [1110.0, 2110.0]]],
		"bollards": [[1040.0, 2000.0]]}))
	check(map.add_chunk(message) and not map.add_chunk(message), "obstacles arrive with their chunk, once")
	var chunk = map._chunks["2_4"]
	check(chunk._trees != null and chunk._px_layers.size() == 2 + 2, "trees and bollards share one canvas item, fences another")
	check(MapChunk.obstacle_key(1010.0, 2020.0) == "1010.0,2020.0", "obstacles are named by position at 0.1 m, as the server rounds")

	# Look, as render/scenery.py: palette by variation, pine crowns smaller.
	var pine := MapChunk.tree_style("pine", 0.25)
	check(pine["crown"] == Color8(88, 108, 42) and is_equal_approx(pine["radius"], 1.9 * (0.72 + 0.25 * 0.62)), "a pine's crown")
	check(MapChunk.tree_style("birch", 0.8)["trunk"] == Color8(222, 218, 206) and is_equal_approx(MapChunk.tree_style("birch", 0.8)["radius"], 2.2 * (0.72 + 0.8 * 0.62)), "a birch's crown and white trunk")

	# Dashes: 1.5 m on, 1 m off, carried round a corner.
	var pieces := MapChunk.dashes(PackedVector2Array([Vector2(0, 0), Vector2(2, 0), Vector2(2, 3)]), 1.5, 1.0)
	check(pieces.size() == 2 and pieces[0] == [Vector2(0, 0), Vector2(1.5, 0)] and pieces[1][0].is_equal_approx(Vector2(2, 0.5)) and pieces[1][1].is_equal_approx(Vector2(2, 2)), "dash pattern carries over the corner")

	# The server's state: a felled tree, a knocked bollard and a knocked lamp (no static lamp data).
	var fallen: Array = JSON.parse_string("[[1010.0, 2020.0, 1.5]]")
	var knocked: Array = JSON.parse_string("[[1040.0, 2000.0, 3.14, \"bollard\"], [1200.0, 2200.0, 0.0, \"street_lamp\"]]")
	map.set_obstacles(fallen, knocked)
	check(chunk._fallen == {"1010.0,2020.0": 1.5} and chunk._knocked.has("1040.0,2000.0"), "the chunk takes its own felled tree and knocked bollard")
	check(map.knocked.size() == 2, "the knocked lamp is drawn from the state alone")
	check(not chunk.set_obstacles(map.fallen, map.knocked), "unchanged state: no redraw")
	map.set_obstacles(fallen.duplicate(true), knocked.duplicate(true))
	check(chunk._fallen.size() == 1, "the same lists again change nothing")

	# Unload and reload: gone, back once, still felled.
	check(map.remove_chunk("2_4") and map.chunk_count() == 0, "obstacles go with their chunk")
	check(map.add_chunk(message.duplicate(true)) and map._chunks["2_4"]._fallen.has("1010.0,2020.0"), "reloaded, the felled tree is still down")
	check(map.chunk_count() == 1 and not map.add_chunk(message), "no duplicate after a revisit")
	check(map.add_chunk({"chunk_id": "0_0"}) and map._chunks["0_0"]._trees == null, "a chunk without obstacles adds no layer (older servers too)")
	map.free()


## godot-14: night is the server's darkness, drawn as Pygame's tint; the
## client keeps no clock of its own.
func test_day_night() -> void:
	# godot-lights-01: the light is a continuous function of the sun's altitude.
	check(Daylight.ambient(30.0) == 1.0 and Daylight.artificial(30.0) == 0.0 and Daylight.ambient_color(30.0) == Color.WHITE, "full daylight: no darkening, no artificial light")
	check(Daylight.ambient(-30.0) == 0.0 and Daylight.artificial(-30.0) == 1.0, "deep night: ambient at its floor, the lights full")
	var night_blue := Daylight.ambient_color(-30.0)
	check(night_blue.b > night_blue.r and night_blue.b > night_blue.g and night_blue.r > 0.1, "night is a cold blue, never black")
	var low := Daylight.ambient(5.0)
	check(low > 0.8 and low < 1.0 and Daylight.artificial(5.0) > 0.0 and Daylight.artificial(5.0) < 0.5, "a low sun: still bright, the lights starting to show")
	var above := Daylight.ambient(0.01)
	var below := Daylight.ambient(-0.01)
	check(above > below and above - below < 0.005 and absf(Daylight.artificial(0.01) - Daylight.artificial(-0.01)) < 0.005, "no step at the horizon (0.02 degrees changes it by under 0.5 %)")
	var previous_ambient := 2.0
	var previous_lights := -1.0
	var worst_step := 0.0
	var monotonic := true
	var altitude := 40.0
	while altitude >= -40.0:
		var a := Daylight.ambient(altitude)
		var l := Daylight.artificial(altitude)
		monotonic = monotonic and a <= previous_ambient + 1e-9 and l >= previous_lights - 1e-9
		if previous_ambient <= 1.0:
			worst_step = maxf(worst_step, maxf(absf(a - previous_ambient), absf(l - previous_lights)))
			var colour_step := Daylight.ambient_color(altitude) - Daylight.ambient_color(altitude + 0.1)
			worst_step = maxf(worst_step, maxf(absf(colour_step.r), maxf(absf(colour_step.g), absf(colour_step.b))))
		previous_ambient = a
		previous_lights = l
		altitude -= 0.1
	check(monotonic, "darker and more lights as the sun sinks, all the way down")
	check(worst_step < 0.012, "no step anywhere: at most %.4f per 0.1 degree" % worst_step)
	check(Daylight.ambient(-3.0) == Daylight.ambient(-3.0) and Daylight.artificial(2.0) == Daylight.artificial(2.0), "dusk and dawn are the same curve (a function of altitude alone)")
	check(Daylight.altitude({"calendar": {"sun_altitude_deg": -4.5, "darkness": 0.9}}) == -4.5, "the server's altitude when it sends one")
	check(is_equal_approx(Daylight.altitude({"calendar": {"darkness": 0.5}}), -3.0) and Daylight.altitude({}) == 90.0, "an older server: back from its darkness; none: daylight")
	var main_source: String = (Main as Script).source_code
	check(not main_source.contains("darkness > 0.25") and not main_source.contains("night_alpha"), "no day/night switch left in the light path")

	# The HUD clock: the server's date, and * while game time runs 1:1.
	var state := {"game_time_seconds": 18.0 * 3600.0 + 20.0 * 60.0, "calendar": {"date": "2026-10-05", "time_scale": 60.0, "darkness": 0.2}}
	check(Hud.values(state)["clock"] == "2026-10-05 18:20", "date and time (%s)" % Hud.values(state)["clock"])
	state["calendar"]["time_scale"] = 1.0
	check(Hud.values(state)["clock"] == "2026-10-05 18:20 *", "real-time marker during a fare")
	check(Hud.values({"game_time_seconds": 3600.0})["clock"] == "01:00", "no calendar: the time alone")


	# Lightning: the sent intensity, nothing of the client's own (shown above the tint).
	var entities = load("res://entity_layer.gd").new()
	check(entities.lightning_now() == 0.0, "no state yet: no flash")
	entities.free()


## godot-15: railings, decorations, street lights (on at night, dark when
## knocked), headlight beams, reflectors, seasons - all drawing, no collision.
func test_static_world() -> void:
	var map := MapLayer.new()
	root.add_child(map)
	map.set_origin(Vector2(1000, 2000))
	var message: Dictionary = JSON.parse_string(JSON.stringify({"chunk_id": "2_4", "bounds": [1000, 2000, 1500, 2500],
		"roads": [], "railways": [], "waters": [[[1100, 2100], [1120, 2100], [1120, 2120]]],
		"buildings": [[[1300, 2300], [1310, 2300], [1310, 2310], [1300, 2310]]],
		"railings": [["hedge", [[1000.0, 2010.0], [1020.0, 2010.0]]], ["fence", [[1000.0, 2020.0], [1010.0, 2020.0]]]],
		"scenery_objects": [[1050.0, 2050.0, "bench", 0.5], [1052.0, 2050.0, "fountain", 0.0]],
		"street_lights": [[1200.0, 2200.0, 1.0, 14.0], [1212.0, 2200.0, 1.0, 14.0]]}))
	check(map.add_chunk(message) and not map.add_chunk(message), "drawing-only objects arrive with their chunk, once")
	var chunk = map._chunks["2_4"]
	check(chunk._trees != null and chunk._px_layers.size() == 2 + 4, "decorations with the trees; railings, light pools, lamp heads: one canvas item each")
	check(chunk.street_lights.size() == 2 and chunk.street_lights[0] == Vector2(200, -200), "street lights at their map position")
	check(chunk._pools.get_parent() == map._pool_group, "a chunk's pools join the one pool group (added once, not per pool)")

	# Night only; a knocked street lamp is dark; nothing collides (no physics nodes anywhere).
	check(not map._pool_group.visible and not chunk._heads.visible, "by day the street lights are off")
	map.set_light(0.5, Color(0.5, 0.5, 0.7))
	check(map._pool_group.visible and chunk._heads.visible and is_equal_approx(map._pool_group.modulate.a, 0.5), "as the light fades they come on, as strong as the artificial light shows")
	map.set_light(1.0, Color(0.15, 0.2, 0.34))
	check(is_equal_approx(map._pool_group.modulate.a, 1.0), "at night, full")
	check(map.lamp_near(Vector2(203, -200), 5.0) and not map.lamp_near(Vector2(203, -250), 5.0), "a working light is near")
	map.set_obstacles([], JSON.parse_string("[[1200.0, 2200.0, 0.5, \"street_lamp\"]]"))
	check(chunk._broken == PackedInt32Array([0]), "the knocked lamp's light goes dark")
	check(not map.lamp_near(Vector2(200, -200), 3.0) and map.lamp_near(Vector2(212, -200), 3.0), "a broken light lights nothing; its neighbour still does")
	check(map.find_children("*", "CollisionObject2D", true, false).is_empty() and map.find_children("*", "CollisionShape2D", true, false).is_empty(),
		"no collision on the client")

	# Seasons: the server's weights, Pygame's palettes; unchanged weights redraw nothing.
	check(MapChunk.seasonal_color(Color8(34, 101, 35), [0.0, 0.0, 1.0, 0.0]) == Color8(34, 101, 35), "summer keeps the colour")
	check(MapChunk.seasonal_color(Color8(34, 101, 35), [1.0, 0.0, 0.0, 0.0]) == Color8(221, 228, 221), "winter: Pygame's frosted palette")
	check(MapChunk.seasonal_color(Color8(34, 101, 35), [0.0, 0.0, 0.0, 1.0]) == Color8(83, 116, 37), "autumn: Pygame's ochre palette")
	map.set_season([1.0, 0.0, 0.0, 0.0])
	check(chunk._season == [1.0, 0.0, 0.0, 0.0] and not chunk.set_season([1.0, 0.0, 0.0, 0.0]), "the chunk takes the season once")

	# Unload: the pools leave the group with their chunk; reload: once again, still dark.
	check(map.remove_chunk("2_4"), "unload")
	check(map._pool_group.get_child_count() == 0, "no stale pools after an unload")
	check(map.add_chunk(message.duplicate(true)) and map._chunks["2_4"]._broken == PackedInt32Array([0]), "reloaded: the knocked lamp is still dark")
	check(map._pool_group.get_child_count() == 1, "no duplicate pools after a revisit")
	map.free()

	# Headlight beams (render/vehicles.py): two quads and two caps per car, 15 m; long beams 45 m.
	var beams := EntityLayer2.beam_polygons(Vector2.ZERO, 0.0, 1.8, 15.0)
	check(beams.size() == 4 and is_equal_approx(beams[0][3].x, 15.0) and is_equal_approx(beams[0][3].y, 3.0), "a beam reaches 15 m ahead, its tip shifted right")
	check(is_equal_approx(EntityLayer2.beam_polygons(Vector2.ZERO, 0.0, 1.8, 45.0)[2][3].x, 45.0), "long beams reach 45 m")
	check(EntityLayer2.beam_length(false, false) == 45.0 and EntityLayer2.beam_length(true, false) == 15.0 and EntityLayer2.beam_length(false, true) == 15.0, "high beam on a dark road, dipped by street lights and oncoming traffic")
	check(not FileAccess.get_file_as_string("res://entity_layer.gd").contains("if vehicle[3] and not lamp_near"), "the taxi gets the high beam too")
	var car := [Vector2.ZERO, 0.0, 1.8, true]
	check(EntityLayer2.oncoming(car, [car, [Vector2(30, 0), PI, 1.8, true]]), "a car 30 m ahead coming the other way dips the beams")
	check(not EntityLayer2.oncoming(car, [car, [Vector2(30, 0), 0.0, 1.8, true]]), "one going the same way doesn't")


	# Reflectors: not in the taxi's cone.
	check(EntityLayer2.reflector_lit(Vector2(10, 0), Vector2.ZERO, 0.0), "ahead in the beam: lit, no reflector needed")
	check(not EntityLayer2.reflector_lit(Vector2(-5, 0), Vector2.ZERO, 0.0) and not EntityLayer2.reflector_lit(Vector2(10, -8), Vector2.ZERO, 0.0), "behind or aside: the reflector shows")

	# godot-final-09: one tint rectangle and every beam in one additive batch.
	var night = NightLayer.new()
	root.add_child(night)
	var two_cars: Array = EntityLayer2.beam_polygons(Vector2.ZERO, 0.0, 1.8, 15.0) + EntityLayer2.beam_polygons(Vector2(0, 20), PI, 1.8, 45.0)
	night.show_lights(1.0, Rect2(0, 0, 10, 10), two_cars)
	check(night.visible and night.beam_triangles.size() == 4 * 6 and night.beam_points.size() == 4 * 4, "two cars, four lamps: four quads in one batch (the caps left out)")
	check(night.beam_colors[0] == Color(NightLayer.BEAM, 1.0) and night.beam_colors[2] == Color(0, 0, 0, 1.0), "bright at the lamp, nothing at the far end")
	check(night.get_child_count() == 1 and (night.beams.material as CanvasItemMaterial).light_mode == CanvasItemMaterial.LIGHT_MODE_UNSHADED, "one node; light the ambient multiply doesn't darken")
	night.show_lights(0.5, Rect2(0, 0, 10, 10), two_cars)
	check(night.beam_colors[0].is_equal_approx(Color(NightLayer.BEAM * 0.5, 1.0)) and night.beam_points.size() == 16, "half the light at dusk; the arrays reused")
	night.show_lights(0.0, Rect2(0, 0, 10, 10), two_cars)
	check(not night.visible and night.beam_triangles.is_empty(), "day: no beams")
	var source: String = (NightLayer as Script).source_code
	check(not source.contains("clip_polygons") and not source.contains("draw_rect"), "no tint polygon, no polygon booleans")
	night.free()


## godot-16: landuse, parking, islands, curbs, crossings, bumps, signs,
## cameras, labels, road markings and colours, building roofs, canopies,
## rail bridges, underground, tyre tracks - drawing only, from the chunks
## and the state.
func test_rest_of_static_world() -> void:
	var map := MapLayer.new()
	root.add_child(map)
	map.set_origin(Vector2(0, 0))
	var message: Dictionary = JSON.parse_string(JSON.stringify({"chunk_id": "0_0", "bounds": [0, 0, 500, 500],
		"roads": [{"points": [[0, 10], [200, 10]], "half_width_m": 4.0, "drivable": true, "layer": 0, "color": [80, 80, 80], "center": [110, 110, 110, 1]},
			{"points": [[50, 0], [50, 100]], "half_width_m": 5.0, "drivable": true, "layer": 1, "color": [80, 80, 80], "bridge": true}],
		"railways": [[[0, 300], [100, 300]]], "rail_bridges": [[[0, 320], [100, 320]]], "rail_decks": [[[0, 318], [100, 318], [100, 322], [0, 322]]],
		"waters": [], "buildings": [[[300, 300], [320, 300], [320, 310], [300, 310]]], "building_styles": [[[40, 63, 92], 1, 6.0, [[310, 300]]]],
		"canopies": [[[400, 400], [410, 400], [410, 410], [400, 410]]],
		"landuse": [[[100, 145, 80], 1, [[0, 0], [100, 0], [100, 100]]]], "traffic_islands": [[[112, 150, 86], 1, [[60, 60], [70, 60], [70, 70]]]],
		"parking": [[[200, 200], [205, 200], [205, 210], [200, 210]]], "curbs": [[[0, 5], [50, 5]]],
		"crossings": [[100, 10, 0.0, 6.0, 2.2]], "speed_bumps": [[150, 10, 0.0, 4.0, "table"]],
		"signs": [[120, 20, "stop", 0.0]], "speed_cameras": [[3, 130, 20, 1.5]], "guardrails": [[45, 0, 45, 100]],
		"labels": [[10, 10, "Isokatu", 4], [12, 10, "Keskusta", 0]], "level_roads": [[[-3], [[0, 50], [80, 50]], 3.0, [70, 70, 70]]]}))
	check(map.add_chunk(message), "the rest of the static world arrives with its chunk")
	var chunk = map._chunks["0_0"]
	check(typeof(chunk._data["landuse"][0][2]) == TYPE_PACKED_VECTOR2_ARRAY and typeof(chunk._data["roads"][0]["points"]) == TYPE_PACKED_VECTOR2_ARRAY,
		"polylines and polygons are kept packed, not as parsed JSON")
	check(chunk._data["buildings"][0][2] == Vector2(320, -310), "packed in layer coordinates")
	check(map.find_children("*", "CollisionObject2D", true, false).is_empty(), "still no collision on the client")
	check(chunk._season_layers.size() == 2 and chunk._signs != null, "landuse and islands follow the season; signs and cameras have their layer")

	# Road markings (render/roads.py): the centre line where the road is 6 px wide or more; chevrons on one-way roads zoomed in.
	var lines := {}
	var chevrons := PackedVector2Array()
	var road: Dictionary = chunk._data["roads"][0]
	Detail.road_markings(chunk, road, road["points"], lines, chevrons)
	check(lines.size() == 1 and lines.values()[0].size() > 2 and chevrons.is_empty(), "a two-way road gets a dashed centre line, no chevrons")
	var dashed: PackedVector2Array = lines.values()[0]
	check(is_equal_approx(dashed[0].distance_to(dashed[1]), 8.0), "dashes are 8 m (at 9 px/m)")
	chunk._px_per_m = 0.5
	lines.clear()
	Detail.road_markings(chunk, road, road["points"], lines, chevrons)
	check(lines.is_empty(), "zoomed out, an 8 m road under 6 px has no centre line")
	chunk._px_per_m = 9.0
	var one_way: Dictionary = {"half_width_m": 4.0, "center": [110, 110, 110, 2], "oneway": -1}
	lines.clear()
	Detail.road_markings(chunk, one_way, PackedVector2Array([Vector2(0, 0), Vector2(100, 0)]), lines, chevrons)
	check(lines.values()[0].size() == 2 and chevrons.size() == 2 * 4, "solid centre line; one-way chevrons at 40 and 80 m (none within 5 m of the start)")

	# Headlights under a higher road; the taxi on that bridge keeps them.
	check(map.covered(Vector2(50, -50), 0) and not map.covered(Vector2(50, -50), 1) and not map.covered(Vector2(150, -50), 0),
		"under the bridge (layer 1) at layer 0: covered; on it or beside it: not")

	# Underground: the level's roads, no street lights; the camera flash only where that camera is.
	map.set_light(1.0, Color(0.15, 0.2, 0.34))
	map.set_map_level(-3)
	check(map.map_level == -3 and not map._pool_group.visible, "below ground: no street lights")
	map.set_map_level(0)
	check(map._pool_group.visible, "back up: the lights again")
	check(chunk.set_flash(3) and chunk._flash == 3 and not chunk.set_flash(3), "the flashing camera redraws its chunk once")

	# Labels (render/labels.py): priority, one per name, no overlaps, zoom gates, the HUD band left free.
	var canvas := Transform2D(0.0, Vector2(9, 9), 0.0, Vector2(640, 360))
	var font := ThemeDB.fallback_font
	var shown := Labels.declutter([[0, 0, "Isokatu", 4], [1, 0, "Keskusta", 0], [0, -20, "Torikatu", 4], [0, 20, "Torikatu", 4], [0, -35, "Ylhaalla", 4]],
		canvas, Vector2(1280, 720), font)
	check(shown.map(func(l): return l[1]) == ["Keskusta", "Torikatu"],
		"the district wins the spot over an overlapping road label; a name shows once; the HUD band (y < 80) stays free")
	check(Labels.declutter([[0, 0, "Isokatu", 4]], Transform2D(0.0, Vector2(0.3, 0.3), 0.0, Vector2(640, 360)), Vector2(1280, 720), font).is_empty(),
		"roads are labelled from 0.35 px/m")
	var many: Array = []
	for i in 50:
		many.append([float(i % 10) * 12.0 - 60.0, float(i / 10) * 4.0 - 10.0, "Place %d" % i, 0])
	check(Labels.declutter(many, canvas, Vector2(1280, 720), font).size() <= 35, "at most 35 labels")
	map.free()

	# Tyre tracks: laid from the server's mark along the drawn taxi; bounded.
	var entities = load("res://entity_layer.gd").new()
	root.add_child(entities)
	for i in 4100:  # trails of 100 points (marking stops in between), as driving lays them
		var mark = null if i % 101 == 100 else {"kind": "dirt", "intensity": 1.0, "front": true}
		var state := {"player": {"x": i * 0.6, "y": 0.0, "heading": 0.0}, "on_foot": false, "tire_mark": mark}
		entities._frame = {"a": state, "b": state, "t": 0.0}
		entities._lay_track()
	check(entities._track_points <= 4000 and entities._track_points >= 3400, "at most 4000 track points; whole oldest trails go, to about 3500 (%d)" % entities._track_points)
	var gap := {"player": {"x": 99999.0, "y": 0.0, "heading": 0.0}, "on_foot": false, "tire_mark": null}
	entities._frame = {"a": gap, "b": gap, "t": 0.0}
	entities._lay_track()
	check(entities._last_track == null, "no mark: the trail breaks")
	entities.free()

	# Snow: the trip text is outlined (readable on white).
	check(Instruments.TEXT_OUTLINE.v < 0.2 and Instruments.TEXT_OUTLINE_PX >= 3, "a dark outline under the light HUD text")


## godot-20: buildings project radially away from the view centre, leaving
## the ground map untouched and exposing facades toward the visible play area.
func test_buildings_2_5d() -> void:
	# The extrusion is screen-relative: roofs move away from the camera, so
	# their walls run back toward the centre on every side of the screen.
	check(B25.lift(10.0, Vector2(0, -20), Vector2.ZERO) == Vector2(0.0, -3.5), "top-screen roof projects upward")
	check(B25.lift(10.0, Vector2(0, 20), Vector2.ZERO) == Vector2(0.0, 3.5), "bottom-screen roof projects downward")
	check(B25.lift(10.0, Vector2(-20, 0), Vector2.ZERO) == Vector2(-3.5, 0.0), "left-screen roof projects left")
	check(B25.lift(10.0, Vector2(20, 0), Vector2.ZERO) == Vector2(3.5, 0.0), "right-screen roof projects right")
	check(B25.lift(100.0).y < B25.lift(40.0).y * 2.0, "no height cap: 100 m projects 2.5 x as far as 40 m")
	check(B25.lift(3.0).length() < B25.lift(9.0).length() and B25.lift(9.0).length() < B25.lift(30.0).length(), "taller lifts further")

	# Visible walls: those whose outward side faces down the screen, either winding.
	var box := PackedVector2Array([Vector2(0, 0), Vector2(20, 0), Vector2(20, 10), Vector2(0, 10)])
	check(B25.visible_walls(box) == PackedInt32Array([2]), "an axis-aligned box shows its south wall (2); east and west are edge-on")
	var reversed := box.duplicate()
	reversed.reverse()
	check(B25.visible_walls(reversed) == PackedInt32Array([0]), "the same wall whichever way the footprint winds")
	var diamond := PackedVector2Array([Vector2(10, 0), Vector2(20, 10), Vector2(10, 20), Vector2(0, 10)])
	check(B25.visible_walls(diamond) == PackedInt32Array([1, 2]), "a turned box shows its two lower walls")
	var l_shape := PackedVector2Array([Vector2(0, 0), Vector2(20, 0), Vector2(20, 10), Vector2(10, 10), Vector2(10, 20), Vector2(0, 20)])
	check(B25.visible_walls(l_shape) == PackedInt32Array([2, 4]), "an L shows the notch's south wall and the bottom wall")
	var view := Vector2(10, 100)
	var l_up := B25.lift(10.0, Vector2(10, 10), view)
	var l_out: Dictionary = B25.build([l_shape], [[[92, 57, 48], 0, 10.0, [], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
	var l_points: PackedVector2Array = l_out["points"]
	check(l_points.has(Vector2(20, 10) + l_up) and l_points.has(Vector2(0, 20) + l_up), "L walls use the same radial projection")

	# Footprint and alignment: height never moves a building sideways.
	for h: float in [5.0, 20.0, 100.0]:
		var radial := B25.lift(h, Vector2(10, 5), view)
		var o: Dictionary = B25.build([box], [[[92, 57, 48], 0, h, [], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
		check(o["points"].has(Vector2(20, 10)) and o["points"].has(Vector2(0, 10)) and o["points"].has(Vector2(0, 10) + radial),
			"%d m: ground edge stays fixed and roof edge gets the radial offset" % h)
	var flip: Dictionary = B25.build([reversed], [[[92, 57, 48], 0, 10.0, [], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
	var fwd: Dictionary = B25.build([box], [[[92, 57, 48], 0, 10.0, [], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
	var fp := Array(fwd["points"])
	var rp := Array(flip["points"])
	fp.sort()
	rp.sort()
	check(fp == rp and flip["colors"].count(B25.WINDOW) == fwd["colors"].count(B25.WINDOW), "either winding: the same vertices and windows")

	# The built geometry: walls from the ground edge to the lifted edge; the roof is the footprint lifted.
	var style := [[92, 57, 48], 0, 10.0, [], [158, 105, 82], 3, 0]
	var out: Dictionary = B25.build([box], [style], Vector2.ZERO, view)
	var up := B25.lift(10.0, Vector2(10, 5), view)
	var points: PackedVector2Array = out["points"]
	var has := func(p: Vector2) -> bool: return points.has(p)
	check(has.call(Vector2(20, 10)) and has.call(Vector2(20, 10) + up) and has.call(Vector2(0, 10) + up), "the south wall spans its fixed ground edge to the radial roof edge")
	check(has.call(Vector2(0, 0) + up) and has.call(Vector2(20, 0) + up), "the roof is the footprint plus the radial height projection")
	for i in out["colors"].size():
		if out["colors"][i] == B25.WINDOW:
			var p: Vector2 = points[i]
			check(p.x > 0.0 and p.x < 20.0 and p.y < 10.0 and p.y > 10.0 + up.y, "windows lie on the south wall")
			break
	check(out["colors"].has(Color8(92, 57, 48)) and out["colors"].has(Color8(58, 80, 94)), "roof colour and facade windows from the style")
	check(out["indices"].size() % 3 == 0 and out["hulls"].size() == 1, "triangles; one hull (headlights) per building")
	var again: Dictionary = B25.build([box], [style], Vector2.ZERO, view)
	check(again["points"] == out["points"] and again["colors"] == out["colors"] and again["lit_points"] == out["lit_points"],
		"deterministic: a reloaded chunk builds the same building, lit windows included")
	var tall: Dictionary = B25.build([box], [[[92, 57, 48], 0, 30.0, [], [158, 105, 82], 10, 0]], Vector2.ZERO, view)
	check(tall["points"].size() > out["points"].size(), "a taller building has more floors of windows")

	# Gabled roof: two facets and the ridge, on the raised roof.
	var gabled: Dictionary = B25.build([box], [[[92, 57, 48], 1, 10.0, [], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
	check(gabled["colors"].has(Color8(92, 57, 48).lightened(14.0 / 255.0)) and gabled["colors"].has(B25.RIDGE), "pitched roof: lit facet and ridge")
	check(gabled["points"].has(Vector2(0, 0) + up) and gabled["points"].has(Vector2(20, 10) + up), "the pitched roof is over the footprint, not shifted")

	# Doors: on a visible wall at the entrance, one storey high; not on a hidden wall.
	var south_door: Dictionary = B25.build([box], [[[92, 57, 48], 0, 10.0, [[10.0, -10.0]], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
	var north_door: Dictionary = B25.build([box], [[[92, 57, 48], 0, 10.0, [[10.0, 0.0]], [158, 105, 82], 3, 0]], Vector2.ZERO, view)
	check(south_door["colors"].has(B25.DOOR) and not north_door["colors"].has(B25.DOOR), "a door on the south wall shows; one on the hidden north wall doesn't")

	# Lit windows: Pygame's probabilities, by category; the glow is a separate list.
	var lit := 0
	var total := 0
	for i in 60:
		var many: Dictionary = B25.build([box], [[[92, 57, 48], 0, 20.0, [], [158, 105, 82], 6, 0]], Vector2(i * 37.0, i * 11.0))
		lit += many["lit_indices"].size() / 6
		total += many["colors"].count(B25.WINDOW) / 4
	check(total > 0 and lit > 0 and float(lit) / total < 0.25, "a scattering of windows lit at night (%d of %d)" % [lit, total])

	# In the map: one building group, ordered far to near; freed with the chunk; no collision.
	var map := MapLayer.new()
	root.add_child(map)
	var north: Dictionary = JSON.parse_string(JSON.stringify({"chunk_id": "0_1", "bounds": [0, 500, 500, 1000], "buildings": [[[10, 510], [30, 510], [30, 530], [10, 530]]], "building_styles": [style]}))
	var south: Dictionary = JSON.parse_string(JSON.stringify({"chunk_id": "0_0", "bounds": [0, 0, 500, 500], "buildings": [[[10, 10], [30, 10], [30, 30], [10, 30]]], "building_styles": [style],
		"canopies": [[[100, 100], [110, 100], [110, 110], [100, 110]]], "canopy_heights": [6.0]}))
	map.add_chunk(south)
	map.add_chunk(north)
	check(map._buildings.get_child_count() == 2 and map._buildings.get_child(0) == map._chunks["0_1"].building_node, "the farther chunk's buildings draw first")
	map.set_building_view(Vector2(0, 100))
	check(map._chunks["0_0"]._built_view == Vector2(0, 100), "camera movement recalculates radial building geometry")
	map.add_chunk(JSON.parse_string(JSON.stringify({"chunk_id": "1_0", "bounds": [500, 0, 1000, 500], "buildings": [[[510, 10], [530, 10], [530, 30], [510, 30]]], "building_styles": [style]})))
	check(map._buildings.get_child(2) == map._chunks["0_0"].building_node, "radial order: the chunk nearest the view centre draws last")
	map.remove_chunk("1_0")
	check(is_equal_approx(Detail.canopy_height(map._chunks["0_0"], map._chunks["0_0"]._data["canopies"][0]), 6.0), "a canopy is raised by its own height")
	map.set_map_level(-3)
	check(map._underground.z_index > map._buildings.z_index, "below ground the dark view covers the buildings")
	check(map._buildings.z_index < 11, "rail bridges (z 11) stay above the buildings")
	map.remove_chunk("0_1")
	check(map._buildings.get_child_count() == 1, "a chunk's buildings go with it")
	check(map.find_children("*", "CollisionObject2D", true, false).is_empty(), "no collision")
	map.free()


static func _area(polygons: Array) -> float:
	var total := 0.0
	for polygon in polygons:
		total += absf(B25.signed_area(polygon))
	return total


## godot-18: the optimisations keep the picture - same areas tinted, lit,
## drawn - with less work.
## godot-21: the 3D building layer's geometry and its alignment with the 2D map.
func test_buildings_3d() -> void:
	check(B3.to_3d(Vector2(12.5, -40.0)) == Vector3(12.5, 0.0, -40.0), "2D (x, y) -> 3D (x, 0, y)")
	check(B3.to_3d(Vector2(1, 2), 7.0).y == 7.0, "height is the 3D y")
	var centre := Vector2(30.0, -20.0)
	var d := B3.camera_height(720.0 / 9.0)
	check(is_equal_approx(2.0 * d * tan(deg_to_rad(B3.FOV) / 2.0), 80.0), "the ground plane fills the 2D view (720 px at 9 px/m = 80 m)")
	for p in [Vector2(0, 0), Vector2(70, -60), Vector2(-5, 13)]:
		check(B3.project(B3.to_3d(p), centre, d).is_equal_approx(p), "a ground point lands where the 2D map has it")
	var r := 25.0
	var low := B3.project(Vector3(centre.x + r, 5.0, centre.y), centre, d).x - centre.x - r
	var high := B3.project(Vector3(centre.x + r, 10.0, centre.y), centre, d).x - centre.x - r
	check(low > 0.0 and high > low * 1.9, "a roof moves outward from the view centre, a 10 m one about twice a 5 m one")
	var a := B3.project(Vector3(centre.x + 0.01, 20.0, centre.y), centre, d)
	var b := B3.project(Vector3(centre.x - 0.01, 20.0, centre.y), centre, d)
	check(a.distance_to(b) < 0.05, "continuous through the view centre: no wall switching")
	var box := PackedVector2Array([Vector2(0, 0), Vector2(20, 0), Vector2(20, 10), Vector2(0, 10)])
	var reversed := box.duplicate()
	reversed.reverse()
	var l_shape := PackedVector2Array([Vector2(0, 0), Vector2(24, 0), Vector2(24, -10), Vector2(10, -10), Vector2(10, -22), Vector2(0, -22)])
	var odd := PackedVector2Array([Vector2(0, 0), Vector2(9, -3), Vector2(14, 6), Vector2(4, 11), Vector2(-3, 5)])
	var style := [[92, 57, 48], 0, 10.0, [], [158, 105, 82], 3, 0]
	for footprint in [box, reversed, l_shape, odd]:
		var out: Dictionary = B3.build([footprint], [style], Vector2.ZERO)
		var ground := 0
		var top := -INF
		for v in out["verts"]:
			if v.y == 0.0:
				ground += 1
				check(Geometry2D.is_point_in_polygon(Vector2(v.x, v.z), footprint.duplicate()) or _on_outline(Vector2(v.x, v.z), footprint) , "ground vertices on the footprint")
			top = maxf(top, v.y)
		check(out["stats"]["walls"] == footprint.size() and ground > 0 and is_equal_approx(top, 10.0), "every wall extruded from the ground to the height (%d sides)" % footprint.size())
		check(out["verts"] == B3.build([footprint], [style], Vector2.ZERO)["verts"], "deterministic geometry")
	# godot-22 back-face culling: every triangle's front (clockwise, so its cross
	# product points away) faces out of the building, whichever way it winds.
	for footprint in [box, reversed, PackedVector2Array([Vector2(10, 0), Vector2(20, -10), Vector2(10, -20), Vector2(0, -10)])]:
		var mid := Vector3.ZERO
		for p in footprint:
			mid += B3.to_3d(p, 5.0) / footprint.size()
		var out: Dictionary = B3.build([footprint], [[[92, 57, 48], 1, 10.0, [[10.0, 0.0]], [158, 105, 82], 3, 2]], Vector2.ZERO)
		var inward := 0
		for key in ["verts", "lit"]:
			var v: PackedVector3Array = out[key]
			for t in range(0, v.size(), 3):
				var away := (v[t + 1] - v[t]).cross(v[t + 2] - v[t])
				if away.dot((v[t] + v[t + 1] + v[t + 2]) / 3.0 - mid) > 0.0:
					inward += 1
		check(inward == 0, "every wall, roof, window and door triangle faces outward (%d did not)" % inward)
	var tall: Dictionary = B3.build([box], [[[92, 57, 48], 0, 40.0, [], [158, 105, 82], 12, 0]], Vector2.ZERO)
	var top_tall := -INF
	for v in tall["verts"]:
		top_tall = maxf(top_tall, v.y)
	check(is_equal_approx(top_tall, 40.0), "a 40 m building is 40 m tall")
	var gabled: Dictionary = B3.build([box], [[[92, 57, 48], 1, 10.0, [], [158, 105, 82], 3, 0]], Vector2.ZERO)
	var ridge := -INF
	for v in gabled["verts"]:
		ridge = maxf(ridge, v.y)
	check(ridge > 10.0 and ridge <= 14.0, "a pitched roof rises above the walls")
	check(B3.build([box], [[[92, 57, 48], 0, 10.0, [[10.0, -10.0]], [158, 105, 82], 3, 0]], Vector2.ZERO)["colors"].has(B25.DOOR), "a door at the entrance")
	# godot-23: the gables close the pitched roof. The ridge runs along x
	# (the box's longest edge) at y = 5, so the two short walls get a peak.
	var peaks := 0
	var capped := 0
	for v in gabled["verts"]:
		if is_equal_approx(v.y, ridge) and (is_equal_approx(v.x, 0.0) or is_equal_approx(v.x, 20.0)):
			peaks += 1
	for t in range(0, gabled["verts"].size(), 3):
		var tri: Array = [gabled["verts"][t], gabled["verts"][t + 1], gabled["verts"][t + 2]]
		if tri.all(func(v): return is_equal_approx(v.x, tri[0].x)) and (is_equal_approx(tri[0].x, 0.0) or is_equal_approx(tri[0].x, 20.0)) and tri.any(func(v): return v.y > 10.0):
			capped += 1
	check(peaks >= 2 and capped >= 2, "both gable ends are closed up to the ridge (%d peaks, %d triangles)" % [peaks, capped])
	# godot-23: canopies project as the 3D camera does.
	B3.view_centre = Vector2(30.0, -20.0)
	B3.view_height = d
	var lifted := B3.lift_point(Vector2(55.0, -20.0), 6.0)
	check(lifted.is_equal_approx(B3.project(Vector3(55.0, 6.0, -20.0), B3.view_centre, d)) and lifted.x > 55.0, "a canopy corner 6 m up moves out from the view centre exactly as the 3D camera shows it")
	check(B3.lift_point(Vector2(55.0, -20.0), 0.0).is_equal_approx(Vector2(55.0, -20.0)), "at ground level nothing moves")
	B3.view_height = 0.0
	MapChunk.buildings_3d = true
	var map := MapLayer.new()
	root.add_child(map)
	map.add_chunk({"chunk_id": "3d", "bounds": [0, 0, 100, 100], "buildings": [[[0, 0], [20, 0], [20, 10], [0, 10]]],
		"building_styles": [style]})
	check(map.buildings_3d != null and map.buildings_3d.instance_count() >= 1, "a chunk's mesh (and its lit windows) join the 3D layer")
	var lit_instances: Array = map.buildings_3d._view.get_children().filter(func(n): return n is MeshInstance3D and n.material_override == B3._shared["lit"])
	check(map.buildings_3d._view.get_children().filter(func(n): return n is MeshInstance3D).all(func(n): return n.layers == B3.LAYER_BUILDINGS), "every instance is in the one building view (godot-final-09)")
	check(map.buildings_3d.get_children().filter(func(n): return n is SubViewport).size() == 1 and map.buildings_3d.get_children().filter(func(n): return n is Sprite2D).size() == 1, "one viewport, one composite: no lit-window pass")
	map.buildings_3d.set_light(0.0, Color.WHITE)
	check(lit_instances.all(func(n): return not n.visible) and B3._shared["material"].albedo_color == Color.WHITE, "by day: the buildings as they are, the lit windows not drawn at all")
	var dusk := Color(0.6, 0.65, 0.8)
	map.buildings_3d.set_light(0.5, dusk)
	check(B3._shared["material"].albedo_color == dusk and lit_instances.all(func(n): return n.visible), "the buildings take the ambient light in their own material")
	check(B3._shared["lit"].albedo_color.is_equal_approx(B3.lit_color(0.0, dusk).lerp(Color.WHITE, 0.5)), "the windows half way to their own light")
	map.buildings_3d.set_light(1.0, Color(0.15, 0.2, 0.34))
	check(B3._shared["lit"].albedo_color.is_equal_approx(Color.WHITE) and lit_instances.size() <= 1, "fully lit at night, whatever the ambient; one lit mesh per chunk")
	var window := B3.lit_color(0.0, Color.WHITE) * B3.WINDOW_LIT_NIGHT
	check(window.is_equal_approx(Color(B25.WINDOW.r, B25.WINDOW.g, B25.WINDOW.b) * Color.WHITE) or absf(window.r - B25.WINDOW.r) < 0.01, "at level 0 a lit window looks like an ordinary one (no pop)")
	check((map.buildings_3d._sprite.material as CanvasItemMaterial).light_mode == CanvasItemMaterial.LIGHT_MODE_UNSHADED, "the composite isn't darkened twice")
	map.buildings_3d.set_light(0.0, Color.WHITE)
	map.clear()
	check(map.buildings_3d.instance_count() == 0, "a chunk's meshes go with it")
	map.free()
	MapChunk.buildings_3d = false


func _on_outline(p: Vector2, polygon: PackedVector2Array) -> bool:
	for i in polygon.size():
		if Geometry2D.get_closest_point_to_segment(p, polygon[i], polygon[(i + 1) % polygon.size()]).distance_to(p) < 1e-3:
			return true
	return false


func test_performance_paths() -> void:
	# godot-final-09: street-light pools are direct fans in one triangle list (no boolean union, no worker).
	var positions := PackedVector2Array([Vector2(0, 0), Vector2(12, 0), Vector2(24, 0)])
	var lights := [[0, 0, 0.0, 14.0], [12, 0, 0.0, 14.0], [24, 0, 0.0, 14.0]]
	var fans: Array = MapChunk.pool_fans(positions, lights, PackedInt32Array())
	check(fans[0].size() == 3 * (2 * MapChunk.POOL_STEPS + 1) and fans[1].size() == 3 * MapChunk.POOL_STEPS * 9, "three lamps: three whole pools, overlapping as they are")
	var far_point := 0.0
	for k in range(MapChunk.POOL_STEPS + 1, 2 * MapChunk.POOL_STEPS + 1):
		far_point = maxf(far_point, fans[0][k].length())
	check(far_point <= 14.0 and far_point > 10.0, "each within its lamp's reach")
	var broken: Array = MapChunk.pool_fans(positions, lights, PackedInt32Array([1]))
	check(broken[0].size() == 2 * (2 * MapChunk.POOL_STEPS + 1) and not broken[0].has(Vector2(12, 0)), "a broken lamp leaves a dark gap")
	var chunk_source: String = (MapChunk as Script).source_code
	check(not chunk_source.contains("pool_union") and not chunk_source.contains("_pool_task"), "no boolean pool pieces, no dusk worker")
	check(MapChunk.POOL_CORE.r > MapChunk.POOL_CORE.g and MapChunk.POOL_CORE.g > MapChunk.POOL_CORE.b and MapChunk.POOL_CORE.r * 2.5 < 1.0, "warm amber at the lamp, fading out; two or three overlapping stay amber, not white")
	check(fans[2].size() == 3 and fans[2][1] == 2 * MapChunk.POOL_STEPS + 1, "the lamp points (bright) per pool")

	# Roads, rails and water clipped to the chunk: only its own share.
	var map := MapLayer.new()
	root.add_child(map)
	map.add_chunk(JSON.parse_string(JSON.stringify({"chunk_id": "0_0", "bounds": [0, 0, 500, 500],
		"roads": [{"points": [[100, 100], [900, 100]], "half_width_m": 4.0, "drivable": true, "layer": 0}],
		"railways": [[[100, 200], [100, 900]]], "waters": [[[400, 400], [700, 400], [700, 700], [400, 700]]]})))
	var chunk = map._chunks["0_0"]
	var road: PackedVector2Array = chunk._data["roads"][0]["points"]
	check(road.size() == 2 and is_equal_approx(road[1].x, 500.0) and chunk._roads_by_z[1].size() == 1, "a road leaving the chunk is cut at its border")
	check(is_equal_approx(chunk._data["railways"][0][1].y, -500.0), "rails too")
	check(is_equal_approx(_area(chunk._data["waters"]), 100.0 * 100.0), "water: only the part inside")

	# Dry: no wet overlays drawn; no lightning: no full-screen flash.
	chunk.set_wetness(0.0)
	check(not chunk._wet_darken.visible and not chunk._wet_sheen.visible, "dry roads: the wet overlays are not drawn at all")
	chunk.set_wetness(0.6)
	check(chunk._wet_darken.visible and chunk._wet_sheen.visible, "wet: they are")
	map.free()

	# Buildings built on a worker: nothing drawn until ready, then exactly what in-place building gives.
	MapChunk.build_async = true
	var style := [[92, 57, 48], 0, 10.0, [], [158, 105, 82], 3, 0]
	var message: Dictionary = JSON.parse_string(JSON.stringify({"chunk_id": "0_0", "bounds": [0, 0, 500, 500],
		"buildings": [[[10, 10], [30, 10], [30, 30], [10, 30]]], "building_styles": [style]}))
	var async_chunk = MapChunk.new()
	async_chunk.setup(message, Vector2.ZERO)
	check(async_chunk.building_node != null and async_chunk._building_task >= 0, "the build runs on a worker")
	while not WorkerThreadPool.is_task_completed(async_chunk._building_task):
		OS.delay_msec(1)
	var built: Dictionary = MapChunk._build_timed([async_chunk._data["buildings"][0]], [style], Vector2.ZERO)
	async_chunk._buildings_ready(built)
	MapChunk.build_async = false
	var sync_chunk = MapChunk.new()
	sync_chunk.setup(message.duplicate(true), Vector2.ZERO)
	check(async_chunk._volumes["points"] == sync_chunk._volumes["points"] and async_chunk._volumes["stats"] == sync_chunk._volumes["stats"],
		"the worker builds the same buildings as in place")
	async_chunk.free()
	sync_chunk.free()

	# Chunk messages parsed off the main thread: one unloaded meanwhile is dropped.
	var sim := SimClient.new()
	root.add_child(sim)
	var got: Array = []
	sim.chunk_received.connect(func(m): got.append(m["chunk_id"]))
	sim._parse_chunk('{"type":"chunk","version":1,"chunk_id":"3_4","bounds":[0,0,1,1]}')
	sim._parse_chunk('{"type":"chunk","version":1,"chunk_id":"5_6","bounds":[0,0,1,1]}')
	check(sim._parsing.has("3_4") and sim._parsing.has("5_6"), "the chunk id is read without parsing the line")
	sim._cancelled["5_6"] = true  # its chunk_unload came first
	for id in sim._parsing.keys():
		while not WorkerThreadPool.is_task_completed(sim._parsing[id]):
			OS.delay_msec(1)
	sim._chunk_parsed("3_4", JSON.parse_string('{"type":"chunk","version":1,"chunk_id":"3_4"}'), 10)
	sim._chunk_parsed("5_6", JSON.parse_string('{"type":"chunk","version":1,"chunk_id":"5_6"}'), 10)
	check(got == ["3_4"], "parsed chunks arrive; one unloaded while parsing doesn't (%s)" % [got])
	sim.free()

	# The frame report: percentiles, lows and long frames from the recorded frame times.
	var times := PackedFloat32Array()
	for i in 99:
		times.append(10.0)
	times.append(100.0)
	var report := Perf.summary(times)
	check(is_equal_approx(report["worst_ms"], 100.0) and is_equal_approx(report["p95_ms"], 10.0) and report["over_66ms"] == 1, "worst, p95 and frames over 66 ms")
	check(is_equal_approx(report["low_1pct_fps"], 10.0) and is_equal_approx(report["avg_ms"], 10.9), "1 % low is the slowest 1 % of frames, as FPS")
