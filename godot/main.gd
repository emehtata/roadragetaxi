## The Godot client: connects to the Python simulation (authoritative),
## draws what it sends, follows the player with the camera and sends the
## player's input as commands. No game rules here.
##
## Command line (after `--`): --host H --port P, and --selftest to drive the
## taxi for a few seconds headless and print a JSON report (CI / dev check).
extends Node2D

const COMMAND_INTERVAL_S := 0.05  # input -> simulation at 20 Hz, independent of the frame rate

@onready var sim: SimClient = $SimClient
@onready var map_layer: Node2D = $MapLayer
@onready var entities: Node2D = $EntityLayer
@onready var camera: Camera2D = $Camera
@onready var debug_label: Label = $Hud/Debug

var _world_info := ""
var _state: Dictionary = {}
var _tick := 0
var _states_received := 0
var _events: Array = []
var _command_timer := 0.0
var _interact_pending := false
var _engine_on := true

var _selftest := false
var _selftest_time := 0.0
var _selftest_start := Vector2.INF
var _last_interact := -10.0
var _screenshot_path := ""
var _screenshot_wait := 6.0
var _report := {}


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		match args[i]:
			"--host":
				sim.host = args[i + 1]
			"--port":
				sim.port = int(args[i + 1])
			"--selftest":
				_selftest = true
			"--screenshot":
				_screenshot_path = args[i + 1]
	sim.world_received.connect(_on_world)
	sim.state_received.connect(_on_state)
	sim.connection_changed.connect(func(up: bool): print("simulation ", "connected" if up else "disconnected"))


func _on_world(world: Dictionary) -> void:
	var started := Time.get_ticks_usec()
	var origin := Vector2(world["center"][0], world["center"][1])
	map_layer.set_world(world, origin)
	entities.origin = origin
	_world_info = "%d roads, %d railways, %d buildings" % [world["roads"].size(), world["railways"].size(), world["buildings"].size()]
	_report["world_roads"] = world["roads"].size()
	_report["world_load_ms"] = (Time.get_ticks_usec() - started) / 1000.0 + sim.parse_usec / 1000.0


func _on_state(message: Dictionary) -> void:
	var started := Time.get_ticks_usec()
	_state = message["state"]
	_tick = message["tick"]
	_states_received += 1
	entities.push_state(_state)
	for event in _state.get("events", []):
		_events.push_front(event)  # presentation (sound, UI) would hook in here
	_events.resize(min(_events.size(), 6))
	_report["state_update_ms"] = (Time.get_ticks_usec() - started) / 1000.0 + sim.parse_usec / 1000.0


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_F:
				_interact_pending = true
			KEY_E:
				_engine_on = not _engine_on
			KEY_EQUAL, KEY_KP_ADD:
				camera.zoom *= 1.25
			KEY_MINUS, KEY_KP_SUBTRACT:
				camera.zoom /= 1.25


func _key(a: Key, b: Key) -> float:
	return 1.0 if Input.is_physical_key_pressed(a) or Input.is_physical_key_pressed(b) else 0.0


func _process(delta: float) -> void:
	if _selftest:
		_run_selftest(delta)
	if _screenshot_path != "" and not _state.is_empty():
		_screenshot_wait -= delta
		if _screenshot_wait <= 0.0:
			get_viewport().get_texture().get_image().save_png(_screenshot_path)
			print("screenshot saved: ", _screenshot_path)
			get_tree().quit()
	camera.position = entities.player_position()
	_command_timer -= delta
	if _command_timer <= 0.0 and not _selftest:  # the self-test drives instead
		_command_timer = COMMAND_INTERVAL_S
		var up := _key(KEY_W, KEY_UP)
		var down := _key(KEY_S, KEY_DOWN)
		var left := _key(KEY_A, KEY_LEFT)
		var right := _key(KEY_D, KEY_RIGHT)
		var on_foot: bool = _state.get("on_foot", true)
		send({"throttle": 0.0 if on_foot else up, "brake": 0.0 if on_foot else down,
			"steer_left": 0.0 if on_foot else left, "steer_right": 0.0 if on_foot else right,
			"forward": up - down if on_foot else 0.0, "turn": left - right if on_foot else 0.0,
			"sprint": on_foot and Input.is_physical_key_pressed(KEY_SHIFT)})
	_update_debug()


## One command to the simulation (it validates and applies it).
func send(controls: Dictionary) -> void:
	var command := {"speed_limiter_enabled": true, "red_light_assist_enabled": false, "refuel": false,
		"engine_on": _engine_on, "interact": _interact_pending}
	command.merge(controls, true)
	_interact_pending = false
	sim.send_command(command)


func _update_debug() -> void:
	if _state.is_empty():
		debug_label.text = "Waiting for the simulation at %s:%d ..." % [sim.host, sim.port]
		return
	var minutes := int(_state["game_time_seconds"] / 60.0)
	var taxi: Dictionary = _state["taxi"]
	var lines := [
		"Road Rage Trip - Godot client 0.16.0g-alpha",
		"tick %d   game time %02d:%02d   %d fps   states %d" % [_tick, minutes / 60 % 24, minutes % 60, Engine.get_frames_per_second(), _states_received],
		"map: %s" % _world_info,
		"npcs %d   pedestrians %d   trains %d" % [_state["npcs"].size(), _state["pedestrians"].size(), _state["trains"].size()],
		"%s   speed %.0f km/h   balance %.2f EUR   fares %d" % ["on foot" if _state["on_foot"] else "driving", abs(_state["player"]["speed"]) * 3.6, taxi["balance_cents"] / 100.0, taxi["completed_fares"]],
		"weather %s   wetness %.0f%%" % [_state["weather"]["weather_type"], _state["weather"]["wetness"] * 100],
		"%s" % taxi["notification_msg"],
		"events: %s" % ", ".join(_events.map(func(e): return e.get("group", e["type"]))),
		"F enter/exit   WASD drive/walk   E engine   +/- zoom",
	]
	debug_label.text = "\n".join(lines)


## Headless check: get in, drive for 4 s, report what arrived and quit.
func _run_selftest(delta: float) -> void:
	_selftest_time += delta
	if _state.is_empty():
		if _selftest_time > 20.0:
			_finish({"ok": false, "error": "no state from the simulation"})
		return
	if _state["on_foot"]:
		if _selftest_time > 12.0:
			_finish({"ok": false, "error": "could not get into the taxi"})
		elif _selftest_time - _last_interact > 2.0:  # one F, then wait for the simulation's answer
			_last_interact = _selftest_time
			send({"interact": true})
		return
	var at := Vector2(_state["player"]["x"], _state["player"]["y"])
	if _selftest_start == Vector2.INF:
		_selftest_start = at
		_selftest_time = 0.0
	send({"throttle": 1.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
	if _selftest_time > 4.0:
		_report.merge({"ok": at.distance_to(_selftest_start) > 5.0, "driven_m": at.distance_to(_selftest_start),
			"states": _states_received, "trains": _state["trains"].size(), "npcs": _state["npcs"].size(),
			"on_foot": _state["on_foot"], "engine_on": _state["player"]["engine_on"], "speed_mps": _state["player"]["speed"],
			"camera_follows": camera.position.distance_to(entities.player_position()) < 1.0})
		_finish(_report)


func _finish(report: Dictionary) -> void:
	print("SELFTEST ", JSON.stringify(report))
	get_tree().quit(0 if report.get("ok", false) else 1)
