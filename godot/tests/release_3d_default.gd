## The client starts in the 3D outdoor view with no flag; --outdoor-2d keeps the 2D view; 3 shows the driver-eye view, I does nothing driving.
## Run with `-- --outdoor-2d` (test_outdoor_2d_flag re-runs this script so) it only checks the 2D flag.
extends SceneTree

const MapChunk := preload("res://map_chunk.gd")
const Buildings3D := preload("res://buildings_3d.gd")
var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var game: Node = load("res://main.tscn").instantiate()
	root.add_child(game)
	await process_frame
	if "--outdoor-2d" in OS.get_cmdline_user_args():
		check(not MapChunk.outdoor_3d, "--outdoor-2d: outdoor_3d is false")
		quit(failures)
		return
	test_default_is_3d()
	test_camera_keys(game)
	test_outdoor_2d_flag()
	print("release_3d_default: %d failures" % failures)
	quit(1 if failures else 0)


func test_default_is_3d() -> void:
	check(MapChunk.outdoor_3d, "no args: outdoor_3d is true")
	check(Buildings3D.opaque, "no args: Buildings3D.opaque is true")


func test_camera_keys(game: Node) -> void:
	var player := {"x": 0.0, "y": 0.0, "heading": 0.0, "speed": 8.0, "state": "DRIVING"}
	game.entities._frame = {"a": {"player": player}, "b": {"player": player}, "t": 0.0}
	game.entities._frame["a"]["on_foot"] = false
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_I
	game._unhandled_input(key)
	check(not game._windshield.visible, "KEY_I driving: no windshield view")
	for code in [KEY_3, KEY_1, KEY_2]:
		key.keycode = code
		game._unhandled_input(key)
		check(game._windshield.visible == (code != KEY_2), "key %d: 3D view %s" % [code, code != KEY_2])
		check(game.map_layer.buildings_3d.chase_on == (code == KEY_1), "key %d: chase camera only on 1" % code)

func test_outdoor_2d_flag() -> void:
	var out := []
	var code := OS.execute(OS.get_executable_path(), ["--headless", "--path", ProjectSettings.globalize_path("res://"),
		"--script", "res://tests/release_3d_default.gd", "--", "--outdoor-2d"], out, true)
	check(code == 0, "--outdoor-2d run: %s" % "".join(out).right(2000))
