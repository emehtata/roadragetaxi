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

@onready var sim: SimClient = $SimClient
@onready var map_layer: Node2D = $MapLayer
@onready var entities: Node2D = $EntityLayer
@onready var camera: Camera2D = $Camera
@onready var audio: AudioManager = $Audio
@onready var hud: Control = $Ui/Hud
@onready var debug_label: Label = $Ui/Debug

var _tick := 0
var _states_received := 0
var _recent_events: Array = []
var _command_timer := 0.0
var _interact_pending := false
var _engine_on := true
var _state_usec := 0.0  # handling one state (parse + buffer), smoothed
var _interp_usec := 0.0  # sampling + blending one frame, smoothed

var _selftest := false
var _selftest_time := 0.0
var _selftest_start := Vector2.INF
var _last_interact := -10.0
var _screenshot_path := ""
var _screenshot_wait := 6.0
var _report := {}
var _fps_samples: Array = []
var events_presented := 0
var _audiotest := false
var override_night := -1.0  # >= 0: presentation override for the audio test (never sent to Python)
var override_rain := -1.0


func _ready() -> void:
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
			"--audiotest":
				_audiotest = true
			"--screenshot":
				_screenshot_path = args[i + 1]
	sim.world_received.connect(_on_world)
	sim.state_received.connect(_on_state)
	sim.chunk_received.connect(func(message: Dictionary): map_layer.add_chunk(message))
	sim.chunk_unloaded.connect(func(chunk_id: String): map_layer.remove_chunk(chunk_id))
	sim.connection_changed.connect(_on_connection)
	if _audiotest:
		var tester: Node = preload("res://audio_test.gd").new()
		tester.main = self
		var at := args.find("--audiotest")
		if at + 1 < args.size() and not args[at + 1].begins_with("--"):
			tester.out_path = args[at + 1]
		add_child(tester)


func _on_connection(up: bool) -> void:
	print("simulation ", "connected" if up else "disconnected")
	if not up:  # a new connection starts over: header, chunks, states
		entities.buffer.clear()
		map_layer.clear()
		audio.stop_loops()


func _on_world(world: Dictionary) -> void:
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
			KEY_E:
				_engine_on = not _engine_on
			KEY_F3:
				debug_label.visible = not debug_label.visible
			KEY_EQUAL, KEY_KP_ADD:
				camera.zoom *= 1.25
			KEY_MINUS, KEY_KP_SUBTRACT:
				camera.zoom /= 1.25


func _key(a: Key, b: Key) -> float:
	return 1.0 if Input.is_physical_key_pressed(a) or Input.is_physical_key_pressed(b) else 0.0


func _process(delta: float) -> void:
	var state: Dictionary = entities.shown_state()
	_interp_usec = lerpf(_interp_usec, float(entities.interp_usec), 0.1)
	if _selftest:
		_run_selftest(delta, state)
	if _screenshot_path != "" and not state.is_empty():
		_screenshot_wait -= delta
		if _screenshot_wait <= 0.0:
			get_viewport().get_texture().get_image().save_png(_screenshot_path)
			print("screenshot saved: ", _screenshot_path)
			get_tree().quit()
	camera.position = entities.player_position()
	_present(state)
	_command_timer -= delta
	if _command_timer <= 0.0 and not _selftest and not _audiotest:  # the tests drive instead
		_command_timer = COMMAND_INTERVAL_S
		var up := _key(KEY_W, KEY_UP)
		var down := _key(KEY_S, KEY_DOWN)
		var left := _key(KEY_A, KEY_LEFT)
		var right := _key(KEY_D, KEY_RIGHT)
		var on_foot: bool = state.get("on_foot", true)
		send({"throttle": 0.0 if on_foot else up, "brake": 0.0 if on_foot else down,
			"steer_left": 0.0 if on_foot else left, "steer_right": 0.0 if on_foot else right,
			"forward": up - down if on_foot else 0.0, "turn": left - right if on_foot else 0.0,
			"sprint": on_foot and Input.is_physical_key_pressed(KEY_SHIFT)})


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
		audio.handle_event(event)
		events_presented += 1
		_recent_events.push_front(event.get("group", event.get("type", "?")))
	_recent_events.resize(min(_recent_events.size(), 6))
	var driving: bool = not state.get("on_foot", true) and state["player"].get("engine_on", false)
	var speed: float = absf(state["player"].get("speed", 0.0))
	audio.set_loop("engine", 0.6 if driving else 0.0, minf(1.0 + speed / 25.0, 2.2))
	var night := _night(state.get("game_time_seconds", 12.0 * 3600.0)) if override_night < 0.0 else override_night
	audio.set_loop("city_day", 0.5 * (1.0 - night))
	audio.set_loop("city_night", 0.5 * night)
	var raining: bool = state.get("weather", {}).get("weather_type", "") == "rain"
	audio.set_loop("rain", (0.6 if raining else 0.0) if override_rain < 0.0 else override_rain)
	_train_loop(state)
	hud.show_state(state)
	if debug_label.visible:
		_update_debug(state)


