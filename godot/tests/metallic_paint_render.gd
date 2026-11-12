## Render the four-wheelers' metallic paint (car.gdshader part 4) top-down
## under a sun ahead of them, as the outdoor 3D view sees them, and check
## the sheen: the roof glints on the sun's side, the far side is not black,
## and no roof is blown out into a band (a bus's long roof once was).
## godot --path godot --script res://tests/metallic_paint_render.gd -- /tmp/metal
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const EntityLayer := preload("res://entity_layer.gd")


func _initialize() -> void:
	call_deferred("run")


func run() -> void:
	root.size = Vector2i(1200, 400)
	var args := OS.get_cmdline_user_args()
	var prefix: String = args[0] if not args.is_empty() else "/tmp/metallic-paint"
	B3.use_shaded()
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 16.0
	camera.position = Vector3(0, 60, 0)
	camera.rotation_degrees.x = -90.0  # top-down, as the outdoor view
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.2, 0.2, 0.2)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color.WHITE
	env.ambient_light_energy = B3.AMBIENT_ENERGY
	env.sky = Sky.new()
	env.sky.sky_material = ProceduralSkyMaterial.new()
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	camera.environment = env
	root.add_child(camera)
	camera.make_current()
	var sun := DirectionalLight3D.new()
	sun.basis = B3.sun_basis(Vector3(1.0, tan(deg_to_rad(53.0)), 0.0).normalized())  # June noon height, ahead (+x) of every vehicle
	root.add_child(sun)
	var yellow := Color8(230, 170, 20)
	# [name, arrays, centre x, centre z, roof height, half length]
	var vehicles := [
		["car", B3.car_arrays(4.6, 1.8, yellow, EntityLayer.CAR_SHAPES[0], 0), -12.0, 0.0, 1.42, 2.3],
		["bus", B3.vehicle_arrays("bus", 12.0, 2.5, yellow, 0, {}), -3.0, 0.0, 3.0, 6.0],
		["truck", B3.vehicle_arrays("truck", 9.0, 2.5, yellow, 0, {}), 8.0, -3.5, 3.4, 4.5],
		["camper_van", B3.vehicle_arrays("camper_van", 6.0, 2.2, yellow, 0, {}), 8.0, 3.5, 2.6, 3.0],
	]
	for row in vehicles:
		var arrays: Dictionary = row[1]
		var mesh := B3._mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"])
		var node := B3._instance(mesh, B3._shared["car"], B3.LAYER_BUILDINGS)
		node.position = Vector3(row[2], 0.0, row[3])
		root.add_child(node)
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	shot.save_png(prefix + ".png")
	var luma := func(p: Color) -> float: return 0.299 * p.r + 0.587 * p.g + 0.114 * p.b
	var failures := []
	var glare := {}
	for row in vehicles:
		var name: String = row[0]
		var near := []  # paint luminance along the length (glass and black trim left out), sun half / far half
		var far := []
		var white := 0
		for k in 81:
			var along: float = row[5] * (k / 40.0 - 1.0)
			var at := camera.unproject_position(Vector3(row[2] + along, row[4], row[3]))
			var pixel := shot.get_pixel(int(at.x), int(at.y))
			var y: float = luma.call(pixel)
			if y < 0.12 or (pixel.b > pixel.r and y < 0.9):
				continue  # windows, the roof sign's frame
			(near if along > 0.0 else far).append(y)
			if y > 0.97:
				white += 1
		var mean := func(values: Array) -> float: return values.reduce(func(a, b): return a + b, 0.0) / maxi(1, values.size())
		var sun_side: float = mean.call(near)
		var far_side: float = mean.call(far)
		print("%s: sun half %.3f, far half %.3f" % [name, sun_side, far_side])
		if sun_side <= far_side + 0.02:
			failures.append("%s: the paint does not glint on the sun's side" % name)
		if far_side <= 0.25:
			failures.append("%s: the far side of the paint is too dark" % name)
		glare[name] = white * row[5] * 2.0 / 80.0  # metres of the length blown out
		print("%s: blown out over %.1f m" % [name, glare[name]])
	for name in glare:
		if glare[name] > 1.5:
			failures.append("%s: blown out over %.1f m - a band, not a glint" % [name, glare[name]])
	for failure in failures:
		printerr("FAIL: ", failure)
	print("metallic paint render: ", "ok" if failures.is_empty() else "%d failed" % failures.size())
	quit(1 if not failures.is_empty() else 0)
