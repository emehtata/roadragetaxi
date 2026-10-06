## The Godot client: connects to the Python simulation (authoritative),
## draws what it sends, follows the player with the camera, plays the
## simulation's events as sound, shows the HUD and sends the player's input
## as commands. No game rules here.
##
## Command line (after `--`): --host H --port P, --interp-delay-ms N (see
## state_buffer.gd), --selftest to drive the taxi for a few seconds and
## print a JSON report (CI / dev check), --audiotest for a scripted run to
## record the sound output (audio_test.gd), --screenshot PATH.
extends Node2D

const COMMAND_INTERVAL_S := 0.05  # input -> simulation at 20 Hz, independent of the frame rate

const NightLayer := preload("res://night_layer.gd")
const Perf := preload("res://perf.gd")
const MapChunk := preload("res://map_chunk.gd")
@onready var sim: SimClient = $SimClient
@onready var map_layer: Node2D = $MapLayer
@onready var entities: Node2D = $EntityLayer
@onready var camera: Camera2D = $Camera
@onready var audio: AudioManager = $Audio
@onready var hud: Control = $Ui/Hud
@onready var debug_label: Label = $Ui/Debug
@onready var phone: Phone = $Ui/Phone
@onready var instruments: Control = $Ui/Instruments
@onready var nav_overlay: Control = $Ui/NavOverlay
@onready var night: Node2D = $NightLayer
@onready var labels: Control = $Ui/Labels
@onready var flash: ColorRect = $Sky/Flash

var _tick := 0
var _states_received := 0
var _recent_events: Array = []
var _command_timer := 0.0
var _interact_pending := false
var _refuel_pending := false  # G: one press, sent once (the server buys once per press)
var _engine_on := true
var drive := DriveInput.new()  # the held driving keys (drive_input.gd)
var _state_usec := 0.0  # handling one state (parse + buffer), smoothed
var _interp_usec := 0.0  # sampling + blending one frame, smoothed

var _selftest := false
var _selftest_time := 0.0
var _selftest_start := Vector2.INF
var _last_interact := -10.0
var _screenshot_path := ""
var _screenshot_wait := 6.0
var _screenshot_drive := 0.0
var _report := {}
var _fps_samples: Array = []
var _max_camera_lag_px := 0.0
var _motion: Array = []  # selftest, while driving: [raw dt, godot delta, render dt, camera step m]
var _last_raw := 0.0
var _last_render := 0.0
var _last_camera := Vector2.ZERO
var _phone_check := {}  # selftest: what the phone saw and how an accept went
var _phone_wait := 0.0  # --phone-wait S: after driving, wait up to S s for a real offer and accept it
var events_presented := 0
var _audiotest := false
var _chunk_queue: Array = []  # chunk messages waiting for their frame
var _last_frame_usec := 0  # frame-time accounting (godot-18): real time between frames, not the smoothed delta
var _bench := 0.0  # --bench SECONDS: drive-through measurement, then the report as JSON
var _bench_left := 0.0
var _bench_hide: PackedStringArray = []
var _visible_roads := -1  # drivable roads in view (night tint), recounted every 0.1 s as Pygame does
var _visible_roads_elapsed := 0.0
var override_night := -1.0  # >= 0: presentation override for the audio test (never sent to Python)
var override_rain := -1.0
var override_train_at := Vector2.INF
var override_wetness := -1.0  # audio test: a moving train here (presentation only)


