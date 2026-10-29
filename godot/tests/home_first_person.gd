## Real CharacterBody3D movement in the generated interior's isolated physics world.
extends SceneTree

const View := preload("res://home_first_person.gd")
const Walk := preload("res://home_walk.gd")
var failures := 0

class Shell extends 'res://startup.gd':
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_ALWAYS
		_build_shell()

class Client extends SimClient:
	var reply: Dictionary
	var requests := 0
	func _process(_delta: float) -> void:
		pass
	func send_home_interior() -> bool:
		requests += 1
		home_plan = reply
		return true



func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var plans: Array = JSON.parse_string(FileAccess.get_file_as_string("res://tests/data/home_plans.json"))
	var view := View.new()
	root.add_child(view)
	var exterior := Camera2D.new()
	root.add_child(exterior)
	exterior.position = Vector2(17, 29)
	var original_camera := exterior.transform
	for plan in plans:
		check(view.enter(plan), str(plan["building_id"]) + ": safe spawn")
		if not view.visible:
			continue
		var player = view.player
		player.controls_enabled = false
		for i in 15:
			await physics_frame
		check(player.is_on_floor() and absf(player.position.y) < 0.03, "gravity settles capsule on floor")
		var shape := PhysicsShapeQueryParameters3D.new()
		shape.shape = player.get_child(0).shape
		shape.transform = player.global_transform * player.get_child(0).transform
		shape.exclude = [player.get_rid()]
		# Move slightly up so resting floor contact is not counted as wall penetration.
		shape.transform.origin.y += 0.02
		check(player.get_world_3d().direct_space_state.intersect_shape(shape).is_empty(), "spawn capsule clears walls and lintel")
		view.leave()
		check(view.get_child_count() == 0 and view.player == null, "exit releases world and controller")
	check(view.enter(plans[0]), "movement test enters")
	var p = view.player
	p.controls_enabled = false
	p.set_physics_process(false)
	await physics_frame
	await physics_frame
	var hall: Array = plans[0]["rooms"][0]["label_at"]
	for direction in [Vector2(1, 0), Vector2(-1, 0), Vector2(0, 1), Vector2(0, -1), Vector2(1, 1)]:
		p.position = Vector3(hall[0], 0.01, -hall[1])
		p.rotation.y = 0
		p.velocity = Vector3.ZERO
		var before: Vector3 = p.position
		p.walk(direction, 1.0 / 60)
		var travelled: float = Vector2(p.position.x - before.x, p.position.z - before.z).length()
		check(absf(travelled - p.walking_speed / 60.0) < 0.005, "all four directions and diagonal have equal horizontal speed")
	p.look(Vector2(100, 10000))
	check(p.rotation.y < 0 and is_equal_approx(p.head.rotation.x, deg_to_rad(-85)), "mouse yaw and lower pitch clamp")
	p.look(Vector2(0, -20000))
	check(is_equal_approx(p.head.rotation.x, deg_to_rad(85)) and p.rotation.z == 0, "upper pitch clamp and no roll")
	p.position = Vector3(hall[0], 0.01, -hall[1])
	p.rotation.y = PI / 2.0
	p.velocity = Vector3.ZERO
	var facing_start: Vector3 = p.position
	p.walk(Vector2(0, -1), 1.0 / 60)
	check(p.position.x < facing_start.x and absf(p.position.z - facing_start.z) < 0.001, "forward follows yaw, not camera pitch")
	# Walk through every internal door, and then drive into its adjacent solid wall.
	for door in plans[0]["doors"]:
		if int(door["rooms"][0]) == -1:
			continue
		var a := Vector2(door["points"][0][0], door["points"][0][1])
		var b := Vector2(door["points"][1][0], door["points"][1][1])
		var middle := (a + b) / 2.0
		var n := (b - a).orthogonal().normalized()
		p.rotation.y = 0
		p.velocity = Vector3.ZERO
		p.position = Vector3(middle.x - n.x * 0.7, 0.01, -middle.y + n.y * 0.7)
		for i in 30:
			p.walk(Vector2(n.x, -n.y), 1.0 / 60)
		check((Vector2(p.position.x, -p.position.z) - middle).dot(n) > 0.6, "capsule walks through internal door")
		var solid := middle + (b - a).normalized() * 1.0
		p.position = Vector3(solid.x - n.x * 0.7, 0.01, -solid.y + n.y * 0.7)
		p.velocity = Vector3.ZERO
		for i in 30:
			p.walk(Vector2(n.x, -n.y), 1.0 / 60)
		check((Vector2(p.position.x, -p.position.z) - solid).dot(n) < -0.3, "solid wall stops capsule")
	var entrance := Walk.front_door(plans[0])
	var inward: Vector2 = entrance["inward"]
	var inside: Vector2 = entrance["middle"] + inward * 0.6
	p.position = Vector3(inside.x, 0.01, -inside.y)
	p.rotation.y = 0
	p.velocity = Vector3.ZERO
	for i in 40:
		p.walk(Vector2(-inward.x, inward.y), 1.0 / 60)
	check((Vector2(p.position.x, -p.position.z) - entrance["middle"]).dot(inward) > 0.25 and p.position.y > -0.02, "front door threshold prevents falling into the exterior void")
	view.capture_mouse()
	if DisplayServer.get_name() != "headless":
		check(Input.mouse_mode == Input.MOUSE_MODE_CAPTURED, "entry captures cursor")
	view.set_paused(true)
	check(not p.controls_enabled and Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "pause releases cursor and movement")
	view.set_paused(false)
	check(p.controls_enabled, "resume restores exploration")
	view._notification(NOTIFICATION_APPLICATION_FOCUS_OUT)
	check(not p.controls_enabled, "focus loss stops movement")
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	check(view.handle_input(click) and p.controls_enabled, "click recaptures after focus loss")
	view.leave()
	check(Input.mouse_mode == Input.MOUSE_MODE_VISIBLE and exterior.transform == original_camera, "exit restores cursor and preserves exterior camera")
	var invalid: Dictionary = plans[0].duplicate(true)
	invalid["footprint"] = [[100, 100], [101, 100], [101, 101], [100, 101]]
	check(not view.enter(invalid) and not view.visible, "invalid spawn fails without leaving resources")
	check(view.get_child_count() == 0, "failed entry leaves no world")
	var old := Walk.new()
	root.add_child(old)
	check(old.enter(plans[0]) and old.fits(old.at), "2D walking remains available")
	old.free()
	view.free()
	exterior.free()
	# Exercise the game's actual entry, input, pause and mode-selection paths.
	var shell := Shell.new()
	root.add_child(shell)
	var game = load("res://main.tscn").instantiate()
	game.get_node("SimClient").set_script(Client)
	shell._game = game
	shell.add_child(game)
	shell._panel.visible = false
	game.set_process(false)
	game.sim.reply = plans[0]
	game.set_interior_options(true, 0.003)
	var state := {"home_door": {"indoors": true, "is_home": true}}
	game._home_view(state)
	check(game.sim.requests == 1, "entry requests the selected house's plan")
	game._home_view(state)
	check(game.home_first_person.visible and not game.home_walk.visible, "game enters optional first-person mode")
	var key := InputEventKey.new()
	key.physical_keycode = KEY_W
	key.keycode = KEY_W
	key.pressed = true
	Input.parse_input_event(key)
	Input.flush_buffered_events()
	check(Input.is_action_pressed("interior_forward"), "W uses the indoor Input Map action")
	game._input(key)
	var release := key.duplicate()
	release.pressed = false
	Input.parse_input_event(release)
	Input.flush_buffered_events()
	check(not game.drive.any_held(), "indoor movement does not reach exterior driving")
	game.set_interior_paused(true)
	check(not game.home_first_person.player.controls_enabled, "game pause stops controller")
	game.set_interior_paused(false)
	check(game.home_first_person.player.controls_enabled, "game resume restores controller")
	if DisplayServer.get_name() != "headless":
		shell._pause_menu()
		check(paused and Input.mouse_mode == Input.MOUSE_MODE_VISIBLE and not game.home_first_person.player.can_process(), "Escape menu releases cursor and pauses physics")
		shell._pause_menu()  # returning from settings rebuilds the same menu
		shell._resume()
		check(not paused and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED, "menu resume recaptures cursor after navigating settings")
	key = InputEventKey.new()
	key.keycode = KEY_E
	key.pressed = true
	game._unhandled_input(key)
	check(game._home_door_pending, "E at entrance requests the existing server exit")
	game._home_view({"home_door": {"indoors": false}})
	check(not game.home_first_person.visible and game.home_first_person.get_child_count() == 0, "server exit tears down the 3D view")
	game.sim.reply = plans[4]
	game.set_interior_options(false, 0.003)
	game._home_view(state)
	game._home_view(state)
	check(game.sim.requests == 2 and game.home_walk.visible and game.home_walk.plan == plans[4], "2D selection works and a different house uses a fresh plan")
	game._home_view({"home_door": {"indoors": false}})
	game.set_interior_options(true, 0.002)
	game.sim.reply = invalid
	game._home_view(state)
	game._home_view(state)
	check(game.home_walk.visible and not game.home_first_person.visible and game.home_walk.notice != "", "unsafe 3D spawn falls back to 2D with a visible notice")
	game._home_view({"home_door": {"indoors": false}})
	game.sim.reply = plans[0]
	game._home_view(state)
	game._home_view(state)
	game._on_connection(false)
	check(not game.home_first_person.visible and game.home_first_person.player == null, "disconnect releases interior and mouse")
	# Drain the real game's opening phone sound before shutting down the audio mixer.
	for voice in game.audio.get_children():
		if voice is AudioStreamPlayer or voice is AudioStreamPlayer2D:
			voice.stop()
	await physics_frame
	await physics_frame
	shell._game = null
	game.queue_free()
	shell.queue_free()
	await process_frame
	print("HOME_FIRST_PERSON: %d plans, %d failures" % [plans.size(), failures])
	quit(1 if failures else 0)
