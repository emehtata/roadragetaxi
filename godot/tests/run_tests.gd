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
	check(first.size() > 5 and first.size() < 40 and str(first) == str(again), "puddle spots are deterministic (%d of 40 roads)" % first.size())
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
	check(gauge._shown != shown and gauge._shown[-1] == "", "driving away: the price goes")
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
	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
	var sim: Node = main.get_node("SimClient")
	main._unhandled_input(_key_event(KEY_V))
	main.send({})
	check(sim._last_command["speed_limiter_enabled"] == false, "V turns the limiter off in the commands")
	main._unhandled_input(_key_event(KEY_B))
	main._unhandled_input(_key_event(KEY_F))
	main._unhandled_input(_key_event(KEY_G))
	main.send({"throttle": 1.0})
	var pressed: Dictionary = sim._last_command
	check(pressed["red_light_assist_enabled"] == true and pressed["speed_limiter_enabled"] == false, "B turns the assist on; the limiter stays off")
	check(pressed["interact"] == true and pressed["refuel"] == true, "F and G still ride on the next command")
	main.send({"throttle": 0.0})
	var later: Dictionary = sim._last_command
	check(later["speed_limiter_enabled"] == false and later["red_light_assist_enabled"] == true, "later commands keep both toggles")
	check(later["interact"] == false and later["refuel"] == false, "F and G are sent once")
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
	# The tint: render/hud.py draw_day_night_overlay's alpha.
	check(Main.night_alpha(0.0, 40) == 0.0, "day: no tint")
	check(Main.night_alpha(1.0, 40) == 115.0 / 255.0, "night in town: 115")
	check(Main.night_alpha(0.5, 40) == 57.0 / 255.0, "dusk: half, truncated as Pygame's int()")
	check(Main.night_alpha(1.0, 0) == 210.0 / 255.0 and Main.night_alpha(1.0, 6) == (115.0 + 47.0) / 255.0, "night in empty country: up to 95 darker")
	check(Main.night_alpha(0.0, 0) == 0.0, "an empty view in daylight stays light")
	check(Main.night_alpha(-1.0, 0) == 0.0, "an older server without a calendar: no tint")

	# The HUD clock: the server's date, and * while game time runs 1:1.
	var state := {"game_time_seconds": 18.0 * 3600.0 + 20.0 * 60.0, "calendar": {"date": "2026-10-05", "time_scale": 60.0, "darkness": 0.2}}
	check(Hud.values(state)["clock"] == "2026-10-05 18:20", "date and time (%s)" % Hud.values(state)["clock"])
	state["calendar"]["time_scale"] = 1.0
	check(Hud.values(state)["clock"] == "2026-10-05 18:20 *", "real-time marker during a fare")
	check(Hud.values({"game_time_seconds": 3600.0})["clock"] == "01:00", "no calendar: the time alone")

	# Roads in view, each once though two chunks carry it.
	var map := MapLayer.new()
	root.add_child(map)
	var road := {"points": [[490.0, 10.0], [510.0, 10.0]], "half_width_m": 3.0, "drivable": true}
	var path := {"points": [[100.0, 100.0], [110.0, 100.0]], "half_width_m": 1.0, "drivable": false}
	map.add_chunk(JSON.parse_string(JSON.stringify({"chunk_id": "0_0", "bounds": [0, 0, 500, 500], "roads": [road, path]})))
	map.add_chunk(JSON.parse_string(JSON.stringify({"chunk_id": "1_0", "bounds": [500, 0, 1000, 500], "roads": [road]})))
	check(map.count_drivable_roads(Rect2(400, -100, 200, 200)) == 1, "a road in two chunks counts once; a path not at all")
	check(map.count_drivable_roads(Rect2(2000, 2000, 100, 100)) == 0, "nothing in view")
	map.free()

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
	map.set_lights_on(true)
	check(map._pool_group.visible and chunk._heads.visible, "at night they are on")
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
	var car := [Vector2.ZERO, 0.0, 1.8, true]
	check(EntityLayer2.oncoming(car, [car, [Vector2(30, 0), PI, 1.8, true]]), "a car 30 m ahead coming the other way dips the beams")
	check(not EntityLayer2.oncoming(car, [car, [Vector2(30, 0), 0.0, 1.8, true]]), "one going the same way doesn't")

	# Beams minus buildings: clipped where they meet one; one wholly inside is tinted again.
	var beam := PackedVector2Array([Vector2(0, -5), Vector2(20, -5), Vector2(20, 5), Vector2(0, 5)])
	var inside := PackedVector2Array([Vector2(8, -1), Vector2(10, -1), Vector2(10, 1), Vector2(8, 1)])
	var across := PackedVector2Array([Vector2(15, -10), Vector2(30, -10), Vector2(30, 10), Vector2(15, 10)])
	var clipped := NightLayer.clip_beams([beam], [[Rect2(8, -1, 2, 2), inside], [Rect2(15, -10, 15, 20), across], [Rect2(100, 100, 1, 1), inside]])
	check(clipped[1] == [inside], "a building inside the beam is tinted again")
	var right_edge := -INF
	for piece in clipped[0]:
		for point in piece:
			right_edge = maxf(right_edge, point.x)
	check(is_equal_approx(right_edge, 15.0), "the beam stops at the building it meets")

	# Reflectors: not in the taxi's cone.
	check(EntityLayer2.reflector_lit(Vector2(10, 0), Vector2.ZERO, 0.0), "ahead in the beam: lit, no reflector needed")
	check(not EntityLayer2.reflector_lit(Vector2(-5, 0), Vector2.ZERO, 0.0) and not EntityLayer2.reflector_lit(Vector2(10, -8), Vector2.ZERO, 0.0), "behind or aside: the reflector shows")

	# The night layer redraws only on a change.
	var night = NightLayer.new()
	root.add_child(night)
	night.show_night(0.4, Rect2(0, 0, 10, 10), [], [])
	check(night.visible and night.alpha == 0.4, "night shown")
	night.show_night(0.0, Rect2(0, 0, 10, 10), [], [])
	check(not night.visible, "day: the layer is off")
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
		"roads": [{"points": [[0, 10], [200, 10]], "half_width_m": 4.0, "kind": "primary", "drivable": true, "layer": 0, "color": [80, 80, 80], "center": [110, 110, 110, 1]},
			{"points": [[50, 0], [50, 100]], "half_width_m": 5.0, "kind": "primary", "drivable": true, "layer": 1, "color": [80, 80, 80], "bridge": true}],
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
	map.set_lights_on(true)
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
	check(map._chunks["0_0"].building_shapes()[0][1].size() >= 4, "headlights clip against the whole projected volume")
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
	check(B3.build([box], [[[92, 57, 48], 1, 10.0, [], [158, 105, 82], 3, 0]], Vector2.ZERO)["tops"] == [ridge], "a pitched roof's top is its ridge (headlight silhouette)")
	# godot-23: canopies and headlight silhouettes project as the 3D camera does.
	B3.view_centre = Vector2(30.0, -20.0)
	B3.view_height = d
	var lifted := B3.lift_point(Vector2(55.0, -20.0), 6.0)
	check(lifted.is_equal_approx(B3.project(Vector3(55.0, 6.0, -20.0), B3.view_centre, d)) and lifted.x > 55.0, "a canopy corner 6 m up moves out from the view centre exactly as the 3D camera shows it")
	check(B3.lift_point(Vector2(55.0, -20.0), 0.0).is_equal_approx(Vector2(55.0, -20.0)), "at ground level nothing moves")
	var shape: Array = B3.silhouette(Geometry2D.convex_hull(box), 10.0)
	var far_corner := B3.lift_point(Vector2(0.0, 10.0), 10.0)
	check(shape[0].grow(1e-3).has_point(far_corner) and shape[0].grow(1e-3).has_point(Vector2(0.0, 10.0)), "the headlight silhouette covers the footprint and the projected roof")
	B3.view_height = 0.0
	MapChunk.buildings_3d = true
	var map := MapLayer.new()
	root.add_child(map)
	map.add_chunk({"chunk_id": "3d", "bounds": [0, 0, 100, 100], "buildings": [[[0, 0], [20, 0], [20, 10], [0, 10]]],
		"building_styles": [style]})
	check(map.buildings_3d != null and map.buildings_3d.instance_count() >= 2, "a chunk's mesh and its occluder (and lit windows) join the 3D layer")
	check(map.buildings_in(Rect2(-5, -15, 30, 20)).size() == 1, "headlights still clip at the footprint")
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
	# The night tint as polygons: the view minus the beams, no holes, nothing lost.
	var view := Rect2(0, 0, 100, 60)
	var beam := PackedVector2Array([Vector2(40, 20), Vector2(60, 20), Vector2(60, 40), Vector2(40, 40)])  # wholly inside
	var pieces := NightLayer.tint_pieces(view, [beam])
	check(not NightLayer.has_hole(pieces) and is_equal_approx(_area(pieces), 100.0 * 60.0 - 400.0), "tint = view minus a beam inside it, cut without holes")
	var edge_beam := PackedVector2Array([Vector2(90, 0), Vector2(120, 0), Vector2(120, 10), Vector2(90, 10)])
	check(is_equal_approx(_area(NightLayer.tint_pieces(view, [beam, edge_beam])), 6000.0 - 400.0 - 100.0), "two beams, one over the edge")
	var reversed := beam.duplicate()
	reversed.reverse()
	check(is_equal_approx(_area(NightLayer.tint_pieces(view, [reversed])), 5600.0), "either winding (the hole test is about mixed orientations)")

	# Light pools cut into disjoint pieces: their total is the union, so +22 is added once.
	var positions := PackedVector2Array([Vector2(0, 0), Vector2(12, 0), Vector2(24, 0)])
	var lights := [[0, 0, 0.0, 14.0], [12, 0, 0.0, 14.0], [24, 0, 0.0, 14.0]]
	var parts := MapChunk.pool_union(positions, lights, PackedInt32Array())
	var fans := MapChunk.pool_union(PackedVector2Array([positions[0]]), [lights[0]], PackedInt32Array())
	check(parts.size() >= 3 and _area(parts) < 3.0 * _area(fans) - 1.0, "overlapping pools: pieces cover the union, not the sum")
	var cross := 0.0
	for i in parts.size():
		for j in range(i + 1, parts.size()):
			cross += _area(Geometry2D.intersect_polygons(parts[i], parts[j]))
	check(cross < 0.01, "the pieces don't overlap (%.3f)" % cross)
	check(MapChunk.pool_union(positions, lights, PackedInt32Array([1])).size() < parts.size() + 1, "a broken lamp's pool is left out")

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
