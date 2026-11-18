## Native GPU regression: production particles above sea-level and elevated terrain.
## Run with --script res://tests/snow_visibility_render.gd -- --out ABSOLUTE_DIR.
extends SceneTree
const P3 = preload("res://precipitation_3d.gd")
var failures := 0
var out := "res://../docs/visual-quality-corrections/snow-visibility/render"

func _initialize() -> void:
	for i in OS.get_cmdline_user_args().size() - 1:
		if OS.get_cmdline_user_args()[i] == "--out": out = OS.get_cmdline_user_args()[i + 1]
	test_visible_snow_at_ground_heights.call_deferred()

func check(ok: bool, what: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL ", what)

func test_visible_snow_at_ground_heights() -> void:
	root.size = Vector2i(640, 360)
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(out))
	var world := Node3D.new()
	root.add_child(world)
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.025, 0.035, 0.05)
	world.add_child(env)
	var camera := Camera3D.new()
	camera.fov = 40.0
	world.add_child(camera)
	camera.current = true
	var ground := MeshInstance3D.new()
	ground.mesh = PlaneMesh.new()
	ground.mesh.size = Vector2(180, 180)
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(0.08, 0.1, 0.13)
	ground.material_override = material
	world.add_child(ground)
	var roof := MeshInstance3D.new()
	roof.mesh = BoxMesh.new()
	roof.mesh.size = Vector3(12, 0.5, 20)
	roof.material_override = material
	world.add_child(roof)
	var p: Node3D = P3.new()
	world.add_child(p)
	p.particles.use_fixed_seed = true
	p.particles.seed = 139
	for height: float in [0.0, 70.0]:
		ground.position.y = height
		roof.position = Vector3(10, height + 4.0, -15)
		camera.position = Vector3(0, height + 1.35, 0)
		camera.look_at(Vector3(0, height + 1.35, -30))
		if "ground_elevation" in p: p.ground_elevation = height
		p.particles.speed_scale = 1.0
		p.set_weather("snow", 0.7, Vector2.ZERO)
		await create_timer(0.7).timeout
		var lit: int = await flake_pixels(p, "snow_%d" % height)
		check(lit >= 80, "visible snow shortly after setup/relocation above terrain at %s m (%s pixels)" % [height, lit])
		p.particles.speed_scale = 1.0
		p.set_weather("", 0.7, Vector2.ZERO)
		await process_frame
		p.set_weather("snow", 0.7, Vector2.ZERO)
		await create_timer(0.7).timeout
		lit = await flake_pixels(p, "reentry_%d" % height)
		check(lit >= 80, "clear/snow reentry fills visible volume at %s m (%s pixels)" % [height, lit])
	# A broad roof covers the complete visible landing area; its height field must stop flakes above the eye.
	roof.mesh.size = Vector3(180, 0.5, 180)
	roof.position = Vector3(0, 74, 0)
	p.collision.position.x += 0.01  # capture the newly added roof before restarting the weather
	await process_frame
	await RenderingServer.frame_post_draw
	p.particles.speed_scale = 1.0
	p.set_weather("", 0.7, Vector2.ZERO)
	p.set_weather("snow", 0.7, Vector2.ZERO)
	await create_timer(0.7).timeout
	var roof_pixels: int = await flake_pixels(p, "under_roof_70")
	check(roof_pixels <= 2, "height-field roof prevents snow below it (%s pixels)" % roof_pixels)
	world.free()
	print("SNOW_VISIBILITY_RENDER failures=", failures)
	quit(1 if failures else 0)


func flake_pixels(p: Node3D, label: String) -> int:
	p.particles.speed_scale = 0.0
	p.particles.visible = true
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var snow := root.get_texture().get_image()
	snow.save_png(out.path_join(label + ".png"))
	p.particles.visible = false
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var baseline := root.get_texture().get_image()
	baseline.save_png(out.path_join(label + "_clear.png"))
	var lit := 0
	var diff := Image.create(640, 360, false, Image.FORMAT_RGB8)
	for y in 360:
		for x in 640:
			var delta := snow.get_pixel(x, y).get_luminance() - baseline.get_pixel(x, y).get_luminance()
			if delta > 0.08: lit += 1
			diff.set_pixel(x, y, Color(maxf(delta, 0), maxf(delta, 0), maxf(delta, 0)))
	diff.save_png(out.path_join(label + "_flakes.png"))
	p.particles.visible = true
	print("SNOW_RENDER ",label," flake_pixels=",lit," emitter=",p.particles.global_position)
	return lit