func _ready() -> void:
	entities.lamp_near = map_layer.lamp_near  # reflectors and long beams look up working street lights
	entities.covered = map_layer.covered  # headlights under a higher road
	labels.map_layer = map_layer
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		match args[i]:
			"--host":
				sim.host = args[i + 1]
			"--port":
				sim.port = int(args[i + 1])
			"--interp-delay-ms":
				entities.buffer.delay = float(args[i + 1]) / 1000.0
			"--selftest":
				_selftest = true
			"--phone-wait":
				_phone_wait = float(args[i + 1])
			"--audiotest":
				_audiotest = true
			"--inputtest":
				var tester: Node = preload("res://input_test.gd").new()
				tester.main = self
				add_child.call_deferred(tester)
			"--screenshot":
				_screenshot_path = args[i + 1]
			"--wetness":  # presentation override for visual checks (never sent to Python)
				override_wetness = float(args[i + 1])
			"--bench-hide":  # godot-18 profiling: hide layers ("z7,labels,...": chunk layers by z, or named groups)
				_bench_hide = args[i + 1].split(",")
			"--bench":  # godot-18: record SECONDS of frames once the simulation is here, print BENCH {json}, quit
				_bench = float(args[i + 1])
				_bench_left = _bench
				Perf.keep_all = true
			"--buildings":  # godot-21: "2d" the radial 2D renderer, "3d" (default) the 3D building layer
				MapChunk.buildings_3d = args[i + 1] != "2d"
			"--building-fov":  # godot-22: try a 3D building camera FOV (degrees)
				preload("res://buildings_3d.gd").FOV = float(args[i + 1])
			"--compass":
				$Ui/NavOverlay.show_compass = true
			"--screenshot-drive":  # with --screenshot: get in and drive this many seconds first
				_screenshot_drive = float(args[i + 1])
	sim.world_received.connect(_on_world)
	sim.state_received.connect(_on_state)
	# One new chunk per frame (godot-16): a chunk's first drawing takes ~10-20 ms, and crossing into
	# a new area brings a whole row of them at once.
	sim.chunk_received.connect(func(message: Dictionary): _chunk_queue.append(message))
	sim.chunk_unloaded.connect(_unload_chunk)
	sim.connection_changed.connect(_on_connection)
	phone.sound.connect(func(group: String, variation: int): audio.handle_event({"type": "sound", "group": group, "variation": variation}))
	phone.request.connect(func(action: String, item_id: String, request_id: int): sim.send_phone(action, item_id, request_id))
	if _audiotest:
		var tester: Node = preload("res://audio_test.gd").new()
		tester.main = self
		var at := args.find("--audiotest")
		if at + 1 < args.size() and not args[at + 1].begins_with("--"):
			tester.out_path = args[at + 1]
		add_child(tester)


func _on_connection(up: bool) -> void:
	print("simulation ", "connected" if up else "disconnected")
	phone.set_connected(up)
	if not up:  # a new connection starts over: header, chunks, states
		entities.buffer.clear()
		map_layer.clear()
		audio.stop_loops()


func _unload_chunk(chunk_id: String) -> void:
	_chunk_queue = _chunk_queue.filter(func(m): return m["chunk_id"] != chunk_id)  # gone before it was ever drawn
	map_layer.remove_chunk(chunk_id)


func _on_world(world: Dictionary) -> void:
	_chunk_queue.clear()  # a new world (reconnect): the old one's chunks are void
	var origin := Vector2(world["center"][0], world["center"][1])
	map_layer.set_origin(origin)
	entities.origin = origin
	audio.origin = origin
	sim.player_id = world.get("player_id", sim.player_id)


func _on_state(message: Dictionary) -> void:
	var started := Time.get_ticks_usec()
	_tick = message["tick"]
	_states_received += 1
	entities.buffer.push(message["tick"], message.get("server_time", message["tick"] / 30.0), message["state"], entities.now())
	_state_usec = lerpf(_state_usec, float(Time.get_ticks_usec() - started + sim.parse_usec), 0.1)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_F:
				_interact_pending = true
			KEY_G:
				_refuel_pending = true
			KEY_E:
				_engine_on = not _engine_on
			KEY_F3:
				debug_label.visible = not debug_label.visible
			KEY_EQUAL, KEY_KP_ADD:
				camera.zoom *= 1.25
			KEY_MINUS, KEY_KP_SUBTRACT:
				camera.zoom /= 1.25


## Driving keys: every press and release, before any UI can consume it.
func _input(event: InputEvent) -> void:
	drive.handle(event)


func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT or what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		# Key-ups of keys held now will never arrive: let go of everything,
		# and tell the simulation at once rather than at the next interval.
		drive.clear()
		_command_timer = 0.0


