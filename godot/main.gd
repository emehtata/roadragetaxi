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
const Hud := preload("res://hud.gd")
const WeatherLayer := preload("res://weather_layer.gd")
const T := preload("res://i18n.gd")
const NightclubAudio := preload("res://nightclub_audio.gd")
const CarAudio := preload("res://car_audio.gd")
const WildlifeLayer := preload("res://wildlife.gd")
@onready var sim: SimClient = $SimClient
@onready var map_layer: Node2D = $MapLayer
@onready var entities: Node2D = $EntityLayer
@onready var camera: Camera2D = $Camera
@onready var audio: AudioManager = $Audio
var nightclubs := NightclubAudio.new()  # rrt-019: the music leaking out of the venues nearby
var car_stereos := CarAudio.new()  # rrt-019: NPC cars booming electro pop
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
var show_next_train := false  # J: the nearest station's board, local only
var _road_rage_pending := false  # SPACE: one press, sent once; the simulation decides if there's rage to spend
var speed_limiter := true  # V: a session toggle, reported in every command
var red_light_assist := false  # B: likewise
var lane_assist := false  # K: likewise
var _respawn_pending := false
var _home_pending := false  # H: choose this yard as home / back home
var _home_door_pending := false  # E on foot: into the home at its front door / out again
var home_walk := preload("res://home_walk.gd").new()  # inside the home (state home_door.indoors)
const SiteSounds := preload("res://site_sounds.gd")
var _sites := {}  # site_sounds.gd: the nearest playground, campfire, beer garden and building site
var _sites_left := 0.0  # seconds to the next sample
var door_marks := preload("res://door_marks.gd").new()  # nearby houses' front doors, on foot
var _home_plan_asked := false  # indoors without the plan: asked for once
var _cancel_ride_pending := false
var _reset_trip_pending := false
var _help: PanelContainer
var _inspect_panel: PanelContainer
var _inspect_label: Label
var _focus := {}  # {kind: pan|pedestrian|npc, id or position}; empty follows the player
var _pan_button := 0
var summary_shown := false  # the career city summary is up: the session is over, no more driving commands
var _engine_on := false  # the driver starts on foot, E starts the engine after getting in
var _entered_taxi := false  # the "Press F" hint until the driver first gets in
var hud_layout = preload("res://hud_layout.gd").new()  # the movable panels, saved (U / F2 resets)
var _start_sign: PanelContainer  # the start sign: city and forecast, any key starts
var drive := DriveInput.new()  # the held driving keys (drive_input.gd)
var _lead := Vector2.ZERO  # camera look-ahead, metres
const LEAD_S := 0.6  # look this far ahead of the taxi at its speed
const LEAD_MAX := 0.3  # at most this share of the view
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
var _chunk_queue: Array = []  # chunk messages waiting for their frame, nearest first (as the server sends them)
var _chunk_unload_queue: Array[String] = []  # old meshes freed once no chunk is waiting to be drawn
## Per frame: chunks are added until this much time has gone (at least one;
## a chunk with buildings takes ~10-20 ms, an empty one far less), then
## unloads the same way once nothing waits to be drawn - after a Home jump the
## destination is drawn first and the old area's chunks are freed afterwards.
const CHUNK_BUDGET_USEC := 4000
## A chunk's first draw runs later in the frame it is added in: ~1 us a point of
## its geometry (headless; a dense city chunk is ~10k points).
const DRAW_USEC_PER_POINT := 1.0
const CHUNK_SIZE_M := 500.0  # map_chunks.CHUNK_SIZE_M: chunk "ix_iy" covers [ix, ix + 1) x [iy, iy + 1) of these
const JUMP_M := 500.0  # the player moving this far between two states is a jump (Home, respawn)
var _last_player_at = null  # Vector2 metres, the last state's
var _jumped_usec := 0  # when the last jump was seen, until the chunk under the player is drawn
var _last_frame_usec := 0  # frame-time accounting (godot-18): real time between frames, not the smoothed delta
var _bench := 0.0  # --bench SECONDS: drive-through measurement, then the report as JSON
var _bench_left := 0.0
var _bench_hide: PackedStringArray = []
var _bench_pre_draw := 0  # --bench: when the renderer started this frame (usec)
var override_altitude := NAN  # --sun-altitude
var override_azimuth := NAN  # --sun-azimuth (degrees from grid north), for the shadow checks
var override_cloud := NAN  # --cloud-cover (0 clear .. 1 overcast)
var override_night := -1.0  # >= 0: presentation override for the audio test (never sent to Python)
var override_rain := -1.0
var override_train_at := Vector2.INF
var override_wetness := -1.0  # audio test: a moving train here (presentation only)
var language := "en"
var graphics: Dictionary = {}  # empty for direct scenes/tests; the launcher supplies saved defaults


var weather: Node = WeatherLayer.new()  # godot-final-06: precipitation, ripples, splashes
var holidays: Node = preload("res://holiday_layer.gd").new()
var wildlife := WildlifeLayer.new()
var environment_ambience := preload("res://environment_ambience.gd").new()
var animal_audio := preload("res://animal_audio.gd").new()
var _tram_states := {}  # tram id -> its state last frame: the bell when one sets off
var world_light := CanvasModulate.new()  # godot-lights-01: the ambient light, multiplied over the world canvas
var moon_grey := WorldEnvironment.new()  # desaturates the world (canvas layers <= 0, not the HUD) under moonlight


func _ready() -> void:
	add_child(nightclubs)
	add_child(car_stereos)
	if graphics.has("buildings_3d"):
		MapChunk.buildings_3d = graphics["buildings_3d"]
	MapChunk.forest_canopy = graphics.get("forest_canopy", true)  # like the buildings: for the whole session
	_apply_language()
	_build_help()
	_build_inspector()
	add_child(home_walk)
	add_child(door_marks)
	add_child(weather)
	add_child(wildlife)
	add_child(animal_audio)
	add_child(world_light)
	moon_grey.environment = Environment.new()
	moon_grey.environment.background_mode = Environment.BG_CANVAS
	moon_grey.environment.adjustment_enabled = false
	add_child(moon_grey)
	weather.setup($Sky, map_layer)
	add_child(holidays)
	holidays.setup(map_layer)
	holidays.audio = audio
	entities.lamp_near = map_layer.lamp_near
	entities.light_at = map_layer.light_at  # street light on the vehicles  # reflectors and long beams look up working street lights
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
			"--screenshot-wait":  # seconds of play before the screenshot (default 6), e.g. for phone offers
				_screenshot_wait = float(args[i + 1])
			"--wetness":  # presentation override for visual checks (never sent to Python)
				override_wetness = float(args[i + 1])
			"--sun-altitude":  # godot-lights-01 visual checks: the sun at this altitude (never sent to Python)
				override_altitude = float(args[i + 1])
			"--sun-azimuth":  # rrt-018-shadows visual checks, like --sun-altitude
				override_azimuth = float(args[i + 1])
			"--cloud-cover":
				override_cloud = float(args[i + 1])
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
			"--zoom":  # start zoomed by this factor (+/- keys), for screenshots
				camera.zoom *= float(args[i + 1])
			"--phone":  # start with the phone open, for screenshots
				phone.call_deferred("open")
			"--labels":  # start with labels: 1 streets, 2 everything (L), for screenshots
				labels.mode = int(args[i + 1])
			"--navigation":  # godot-final-04: start with the route shown (N), for screenshots
				phone.call_deferred("open")
			"--next-train":  # godot-final-07: start with the J board shown, for screenshots
				show_next_train = true
			"--screenshot-drive":  # with --screenshot: get in and drive this many seconds first
				_screenshot_drive = float(args[i + 1])
	if _selftest or _bench > 0.0 or _screenshot_path != "" or "--audiotest" in args or "--inputtest" in args:
		_engine_on = true  # automated runs drive straight away: no sign, no hints
		_entered_taxi = not "--start-sign" in args  # --start-sign: a screenshot of the city's start sign and forecast
	if _bench > 0.0:  # rrt-019.1: the frame in phases - scripts, redraws and layout up to the render, then the render
		Perf.time_draws(entities, "draw_entities")  # and the vehicles, people, lamps... each
		RenderingServer.frame_pre_draw.connect(func():
			_bench_pre_draw = Time.get_ticks_usec()
			Perf.add("phase_process_to_render", _bench_pre_draw - _last_frame_usec))
		RenderingServer.frame_post_draw.connect(func(): Perf.add("phase_render", Time.get_ticks_usec() - _bench_pre_draw))
	instruments.layout = hud_layout
	_apply_graphics()
	hud.layout = hud_layout
	phone.layout = hud_layout
	sim.world_received.connect(_on_world)
	sim.state_received.connect(_on_state)
	# One new chunk per frame (godot-16): a chunk's first drawing takes ~10-20 ms, and crossing into
	# a new area brings a whole row of them at once.
	sim.chunk_received.connect(_queue_chunk)
	sim.chunk_unloaded.connect(_queue_chunk_unload)
	sim.connection_changed.connect(_on_connection)
	phone.sound.connect(func(group: String, variation: int): audio.handle_event({"type": "sound", "group": group, "variation": variation}))
	phone.request.connect(func(action: String, item_id: String, request_id: int): sim.send_phone(action, item_id, request_id))
	phone.open()
	if _audiotest:
		var tester: Node = preload("res://audio_test.gd").new()
		tester.main = self
		var at := args.find("--audiotest")
		if at + 1 < args.size() and not args[at + 1].begins_with("--"):
			tester.out_path = args[at + 1]
		add_child(tester)


