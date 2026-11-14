## Controlled close view of the client character meshes. Run with a PNG path and
## optional light level (day, evening, night) after --.
extends SceneTree
const B3 := preload("res://buildings_3d.gd")


func _initialize() -> void:
	call_deferred("capture")


func capture() -> void:
	var args := OS.get_cmdline_user_args()
	var output: String = args[0] if args.size() > 0 else "/tmp/characters.png"
	var light: String = args[1] if args.size() > 1 else "day"
	var group: String = args[2] if args.size() > 2 else "mixed"
	root.size = Vector2i(1280, 720)
	B3.use_shaded()
	var camera := Camera3D.new()
	root.add_child(camera)
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 3.2 if group == "close" else 10.5 if group == "wildlife" else 10.0
	camera.position = Vector3(0.0, 0.9, 10.0) if group == "legs" else Vector3(5.0, 3.7, 10.0)  # legs: from the side
	camera.look_at(Vector3(0.0, 0.9, 0.0))
	if group == "legs":
		camera.size = 3.4
	if group == "beards":  # docs/specs/male-facial-hair-and-arm-fix.md: three men's faces, beards 2, 3, 5
		camera.size = 1.6
		camera.position = Vector3(10.0, 1.6, 4.0)
		camera.look_at(Vector3(0.0, 1.4, 0.0))
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color(0.36, 0.42, 0.48) * (0.45 if light == "night" else 0.75 if light == "evening" else 1.0)
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.7, 0.76, 1.0) if light == "night" else Color.WHITE
	environment.ambient_light_energy = 0.2 if light == "night" else 0.35 if light == "evening" else 0.65
	camera.environment = environment
	camera.make_current()
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45.0, 20.0, 0.0)
	sun.light_energy = 0.08 if light == "night" else 0.5 if light == "evening" else 1.0
	root.add_child(sun)
	if light == "night":
		var lamp := OmniLight3D.new()
		lamp.position = Vector3(2.0, 4.0, 1.0)
		lamp.light_color = Color8(255, 205, 135)
		lamp.light_energy = 2.5
		lamp.omni_range = 12.0
		root.add_child(lamp)
	var people := [
		[Color8(70, 130, 240), "standing", 1.0, ""],
		[Color8(240, 200, 70), "walk_0", 1.0, ""],
		[Color8(230, 80, 80), "walk_1", 1.0, ""],
		[Color8(180, 80, 190), "walk_2", 1.0, ""],
		[Color8(60, 180, 100), "walk_3", 0.9, ""],
		[Color8(235, 176, 48), "run_4", 1.0, ""],
		[Color8(220, 220, 230), "sitting", 1.0, ""],
		[Color8(240, 140, 60), "standing", 1.1, ""],
	]
	if group == "legs":  # docs/specs/person-legs-walk-swing.md: two walk phases, procedural and GLB scooter riders
		people = [[Color8(230, 80, 80), "walk_1", 1.0, ""], [Color8(230, 80, 80), "walk_4", 1.0, ""]]
		add_mesh(B3.vehicle_arrays("e_scooter", 1.2, 0.5, Color8(60, 120, 220), 0, {"riding": true}), Vector3(0.3, 0.0, 0.0), 0.0)
		var model: Node3D = B3.MODEL_SCENES["e_scooter"].instantiate()
		root.add_child(model)
		model.transform = Transform3D(Basis(Vector3.UP, PI / 2.0).scaled_local(B3.model_scale("e_scooter", 1.2, 0.5)), Vector3(1.9, 0.0, 0.0))
		var rider := B3._empty_arrays()
		B3._rider(rider, -0.072, 0.168, B3.SCOOTER_RIDER_SEAT, Color8(60, 120, 220), Color8(236, 196, 160))
		B3._rider_legs(rider, -0.072, 0.168, B3.SCOOTER_RIDER_SEAT, B3.SCOOTER_DECK_Y, Color8(48, 58, 74))
		add_mesh(rider, Vector3(1.9, 0.0, 0.0), 0.0)
	if group == "beards":
		for i in 3:
			add_mesh(B3.person_arrays(people[i][0], "standing", 1.0, "", [0, 2, 6][i], false, 1, [2, 3, 5][i]), Vector3(0.0, 0.0, (i - 1) * 0.75), 0.3)
	for i in (0 if group in ["wildlife", "beards"] else 2 if group in ["close", "legs"] else people.size()):
		var row: Array = people[i]
		var arrays: Dictionary = B3.person_arrays(row[0], row[1], row[2], row[3], i + 1, group == "winter")
		add_mesh(arrays, Vector3(-1.9 + i * 1.1, 0.0, 0.0) if group == "legs" else Vector3((i - 0.5) * 1.3 if group == "close" else (i - 3.5) * 1.08, 0.0, 0.0 if group == "close" else -1.8), -0.55)
	var animals := [
		["moose", Color8(91, 67, 48), "stand", 0.65],
		["roe_deer", Color8(151, 104, 62), "walk_a", 1.0],
		["fox", Color8(194, 91, 38), "stand", 1.0],
		["dog", Color8(120, 90, 60), "feed", 1.0],
	]
	if group == "wildlife":
		animals = [["squirrel", Color8(144, 79, 38), "stand", 1.0], ["hare", Color8(142, 126, 101), "stand", 1.0],
			["small_bird", Color8(54, 49, 42), "stand", 1.0], ["pigeon", Color8(92, 99, 108), "stand", 1.0],
			["crow", Color8(42, 43, 45), "fly_1", 1.0], ["duck", Color8(120, 98, 72), "stand", 1.0],
			["gull", Color8(242, 243, 240), "fly_0", 1.0], ["fox", Color8(194, 91, 38), "stand", 1.0],
			["roe_deer", Color8(151, 104, 62), "stand", 1.0], ["moose", Color8(91, 67, 48), "stand", 0.65]]
	for i in (0 if group in ["close", "legs", "beards"] else animals.size()):
		var row: Array = animals[i]
		var arrays: Dictionary = B3.animal_arrays(row[0], row[1], row[2], row[3])
		add_mesh(arrays, Vector3((i % 5 - 2) * 1.8, 0.0, (i / 5 - 0.5) * 2.0) if group == "wildlife" else Vector3((i - 1.5) * 2.1, 0.0, 1.5), -0.3)
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(output)
	quit()


func add_mesh(arrays: Dictionary, at: Vector3, heading: float) -> void:
	var mesh := B3._mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"], true)
	var node := B3._instance(mesh, B3._shared["organic"], B3.LAYER_BUILDINGS)
	node.position = at
	node.rotation.y = heading
	root.add_child(node)
