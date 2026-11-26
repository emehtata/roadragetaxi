## Samples the actual sky shader: projected illuminated area and terminator curvature.
extends SceneTree

var failures := 0
var measurements := []

func check(ok: bool, text: String) -> void:
	if not ok:
		failures += 1
		push_error(text)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	if DisplayServer.get_name() == "headless":
		print("MOON_PHASE: native rendering required; run without --headless")
		quit(); return
	var view := SubViewport.new()
	view.size = Vector2i(384, 384)
	view.own_world_3d = true
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	var camera := Camera3D.new()
	view.add_child(camera)
	camera.fov = 3.0
	camera.look_at(Vector3(0, 1, -1))
	var material := ShaderMaterial.new()
	material.shader = load("res://sky_clouds.gdshader")
	material.set_shader_parameter("sky_top_color", Color.BLACK)
	material.set_shader_parameter("sky_horizon_color", Color.BLACK)
	material.set_shader_parameter("energy", 0.0)
	material.set_shader_parameter("coverage", 1.2)
	material.set_shader_parameter("moon_visible", 1.0)
	material.set_shader_parameter("moon_texture", load("res://assets/moon/2k_moon.jpg"))
	var moon := Vector3(0, 1, -1).normalized()
	material.set_shader_parameter("moon_dir", moon)
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	environment.sky = Sky.new()
	environment.sky.sky_material = material
	camera.environment = environment
	for phase in [0.0, 0.25, 0.5, 0.75, 0.95, 1.0]:
		for orientation in [0.0, PI, PI / 3.0]:
			var side := camera.global_basis.x * cos(orientation) + camera.global_basis.y * sin(orientation)
			material.set_shader_parameter("sun_dir", (moon * 0.4 + side * 0.9).normalized())
			material.set_shader_parameter("moon_illumination", phase)
			for i in 3: await process_frame
			await RenderingServer.frame_post_draw
			var image := view.get_texture().get_image()
			var radius := 384.0 * tan(acos(0.99985)) / (2.0 * tan(deg_to_rad(1.5)))
			var lit := 0
			var centroid := Vector2.ZERO
			var disk := 0
			var boundaries := []
			for y in 384:
				var row := -1
				for x in 384:
					if Vector2(x + 0.5 - 192, y + 0.5 - 192).length() > radius - 1: continue
					disk += 1
					var color := image.get_pixel(x, y)
					check(is_finite(color.r), "finite rendered moon")
					if color.r > 0.5:
						lit += 1
						centroid += Vector2(x + .5 - 192, 192 - y - .5)
						if row < 0: row = x
				if row >= 0 and absf(y - 192) < radius * 0.65: boundaries.append(row)
			if phase > 0.0 and phase < 1.0:
				check(centroid.dot(Vector2(cos(orientation),sin(orientation))) > 0, "bright side faces projected Sun")
			var fraction := float(lit) / disk
			measurements.append([phase, orientation, fraction])
			# 3.5 percentage points allows limb rasterization and the one-pixel interior sampling margin.
			check(absf(fraction - phase) < 0.035, "rendered lit fraction %.3f follows %.2f" % [fraction, phase])
			if orientation == 0.0 and phase in [0.25, 0.75, 0.95]:
				check(boundaries.max() - boundaries.min() > 8, "crescent/gibbous terminator is curved at %.2f" % phase)
	for aligned in [moon, -moon]:
		material.set_shader_parameter("sun_dir", aligned)
		for phase in [0.0, 1.0]:
			material.set_shader_parameter("moon_illumination", phase)
			for i in 3: await process_frame
			await RenderingServer.frame_post_draw
			var color := view.get_texture().get_image().get_pixel(192,192)
			check(is_finite(color.r) and (color.r > .5) == (phase == 1.0), "aligned full/new Moon remains stable")
	material.set_shader_parameter("sun_dir", moon)
	material.set_shader_parameter("moon_illumination", 1.0)
	for i in 3: await process_frame
	await RenderingServer.frame_post_draw
	var full_moon := view.get_texture().get_image()
	var texture_min := 1.0
	var texture_max := 0.0
	var radius := 384.0 * tan(acos(0.99985)) / (2.0 * tan(deg_to_rad(1.5)))
	var clipped := 0
	var interior := 0
	for y in 384:
		for x in 384:
			if Vector2(x + 0.5 - 192, y + 0.5 - 192).length() > radius * 0.6: continue
			var value := full_moon.get_pixel(x, y).r
			interior += 1
			clipped += int(value > 0.98)
			texture_min = minf(texture_min, value)
			texture_max = maxf(texture_max, value)
	check(texture_max - texture_min > 0.1, "the full Moon shows interior surface detail from its texture")
	check(float(clipped) / interior < 0.05, "the full Moon interior does not clip to white")
	material.set_shader_parameter("coverage", .125)
	for i in 3: await process_frame
	await RenderingServer.frame_post_draw
	check(view.get_texture().get_image().get_pixel(192,192).r < .1, "overcast hides lunar light")
	material.set_shader_parameter("coverage",1.2)
	material.set_shader_parameter("moon_visible",0.0)
	for i in 3: await process_frame
	await RenderingServer.frame_post_draw
	check(view.get_texture().get_image().get_pixel(192,192).r < .1, "below-horizon visibility hides Moon")
	view.free()
	print("MOON_PHASE failures=", failures, " samples=", JSON.stringify(measurements))
	quit(1 if failures else 0)