func set_graphics(options: Dictionary) -> void:
	graphics = options.duplicate()
	if is_node_ready():
		_apply_graphics()


func _apply_graphics() -> void:
	map_layer.set_shadows_enabled(MapChunk.buildings_3d and graphics.get("buildings_3d", true) and graphics.get("shadows", true))
	weather.precipitation_enabled = graphics.get("precipitation", true)
	weather.ripples_enabled = graphics.get("water_ripples", true)
	weather.splashes_enabled = graphics.get("splashes", true)
	entities.smoke_enabled = graphics.get("vehicle_smoke", true)
	for effect in [[weather.precipitation, "precipitation"], [weather.ripples, "water_ripples"], [weather.splash_node, "splashes"]]:
		if not graphics.get(effect[1], true):
			effect[0].hide()
	entities.queue_redraw()
	if not graphics.get("lightning_flashes", true):
		flash.hide()
	# 3D/2D geometry stays consistent across loaded and incoming chunks until the next session.


func set_language(value: String) -> void:
	language = value
	if is_inside_tree():
		_apply_language()


func _apply_language() -> void:
	hud.language = language
	MapChunk.language = language
	phone.set_language(language)
	instruments.language = language
	nav_overlay.language = language
	entities.language = language
	if _help != null:
		_help.queue_free()
		_build_help()
	if _inspect_panel != null:
		_inspect_panel.get_node("Rows/Back").text = T.text("back_to_taxi", language)


func _on_connection(up: bool) -> void:
	print("simulation ", "connected" if up else "disconnected")
	phone.set_connected(up)
	if not up:  # a new connection starts over: header, chunks, states
		_clear_focus()
		entities.buffer.clear()
		map_layer.clear()
		wildlife.clear()
		environment_ambience.clear()
		audio.stop_loops()
		audio.stop_voices()


func _process_chunk_queues(started_usec: int) -> void:
	# Another one only if it fits too: a 3 ms frame doesn't start a 20 ms chunk. A chunk costs
	# its add (cheap: the worker prepared it) and its first draw, later in this frame, by its points.
	var at := started_usec
	var spent := 0
	var last := 0
	while not _chunk_queue.is_empty():
		var draw := int(_chunk_queue[0].get("prepared", {}).get("points", 0) * DRAW_USEC_PER_POINT)
		if spent > 0 and spent + last + draw > CHUNK_BUDGET_USEC:
			break
		var message: Dictionary = _chunk_queue.pop_front()
		wildlife.replace_chunk(message, map_layer.origin)
		map_layer.replace_chunk(message)
		var now := Time.get_ticks_usec()
		last = now - at
		Perf.add("chunk_add", last)
		spent += last + draw
		at = now
	if not _chunk_queue.is_empty():
		return  # unloads wait: drawing what the player needs comes first
	while not _chunk_unload_queue.is_empty() and (spent == 0 or spent + last <= CHUNK_BUDGET_USEC):
		var chunk_id: String = _chunk_unload_queue.pop_front()
		wildlife.remove_chunk(chunk_id)
		map_layer.remove_chunk(chunk_id)
		var now := Time.get_ticks_usec()
		last = now - at
		Perf.add("chunk_unload", last)
		spent += last
		at = now


## After a jump (Home, respawn): how long until the chunk under the player
## is drawn with its roads - "relocation_visible" in --bench and F3.
func _time_relocation(state: Dictionary, now_usec: int) -> void:
	if not state.has("player"):
		return
	var at := Vector2(state["player"]["x"], state["player"]["y"])
	if _last_player_at != null and at.distance_to(_last_player_at) > JUMP_M:
		_jumped_usec = now_usec
	_last_player_at = at
	if _jumped_usec == 0:
		return
	var chunk = map_layer._chunks.get("%d_%d" % [floori(at.x / CHUNK_SIZE_M), floori(at.y / CHUNK_SIZE_M)])
	if chunk != null and not chunk._data.get("roads", []).is_empty():
		Perf.add("relocation_visible", now_usec - _jumped_usec)
		print("relocation: the map under the player drawn %.0f ms after the jump" % ((now_usec - _jumped_usec) / 1000.0))
		_jumped_usec = 0


## The latest message for a chunk wins: a newer copy (the server resends a
## changed chunk) replaces a queued one and cancels a pending unload of it.
func _queue_chunk(message: Dictionary) -> void:
	var chunk_id: String = message["chunk_id"]
	_chunk_unload_queue.erase(chunk_id)
	for i in _chunk_queue.size():
		if _chunk_queue[i]["chunk_id"] == chunk_id:
			_chunk_queue[i] = message
			return
	_chunk_queue.append(message)


func _queue_chunk_unload(chunk_id: String) -> void:
	_chunk_queue = _chunk_queue.filter(func(m): return m["chunk_id"] != chunk_id)  # gone before it was ever drawn
	_chunk_unload_queue.append(chunk_id)


func _on_world(world: Dictionary) -> void:
	_chunk_queue.clear()  # a new world (reconnect): the old one's chunks are void
	_chunk_unload_queue.clear()
	var origin := Vector2(world["center"][0], world["center"][1])
	map_layer.set_origin(origin)
	wildlife.clear()
	entities.origin = origin
	audio.origin = origin
	sim.player_id = world.get("player_id", sim.player_id)
	if not _entered_taxi and _start_sign == null and world.get("city", "") != "":
		_start_sign = start_sign(world, language)
		$Ui.add_child(_start_sign)


func _on_state(message: Dictionary) -> void:
	var started := Time.get_ticks_usec()
	_tick = message["tick"]
	_states_received += 1
	entities.buffer.push(message["tick"], message.get("server_time", message["tick"] / 30.0), message["state"], entities.now())
	_state_usec = lerpf(_state_usec, float(Time.get_ticks_usec() - started + sim.parse_usec), 0.1)


