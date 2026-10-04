## Client unit tests, no server needed:
##   godot --headless --path godot --script res://tests/run_tests.gd
## Exits 1 if any check fails.
extends SceneTree

const Hud := preload("res://hud.gd")
const MapLayer := preload("res://map_layer.gd")

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
	test_interpolation()
	test_audio()
	test_hud()
	test_map_chunks()
	test_commands_carry_the_player_id()
	test_phone()
	test_rendering()
	test_drive_input()
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
