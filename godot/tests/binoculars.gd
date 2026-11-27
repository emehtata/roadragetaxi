## Run: godot --headless --path godot --script res://tests/binoculars.gd
## docs/specs/binoculars-fps-moon.md: O raises binoculars in outdoor first person; only the Camera3D FOV narrows.
extends SceneTree

const Binoculars := preload("res://binoculars.gd")

var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("_run")


func key(game: Node, code: Key, echo := false) -> void:
	var event := InputEventKey.new()
	event.pressed = true
	event.keycode = code
	event.echo = echo
	game._unhandled_input(event)


func wheel(game: Node, up: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_WHEEL_UP if up else MOUSE_BUTTON_WHEEL_DOWN
	event.pressed = true
	game._unhandled_input(event)


func set_state(game: Node, on_foot: bool) -> void:
	var walker := {"x": 0.0, "y": 0.0, "heading": 0.3, "facing": 0.3}
	var player := {"x": 0.0, "y": 0.0, "heading": 0.3, "speed": 0.0, "state": "PARKED"}
	var a := {"player": player, "player_pedestrian": walker, "on_foot": on_foot, "calendar": {}}
	game.entities._frame = {"a": a, "b": a, "t": 0.0}


var _tick := 0


## Real frames need real states: feed the buffer (a plain _frame is replaced every frame).
func run_frames(game: Node, seconds: float, on_foot := true) -> void:
	var walker := {"x": 0.0, "y": 0.0, "heading": 0.3, "facing": 0.3}
	var player := {"x": 0.0, "y": 0.0, "heading": 0.3, "speed": 0.0, "state": "PARKED"}
	var state := {"player": player, "player_pedestrian": walker, "on_foot": on_foot, "calendar": {}}
	var end := Time.get_ticks_msec() + int(seconds * 1000.0)
	while Time.get_ticks_msec() < end:
		_tick += 1
		game.entities.buffer.push(_tick, _tick / 30.0, state, game.entities.now())
		await process_frame


func settle(game: Node) -> void:
	for i in 30:  # long enough for the 0.2 s ease at any frame rate
		game._update_binoculars(0.02)


func _run() -> void:
	var game: Node = load("res://main.tscn").instantiate()
	root.add_child(game)
	await process_frame
	set_state(game, true)
	test_controls_and_ui_priority(game)
	test_optical_projection_and_aim(game)
	await test_camera_fov(game)
	await test_overlay_fit(game)
	test_restore_and_transitions(game)
	test_resource_lifecycle(game)
	print("binoculars: %d failures" % failures)
	quit(1 if failures else 0)


func test_controls_and_ui_priority(game: Node) -> void:
	check(InputMap.has_action(Binoculars.ACTION), "binoculars_toggle action bound")
	var o_event: InputEvent = InputMap.action_get_events(Binoculars.ACTION)[0]
	check(o_event is InputEventKey and o_event.keycode == KEY_O, "binoculars_toggle is O")
	var bino = game.binoculars
	key(game, KEY_1)  # on foot: the chase camera
	key(game, KEY_O)
	check(not bino.active, "chase view: O has no effect")
	key(game, KEY_2)
	key(game, KEY_O)
	check(not bino.active, "top-down view: O has no effect")
	key(game, KEY_3)
	check(game.walk_eye, "on foot 3: first person")
	game.phone.close()
	var zoom_before: float = game.camera.zoom.x
	wheel(game, true)
	check(game.camera.zoom.x > zoom_before, "without binoculars the wheel still zooms the map")
	game.camera.zoom = Vector2.ONE * zoom_before
	key(game, KEY_O)
	check(bino.active and bino.magnification() == 2.0, "on foot: O raises at 2x")
	key(game, KEY_O, true)
	check(bino.active, "key repeat does not retrigger O")
	var expected := [4.0, 6.0, 8.0, 8.0]
	for want: float in expected:
		wheel(game, true)
		check(bino.magnification() == want, "wheel up steps to %sx" % want)
	for want: float in [6.0, 4.0, 2.0, 2.0]:
		wheel(game, false)
		check(bino.magnification() == want, "wheel down steps to %sx" % want)
	key(game, KEY_KP_ADD)
	key(game, KEY_EQUAL)
	check(bino.magnification() == 6.0, "keypad + and = step up")
	key(game, KEY_MINUS)
	key(game, KEY_KP_SUBTRACT)
	check(bino.magnification() == 2.0, "- and keypad - step down")
	check(game.camera.zoom.x == zoom_before, "wheel and +/- never change the map zoom")
	# the phone owns its wheel and keys: nothing is consumed, nothing zooms
	game._lower_binoculars()
	game.phone.open()
	key(game, KEY_O)
	check(not bino.active, "phone open: O does not raise (the phone owns its input)")
	bino.raise(30.0)  # forced up: the phone still keeps the wheel and the keys
	wheel(game, true)
	key(game, KEY_EQUAL)
	check(bino.magnification() == 2.0 and game.camera.zoom.x == zoom_before, "phone open: wheel and + leave both zooms alone")
	game._lower_binoculars()
	game.phone.close()
	var field := LineEdit.new()
	game.add_child(field)
	field.grab_focus()
	if game.get_viewport().gui_get_focus_owner() == field:
		wheel(game, true)
		check(bino.magnification() == 2.0, "a focused text control keeps the wheel")
	field.queue_free()
	key(game, KEY_O)
	wheel(game, true)
	key(game, KEY_O)  # lowered, raised again
	key(game, KEY_O)
	check(bino.active and bino.magnification() == 2.0, "lowering and raising restarts at 2x")
	game._lower_binoculars()
	# driver eye
	set_state(game, false)
	key(game, KEY_3)
	check(game._windshield.visible and not game.walk_eye and not game.map_layer.buildings_3d.chase_on, "driver-eye view")
	key(game, KEY_O)
	check(bino.active, "driver-eye: O raises")
	game._lower_binoculars()
	key(game, KEY_1)
	key(game, KEY_O)
	check(not bino.active, "driver chase view: O has no effect")
	key(game, KEY_3)
	key(game, KEY_O)
	var before: Dictionary = game.drive.controls(false)
	wheel(game, true)
	check(game.drive.controls(false) == before, "zooming leaves the driving controls alone")
	game._lower_binoculars()


func test_optical_projection_and_aim(game: Node) -> void:
	for mag: float in [2.0, 4.0, 6.0, 8.0]:
		var want := rad_to_deg(2.0 * atan(tan(deg_to_rad(30.0) / 2.0) / mag))
		check(is_equal_approx(Binoculars.fov_for(30.0, mag), want), "FOV for %sx" % mag)
		check(is_equal_approx(tan(deg_to_rad(30.0) / 2.0) / tan(deg_to_rad(Binoculars.fov_for(30.0, mag)) / 2.0), mag), "tan ratio is %sx" % mag)
	var bino = Binoculars.new()
	bino.raise(30.0)
	for i in 20:
		bino.zoom(1)
	check(bino.magnification() == 8.0, "clamped at 8x")
	for i in 20:
		bino.zoom(-1)
	check(bino.magnification() == 2.0, "clamped at 2x")
	# easing: at most 0.2 s, monotonic, no overshoot, the same at any frame rate
	var coarse = Binoculars.new()
	var fine = Binoculars.new()
	for each in [coarse, fine]:
		each.raise(30.0)
		each.zoom(3)
	var target := Binoculars.fov_for(30.0, 8.0)
	var last := 30.0
	for i in 6:
		coarse.update(0.01)
		check(coarse.optical_fov() <= last + 1e-9 and coarse.optical_fov() >= target - 1e-9, "ease never overshoots")
		last = coarse.optical_fov()
	for i in 60:
		fine.update(0.001)
	check(is_equal_approx(coarse.shown_magnification(), fine.shown_magnification()), "easing is frame-rate independent")
	for i in 10:
		coarse.update(0.017)
	check(is_equal_approx(coarse.optical_fov(), target), "8x reached within 0.2 s (1x to 8x)")
	coarse.lower()
	for i in 20:
		coarse.update(0.017)
	check(coarse.optical_fov() == 0.0 and coarse.sensitivity_scale() == 1.0, "lowered: ordinary FOV and sensitivity")
	# the common projection enlarges a world target and a sky direction alike
	var camera := Camera3D.new()
	root.add_child(camera)
	camera.current = true
	camera.fov = 30.0
	var world_edge := Vector3(1.0, 0.5, -60.0)  # a building corner 60 m ahead
	var sky_edge := (Vector3(0.0, 0.0, -1.0) + Vector3(0.012, 0.006, 0.0)).normalized() * 900.0  # the Moon's limb, far away
	var centre := root.get_visible_rect().size / 2.0
	var base_world := camera.unproject_position(world_edge) - centre
	var base_sky := camera.unproject_position(sky_edge) - centre
	var eye := camera.global_position
	var aim := -camera.global_basis.z
	for mag: float in [2.0, 8.0]:
		camera.fov = Binoculars.fov_for(30.0, mag)
		var world_ratio := (camera.unproject_position(world_edge) - centre).x / base_world.x
		var sky_ratio := (camera.unproject_position(sky_edge) - centre).x / base_sky.x
		check(absf(world_ratio - mag) < 0.01 * mag, "world target grows %sx (%s)" % [mag, world_ratio])
		check(absf(sky_ratio - mag) < 0.01 * mag, "Moon/sky target grows %sx (%s)" % [mag, sky_ratio])
		check(camera.global_position == eye and (-camera.global_basis.z).is_equal_approx(aim), "projection moves neither eye nor aim")
	camera.queue_free()
	# mouse look: the same pixel turns the view 1/8 as far at 8x; the driver's aim is camera-only and bounded
	var look = Binoculars.new()
	look.raise(30.0)
	look.look(Vector2(100, 0), 0.002)
	var wide: float = look.yaw
	look.zoom(3)
	look.update(1.0)
	look.yaw = 0.0
	look.look(Vector2(100, 0), 0.002)
	check(is_equal_approx(look.yaw * 8.0, wide), "sensitivity scales by inverse magnification")
	look.look(Vector2(-1e6, -1e6), 0.002)
	check(is_equal_approx(look.yaw, deg_to_rad(135.0)) and is_equal_approx(look.pitch, deg_to_rad(80.0)), "driver aim limited to 135 deg yaw, 80 deg pitch")
	look.look(Vector2(1e6, 1e6), 0.002)
	check(is_equal_approx(look.yaw, -deg_to_rad(135.0)) and is_equal_approx(look.pitch, -deg_to_rad(80.0)), "driver aim limited both ways")


## The real game camera: FOV narrows to the formula, the eye and the aim stay put, nothing snaps to the Moon.
func test_camera_fov(game: Node) -> void:
	game.phone.close()
	set_state(game, true)
	key(game, KEY_1)
	key(game, KEY_3)
	await run_frames(game, 1.0)
	var layer = game.map_layer.buildings_3d
	var base_fov: float = layer._camera.fov
	var eye: Vector3 = layer._camera.global_position
	var aim: Vector3 = -layer._camera.global_basis.z
	var material: ShaderMaterial = layer._camera.environment.sky.sky_material
	var moon_before = material.get_shader_parameter("moon_dir")
	var yaw_before: float = game.look_yaw
	var pitch_before: float = game.look_pitch
	key(game, KEY_O)
	key(game, KEY_EQUAL)
	await run_frames(game, 0.5)
	check(is_equal_approx(layer._camera.fov, Binoculars.fov_for(base_fov, 4.0)), "camera FOV %s is the 4x formula for %s" % [layer._camera.fov, base_fov])
	check(layer._camera.global_position.is_equal_approx(eye) and (-layer._camera.global_basis.z).is_equal_approx(aim), "raising keeps eye and aim")
	check(game.look_yaw == yaw_before and game.look_pitch == pitch_before, "raising keeps the look angles")
	check(material.get_shader_parameter("moon_dir") == moon_before, "no Moon snapping")
	check(game.binoculars.overlay.visible and game.binoculars._label.text == "4×", "overlay shows 4x")
	key(game, KEY_O)
	await run_frames(game, 0.5)
	check(layer._camera.fov == base_fov, "lowering restores the exact FOV")
	check(not game.binoculars.overlay.visible, "overlay hidden when lowered")
	check(game.look_yaw == yaw_before, "lowering keeps the aim")


## The vignette, the magnification and the hint fit 640x360 and 1280x720 and leave the middle of the image clear.
func test_overlay_fit(game: Node) -> void:
	game.phone.close()
	key(game, KEY_1)
	key(game, KEY_3)
	await run_frames(game, 0.3)
	key(game, KEY_O)
	for size in [Vector2i(640, 360), Vector2i(1280, 720)]:
		root.size = size
		await run_frames(game, 0.3)
		var screen := Rect2(Vector2.ZERO, Vector2(root.get_visible_rect().size))
		var middle := Rect2(screen.size * 0.25, screen.size * 0.5)
		check(game.binoculars.active and game.binoculars.overlay.visible, "%s: overlay shown" % size)
		for label: Label in [game.binoculars._label, game.binoculars._hint]:
			var box := label.get_global_rect()
			check(label.text != "" and screen.encloses(box), "%s: %s fits (%s in %s)" % [size, label.text, box, screen])
			check(not box.intersects(middle), "%s: %s keeps the middle clear" % [size, label.text])
		var vignette: Rect2 = game.binoculars._vignette.get_global_rect()
		check(is_equal_approx(vignette.size.x, screen.size.x) and is_equal_approx(vignette.size.y, screen.size.y), "%s: vignette covers the view" % size)
		check(game.binoculars._vignette.texture.gradient.colors[0].a == 0.0, "%s: vignette is clear in the middle" % size)
	game._lower_binoculars()


func test_restore_and_transitions(game: Node) -> void:
	var bino = game.binoculars
	var layer = game.map_layer.buildings_3d
	var exits := {
		"camera switch": func(): key(game, KEY_1),
		"top-down": func(): key(game, KEY_2),
		"phone": func(): game.phone.open(),
		"help": func(): key(game, KEY_F1),
		"respawn": func(): key(game, KEY_R),
		"focus loss": func(): game._notification(NOTIFICATION_APPLICATION_FOCUS_OUT),
		"pause": func(): game.set_interior_paused(true),
		"session end": func(): game._on_connection(false),
		"summary": func(): game.summary_shown = true; game._update_binoculars(0.016),
		"building": func(): game.home_first_person.visible = true; game._update_binoculars(0.016),
		"enter taxi": func(): set_state(game, false); game._set_windshield(true),
		"leave taxi": func(): set_state(game, true); game._set_windshield(true, true),
	}
	for name: String in exits:
		set_state(game, true)
		game.summary_shown = false
		game.home_first_person.visible = false
		game.set_interior_paused(false)
		game.phone.close()
		game._help.visible = false
		key(game, KEY_3)
		var drive_before: Dictionary = game.drive.controls(true)
		key(game, KEY_O)
		wheel(game, true)
		wheel(game, true)
		settle(game)
		check(bino.active and bino.magnification() == 6.0 and layer.optical_fov > 0.0, "%s: raised at 6x" % name)
		var yaw: float = game.look_yaw
		exits[name].call()
		game._update_binoculars(0.016)
		check(not bino.active and bino.step == 0, "%s: binoculars down, back to 2x" % name)
		check(bino.optical_fov() == 0.0 and layer.optical_fov == 0.0, "%s: optical zoom cleared" % name)
		check(bino.sensitivity_scale() == 1.0 and not bino.overlay.visible, "%s: sensitivity and overlay restored" % name)
		check(game.look_yaw == yaw, "%s: aim kept" % name)
		check(game.drive.controls(true) == drive_before and game.walk_controls({"turn": 1.0}, 0.5).get("look_heading", 0.0) == 0.5, "%s: walking input unchanged" % name)
	game.summary_shown = false
	game.home_first_person.visible = false
	game.set_interior_paused(false)
	game._help.visible = false
	set_state(game, true)
	game.phone.close()
	key(game, KEY_3)
	key(game, KEY_O)
	check(game.binoculars.active and game.binoculars.magnification() == 2.0, "reopening starts at 2x")
	# the driver's seat: aim is camera-only and clears on lowering
	set_state(game, false)
	key(game, KEY_3)
	key(game, KEY_O)
	game.binoculars.yaw = 1.0
	game.binoculars.pitch = 0.4
	game._update_binoculars(0.016)
	check(is_equal_approx(layer.windshield_heading, 0.3 + 1.0) and is_equal_approx(layer.eye_pitch, 0.4), "driver aim turns only the camera")
	check(is_equal_approx(game.entities.player_body()["heading"], 0.3), "the taxi's heading is untouched")
	key(game, KEY_O)
	settle(game)
	check(not bino.active and bino.optical_fov() == 0.0, "driver: lowered")
	check(is_equal_approx(layer.windshield_heading, 0.3 + 1.0) and is_equal_approx(layer.eye_pitch, 0.4), "driver: lowering keeps the aim")
	key(game, KEY_O)
	check(bino.active and bino.yaw == 1.0 and bino.pitch == 0.4, "driver: raising keeps the aim")
	game._lower_binoculars()
	game._update_binoculars(0.016)
	check(is_equal_approx(layer.eye_pitch, 0.0) and bino.yaw == 0.0, "driver: an exit path (camera switch, pause, ...) clears the aim")


func count_nodes(of: Node, type: String) -> int:
	return of.find_children("*", type, true, false).size()


func test_resource_lifecycle(game: Node) -> void:
	var bino = game.binoculars
	set_state(game, true)
	game.phone.close()
	key(game, KEY_3)
	var view = game.map_layer.buildings_3d._view
	key(game, KEY_O)  # warm up
	wheel(game, true)
	settle(game)
	game._lower_binoculars()
	settle(game)
	var nodes := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	var resources := Performance.get_monitor(Performance.OBJECT_RESOURCE_COUNT)
	var viewports := count_nodes(root, "SubViewport")
	var cameras := count_nodes(root, "Camera3D")
	var zoom: float = game.camera.zoom.x
	var radius_before: float = game.map_layer.buildings_3d.FOV
	for i in 40:
		key(game, KEY_O)
		wheel(game, true)
		settle(game)
		root.size = Vector2i(640, 360) if i % 2 == 0 else Vector2i(1280, 720)
		game._on_connection(false) if i % 10 == 9 else game._lower_binoculars()
		key(game, KEY_3)
	game._lower_binoculars()
	check(Performance.get_monitor(Performance.OBJECT_NODE_COUNT) == nodes, "node count bounded over repeated raises")
	check(Performance.get_monitor(Performance.OBJECT_RESOURCE_COUNT) <= resources + 2, "resource count bounded over repeated raises")
	check(count_nodes(root, "SubViewport") == viewports and count_nodes(root, "Camera3D") == cameras, "no extra camera or SubViewport")
	check(game.map_layer.buildings_3d._view == view, "one outdoor viewport throughout")
	check(game.camera.zoom.x == zoom and game.map_layer.buildings_3d.FOV == radius_before, "map zoom and base FOV unchanged")
	check(bino.overlay.get_parent() == game._windshield and game._windshield.find_children("*", "Control", true, false).size() < 20, "overlay built once")