## F12: the window as screenshot_<ns>.png in the screenshots folder, and
## the server writes the debug JSON beside it.
func save_screenshot() -> String:
	var path := screenshot_directory(OS.get_name(), OS.get_environment("USERPROFILE")).path_join(
		"screenshot_%d.png" % int(Time.get_unix_time_from_system() * 1e9))
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var error := get_viewport().get_texture().get_image().save_png(path)
	print("Screenshot " + (path if error == OK else "failed: %s" % error_string(error)))
	sim.send_debug_snapshot(path.get_basename() + ".json")  # the debug JSON beside it, from the server
	return path


static func screenshot_directory(os_name: String, user_profile: String) -> String:
	if os_name == "Windows":
		return user_profile.path_join("Pictures").path_join("TheRoadRageTrip")
	return OS.get_environment("PWD").path_join("screenshots") if OS.has_environment("PWD") else "screenshots"


## Mouse on a HUD panel: drag it, kept on screen.
func _input(event: InputEvent) -> void:
	drive.handle(event)
	if event is InputEventMouseButton:
		if event.pressed and _start_sign == null and not (phone.visible and phone.get_global_rect().has_point(event.position)) and (event.button_index == MOUSE_BUTTON_MIDDLE or (event.button_index == MOUSE_BUTTON_LEFT and event.ctrl_pressed)):
			_pan_button = event.button_index
			_focus = {"kind": "pan", "position": camera.position}
			_inspect_panel.visible = true
			get_viewport().set_input_as_handled()
			return
		if not event.pressed and event.button_index == _pan_button:
			_pan_button = 0
			get_viewport().set_input_as_handled()
			return
	if event is InputEventMouseMotion and _pan_button != 0:
		_focus["position"] -= event.relative / camera.zoom.x
		get_viewport().set_input_as_handled()
		return
	if event is InputEventMouseButton and event.pressed and _inspect_panel.visible and _inspect_panel.get_global_rect().has_point(event.position):
		return  # the Back button gets the click, even if a HUD panel overlaps it
	if event is InputEventMouseButton and event.pressed and phone.visible and phone.get_global_rect().has_point(event.position):
		if not hud_layout.rects.get("navigation_phone", Rect2()).has_point(event.position) \
				and hud_layout.grip_at(event.position) != "navigation_phone":  # its resize corner
			return  # phone app controls take priority over HUD panels beneath them
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT and instruments.trip_reset_rect.grow(3).has_point(event.position):
		_reset_trip_pending = true  # the trip LCD's reset button, same as T
		get_viewport().set_input_as_handled()
		return
	if _start_sign == null and hud.visible and hud_layout.handle(event):
		instruments.queue_redraw()
		hud._layout()
		phone.update_layout()
		get_viewport().set_input_as_handled()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and _start_sign == null:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP or event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_zoom(1.1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 0.9)
			get_viewport().set_input_as_handled()
			return
		if event.button_index == MOUSE_BUTTON_LEFT:
			_focus = entities.entity_at(event.position, get_viewport().get_canvas_transform())
			_inspect_panel.visible = not _focus.is_empty()
			get_viewport().set_input_as_handled()
			return
	if _start_sign != null and event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_F12:  # a screenshot of the sign itself
			save_screenshot()
		elif event.keycode != KEY_ESCAPE:  # any key but Esc and F12 starts
			_start_sign.queue_free()
			_start_sign = null
		get_viewport().set_input_as_handled()
		return
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_F12:
				save_screenshot()
			KEY_U, KEY_F2:  # the HUD layout back to default
				hud_layout.reset()
				instruments.queue_redraw()
				hud._layout()
				phone.update_layout()
			KEY_F:
				_interact_pending = true
			KEY_G:
				_refuel_pending = true
			KEY_J:
				if not phone.is_open or phone.busy:
					show_next_train = not show_next_train
			KEY_SPACE:
				if (not phone.is_open or phone.busy) and not summary_shown:
					_road_rage_pending = true
			KEY_V:
				speed_limiter = not speed_limiter
			KEY_B:
				red_light_assist = not red_light_assist
			KEY_K:
				lane_assist = not lane_assist
			KEY_R:
				_respawn_pending = true
			KEY_H:
				_home_pending = true
			KEY_X:
				if not phone.is_open or phone.busy:
					_cancel_ride_pending = true
			KEY_T:
				_reset_trip_pending = true
			KEY_E:  # toggles what the simulation shows (it may have stopped the engine: no fuel)
				var door: Dictionary = entities.shown_state().get("home_door", {})
				if door.get("available", false) or (door.get("indoors", false) and home_walk.visible and home_walk.at_exit()):
					_home_door_pending = true  # on foot at home's door (only then: E means nothing else on foot)
				elif not entities.shown_state().get("on_foot", true) and not _interact_pending:
					_engine_on = not bool(entities.shown_state().get("player", {}).get("engine_on", _engine_on))
			KEY_F1:
				_help.visible = not _help.visible
			KEY_ESCAPE:
				if _help.visible:
					_help.visible = false
					get_viewport().set_input_as_handled()
			KEY_F3:
				debug_label.visible = not debug_label.visible
			KEY_EQUAL, KEY_KP_ADD:
				_zoom(1.25)
			KEY_MINUS, KEY_KP_SUBTRACT:
				_zoom(0.8)


## Look ahead of the taxi: at 72 km/h the centred view showed only ~2 s of
## road ahead. Eased (exponentially) so steering and braking don't swing the
## view. No speed zoom: every zoom change redraws the pixel-sized map layers
## (13 fps in the selftest).
func _camera_lead(delta: float) -> Vector2:
	var view := get_viewport().get_visible_rect().size / camera.zoom.x
	var target: Vector2 = (entities.player_velocity() * LEAD_S).limit_length(minf(view.x, view.y) * LEAD_MAX)
	_lead = _lead.lerp(target, 1.0 - exp(-3.0 * delta))
	return _lead


func _zoom(factor: float) -> void:
	camera.zoom = Vector2.ONE * clampf(camera.zoom.x * factor, 3.0, 24.0)


func _clear_focus() -> void:
	_focus.clear()
	_pan_button = 0
	if _inspect_panel != null:
		_inspect_panel.visible = false


## Driving keys: every press and release, before any UI can consume it.
func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT or what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		# Key-ups of keys held now will never arrive: let go of everything,
		# and tell the simulation at once rather than at the next interval.
		drive.clear()
		_pan_button = 0
		_command_timer = 0.0


