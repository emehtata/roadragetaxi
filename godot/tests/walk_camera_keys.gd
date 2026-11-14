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
	press(game, KEY_3)
	check(game._windshield.visible and game.walk_eye and not game.walk_chase, "on foot 3: first person")
	check(not game.map_layer.buildings_3d.chase_on and game.entities.first_person, "on foot 3: eye camera, no own figure")
	press(game, KEY_2)
	check(not game._windshield.visible and not game.walk_eye and not game.walk_chase, "on foot 2: top-down")
	print("walk_camera_keys: %d failures" % failures)
	quit(1 if failures else 0)