## The nearest moving train rumbles from where it is (Pygame mixes the
## loudest intercity and commuter train as two layers; one is enough here).
func _train_loop(state: Dictionary) -> void:
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


## One command to the simulation (it validates and applies it).
func send(controls: Dictionary) -> void:
	var command := {"speed_limiter_enabled": true, "red_light_assist_enabled": false, "refuel": false,
		"engine_on": _engine_on, "interact": _interact_pending}
	command.merge(controls, true)
	_interact_pending = false
	sim.send_command(command)


func _update_debug(state: Dictionary) -> void:
	debug_label.text = "\n".join([
		"Road Rage Trip - Godot client 0.16.0g-alpha   player %s" % sim.player_id,
		"tick %d   %d fps   states %d   buffered %d   delay %d ms   underruns %d" % [_tick, Engine.get_frames_per_second(),
			_states_received, entities.buffer.size(), entities.buffer.delay * 1000, entities.buffer.underruns],
		"state %.2f ms   interpolate+draw %.2f ms   map chunks %d   drawn %d" % [_state_usec / 1000.0, _interp_usec / 1000.0,
			map_layer.chunk_count(), entities.drawn_entities],
		"npcs %d   pedestrians %d   trains %d" % [state["npcs"].size(), state["pedestrians"].size(), state["trains"].size()],
		"sounds played %d   no sound for %s" % [audio.played, ", ".join(audio.unhandled.keys())],
		"events: %s" % ", ".join(_recent_events),
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
		entities.buffer.underruns = 0  # count from here: steady state, not the connect burst
	send({"throttle": 1.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
	_fps_samples.append(1.0 / maxf(delta, 0.0001))
	if _selftest_time > 6.0:
		var hud_text: Dictionary = hud.values(state)
		_report.merge({"ok": at.distance_to(_selftest_start) > 5.0 and map_layer.chunk_count() > 0,
			"driven_m": at.distance_to(_selftest_start), "states": _states_received,
			"trains": state["trains"].size(), "npcs": state["npcs"].size(), "pedestrians": state["pedestrians"].size(),
			"drawn_entities": entities.drawn_entities, "map_chunks": map_layer.chunk_count(),
			"on_foot": state["on_foot"], "speed_mps": state["player"]["speed"], "hud_speed": hud_text["speed"],
			"hud_money": hud_text["money"], "camera_follows": camera.position.distance_to(entities.player_position()) < 1.0,
			"state_ms": _state_usec / 1000.0, "interp_draw_ms": _interp_usec / 1000.0,
			"buffered_states": entities.buffer.size(), "underruns_6s": entities.buffer.underruns,
			"fps_mean": _fps_samples.reduce(func(a, b): return a + b, 0.0) / _fps_samples.size(),
			"sounds_played": audio.played, "engine_loop": audio.loop_playing("engine"), "unhandled_events": audio.unhandled,
			"static_memory_mib": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
			"player_id": sim.player_id})
		_finish(_report)


func _finish(report: Dictionary) -> void:
	print("SELFTEST ", JSON.stringify(report))
	get_tree().quit(0 if report.get("ok", false) else 1)