func _process(delta: float) -> void:
	var now_usec := Time.get_ticks_usec()
	if _last_frame_usec > 0 and not entities.shown_state().is_empty() and (_bench <= 0.0 or _bench - _bench_left > 5.0):
		Perf.frame((now_usec - _last_frame_usec) / 1000.0)  # --bench: after 5 s of warm-up (the first chunks)
	_last_frame_usec = now_usec
	_process_chunk_queues(now_usec)
	entities.update_frame(delta)  # first: the camera below and the drawing use this one sample
	var state: Dictionary = entities.shown_state()
	var vehicles: Array = entities.npc_cars().map(func(row): return row[1])
	vehicles.append(entities.player_position())
	wildlife.update(delta, float(state.get("game_time_seconds", 12.0 * 3600.0)), camera.position, vehicles)
	animal_audio.update(wildlife.animals, entities.dogs(), camera.position, delta,
		not state.is_empty() and int(state.get("player", {}).get("map_level", 0)) == 0)
	Perf.counters["wildlife"] = wildlife.animals.size()
	_time_relocation(state, now_usec)
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
	camera.position = entities.player_position() + _camera_lead(delta)
	if _focus.get("kind") == "pan":
		camera.position = _focus["position"]
	elif _focus.has("id"):
		var focused: Vector2 = entities.entity_position(_focus["kind"], _focus["id"])
		if focused == Vector2.INF:
			_clear_focus()
		else:
			camera.position = focused
	entities.px_per_m = camera.zoom.x
	nav_overlay.show_route = phone.is_open and phone.busy
	entities.show_route = nav_overlay.show_route
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
		Perf.add("time_physics", int(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1e6))
		if map_layer.buildings_3d != null:  # godot-22: the 3D building pass alone
			var view_3d: RID = map_layer.buildings_3d._view.get_viewport_rid()
			RenderingServer.viewport_set_measure_render_time(view_3d, true)
			Perf.add("render_3d_cpu", int(RenderingServer.viewport_get_measured_render_time_cpu(view_3d) * 1000.0))
			Perf.add("render_3d_gpu", int(RenderingServer.viewport_get_measured_render_time_gpu(view_3d) * 1000.0))
	if _bench > 0.0 and not state.is_empty():
		_bench_left -= delta
		if _bench - _bench_left > 5.0 and _bench - _bench_left - delta <= 5.0:
			Perf.sections.clear()  # the sections as the frames: steady state, not the first chunks' loading
		if _bench_left <= 0.0:
			_perf_counters()
			print("BENCH ", JSON.stringify(Perf.report()))
			get_tree().quit()
	_command_timer -= delta
	if _command_timer <= 0.0 and not _selftest and not _audiotest and not screenshot_driving and not summary_shown:  # the tests drive instead
		_command_timer = COMMAND_INTERVAL_S
		send({} if _start_sign != null else drive.controls(state.get("on_foot", true)))  # the start sign: no driving yet


## Sound and HUD for the state on screen; events as the picture reaches them.
func _nearest_nightclub_m() -> float:
	var listener := Vector2(camera.position.x + entities.origin.x, entities.origin.y - camera.position.y)
	var nearest := INF
	for club in map_layer.nightclubs():
		nearest = minf(nearest, listener.distance_to(Vector2(club[0], club[1])))
	return snappedf(nearest, 1.0) if is_finite(nearest) else -1.0


func _present(state: Dictionary) -> void:
	if state.is_empty():
		if summary_shown:
			return  # the session is over: the summary stays, even when the server goes away
		hud.visible = false
		debug_label.visible = true
		debug_label.text = T.text("waiting", language) % [sim.host, sim.port]
		return
	if not hud.visible:  # the simulation is here: the HUD replaces the waiting text (F3 brings the readout back)
		hud.visible = true
		debug_label.visible = false
	var player: Dictionary = state["player_pedestrian"] if state.get("on_foot", false) else state["player"]
	audio.player_at = Vector2(player["x"], player["y"])
	if home_walk.visible:  # walking a floor plan: its own steps, the outdoors muffled
		audio.update_footsteps(true, home_walk.at, "pedestrian.footsteps_indoor")
	else:
		audio.update_footsteps(state.get("on_foot", false), audio.player_at)
	audio.set_indoors(home_walk.visible)
	for event in entities.buffer.take_due_events(entities.now()):
		events_presented += 1
		if event.get("type") == "phone_result":
			phone.handle_result(event)
			continue
		if event.get("type") == "speech":  # godot-final-07: the server chose the line; play it, subtitle it
			if audio.speak(event):
				hud.show_subtitle(event)
			continue
		if event.get("type") == "station_announcement":
			audio.announce(event)
			continue
		audio.handle_event(event)
		_recent_events.push_front(event.get("group", event.get("type", "?")))
	_recent_events.resize(min(_recent_events.size(), 6))
	var driving: bool = not state.get("on_foot", true) and state["player"].get("engine_on", false)
	var speed: float = absf(state["player"].get("speed", 0.0))
	audio.set_loop("engine", 0.6 if driving else 0.0, minf(1.0 + speed / 25.0, 2.2))
	audio.set_loop("damaged_steam", 0.35 if state.get("taxi", {}).get("taxi_smoke_timer", 0.0) > 0.0 else 0.0)
	var calendar = state.get("calendar")
	var darkness: float = calendar.get("darkness", 0.0) if typeof(calendar) == TYPE_DICTIONARY else -1.0
	var view := get_viewport().get_canvas_transform().affine_inverse() * get_viewport().get_visible_rect()
	if typeof(calendar) == TYPE_DICTIONARY:
		map_layer.set_season(calendar.get("season", []))
		var season = calendar.get("season", [])
		wildlife.winter = float(season[0]) if season is Array and season.size() == 4 else 0.0  # winter coats
		map_layer.set_sports_hours(bool(calendar.get("sports_lights", false)))
		map_layer.set_arena_lights(bool(calendar.get("arena_lights", false)))
	# godot-lights-01: the world's light from the sun's altitude, continuously - the
	# ambient multiply (CanvasModulate: no fill) and how strongly the lights show.
	var altitude := Daylight.altitude(state) if is_nan(override_altitude) else override_altitude
	var cloud := Daylight.cloud_cover(state) if is_nan(override_cloud) else override_cloud
	MapChunk.WATER_MATERIAL.set_shader_parameter("sky_color", Daylight.sky_color(altitude, cloud))
	var water_wind := WeatherLayer.wind_vector(state)
	water_wind.y = -water_wind.y
	MapChunk.WATER_MATERIAL.set_shader_parameter("wind", water_wind)
	MapChunk.SHORE_MATERIAL.set_shader_parameter("wind", water_wind)
	var moon_altitude := Daylight.moon_value(state, "moon_altitude_deg", -90.0)
	var moon_strength := Daylight.moonlight(altitude, moon_altitude,
		Daylight.moon_value(state, "moon_illumination", 0.0), cloud)
	# Moonlight shows only away from city lights (rural roads): there it whitens
	# the ambient light, casts faint shadows and washes the colours out.
	if moon_strength > 0.0:
		var player_at := MapMath.point(entities.origin, player["x"], player["y"])
		var local_light: float = map_layer.light_at(player_at)
		if map_layer.lamp_near(player_at, 25.0):
			local_light = maxf(local_light, 1.0)
		moon_strength = Daylight.moon_shadow(moon_strength, local_light)
	var ambient := Daylight.moon_ambient(Daylight.ambient_color(altitude), moon_strength)
	var lights := Daylight.artificial(altitude)
	if not ambient.is_equal_approx(world_light.color):
		world_light.color = ambient
	map_layer.set_light(lights, ambient)
	var sun_strength := Daylight.sunlight(altitude, cloud)
	if sun_strength > 0.01:
		map_layer.set_celestial_light(altitude, Daylight.azimuth(state) if is_nan(override_azimuth) else override_azimuth, sun_strength)
	else:
		map_layer.set_celestial_light(moon_altitude, Daylight.moon_value(state, "moon_azimuth_deg", 180.0), moon_strength)
	var grey := Daylight.moon_desaturation(moon_strength)
	moon_grey.environment.adjustment_enabled = grey > 0.01
	moon_grey.environment.adjustment_saturation = 1.0 - grey
	entities.ambient = ambient
	night.ambient = ambient
	entities.reflectors_on = typeof(calendar) == TYPE_DICTIONARY and calendar.get("sun_altitude_deg", 90.0) < -7.5
	var night_started := Time.get_ticks_usec()
	entities.light_level = lights
	night.show_lights(lights, view, entities.headlight_beams() if lights > 0.01 else [])
	Perf.add("night_beams", Time.get_ticks_usec() - night_started)
	var lightning: float = entities.lightning_now() if graphics.get("lightning_flashes", true) else 0.0
	if not is_equal_approx(flash.color.a, lightning):
		flash.color.a = lightning
	flash.visible = lightning > 0.0  # godot-18: an invisible full-screen rect is still blended every frame
	# The server's darkness; an older server without a calendar: the hour.
	var night := (darkness if darkness >= 0.0 else _night(state.get("game_time_seconds", 12.0 * 3600.0))) if override_night < 0.0 else override_night
	var loops := weather_loops(state)
	if override_rain >= 0.0:
		loops["rain"] = override_rain
	var music_gain := minf(nightclubs.city_ambience_gain(), car_stereos.city_ambience_gain())
	var season: Array = calendar.get("season", [0.0, 0.0, 1.0, 0.0]) if typeof(calendar) == TYPE_DICTIONARY else [0.0, 0.0, 1.0, 0.0]
	var rain := clampf(float(loops.get("rain", 0.0)) / 0.6, 0.0, 1.0)
	var beds := environment_ambience.mix(map_layer._chunks, entities.origin, camera.position, clampf(night, 0.0, 1.0),
		clampf(float(season[0]), 0.0, 1.0), rain, int(state.get("player", {}).get("map_level", 0)) == 0, get_process_delta_time())
	for key in beds:
		audio.set_loop(key, beds[key] * music_gain)
	for key in loops:
		audio.set_loop(key, loops[key])
	_train_loop(state)
	_feature_loops(state)
	var crowd := station_ambience(state.get("railway"), Vector2(camera.position.x + entities.origin.x, entities.origin.y - camera.position.y),
		audio._config.get("ranges_m", {}).get("station.ambience", [15.0, 150.0]))
	audio.set_loop("station_crowd", crowd[0] * 0.6, 1.0, crowd[1])
	if typeof(calendar) == TYPE_DICTIONARY and calendar.has("date"):  # rrt-019: the game clock's night, not the computer's
		nightclubs.update(map_layer.nightclubs(), Vector2(camera.position.x + entities.origin.x, entities.origin.y - camera.position.y),
			NightclubAudio.week_minute(calendar["date"], state.get("game_time_seconds", 0.0)), entities.origin, get_process_delta_time())
		car_stereos.update(entities.npc_cars(), camera.position,
			NightclubAudio.week_minute(calendar["date"], state.get("game_time_seconds", 0.0)), get_process_delta_time())
	audio.set_loop("station_luggage", crowd[0] * 0.4, 1.0, crowd[1])
	if state.get("should_stop", false) and not summary_shown:
		show_summary(state)
	if not state.get("on_foot", true):
		_entered_taxi = true
	hud.show_state(state, {"entered_taxi": _entered_taxi, "speed_limiter": speed_limiter, "red_light_assist": red_light_assist, "lane_assist": lane_assist, "navigation": nav_overlay.show_route, "labels": labels.mode, "next_train": show_next_train})
	instruments.chips = [lane_assist, speed_limiter, nav_overlay.show_route]  # K, V, N under the speedometer
	instruments.show_state(state)
	map_layer.set_wetness(state.get("weather", {}).get("wetness", 0.0) if override_wetness < 0.0 else override_wetness)
	map_layer.set_road_snow(float(state.get("weather", {}).get("road_snow", 0.0)), state.get("weather", {}).get("plowed_cells", []), state.get("weather", {}).get("weather_type", "") == "snow")
	map_layer.set_px_per_m(camera.zoom.x)  # after the camera is placed; only reads its zoom
	map_layer.set_building_view(camera.position)
	map_layer.set_traffic_lights(state.get("traffic_lights", {}))
	# godot-16: below ground (the server's map level), the flashing speed camera, the labels.
	var level := int(state.get("player", {}).get("map_level", 0))
	map_layer.set_map_level(level)
	entities.underground = level != 0
	wildlife.visible = level == 0
	weather.update(get_process_delta_time(), state, entities.player_position(), level != 0)
	holidays.update(get_process_delta_time(), state, view, level != 0)
	map_layer.set_flash(state.get("speed_camera_flash"))
	labels.update_view(get_viewport().get_canvas_transform(), map_layer.chunk_count(), level != 0)
	map_layer.set_obstacles(state.get("knocked_posts", []))
	var body: Dictionary = entities.player_body()
	if not body.is_empty() and body["speed"] > 0.5 and map_layer.knock_trees(body) > 0:  # trees: the client's alone
		audio.handle_event({"type": "sound", "group": "collision.tree"})
		audio.handle_event({"type": "sound", "group": "collision.tree_fall"})
	map_layer.set_broken_hedges(state.get("broken_hedges", []))
	phone.clock_text = hud._clock.text.get_slice(" ", 1) if hud._clock.text.contains(" ") else hud._clock.text
	if state.has("game_time_seconds"):
		phone.set_game_seconds(float(state["game_time_seconds"]))
	phone.protest_active = state.get("protest_active", false)
	_home_view(state)
	door_marks.show_doors(state.get("home_door", {}), entities.origin, camera.zoom.x)
	phone.show_phone(state.get("phone", {}))
	phone.show_navigation(state.get("navigation", {}), hud.task_text(state.get("taxi", {}), hud.language))
	_refresh_inspector(state)
	var target: Dictionary = entities.current_target(state)
	var target_screen := Vector2.ZERO
	if not target.is_empty():
		target_screen = get_viewport().get_canvas_transform() * MapMath.point(entities.origin, target["x"], target["y"])
	var camera_world := Vector2(camera.position.x + entities.origin.x, entities.origin.y - camera.position.y)
	nav_overlay.update_view(target, target_screen, camera_world, state["player"].get("heading", 0.0))
	if debug_label.visible:
		_update_debug(state)


