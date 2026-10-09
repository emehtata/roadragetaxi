## --inputtest: drive with real key events (Input.parse_input_event, the
## path a keyboard takes) and record what the client sends and what the
## simulation does: the throttle in every command after W is released, and
## the taxi's speed. Scenarios from godot-08: hold and release, rapid taps,
## release then brake, steer while accelerating and release while turning,
## release while the window loses focus.
extends Node

var main: Node
var _t := 0.0
var _step := 0
var _step_t := 0.0
var _report := {}
var _speeds: Array = []  # speed samples after a release
var _stuck_commands := 0  # commands with throttle > 0 sent after a release
var _commands_after_release := 0
var _watching := ""  # scenario being measured after its release

const STEPS := [
	["board", 3.0],
	["hold_w", 3.0],
	["release_w", 2.5],
	["taps", 2.0],
	["after_taps", 2.0],
	["hold_w_turn", 2.0],
	["release_w_turning", 2.0],
	["hold_w_again", 2.0],
	["release_then_brake", 2.0],
	["hold_w_focus", 2.0],
	["focus_lost_release", 2.0],
	["done", 0.0],
]


func _key(code: Key, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)


func _process(delta: float) -> void:
	var state: Dictionary = main.entities.shown_state()
	if state.is_empty():
		return
	_t += delta
	_step_t += delta
	var name: String = STEPS[_step][0]
	if _watching != "":
		var sent: Dictionary = main.sim._last_command
		_commands_after_release += 1
		if sent.get("throttle", 0.0) > 0.0:
			_stuck_commands += 1
		_speeds.append(state["player"].get("speed", 0.0))
	if _step_t >= STEPS[_step][1]:
		_finish_step(name, state)
		_step += 1
		_step_t = 0.0
		_start_step(STEPS[_step][0], state)


func _start_step(name: String, state: Dictionary) -> void:
	match name:
		"hold_w", "hold_w_again", "hold_w_focus":
			_key(KEY_W, true)
		"release_w":
			_key(KEY_W, false)
			_watch()
		"taps":
			for i in 5:
				_key(KEY_W, true)
				_key(KEY_W, false)
		"after_taps":
			_watch()
		"hold_w_turn":
			_key(KEY_W, true)
			_key(KEY_A, true)
		"release_w_turning":
			_key(KEY_W, false)
			_watch()
		"release_then_brake":
			_key(KEY_W, false)
			_key(KEY_S, true)
			_watch()
		"focus_lost_release":
			# The window loses focus while W is down: Godot gets no key-up.
			main.get_viewport().get_window().propagate_notification(NOTIFICATION_APPLICATION_FOCUS_OUT)
			Input.flush_buffered_events()
			_watch()
		"done":
			_key(KEY_S, false)
			_key(KEY_A, false)
			print("INPUTTEST ", JSON.stringify(_report))
			get_tree().quit()
		"board":
			pass


func _watch() -> void:
	_watching = STEPS[_step][0]
	_speeds.clear()
	_stuck_commands = 0
	_commands_after_release = 0


func _finish_step(name: String, state: Dictionary) -> void:
	if name == "board":
		if state.get("on_foot", true):
			_key(KEY_F, true)
			_key(KEY_F, false)
			_step_t = 0.0
			_step -= 1  # try again
		return
	if _watching == name:
		# Throttle must be off in every command sent after the first 0.1 s
		# (one command interval); the speed must not grow after release.
		var growing := 0
		for i in range(1, _speeds.size()):
			growing += int(_speeds[i] > _speeds[i - 1] + 0.05)
		_report[name] = {"commands": _commands_after_release, "throttle_on": _stuck_commands,
			"speed_start": snappedf(_speeds[0] if not _speeds.is_empty() else 0.0, 0.01),
			"speed_end": snappedf(_speeds[-1] if not _speeds.is_empty() else 0.0, 0.01), "speed_rises": growing}
		_watching = ""
	elif name.begins_with("hold"):
		_report[name] = {"speed": snappedf(state["player"].get("speed", 0.0), 0.01),
			"throttle_sent": main.sim._last_command.get("throttle", 0.0)}
