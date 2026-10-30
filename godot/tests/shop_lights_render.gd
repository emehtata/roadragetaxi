## Render the production wall shader and sample every storefront window.
## godot --path godot --script res://tests/shop_lights_render.gd -- /tmp/shop
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
func _initialize() -> void:
	call_deferred("run")
func run() -> void:
	root.size = Vector2i(960, 240)
	var args := OS.get_cmdline_user_args()
	var prefix: String = args[0] if not args.is_empty() else "/tmp/shop-lights"
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 8.0
	root.add_child(camera)
	camera.position = Vector3(15, 3, -40)
	camera.look_at(Vector3(15, 3, 0))
	camera.make_current()
	var label := Label.new()
	var hud := CanvasLayer.new()
	hud.add_child(label)
	root.add_child(hud)
	var footprint := PackedVector2Array([Vector2(0, 0), Vector2(30, 0), Vector2(30, 10), Vector2(0, 10)])
	for scenario in [[1, 1.0, 4, "open-night"], [0, 1.0, 4, "closed-night"], [1, 0.0, 4, "open-day"], [1, 1.0, 2, "mixed-open-night"]]:
		var status: int = scenario[0]
		var category: int = scenario[2]
		var style := [[83, 86, 87], 0, 6.0, [], [139, 139, 137], 2, category, 0, status]
		var arrays := B3.build([footprint], [style], Vector2.ZERO)
		var instances := B3.meshes(arrays)
		for node in instances:
			root.add_child(node)
		B3._shared["material"].set_shader_parameter("ambient", Color(0.1, 0.12, 0.15) if scenario[1] > 0.5 else Color.WHITE)
		B3._shared["material"].set_shader_parameter("lit_level", scenario[1])
		label.text = "Mapped retail hours: " + scenario[3]
		for i in 5:
			await process_frame
		await RenderingServer.frame_post_draw
		var shot := root.get_texture().get_image()
		shot.save_png(prefix + "-" + scenario[3] + ".png")
		for w in 10:
			var at := camera.unproject_position(Vector3(1.5 + w * 3.0, 1.2, 0))
			var pixel := shot.get_pixel(int(at.x), int(at.y))
			assert((pixel.r > 0.8 and pixel.g > 0.8) if status == 1 else pixel.r < 0.3, "every shop window follows its mapped open/closed state")
		if category == 4:
			for w in 10:
				var at := camera.unproject_position(Vector3(1.5 + w * 3.0, 4.5, 0))
				assert(shot.get_pixel(int(at.x), int(at.y)).r < 0.8, "retail halls have no apartment windows above the storefront")
		else:
			var lit := 0
			for w in 10:
				var at := camera.unproject_position(Vector3(1.5 + w * 3.0, 4.5, 0))
				lit += int(shot.get_pixel(int(at.x), int(at.y)).r > 0.8)
			assert(lit < 10, "opening a shop must not light every apartment above it")
		for node in instances:
			node.free()
	print("SHOP LIGHTS: all 10 shop windows open/closed, day/night, plain retail upper walls and independent apartments passed")
	quit()