## Indoors (the server's home_door.indoors): the floor plan to walk in, asked for once.
func _home_view(state: Dictionary) -> void:
	var indoors: bool = state.get("home_door", {}).get("indoors", false)
	home_walk.is_home = state.get("home_door", {}).get("is_home", false)
	if not indoors:
		home_walk.leave()
		_home_plan_asked = false
		return
	if home_walk.visible:
		return
	home_walk.language = language
	if sim.home_plan.has("footprint") and home_walk.enter(sim.home_plan):
		return
	if home_walk.plan.has("footprint") and home_walk.enter(home_walk.plan):  # back in: the cached plan
		return
	if not _home_plan_asked:
		_home_plan_asked = sim.send_home_interior()


## The nearest moving train rumbles from where it is (one train is enough).
func _train_loop(state: Dictionary) -> void:
	if override_train_at != Vector2.INF:
		audio.set_loop("train_running", 0.8, 1.0, override_train_at)
		return
	var nearest = null
	var best := INF
	var speed := 0.0
	for train in state.get("trains", []):
		if is_tram(train) or train["state"] != "RUNNING" or train["speed"] < 2.0 or train["cars"].is_empty():
			continue
		var at := Vector2(train["cars"][0][0], train["cars"][0][1])
		if at.distance_to(audio.player_at) < best:
			best = at.distance_to(audio.player_at)
			nearest = at
			speed = train["speed"]
	audio.set_loop("train_running", minf(1.0, speed / 20.0) if nearest != null else 0.0, 1.0, nearest)


static func is_tram(train: Dictionary) -> bool:
	return str(train.get("id", "")).begins_with("tram-")


## The nearest of `points` ([x, y] world metres) to `from`, or null.
static func nearest_point(points: Array, from: Vector2):
	var best = null
	var best_distance := INF
	for point in points:
		var at := Vector2(point[0], point[1])
		if at.distance_to(from) < best_distance:
			best_distance = at.distance_to(from)
			best = at
	return best


