## The player's driving/walking keys, owned by the client: set by key
## press/release events and cleared when the window or the application
## loses focus - the key-up of a key held while focus goes never arrives,
## and polling the engine's key state then kept the throttle on in every
## command until the key was pressed again (godot-08 "stuck accelerator").
## main.gd builds each command from this state.
class_name DriveInput
extends RefCounted

const UP := [KEY_W, KEY_UP]
const DOWN := [KEY_S, KEY_DOWN]
const LEFT := [KEY_A, KEY_LEFT]
const RIGHT := [KEY_D, KEY_RIGHT]
const SPRINT := [KEY_SHIFT]
const KEYS := UP + DOWN + LEFT + RIGHT + SPRINT

var _held: Dictionary = {}  # physical keycode -> true while down


## A key event; true when it is one of the driving keys.
func handle(event: InputEvent) -> bool:
	if not event is InputEventKey or event.is_echo():
		return false
	var code: Key = event.physical_keycode
	if not code in KEYS:
		return false
	if event.pressed:
		_held[code] = true
	else:
		_held.erase(code)
	return true


## Focus lost (or the connection reset): nothing is held any more.
func clear() -> void:
	_held.clear()


func held(keys: Array) -> float:
	for code in keys:
		if _held.has(code):
			return 1.0
	return 0.0


func any_held() -> bool:
	return not _held.is_empty()


## The command's control fields, as Pygame's main() builds PlayerCommand:
## driving keys drive the taxi, or walk the player when on foot.
func controls(on_foot: bool) -> Dictionary:
	var up := held(UP)
	var down := held(DOWN)
	var left := held(LEFT)
	var right := held(RIGHT)
	return {"throttle": 0.0 if on_foot else up, "brake": 0.0 if on_foot else down,
		"steer_left": 0.0 if on_foot else left, "steer_right": 0.0 if on_foot else right,
		"forward": up - down if on_foot else 0.0, "turn": left - right if on_foot else 0.0,
		"sprint": on_foot and held(SPRINT) > 0.0}