func _process(delta: float) -> void:
	var now_usec := Time.get_ticks_usec()
	if _last_frame_usec > 0 and not entities.shown_state().is_empty() and (_bench <= 0.0 or _bench - _bench_left > 5.0):
		Perf.frame((now_usec - _last_frame_usec) / 1000.0)  # --bench: after 5 s of warm-up (the first chunks)
	_last_frame_usec = now_usec
	if not _chunk_queue.is_empty():
		map_layer.add_chunk(_chunk_queue.pop_front())
		Perf.add("chunk_add", Time.get_ticks_usec() - now_usec)
	entities.update_frame(delta)  # first: the camera below and the drawing use this one sample
	var state: Dictionary = entities.shown_state()
	_interp_usec = lerpf(_interp_usec, float(entities.interp_usec), 0.1)
	if _selftest:
		_run_selftest(delta, state)
	var screenshot_driving := _screenshot_path != "" and _screenshot_drive > 0.0
	if screenshot_driving and not state.is_empty():
		if state.get("on_foot", true):
			if Engine.get_process_frames() % 90 == 0:
				send({"interact": true})
		else:
			_screenshot_drive -= delta
			send({"throttle": 1.0 if _screenshot_drive > 1.0 else 0.0, "brake": 0.0 if _screenshot_drive > 1.0 else 1.0,
				"steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
	elif _screenshot_path != "" and not state.is_empty():
		_screenshot_wait -= delta
		if _screenshot_wait <= 0.0:
			get_viewport().get_texture().get_image().save_png(_screenshot_path)
			print("screenshot saved: ", _screenshot_path)
			get_tree().quit()
	camera.position = entities.player_position()
	entities.px_per_m = camera.zoom.x
	if _selftest and _selftest_start != Vector2.INF and _selftest_time > 0.5:
		var raw: float = entities.now()
		var render: float = entities.buffer._clock_time
		_motion.append([raw - _last_raw, delta, render - _last_render, camera.position.distance_to(_last_camera)])
	_last_raw = entities.now()
	_last_render = entities.buffer._clock_time
	_last_camera = camera.position
	if _selftest and _selftest_start != Vector2.INF:
		# How far from the screen centre the taxi is drawn this frame (it is
		# drawn from the same sample the camera just used; godot-08).
		_max_camera_lag_px = maxf(_max_camera_lag_px, entities.player_position().distance_to(camera.position) * camera.zoom.x)
	var present_started := Time.get_ticks_usec()
	_present(state)
	Perf.add("present", Time.get_ticks_usec() - present_started)
	if not _bench_hide.is_empty():
		_apply_bench_hide()  # after _present, which sets some layers' visibility itself
	Perf.add("main_process", Time.get_ticks_usec() - now_usec)
	if _bench > 0.0:  # the renderer's own measurement of the previous frame (godot-18)
		var rid := get_viewport().get_viewport_rid()
		RenderingServer.viewport_set_measure_render_time(rid, true)
		Perf.add("render_cpu", int(RenderingServer.viewport_get_measured_render_time_cpu(rid) * 1000.0))
		Perf.add("render_gpu", int(RenderingServer.viewport_get_measured_render_time_gpu(rid) * 1000.0))
		Perf.add("frame_setup_cpu", int(RenderingServer.get_frame_setup_time_cpu() * 1000.0))
		if map_layer.buildings_3d != null:  # godot-22: the 3D building pass alone
			var view_3d: RID = map_layer.buildings_3d._view.get_viewport_rid()
			RenderingServer.viewport_set_measure_render_time(view_3d, true)
			Perf.add("render_3d_cpu", int(RenderingServer.viewport_get_measured_render_time_cpu(view_3d) * 1000.0))
			Perf.add("render_3d_gpu", int(RenderingServer.viewport_get_measured_render_time_gpu(view_3d) * 1000.0))
			var lit_3d: RID = map_layer.buildings_3d._lit_view.get_viewport_rid()  # godot-23: the night's lit-window pass
			RenderingServer.viewport_set_measure_render_time(lit_3d, true)
			Perf.add("render_3d_lit_cpu", int(RenderingServer.viewport_get_measured_render_time_cpu(lit_3d) * 1000.0))
	if _bench > 0.0 and not state.is_empty():
		_bench_left -= delta
		if _bench_left <= 0.0:
			_perf_counters()
			print("BENCH ", JSON.stringify(Perf.report()))
			get_tree().quit()
	_command_timer -= delta
	if _command_timer <= 0.0 and not _selftest and not _audiotest and not screenshot_driving:  # the tests drive instead
		_command_timer = COMMAND_INTERVAL_S
		send(drive.controls(state.get("on_foot", true)))


## Sound and HUD for the state on screen; events as the picture reaches them.
func _present(state: Dictionary) -> void:
	if state.is_empty():
		hud.visible = false
		debug_label.visible = true
		debug_label.text = "Waiting for the simulation at %s:%d ..." % [sim.host, sim.port]
		return
	if not hud.visible:  # the simulation is here: the HUD replaces the waiting text (F3 brings the readout back)
		hud.visible = true
		debug_label.visible = false
	var player: Dictionary = state["player_pedestrian"] if state.get("on_foot", false) else state["player"]
	audio.player_at = Vector2(player["x"], player["y"])
	for event in entities.buffer.take_due_events(entities.now()):
		events_presented += 1
		if event.get("type") == "phone_result":
			phone.handle_result(event)
			continue
		audio.handle_event(event)
		_recent_events.push_front(event.get("group", event.get("type", "?")))
	_recent_events.resize(min(_recent_events.size(), 6))
	var driving: bool = not state.get("on_foot", true) and state["player"].get("engine_on", false)
	var speed: float = absf(state["player"].get("speed", 0.0))
	audio.set_loop("engine", 0.6 if driving else 0.0, minf(1.0 + speed / 25.0, 2.2))
	var calendar = state.get("calendar")
	var darkness: float = calendar.get("darkness", 0.0) if typeof(calendar) == TYPE_DICTIONARY else -1.0
	var view := get_viewport().get_canvas_transform().affine_inverse() * get_viewport().get_visible_rect()
	_visible_roads_elapsed += get_process_delta_time()
	if darkness > 0.0 and _visible_roads_elapsed >= 0.1:
		_visible_roads_elapsed = 0.0
		_visible_roads = map_layer.count_drivable_roads(view)
	if typeof(calendar) == TYPE_DICTIONARY:
		map_layer.set_season(calendar.get("season", []))
	# Street lights, beams and reflectors at the server's darkness and sun (render/roads.py, vehicles.py, pedestrians.py).
	map_layer.set_lights_on(darkness > 0.25)
	map_layer.set_darkness(maxf(darkness, 0.0))  # lit windows (godot-17)
	entities.reflectors_on = typeof(calendar) == TYPE_DICTIONARY and calendar.get("sun_altitude_deg", 90.0) < -7.5
	var lit := [[], []]
	var night_started := Time.get_ticks_usec()
	if darkness > 0.25:
		var beams: Array = entities.headlight_beams()
		if not beams.is_empty():
			var box := Rect2(beams[0][0], Vector2.ZERO)
			for beam in beams:
				for point in beam:
					box = box.expand(point)
			lit = NightLayer.clip_beams(beams, map_layer.buildings_in(box.grow(8.0)))
	night.show_night(night_alpha(darkness, _visible_roads), view, lit[0], lit[1])
	Perf.add("night_beams", Time.get_ticks_usec() - night_started)
	var lightning: float = entities.lightning_now()
	if not is_equal_approx(flash.color.a, lightning):
		flash.color.a = lightning
	flash.visible = lightning > 0.0  # godot-18: an invisible full-screen rect is still blended every frame
	# The server's darkness; an older server without a calendar: the hour.
	var night := (darkness if darkness >= 0.0 else _night(state.get("game_time_seconds", 12.0 * 3600.0))) if override_night < 0.0 else override_night
	audio.set_loop("city_day", 0.5 * (1.0 - night))
	audio.set_loop("city_night", 0.5 * night)
	var raining: bool = state.get("weather", {}).get("weather_type", "") == "rain"
	audio.set_loop("rain", (0.6 if raining else 0.0) if override_rain < 0.0 else override_rain)
	_train_loop(state)
	hud.show_state(state)
	instruments.show_state(state)
	map_layer.set_wetness(state.get("weather", {}).get("wetness", 0.0) if override_wetness < 0.0 else override_wetness)
	map_layer.set_px_per_m(camera.zoom.x)  # after the camera is placed; only reads its zoom
	map_layer.set_building_view(camera.position)
	map_layer.set_traffic_lights(state.get("traffic_lights", {}))
	# godot-16: below ground (the server's map level), the flashing speed camera, the labels.
	var level := int(state.get("player", {}).get("map_level", 0))
	map_layer.set_map_level(level)
	entities.underground = level != 0
	map_layer.set_flash(state.get("speed_camera_flash"))
	labels.update_view(get_viewport().get_canvas_transform(), map_layer.chunk_count(), level != 0)
	map_layer.set_obstacles(state.get("fallen_trees", []), state.get("knocked_posts", []))
	phone.show_phone(state.get("phone", {}))
	var target: Dictionary = entities.current_target(state)
	var target_screen := Vector2.ZERO
	if not target.is_empty():
		target_screen = get_viewport().get_canvas_transform() * MapMath.point(entities.origin, target["x"], target["y"])
	var camera_world := Vector2(camera.position.x + entities.origin.x, entities.origin.y - camera.position.y)
	nav_overlay.update_view(target, target_screen, camera_world, state["player"].get("heading", 0.0))
	if debug_label.visible:
		_update_debug(state)


## render/hud.py draw_day_night_overlay: dark blue at 115 x darkness, up
## to 95 more where fewer than 12 drivable roads are in view (no street
## lighting out there). 0..1 alpha; darkness < 0 (no calendar) is none.
static func night_alpha(darkness: float, visible_roads: int) -> float:
	var alpha := int(115.0 * maxf(darkness, 0.0))
	if visible_roads >= 0 and alpha > 0:
		alpha += int(95.0 * clampf((12.0 - visible_roads) / 12.0, 0.0, 1.0))
	return alpha / 255.0


## The nearest moving train rumbles from where it is (Pygame mixes the
## loudest intercity and commuter train as two layers; one is enough here).
func _train_loop(state: Dictionary) -> void:
	if override_train_at != Vector2.INF:
		audio.set_loop("train_running", 0.8, 1.0, override_train_at)
		return
	var nearest = null
	var best := INF
	var speed := 0.0
	for train in state.get("trains", []):
		if train["state"] != "RUNNING" or train["speed"] < 2.0 or train["cars"].is_empty():
			continue
		var at := Vector2(train["cars"][0][0], train["cars"][0][1])
		if at.distance_to(audio.player_at) < best:
			best = at.distance_to(audio.player_at)
			nearest = at
			speed = train["speed"]
	audio.set_loop("train_running", minf(1.0, speed / 20.0) if nearest != null else 0.0, 1.0, nearest)


## 0 by day, 1 at night, fading over an hour at dusk (21-22) and dawn (5-6).
static func _night(game_time_seconds: float) -> float:
	var hour := fmod(game_time_seconds / 3600.0, 24.0)
	if hour >= 22.0 or hour < 5.0:
		return 1.0
	if hour >= 21.0:
		return hour - 21.0
	if hour < 6.0:
		return 6.0 - hour
	return 0.0


## One command to the simulation (it validates and applies it). The
## presses (F, G) go out once, in the next command only.
func send(controls: Dictionary) -> void:
	var command := command_for(controls, _engine_on, _interact_pending, _refuel_pending)
	_interact_pending = false
	_refuel_pending = false
	sim.send_command(command)


static func command_for(controls: Dictionary, engine_on: bool, interact: bool, refuel: bool) -> Dictionary:
	var command := {"speed_limiter_enabled": true, "red_light_assist_enabled": false, "refuel": refuel,
		"engine_on": engine_on, "interact": interact}
	command.merge(controls, true)
	return command


func _apply_bench_hide() -> void:
	for name in _bench_hide:
		match name:
			"labels": labels.visible = false
			"buildings": map_layer._buildings.visible = false
			"composite3d": if map_layer.buildings_3d:  # the 3D pass still renders (a hidden texture's viewport would skip it)
				map_layer.buildings_3d._sprite.visible = false
				map_layer.buildings_3d._view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
			"meshes3d": if map_layer.buildings_3d:  # the 3D pass with nothing to draw: its fixed cost
				for node in map_layer.buildings_3d._view.get_children():
					if node is MeshInstance3D:
						node.visible = false
			"buildings3d": if map_layer.buildings_3d:
				map_layer.buildings_3d._sprite.visible = false
				map_layer.buildings_3d._view.render_target_update_mode = SubViewport.UPDATE_DISABLED
			"night": night.visible = false
			"pools": map_layer._pool_group.visible = false
			"entities": entities.visible = false
			"ground": map_layer._ground.visible = false
			_:
				if name.begins_with("z"):
					for chunk in map_layer._chunks.values():
						for child in chunk.get_children():
							if child is CanvasItem and child.z_index == int(name.substr(1)):
								child.visible = false
				elif name == "chunkself":
					for chunk in map_layer._chunks.values():
						chunk.self_modulate.a = 0.0


## The performance counters (F3, --bench): what is loaded and drawn.
func _perf_counters() -> void:
	var totals := {"buildings": 0, "walls": 0, "windows": 0, "lit": 0}
	for chunk in map_layer._chunks.values():
		for key in totals:
			totals[key] += chunk._volumes.get("stats", {}).get(key, 0)
	Perf.counters.merge(totals, true)
	Perf.counters["chunks"] = map_layer.chunk_count()
	Perf.counters["chunks_queued"] = _chunk_queue.size()
	Perf.counters["draw_calls"] = Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)
	Perf.counters["static_memory_mib"] = Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0


func _update_debug(state: Dictionary) -> void:
	_perf_counters()
	var f := Perf.summary()
	debug_label.text = "\n".join([
		"Road Rage Trip - Godot client 0.16.0g-alpha   player %s" % sim.player_id,
		"tick %d   %d fps   states %d   buffered %d   delay %d ms   underruns %d" % [_tick, Engine.get_frames_per_second(),
			_states_received, entities.buffer.size(), entities.buffer.delay * 1000, entities.buffer.underruns],
		"state %.2f ms   interpolate+draw %.2f ms   map chunks %d   drawn %d" % [_state_usec / 1000.0, _interp_usec / 1000.0,
			map_layer.chunk_count(), entities.drawn_entities],
		"npcs %d   pedestrians %d   trains %d" % [state["npcs"].size(), state["pedestrians"].size(), state["trains"].size()],
		"sounds played %d   no sound for %s" % [audio.played, ", ".join(audio.unhandled.keys())],
		"events: %s" % ", ".join(_recent_events),
		hud.values(state)["road"],
		"frames: avg %.1f ms  p99 %.1f ms  worst %.1f ms  1%% low %.0f fps   chunks %d (+%d queued)   draw calls %d" % [f.get("avg_ms", 0.0),
			f.get("p99_ms", 0.0), f.get("worst_ms", 0.0), f.get("low_1pct_fps", 0.0), Perf.counters["chunks"], Perf.counters["chunks_queued"], Perf.counters["draw_calls"]],
		"buildings %d  walls %d  windows %d  lit %d" % [Perf.counters["buildings"], Perf.counters["walls"], Perf.counters["windows"], Perf.counters["lit"]],
	])


## Headless check: get in, drive for 6 s, report what arrived and quit.
func _run_selftest(delta: float, state: Dictionary) -> void:
	_selftest_time += delta
	if state.is_empty():
		if _selftest_time > 20.0:
			_finish({"ok": false, "error": "no state from the simulation"})
		return
	if state["on_foot"]:
		if _selftest_time > 12.0:
			_finish({"ok": false, "error": "could not get into the taxi"})
		elif _selftest_time - _last_interact > 2.0:  # one F, then wait for the simulation's answer
			_last_interact = _selftest_time
			send({"interact": true})
		return
	var at := Vector2(state["player"]["x"], state["player"]["y"])
	if _selftest_start == Vector2.INF:
		_selftest_start = at
		_selftest_time = 0.0
		entities.buffer.reset_diagnostics()  # count from here: steady state, not the connect burst
		_max_camera_lag_px = 0.0
	var waiting_for_offer := _selftest_time > 6.0 and phone.items.is_empty() and _selftest_time < 6.0 + _phone_wait
	send({"throttle": 0.0 if _selftest_time > 6.0 else 1.0, "brake": 1.0 if _selftest_time > 6.0 else 0.0,
		"steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
	_fps_samples.append(1.0 / maxf(delta, 0.0001))
	# The taxi is drawn at the layer's sample of this frame; the camera should be on it.
	if not phone.is_open:
		phone.open()  # the selftest drives with the phone open: it must not get in the way
	_phone_check["most_rows"] = maxi(_phone_check.get("most_rows", 0), phone.items.size())
	if waiting_for_offer:
		return
	if _selftest_time > 6.0 and not phone.items.is_empty() and not _phone_check.has("asked"):
		_phone_check["asked"] = phone.selected_id
		_phone_check["sent"] = phone.accept_selected()
		phone.handle_result_hook = func(result): _phone_check["result"] = result
	# An accepted ride offer starts the fare (the phone turns busy); an accepted
	# rail booking only changes that row's status.
	var fare_started: bool = phone.busy or str(_phone_check.get("asked", "")).begins_with("booking-")
	var answered: bool = _phone_check.has("result") and (fare_started or not _phone_check["result"].get("ok", false))
	if _selftest_time > 6.0 and _phone_check.has("asked") and not answered and _selftest_time < 9.0 + _phone_wait:
		return  # wait for the simulation's answer
	if _selftest_time > 6.0:
		var hud_text: Dictionary = hud.values(state)
		var phone_ok: bool = _phone_wait <= 0.0 or (_phone_check.get("result", {}).get("ok", false) and phone.pending.is_empty()
			and (phone.busy or str(_phone_check.get("asked", "")).begins_with("booking-")))
		_report.merge({"ok": at.distance_to(_selftest_start) > 5.0 and map_layer.chunk_count() > 0 and phone_ok,
			"driven_m": at.distance_to(_selftest_start), "states": _states_received,
			"trains": state["trains"].size(), "npcs": state["npcs"].size(), "pedestrians": state["pedestrians"].size(),
			"drawn_entities": entities.drawn_entities, "map_chunks": map_layer.chunk_count(),
			"on_foot": state["on_foot"], "speed_mps": state["player"]["speed"], "hud_speed": hud_text["speed"],
			"hud_money": hud_text["money"], "camera_follows": camera.position.distance_to(entities.player_position()) < 1.0,
			"state_ms": _state_usec / 1000.0, "interp_draw_ms": _interp_usec / 1000.0,
			"buffered_states": entities.buffer.size(), "underruns_6s": entities.buffer.underruns,
			"underrun_episodes": entities.buffer.underrun_episodes, "longest_underrun_ms": entities.buffer.longest_underrun_s * 1000.0,
			"max_state_gap_ms": entities.buffer.max_arrival_gap_s * 1000.0,
			"render_backsteps": entities.buffer.render_backsteps, "max_backstep_ms": entities.buffer.max_backstep_s * 1000.0,
			"taxi_off_centre_px": _max_camera_lag_px, "motion": _motion_stats(), "interp_delay_ms": entities.buffer.delay * 1000.0,
			"fps_mean": _fps_samples.reduce(func(a, b): return a + b, 0.0) / _fps_samples.size(),
			"sounds_played": audio.played, "engine_loop": audio.loop_playing("engine"), "unhandled_events": audio.unhandled,
			"static_memory_mib": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
			"player_id": sim.player_id, "phone": _phone_check, "phone_busy_after": phone.busy, "phone_pending_after": phone.pending.size()})
		_finish(_report)


## Frame-to-frame smoothness while driving: how uneven the frame times
## are (raw clock vs Godot's smoothed delta), the render clock's rate, and
## the camera's step per frame against each time base (cv = stddev/mean).
func _motion_stats() -> Dictionary:
	var cv := func(values: Array) -> float:
		var mean: float = values.reduce(func(a, b): return a + b, 0.0) / maxf(1.0, values.size())
		var variance: float = values.reduce(func(a, b): return a + (b - mean) * (b - mean), 0.0) / maxf(1.0, values.size())
		return sqrt(variance) / mean if mean > 0.0 else 0.0
	var raw: Array = _motion.map(func(m): return m[0])
	var smooth: Array = _motion.map(func(m): return m[1])
	var rate: Array = _motion.map(func(m): return m[2] / maxf(m[0], 0.0001))
	var steps: Array = _motion.map(func(m): return m[3])
	# Shake: how much the camera's step changes from one frame to the next,
	# in screen pixels (smooth driving: a fraction of a pixel; the float32
	# position quantisation fixed in godot-09 made it ~4.5 px).
	var changes: Array = []
	for i in range(1, _motion.size()):
		changes.append(absf(_motion[i][3] - _motion[i - 1][3]) * camera.zoom.x)
	changes.sort()
	return {"frames": _motion.size(),
		"step_change_px_p95": changes[int(changes.size() * 0.95)] if not changes.is_empty() else 0.0,
		"step_change_px_max": changes.max() if not changes.is_empty() else 0.0, "cv_raw_dt": cv.call(raw), "cv_delta": cv.call(smooth), "cv_camera_step": cv.call(steps),
		"cv_step_per_delta": cv.call(_motion.map(func(m): return m[3] / maxf(m[1], 0.0001))),
		"clock_rate_min": rate.min() if not rate.is_empty() else 0.0, "clock_rate_max": rate.max() if not rate.is_empty() else 0.0}


func _finish(report: Dictionary) -> void:
	print("SELFTEST ", JSON.stringify(report))
	get_tree().quit(0 if report.get("ok", false) else 1)