## Trams, tractors, ploughs, sports and arena crowds: each a loop at its
## nearest source (the audio manager attenuates by distance); a tram's bell
## when it sets off from a stop near the listener.
func _feature_loops(state: Dictionary) -> void:
	var from: Vector2 = audio.player_at
	var surface := int(state.get("player", {}).get("map_level", 0)) == 0
	var tram = null
	var tram_speed := 0.0
	var states := {}
	for train in state.get("trains", []):
		if not is_tram(train) or train["cars"].is_empty():
			continue
		var at := Vector2(train["cars"][0][0], train["cars"][0][1])
		states[train["id"]] = train["state"]
		if _tram_states.get(train["id"], "") == "DWELLING" and train["state"] == "RUNNING" and at.distance_to(from) < 150.0:
			audio.handle_event({"type": "sound", "group": "railway.tram_bell", "at": [at.x, at.y]})
		if train["speed"] > 0.5 and (tram == null or at.distance_to(from) < tram.distance_to(from)):
			tram = at
			tram_speed = train["speed"]
	_tram_states = states
	audio.set_loop("tram_running", minf(1.0, tram_speed / 10.0) if tram != null else 0.0, 1.0, tram)
	var tractor = null
	var tractor_speed := 0.0
	var trailer = null
	var trailer_speed := 0.0
	for npc in state.get("npcs", []):
		if surface and npc.has("trailer") and int(npc.get("layer", 0)) >= 0 \
				and npc.get("state", "") not in ["PARKED", "CRASHED"] and absf(npc.get("speed", 0.0)) > 0.5:
			var at := Vector2(npc["trailer"][0], npc["trailer"][1])
			if trailer == null or at.distance_to(from) < trailer.distance_to(from):
				trailer = at
				trailer_speed = absf(npc.get("speed", 0.0))
		if npc.get("vehicle_type", "") != "tractor" or npc.get("state", "") in ["PARKED", "CRASHED"]:
			continue
		var at := Vector2(npc["x"], npc["y"])
		if tractor == null or at.distance_to(from) < tractor.distance_to(from):
			tractor = at
			tractor_speed = absf(npc.get("speed", 0.0))
	audio.set_loop("tractor", 0.7 if tractor != null else 0.0, 0.85 + minf(tractor_speed / 15.0, 0.4), tractor)
	audio.set_loop("plough", minf(1.0, tractor_speed / 6.0) if tractor != null and entities.ploughing else 0.0, 1.0, tractor)
	audio.set_loop("trailer", minf(0.5, trailer_speed / 12.0) if trailer != null else 0.0, 1.0, trailer)
	var skaters: Array = []
	var swimmers: Array = []
	var riders: Array = []
	for ped in state.get("pedestrians", []):
		if ped.get("activity", "") == "ice_skating":
			skaters.append([ped["x"], ped["y"]])
		if surface and ped.get("animation_state", "") == "swimming":
			swimmers.append([ped["x"], ped["y"]])
		if surface and ped.get("activity", "") == "theme_park" and ped.get("animation_state", "") == "riding":
			riders.append([ped["x"], ped["y"]])
	var swimmer = nearest_point(swimmers, from)
	audio.set_loop("swimming", 0.55 if swimmer != null else 0.0, 1.0, swimmer)
	var ride = nearest_point(riders, from)
	audio.set_loop("ride", 0.45 if ride != null else 0.0, 1.0, ride)
	var mark = state.get("tire_mark")
	var spray := float(mark.get("spray", 0.0)) if mark is Dictionary and mark.get("kind") == "dirt" else 0.0
	var moving := absf(state.get("player", {}).get("speed", 0.0)) > 0.5
	var driving: bool = surface and moving and not state.get("on_foot", true)
	audio.set_loop("mud", 0.45 * clampf(spray, 0.0, 1.0) if driving else 0.0, 1.0,
		Vector2(state.get("player", {}).get("x", 0.0), state.get("player", {}).get("y", 0.0)))
	var skater = nearest_point(skaters, from)
	audio.set_loop("ice_skating", 0.6 if skater != null else 0.0, 1.0, skater)
	var puck = nearest_point(state.get("pucks", []), from)
	audio.set_loop("ice_hockey", 0.8 if puck != null else 0.0, 1.0, puck)
	var ball = nearest_point(state.get("balls", []), from)
	audio.set_loop("soccer", 0.7 if ball != null else 0.0, 1.0, ball)
	var calendar = state.get("calendar")
	var arena = nearest_point(calendar.get("arena_games", []), from) if typeof(calendar) == TYPE_DICTIONARY else null
	audio.set_loop("arena_crowd", 0.8 if arena != null else 0.0, 1.0, arena)
	_traffic_loops(state, from, surface)
	_site_loops(state, from, surface)


## Bicycles, motorcycles and heavy vehicles backing up (state npcs), and protests.
func _traffic_loops(state: Dictionary, from: Vector2, surface: bool) -> void:
	var nearest := {"bicycle": null, "motorcycle": null, "reverse_beep": null}
	var speed := {"bicycle": 0.0, "motorcycle": 0.0, "reverse_beep": 0.0}
	for npc in state.get("npcs", []):
		if not surface or npc.get("state", "") in ["PARKED", "CRASHED"]:
			continue
		var kind: String = npc.get("vehicle_type", "")
		var moving := float(npc.get("speed", 0.0))
		var key := ""
		if kind == "bicycle" and moving > 1.5:
			key = "bicycle"
		elif kind == "motorcycle" and absf(moving) > 0.5:
			key = "motorcycle"
		elif kind in ["bus", "truck", "tractor"] and moving < -0.3:
			key = "reverse_beep"
		if key == "":
			continue
		var at := Vector2(npc["x"], npc["y"])
		if nearest[key] == null or at.distance_to(from) < nearest[key].distance_to(from):
			nearest[key] = at
			speed[key] = absf(moving)
	audio.set_loop("bicycle", 0.4 * minf(1.0, speed["bicycle"] / 6.0) if nearest["bicycle"] != null else 0.0, 1.0, nearest["bicycle"])
	audio.set_loop("motorcycle", 0.75 if nearest["motorcycle"] != null else 0.0,
		clampf(0.8 + speed["motorcycle"] / 30.0, 0.8, 1.6), nearest["motorcycle"])
	audio.set_loop("reverse_beep", 0.6 if nearest["reverse_beep"] != null else 0.0, 1.0, nearest["reverse_beep"])
	var protests: Array = []
	for group in state.get("protests", []):
		protests.append([group["x"], group["y"]])
	var protest = nearest_point(protests, from) if surface else null
	audio.set_loop("protest", 0.7 if protest != null else 0.0, 1.0, protest)


## Playgrounds by day, building sites on weekday working hours, campfires and
## beer gardens in the evening outside winter (site_sounds.gd finds them).
func _site_loops(state: Dictionary, from: Vector2, surface: bool) -> void:
	_sites_left -= get_process_delta_time()
	if _sites_left <= 0.0:
		_sites = SiteSounds.nearest(map_layer._chunks, entities.origin, from) if surface else {}
		_sites_left = 0.5
	var calendar = state.get("calendar")
	var hour := fmod(float(state.get("game_time_seconds", 12.0 * 3600.0)) / 3600.0, 24.0)
	var season: Array = calendar.get("season", [0.0, 0.0, 1.0, 0.0]) if typeof(calendar) == TYPE_DICTIONARY else [0.0, 0.0, 1.0, 0.0]
	var winter := float(season[0]) if season.size() == 4 else 0.0
	var weekday := 3
	if typeof(calendar) == TYPE_DICTIONARY and calendar.has("date"):
		weekday = int(Time.get_datetime_dict_from_datetime_string(str(calendar["date"]) + "T12:00:00", true)["weekday"])
	var gains := site_gains(hour, weekday, winter)
	for key in gains:
		audio.set_loop(key, gains[key] if _sites.get(key) != null else 0.0, 1.0, _sites.get(key))


