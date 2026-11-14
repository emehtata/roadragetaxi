## Run: godot --headless --path godot --script res://tests/walk_camera_keys.gd
## docs/specs/walk-third-person.md: on foot 1 is the walker chase, 3 first person, 2 top-down.
extends SceneTree

var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("_run")


func press(game: Node, code: Key) -> void:
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = code
	game._unhandled_input(key)


func _run() -> void:
	var game: Node = load("res://main.tscn").instantiate()
	root.add_child(game)
	await process_frame
	var walker := {"x": 0.0, "y": 0.0, "heading": 0.0, "facing": 0.0}
	var player := {"x": 0.0, "y": 0.0, "heading": 0.0, "speed": 0.0, "state": "PARKED"}
	var a := {"player": player, "player_pedestrian": walker, "on_foot": true}
	game.entities._frame = {"a": a, "b": a, "t": 0.0}
	press(game, KEY_1)
	check(game._windshield.visible and game.map_layer.buildings_3d.chase_on, "on foot 1: chase camera")
	check(not game.walk_eye and game.walk_chase, "on foot 1: walk_chase, not walk_eye")
	check(not game.entities.first_person, "on foot 1: own figure drawn")
	check(Input.mouse_mode != Input.MOUSE_MODE_CAPTURED, "on foot 1: mouse free")
	test_chase_captures_mouse_and_phone_releases(game)
	test_wheel_zooms_chase_not_when_phone_open(game)
	press(game, KEY_3)
	check(game._windshield.visible and game.walk_eye and not game.walk_chase, "on foot 3: first person")
	check(not game.map_layer.buildings_3d.chase_on and game.entities.first_person, "on foot 3: eye camera, no own figure")
	press(game, KEY_2)
	check(not game._windshield.visible and not game.walk_eye and not game.walk_chase, "on foot 2: top-down")
	print("walk_camera_keys: %d failures" % failures)
	quit(1 if failures else 0)


## docs/specs/3rd-person-mouse.md: third person wants the mouse; the phone frees it.
func test_chase_captures_mouse_and_phone_releases(game: Node) -> void:
	game.phone.close()
	check(game.chase_mouse_wanted(), "chase, phone closed: mouse captured")
	check(not game.chase_mouse_wanted(true), "chase, menu open: mouse free")
	game.phone.open()
	check(not game.chase_mouse_wanted(), "chase, phone open: mouse free")
	check(Input.mouse_mode != Input.MOUSE_MODE_CAPTURED, "phone open: MOUSE_MODE_VISIBLE")
	var motion := InputEventMouseMotion.new()
	motion.relative = Vector2(200, 0)
	game._input(motion)
	check(game.camera_modes.orbit_yaw == 0.0, "phone open: motion does not orbit")
	game.phone.close()
	check(game.chase_mouse_wanted(), "phone closed again: recaptured")
	check(InputMap.has_action("camera_reset"), "camera_reset action bound")


func test_wheel_zooms_chase_not_when_phone_open(game: Node) -> void:
	var wheel := InputEventMouseButton.new()
	wheel.button_index = MOUSE_BUTTON_WHEEL_UP
	wheel.pressed = true
	game.phone.close()
	var before: float = game.camera_modes.zoom_walk
	game._unhandled_input(wheel)
	check(game.camera_modes.zoom_walk < before, "wheel up in third person: closer target")
	var mid: float = game.camera_modes.zoom_walk
	game.phone.open()
	game._unhandled_input(wheel)
	check(game.camera_modes.zoom_walk == mid, "phone open: wheel leaves the distance")
	game.phone.close()
	var esc := InputEventKey.new()
	esc.keycode = KEY_ESCAPE
	esc.pressed = true
	game._input(esc)
	game._unhandled_input(wheel)
	check(game.camera_modes.zoom_walk == mid, "cursor freed by Esc: wheel leaves the distance")
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	game._input(click)
	game._unhandled_input(wheel)
	check(game.camera_modes.zoom_walk < mid, "click recaptures: wheel zooms again")
	game._input(esc)
	game.phone.open()
	check(not game._chase_captured(), "phone open: cursor free")
	game.phone.close()
	check(game._chase_captured(), "phone closed: cursor recaptured")
	game.set_interior_paused(true)
	check(not game._chase_captured(), "menu open: cursor free")
	game.set_interior_paused(false)
	check(game._chase_captured(), "menu closed: cursor recaptured")
