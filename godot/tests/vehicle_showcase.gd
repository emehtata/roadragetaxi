## Fixed vehicle lineup for visual review. Usage: -- /tmp/vehicles.png day|evening|night
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const EntityLayer := preload("res://entity_layer.gd")

func _initialize() -> void:
	call_deferred("capture")

func capture() -> void:
	var args := OS.get_cmdline_user_args()
	var output: String = args[0] if args.size() else "/tmp/vehicles.png"
	var light: String = args[1] if args.size() > 1 else "day"
	root.size = Vector2i(1400, 800)
	B3.use_shaded()
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 19.0
	camera.position = Vector3(12.0, 15.0, 24.0)
	root.add_child(camera)
	camera.look_at(Vector3(0.0, 0.6, 0.0))
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.29, 0.34, 0.39) * (0.3 if light == "night" else 0.65 if light == "evening" else 1.0)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.67, 0.75, 0.95) if light == "night" else Color.WHITE
	env.ambient_light_energy = 0.22 if light == "night" else 0.4 if light == "evening" else 0.7
	camera.environment = env
	camera.make_current()
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45.0, 25.0, 0.0)
	sun.light_energy = 0.08 if light == "night" else 0.5 if light == "evening" else 1.0
	root.add_child(sun)
	var rows := [
		["car", 4.4, 1.8, Color8(235, 177, 30), EntityLayer.CAR_SHAPES[0], 2],
		["car", 3.9, 1.7, Color8(55, 125, 180), EntityLayer.CAR_SHAPES[1], 0],
		["car", 4.8, 1.85, Color8(158, 55, 58), EntityLayer.CAR_SHAPES[2], 0],
		["car", 4.8, 1.9, Color8(80, 100, 94), EntityLayer.CAR_SHAPES[3], 0],
		["car", 4.7, 1.8, Color8(197, 201, 206), EntityLayer.CAR_SHAPES[5], 0],
		["car", 5.1, 2.0, Color8(185, 120, 49), EntityLayer.VAN_SHAPE, 0],
		["bus", 10.0, 2.5, Color8(222, 160, 58), [], 0],
		["truck", 8.0, 2.5, Color8(70, 115, 145), [], 0],
		["motorcycle", 2.1, 0.8, Color8(195, 47, 45), [], 0],
		["bicycle", 1.8, 0.6, Color8(62, 158, 102), [], 0],
	]
	for i in rows.size():
		var row: Array = rows[i]
		var arrays: Dictionary = B3.car_arrays(row[1], row[2], row[3], row[4], row[5], B3.LAMPS_ON) if row[0] == "car" else B3.vehicle_arrays(row[0], row[1], row[2], row[3], B3.LAMPS_ON, {})
		var mesh := B3._mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"])
		var node := B3._instance(mesh, B3._shared["car"], B3.LAYER_BUILDINGS)
		node.position = Vector3((i % 5 - 2) * 5.2, 0.0, (i / 5 - 0.5) * 8.0)
		node.rotation.y = 0.45 if i % 2 else -0.4
		root.add_child(node)
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(output)
	quit()