## How loud each site loop is at this hour (0-24), weekday (0 Sunday) and winter weight.
static func site_gains(hour: float, weekday: int, winter: float) -> Dictionary:
	var summer := winter < 0.5
	return {
		"playground": 0.5 if hour >= 9.0 and hour < 20.0 and winter < 0.7 else 0.0,
		"construction": 0.6 if weekday >= 1 and weekday <= 5 and hour >= 7.0 and hour < 16.0 else 0.0,
		"campfire": 0.5 if summer and (hour >= 19.0 or hour < 1.0) else 0.0,
		"biergarten": 0.55 if summer and hour >= 15.0 else 0.0,
	}


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


## The career city is done (state should_stop): the summary covers the
## game and the client stops driving. The server owns what comes next; it
## has no continue request, so this is the end of the session here.
func show_summary(state: Dictionary) -> void:
	summary_shown = true
	drive.clear()
	for node in $Ui.get_children():
		if node != hud:
			node.visible = false
	hud.show_summary(Hud.summary_text(state, language))


## The distance gain: full within `range[0]`, 1/distance
## beyond, faded out over the last quarter of `range[1]`.
static func heard(listener: Vector2, at: Vector2, range_m: Array) -> float:
	var distance := listener.distance_to(at)
	if distance >= range_m[1]:
		return 0.0
	return range_m[0] / maxf(range_m[0], distance) * minf(1.0, (range_m[1] - distance) / (0.25 * range_m[1]))


## The station crowd: of the stations with people
## waiting, the one heard loudest; [volume min(1, waiting / 30), world position].
static func station_ambience(railway, listener: Vector2, range_m: Array) -> Array:
	var best := [0.0, 0.0, null]  # heard, volume, at
	if railway is Dictionary and railway.get("stations") is Array:
		for station in railway["stations"]:
			if not station is Dictionary or not typeof(station.get("waiting")) in [TYPE_INT, TYPE_FLOAT] or station["waiting"] <= 0:
				continue
			if not typeof(station.get("x")) in [TYPE_INT, TYPE_FLOAT] or not typeof(station.get("y")) in [TYPE_INT, TYPE_FLOAT]:
				continue
			var at := Vector2(station["x"], station["y"])
			var volume := minf(1.0, station["waiting"] / 30.0)
			var loud := volume * heard(listener, at, range_m)
			if loud > best[0]:
				best = [loud, volume, at]
	return [best[1], best[2]]


## The weather ambience layers from the server's state: rain
## and slush 0.6, heavy rain 0.7 in a thunderstorm, wind by its gusting
## speed, wet tyres by wetness and speed (slush: its own variation). An older
## server without the wind or thunderstorm: those stay silent.
static func weather_loops(state: Dictionary) -> Dictionary:
	var weather: Dictionary = state.get("weather", {}) if state.get("weather") is Dictionary else {}
	var type = weather.get("weather_type", "")
	var raining: bool = type in ["rain", "slush"]
	var wind_speed := WeatherLayer.wind_vector(state).length()
	var wetness := float(weather.get("wetness", 0.0)) if typeof(weather.get("wetness")) in [TYPE_INT, TYPE_FLOAT] else 0.0
	var player: Dictionary = state.get("player", {}) if state.get("player") is Dictionary else {}
	var speed := absf(float(player.get("speed", 0.0))) if typeof(player.get("speed")) in [TYPE_INT, TYPE_FLOAT] else 0.0
	var tyres := 0.0 if state.get("on_foot", true) else minf(1.0, wetness * speed / 15.0) * 0.6
	return {
		"rain": 0.6 if raining else 0.0,
		"rain_heavy": 0.7 if raining and weather.get("is_thunderstorm", false) == true else 0.0,
		"wind": clampf(wind_speed / 12.0, 0.0, 1.0) * 0.5,
		"wind_strong": clampf((wind_speed - 10.0) / 10.0, 0.0, 1.0) * 0.6,
		"wet_tires": tyres if type != "slush" else 0.0,
		"wet_slush": tyres if type == "slush" else 0.0,
	}


## The start sign: the city, the 24-hour forecast (the source in
## brackets with historical weather) and "press any key".
static func start_sign(world: Dictionary, language: String) -> PanelContainer:
	var sign := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color8(28, 84, 155)
	style.border_color = Color8(220, 235, 255)
	style.set_border_width_all(3)
	style.set_corner_radius_all(8)
	style.set_content_margin_all(24)
	sign.add_theme_stylebox_override("panel", style)
	var lines := VBoxContainer.new()
	lines.add_theme_constant_override("separation", 6)
	sign.add_child(lines)
	var rows := [[str(world.get("weather_city", world.get("city", ""))).to_upper(), 46, Color.WHITE], [T.text("weather_forecast_24h", language), 20, Color8(180, 220, 255)]]
	for line in world.get("forecast", []):
		if line is Dictionary:
			var source := str(line.get("source", "generated"))
			var wind := ""
			if line.get("wind_speed_mps") != null and line.get("wind_from_deg") != null:
				wind = "   %.1f m/s %s %.0f°" % [float(line.wind_speed_mps), wind_arrow(float(line.wind_from_deg)), float(line.wind_from_deg)]
			if line.get("snow_depth_cm") != null and float(line.snow_depth_cm) >= 0.5:  # "0 cm" is no snow: not shown
				wind += "   " + T.text("snow_depth", language) % float(line.snow_depth_cm)
			rows.append(["%s   %+.0f °C   %s%s%s" % [line.get("time", ""), float(line.get("temperature_c", 0.0)), T.weather(str(line.get("weather", "")), language), wind,
				"" if source == "generated" else "   (%s)" % T.text("weather_source_" + source, language)], 20, Color.WHITE])
	rows.append([T.text("press_any_key_start", language), 24, Color.WHITE])
	for row in rows:
		var label := Label.new()
		label.text = row[0]
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.add_theme_font_size_override("font_size", row[1])
		label.add_theme_color_override("font_color", row[2])
		lines.add_child(label)
	sign.set_anchors_preset(Control.PRESET_CENTER)
	sign.grow_horizontal = Control.GROW_DIRECTION_BOTH
	sign.grow_vertical = Control.GROW_DIRECTION_BOTH
	return sign


## FMI reports where wind comes from; the arrow points where it blows.
static func wind_arrow(wind_from_deg: float) -> String:
	var arrows := ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"]
	return arrows[int(round(fposmod(wind_from_deg + 180.0, 360.0) / 45.0)) % arrows.size()]


## One command to the simulation (it validates and applies it). The
## presses (F, G) go out once, in the next command only.
func send(controls: Dictionary) -> void:
	var outside: bool = entities.shown_state().get("on_foot", true)
	if outside:
		_engine_on = bool(entities.shown_state().get("player", {}).get("engine_on", _engine_on))
	var command := command_for(controls, _engine_on, _interact_pending, _refuel_pending, speed_limiter, red_light_assist,
		_road_rage_pending, lane_assist, _respawn_pending, _cancel_ride_pending, _reset_trip_pending, _home_pending)
	if outside or _interact_pending:
		command["engine_on"] = null
	command["language"] = language
	command["home_door"] = _home_door_pending
	# The inspect panel's subject: the simulation sends residents for it alone (protocol.py compact rows).
	command["inspect"] = {"kind": _focus["kind"], "id": _focus["id"]} if _focus.get("kind") in ["npc", "pedestrian"] and _focus.has("id") else null
	var view := get_viewport().get_canvas_transform().affine_inverse() * get_viewport().get_visible_rect()
	command["view_bounds"] = [view.position.x + entities.origin.x, entities.origin.y - view.end.y,
		view.end.x + entities.origin.x, entities.origin.y - view.position.y]
	_interact_pending = false
	_refuel_pending = false
	_road_rage_pending = false
	_respawn_pending = false
	_home_pending = false
	_home_door_pending = false
	_cancel_ride_pending = false
	_reset_trip_pending = false
	sim.send_command(command)


static func command_for(controls: Dictionary, engine_on: bool, interact: bool, refuel: bool,
		limiter := true, assist := false, road_rage := false, lane := false, respawn := false,
		cancel_ride := false, reset_trip := false, home := false) -> Dictionary:
	var command := {"speed_limiter_enabled": limiter, "red_light_assist_enabled": assist, "refuel": refuel, "road_rage": road_rage,
		"lane_assist_enabled": lane, "respawn": respawn, "home": home, "cancel_ride": cancel_ride, "reset_trip": reset_trip,
		"engine_on": engine_on, "interact": interact}
	command.merge(controls, true)
	return command


func _build_help() -> void:
	_help = PanelContainer.new()
	_help.visible = false
	_help.set_anchors_preset(Control.PRESET_CENTER)
	_help.position = Vector2(-390, -255)
	_help.custom_minimum_size = Vector2(780, 510)
	$Ui.add_child(_help)
	var text := Label.new()
	text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	text.add_theme_font_size_override("font_size", 18)
	text.text = T.text("controls_help", language)
	_help.add_child(text)


func _build_inspector() -> void:
	_inspect_panel = PanelContainer.new()
	_inspect_panel.visible = false
	_inspect_panel.custom_minimum_size = Vector2(320, 0)
	var style := StyleBoxFlat.new()
	style.bg_color = Color8(12, 20, 30, 242)
	style.border_color = Color8(255, 190, 80)
	style.set_border_width_all(2)
	style.set_corner_radius_all(6)
	style.set_content_margin_all(12)
	_inspect_panel.add_theme_stylebox_override("panel", style)
	$Ui.add_child(_inspect_panel)
	var rows := VBoxContainer.new()
	rows.name = "Rows"
	rows.add_theme_constant_override("separation", 8)
	_inspect_panel.add_child(rows)
	var back := Button.new()
	back.name = "Back"
	back.text = T.text("back_to_taxi", language)
	back.pressed.connect(_clear_focus)
	rows.add_child(back)
	_inspect_label = Label.new()
	_inspect_label.add_theme_font_size_override("font_size", 16)
	rows.add_child(_inspect_label)
	_inspect_panel.resized.connect(_position_inspector)
	get_viewport().size_changed.connect(_position_inspector)
	_position_inspector.call_deferred()


func _position_inspector() -> void:
	_inspect_panel.position = Vector2(maxf(8.0, get_viewport().get_visible_rect().size.x - _inspect_panel.size.x - 16.0), 54.0)


func _refresh_inspector(state: Dictionary) -> void:
	if _focus.is_empty() or _inspect_panel == null:
		return
	if _focus.get("kind") == "pan":
		_inspect_label.text = T.text("pan_view", language)
		return
	var key := "trains" if _focus["kind"] == "train" else "pedestrians" if _focus["kind"] == "pedestrian" else "npcs"
	for row in state.get(key, []):
		if row.get("id") == _focus["id"]:
			if _focus["kind"] == "train":
				_inspect_label.text = "%s\n%s\n%.0f km/h" % [str(row.get("label", row.get("id", ""))), T.value_label(row.get("state", ""), language), float(row.get("speed", 0.0)) * 3.6]
			else:
				_inspect_label.text = _character_text(_focus["kind"], row)
			return
	if _focus["kind"] == "pedestrian":
		for npc in state.get("npcs", []):
			for person in npc.get("occupants", []):
				if person.get("id") == _focus["id"]:
					_inspect_label.text = _character_text("pedestrian", {"id": _focus["id"], "resident": person, "state": T.text("in_vehicle", language)})
					return


func _character_text(kind: String, row: Dictionary) -> String:
	var unknown := T.text("unknown", language)
	if kind == "pedestrian":
		var resident: Dictionary = row.get("resident") if row.get("resident") is Dictionary else {}
		return "\n".join([
			"%s #%s" % [T.text("resident", language), row.get("id", "?")],
			str(resident.get("name", unknown)),
			"%s: %s" % [T.text("born", language), resident.get("birth_date", unknown)],
			"%s: %s" % [T.text("gender", language), T.value_label(resident.get("gender"), language)],
			"%s: %s" % [T.text("status", language), T.value_label(row.get("state"), language)],
			"%s: %s" % [T.text("activity", language), T.value_label(row.get("activity"), language)],
			"%s: %.2f ‰" % [T.text("blood_alcohol", language), float(row.get("blood_alcohol_promille", 0.0))],
		])
	var owner: Dictionary = row.get("owner") if row.get("owner") is Dictionary else {}
	var occupants := PackedStringArray()
	for person in row.get("occupants", []):
		if person is Dictionary:
			occupants.append(person.get("name", unknown))
	return "\n".join([
		"%s #%s" % [T.text("npc_vehicle", language), row.get("id", "?")],
		"%s: %s" % [T.text("type", language), T.value_label(row.get("vehicle_type"), language)],
		"%s: %s" % [T.text("status", language), T.value_label(row.get("state"), language)],
		"%s: %.0f km/h" % [T.text("speed", language), absf(float(row.get("speed", 0.0))) * 3.6],
		"%s: %s" % [T.text("owner", language), owner.get("name", unknown)],
		"%s: %s" % [T.text("occupants", language), ", ".join(occupants) if not occupants.is_empty() else unknown],
	])


func _apply_bench_hide() -> void:
	for name in _bench_hide:
		match name:
			"labels": labels.visible = false
			"precipitation": weather.precipitation.visible = false  # godot-final-06 attribution
			"ripples": weather.ripples.visible = false
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
			"ui": $Ui.visible = false
			"wildlife": wildlife.visible = false
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
	Perf.counters["nodes"] = Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	Perf.counters["drawn_entities"] = entities.drawn_entities
	var shown: Dictionary = entities.shown_state()
	Perf.counters["npcs"] = shown.get("npcs", []).size()
	Perf.counters["pedestrians"] = shown.get("pedestrians", []).size()
	Perf.counters["objects"] = Performance.get_monitor(Performance.OBJECT_COUNT)
	Perf.counters["canvas_items"] = Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME)
	Perf.counters["primitives"] = Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)
	Perf.counters["static_memory_mib"] = Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0


func _update_debug(state: Dictionary) -> void:
	_perf_counters()
	var f := Perf.summary()
	debug_label.text = "\n".join([
		"Road Rage Trip - %s   player %s" % [ProjectSettings.get_setting("application/config/version"), sim.player_id],
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
		_engine_on = true  # send() follows the stopped engine while the test driver is still outside
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
			"hud_money": hud_text["money"], "camera_follows": camera.position.distance_to(entities.player_position() + _lead) < 1.0,
			"state_ms": _state_usec / 1000.0, "interp_draw_ms": _interp_usec / 1000.0,
			"buffered_states": entities.buffer.size(), "underruns_6s": entities.buffer.underruns,
			"underrun_episodes": entities.buffer.underrun_episodes, "longest_underrun_ms": entities.buffer.longest_underrun_s * 1000.0,
			"max_state_gap_ms": entities.buffer.max_arrival_gap_s * 1000.0,
			"render_backsteps": entities.buffer.render_backsteps, "max_backstep_ms": entities.buffer.max_backstep_s * 1000.0,
			"taxi_off_centre_px": _max_camera_lag_px, "motion": _motion_stats(), "interp_delay_ms": entities.buffer.delay * 1000.0,
			"nightclubs_playing": nightclubs.playing_count(), "car_stereos_playing": car_stereos.playing_count(), "nightclubs_loaded": map_layer.nightclubs().size(), "nightclub_nearest_m": _nearest_nightclub_m(),
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
