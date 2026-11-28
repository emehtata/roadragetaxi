## docs/planet-sky.md: Mercury..Uranus in the sky shader. The rules and the lifecycle run headless; the pixel
## test samples the actual sky shader and needs a native (non-headless) run.
extends SceneTree

const PlanetSky := preload("res://planet_sky.gd")
const SIZE := Vector2i(640, 360)
var failures := 0
var view: SubViewport
var camera: Camera3D
var material: ShaderMaterial


func check(ok: bool, text: String) -> void:
	if not ok:
		failures += 1
		push_error(text)


func _initialize() -> void:
	call_deferred("run")


func run() -> void:
	rules()
	await test_shared_resource_lifecycle()
	if DisplayServer.get_name() == "headless":
		print("PLANET_SKY: pixel test needs native rendering; run without --headless")
	else:
		await test_projection_photometry_occlusion()
	print("PLANET_SKY failures=", failures)
	quit(1 if failures else 0)


func body(id: String, alt: float, az: float, mag: float) -> Dictionary:
	var a := deg_to_rad(alt)
	var z := deg_to_rad(az)
	return {"id": id, "alt": alt, "az": az, "mag": mag, "dir": [sin(z) * cos(a), sin(a), -cos(z) * cos(a)]}


func state_of(bodies: Array, utc := "2026-11-15T01:00:00Z") -> Dictionary:
	return {"supported": true, "utc": utc, "observer": [64.0, 26.0, 0.0], "source": "PyEphem test", "bodies": bodies}


func rules() -> void:
	check(PlanetSky.IDS == ["mercury", "venus", "mars", "jupiter", "saturn", "uranus"], "six bodies in the stable order")
	check(PlanetSky.COLORS.size() == 6 and PlanetSky.B_MINUS_V.size() == 6, "one colour and B-V per body")
	var last := 99.0
	for sun in range(-30, 20):
		var limit: float = PlanetSky.twilight_limit(float(sun))
		check(limit <= last + 0.0001 and limit >= -5.0 and limit <= 6.0, "the twilight limit falls smoothly with the Sun (%d)" % sun)
		check(absf(limit - last) < 1.1 or last == 99.0, "no step in the twilight limit at %d" % sun)
		last = limit
	var dark: float = PlanetSky.limiting_magnitude(-25.0, 0.0, -20.0, 0.0)
	check(dark == 6.0, "a dark moonless sky reaches magnitude six")
	check(PlanetSky.level(5.68, 40.0, dark) > 0.0, "Uranus (5.7) shows in a dark sky")
	check(PlanetSky.level(5.68, 40.0, PlanetSky.limiting_magnitude(-25.0, 1.0, -20.0, 0.0)) == 0.0, "city pollution hides Uranus")
	check(PlanetSky.level(5.68, 40.0, PlanetSky.limiting_magnitude(-10.0, 0.0, -20.0, 0.0)) == 0.0, "nautical twilight hides Uranus")
	check(PlanetSky.level(5.68, 40.0, PlanetSky.limiting_magnitude(-25.0, 0.0, 60.0, 1.0)) < PlanetSky.level(5.68, 40.0, dark), "a bright high Moon dims faint planets")
	check(PlanetSky.level(-4.4, 30.0, PlanetSky.limiting_magnitude(-3.0, 0.0, -20.0, 0.0)) > 0.5, "Venus survives sunset twilight")
	check(PlanetSky.level(-1.9, 30.0, PlanetSky.limiting_magnitude(-5.0, 0.0, -20.0, 0.0)) > 0.3, "Jupiter survives civil twilight")
	check(PlanetSky.level(0.3, 30.0, PlanetSky.limiting_magnitude(-3.0, 0.0, -20.0, 0.0)) == 0.0, "Mercury waits for deeper twilight than Venus")
	for mag in [-4.4, -1.9, 0.7, 5.7]:
		check(PlanetSky.level(mag, 30.0, PlanetSky.limiting_magnitude(15.0, 0.0, -20.0, 0.0)) == 0.0, "the day sky hides magnitude %.1f" % mag)
	for pollution in [0.0, 0.25, 0.5, 0.75, 1.0]:
		var limit: float = PlanetSky.limiting_magnitude(-25.0, pollution, -20.0, 0.0)
		check(PlanetSky.level(5.68, 40.0, limit) <= PlanetSky.level(0.4, 40.0, limit), "faint planets go before bright ones")
		if PlanetSky.level(5.68, 40.0, limit) > 0.0:
			check(PlanetSky.level(0.4, 40.0, limit) > 0.0, "a visible faint planet implies the bright ones")
	var magnitude_ordered := true
	for mag in range(-45, 60, 5):
		magnitude_ordered = magnitude_ordered and PlanetSky.level(mag / 10.0, 40.0, 7.0) > PlanetSky.level(mag / 10.0 + 0.5, 40.0, 7.0)
	check(magnitude_ordered, "brightness increases strictly with magnitude")
	check(PlanetSky.brightness(-4.9) < 1.0, "the display compression never reaches white")
	check(PlanetSky.level(0.0, -1.0, 6.0) == 0.0 and PlanetSky.level(0.0, 0.0, 6.0) == 0.0 and PlanetSky.level(0.0, 2.5, 6.0) < PlanetSky.level(0.0, 5.0, 6.0)
		and is_equal_approx(PlanetSky.level(0.0, 5.0, 6.0), PlanetSky.level(0.0, 40.0, 6.0)), "0-5 degree horizon fade, nothing below")
	var shader := FileAccess.get_file_as_string("res://sky_clouds.gdshader")
	check("planet_dir[6]" in shader and "!AT_CUBEMAP_PASS && planet_visible" in shader and "planets * clear" in shader and "moon_visible * smoothstep" in shader, "six-entry array behind the clouds, outside the radiance pass")
	check(not "OMNI" in shader and not "texture(planet" in shader, "no planet lights or generated textures")


func test_shared_resource_lifecycle() -> void:
	var B3 = load("res://buildings_3d.gd")
	var old_opaque: bool = B3.opaque
	B3.opaque = true
	var objects_before := 0
	for round in 3:  # scene reloads
		var layer = B3.new()
		root.add_child(layer)
		await process_frame
		var sky: ShaderMaterial = layer._camera.environment.sky.sky_material
		var children: int = layer.get_child_count()
		layer.set_planets({}, 0.0, -25.0, -20.0, 0.0)  # an older server: no planet_sky
		check(layer.planet_levels == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] and sky.get_shader_parameter("planet_visible") == 0.0, "missing state hides the layer")
		var state := state_of([body("mercury", -20, 40, 0.3), body("venus", 20, 100, -4.4), body("mars", 30, 90, 0.7), body("jupiter", 40, 120, -1.9),
			body("saturn", 25, 240, 0.6), {"id": "uranus", "unavailable": "provider error"}])
		layer.set_planets(state, 0.0, -25.0, -20.0, 0.0)
		check(layer.planet_levels[0] == 0.0 and layer.planet_levels[1] > layer.planet_levels[3] and layer.planet_levels[3] > layer.planet_levels[2], "below horizon hidden, Venus > Jupiter > Mars")
		check(layer.planet_levels[5] == 0.0, "an unavailable body is hidden, never stale")
		var directions: PackedVector4Array = sky.get_shader_parameter("planet_dir")
		check(directions.size() == 6 and is_equal_approx(directions[1].y, sin(deg_to_rad(20.0))) and is_equal_approx(directions[1].w, layer.planet_levels[1]), "uniform carries direction and level")
		for i in 600:  # repeat updates and time jumps
			var moved := state.duplicate(true)
			moved["utc"] = "2026-11-15T%02d:%02d:00Z" % [i % 24, i % 60]
			layer.set_planets(moved, 0.0, -25.0, -20.0, 0.0)
			layer.set_planets(moved, 0.0, -25.0, -20.0, 0.0)
		check(layer.get_child_count() == children and layer._camera.environment.sky.sky_material == sky, "updates create no nodes, lights or materials")
		check((sky.get_shader_parameter("planet_dir") as PackedVector4Array).size() == 6 and (sky.get_shader_parameter("planet_color") as PackedVector3Array).size() == 6, "the uniforms stay six entries")
		layer.set_planets({"supported": false, "bodies": []}, 0.0, -25.0, -20.0, 0.0)
		check(layer.planet_levels.max() == 0.0 and sky.get_shader_parameter("planet_visible") == 0.0, "an unsupported date leaves no stale points")
		layer.free()
		await process_frame
		if round == 0: objects_before = int(Performance.get_monitor(Performance.OBJECT_COUNT))
		else: check(int(Performance.get_monitor(Performance.OBJECT_COUNT)) <= objects_before + 20, "reloading the scene does not grow the object count")
	B3.opaque = old_opaque


func make_view(size: Vector2i, fov: float) -> void:
	view = SubViewport.new()
	view.size = size
	view.own_world_3d = true
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	camera = Camera3D.new()
	view.add_child(camera)
	camera.fov = fov
	material = ShaderMaterial.new()
	material.shader = load("res://sky_clouds.gdshader")
	material.set_shader_parameter("sky_top_color", Color.BLACK)
	material.set_shader_parameter("sky_horizon_color", Color.BLACK)
	material.set_shader_parameter("energy", 0.0)
	material.set_shader_parameter("coverage", 1.2)
	var colors := PackedVector3Array()
	for c: Color in PlanetSky.COLORS: colors.append(Vector3(c.r, c.g, c.b))
	material.set_shader_parameter("planet_color", colors)
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	environment.sky = Sky.new()
	environment.sky.sky_material = material
	camera.environment = environment


func aim(alt: float, az: float) -> void:
	camera.rotation = Vector3(deg_to_rad(alt), deg_to_rad(-az), 0.0)  # az east of north, -Z north


func put(levels: Array, bodies: Array) -> void:
	var state := state_of(bodies)
	var directions := PlanetSky.directions(state)
	for i in 6:
		var v := directions[i]
		v.w = levels[i]
		directions[i] = v
	material.set_shader_parameter("planet_dir", directions)
	material.set_shader_parameter("planet_visible", 1.0)


func shot() -> Image:
	for i in 3: await process_frame
	await RenderingServer.frame_post_draw
	return view.get_texture().get_image()


## Linear peak (rgb, pixel) in the image; the sky is black, so this is the planet.
func peak(image: Image, region := Rect2i(Vector2i.ZERO, Vector2i(-1, -1))) -> Dictionary:
	var rect := region if region.size.x >= 0 else Rect2i(Vector2i.ZERO, image.get_size())
	var best := Color(0, 0, 0)
	var at := Vector2i(-1, -1)
	for y in range(rect.position.y, rect.end.y):
		for x in range(rect.position.x, rect.end.x):
			var c := image.get_pixel(x, y).srgb_to_linear()
			if c.r + c.g + c.b > best.r + best.g + best.b:
				best = c
				at = Vector2i(x, y)
	return {"rgb": best, "at": at}


func footprint(image: Image, at: Vector2i, level: float) -> int:
	var count := 0
	for y in range(maxi(0, at.y - 12), mini(image.get_height(), at.y + 13)):
		for x in range(maxi(0, at.x - 12), mini(image.get_width(), at.x + 13)):
			var c := image.get_pixel(x, y).srgb_to_linear()
			count += int(maxf(c.r, maxf(c.g, c.b)) > level * 0.1)
	return count


func test_projection_photometry_occlusion() -> void:
	make_view(SIZE, 30.0)
	aim(20.0, 0.0)
	var none := [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
	# east is +X (right of a camera looking north), west is -X, each at its predicted pixel
	for case in [[10.0], [-10.0]]:
		var levels := none.duplicate()
		levels[2] = 0.5
		put(levels, [body("mars", 20.0, case[0], 0.7)])
		var image := await shot()
		var found := peak(image)
		check(found.at.x > 0 and (found.at.x > SIZE.x / 2) == (case[0] > 0.0), "az %+.0f appears on the %s of centre at %s" % [case[0], "right" if case[0] > 0 else "left", found.at])
		var d: Array = body("mars", 20.0, case[0], 0.7).dir
		var expected := camera.unproject_position(camera.global_position + Vector3(d[0], d[1], d[2]) * 1000.0)
		check(Vector2(found.at).distance_to(expected) < 2.0, "the planet sits at its projected pixel (%s vs %s)" % [found.at, expected])
	# magnitude ordering, body colours, no white clipping: each planet alone at its own magnitude
	var mags := [0.3, -4.4, 0.7, -1.9, 0.6, 5.68]
	var level_of := []
	for i in 6:
		var levels := none.duplicate()
		levels[i] = PlanetSky.brightness(mags[i])
		put(levels, [body(PlanetSky.IDS[i], 20.0, 0.0, mags[i])])
		var found := peak(await shot())
		var rgb: Color = found.rgb
		var top := maxf(rgb.r, maxf(rgb.g, rgb.b))
		level_of.append(top)
		check(top < 0.99 and top > levels[i] * 0.55, "%s is a bright point below white clipping (%.3f of %.3f)" % [PlanetSky.IDS[i], top, levels[i]])
		var want: Color = PlanetSky.COLORS[i]
		check(absf(rgb.r / top - want.r) < 0.12 and absf(rgb.g / top - want.g) < 0.12 and absf(rgb.b / top - want.b) < 0.12, "%s keeps its naked-eye colour %s, rendered %s" % [PlanetSky.IDS[i], want, Color(rgb.r / top, rgb.g / top, rgb.b / top)])
		check(footprint(await shot(), found.at, top) <= 14, "%s stays a point, not a disc" % PlanetSky.IDS[i])
	check(level_of[1] > level_of[3] and level_of[3] > level_of[2] and level_of[2] > level_of[5] and level_of[0] > level_of[2] * 0.5, "rendered brightness follows magnitude: Venus > Jupiter > Mars > Uranus")
	# the rendered colours differ subtly: Mars is the reddest, Uranus the only blue-leaning point, Venus nearly white
	check(PlanetSky.COLORS[2].b < PlanetSky.COLORS[4].b and PlanetSky.COLORS[4].b < PlanetSky.COLORS[3].b and PlanetSky.COLORS[3].b < PlanetSky.COLORS[1].b and PlanetSky.COLORS[5].b > PlanetSky.COLORS[5].r, "hue order Mars < Saturn < Jupiter < Venus, Uranus blue-green")
	# occlusion: clouds, overcast, horizon, Sun disc, Moon disc
	var mars := none.duplicate()
	mars[2] = 0.5
	var mars_body := [body("mars", 20.0, 0.0, 0.7)]
	put(mars, mars_body)
	var reference := peak(await shot())
	check(reference.rgb.r > 0.2, "reference Mars is visible")
	material.set_shader_parameter("coverage", 0.125)
	check(peak(await shot()).rgb.r < 0.01, "full overcast hides the planet")
	material.set_shader_parameter("coverage", 1.2)
	material.set_shader_parameter("sun_visible", 1.0)
	material.set_shader_parameter("sun_dir", Vector3(0.0, sin(deg_to_rad(20.0)), -cos(deg_to_rad(20.0))))
	var sun_shot := await shot()
	check(peak(sun_shot, Rect2i(reference.at - Vector2i(2, 2), Vector2i(5, 5))).rgb.g > 0.5, "the Sun disc covers the planet")
	material.set_shader_parameter("sun_visible", 0.0)
	material.set_shader_parameter("moon_visible", 1.0)
	material.set_shader_parameter("moon_texture", load("res://assets/moon/2k_moon.jpg"))
	material.set_shader_parameter("moon_dir", Vector3(0.0, sin(deg_to_rad(20.0)), -cos(deg_to_rad(20.0))))
	material.set_shader_parameter("moon_illumination", 0.0)
	material.set_shader_parameter("sun_dir", Vector3(0.0, -1.0, 0.0))
	check(peak(await shot(), Rect2i(reference.at - Vector2i(2, 2), Vector2i(5, 5))).rgb.r < 0.05, "an unlit Moon disc occludes the planet")
	material.set_shader_parameter("moon_visible", 0.0)
	var below := [body("mars", -10.0, 0.0, 0.7)]
	put(mars, below)
	aim(-10.0, 0.0)
	check(peak(await shot()).rgb.r < 0.01, "nothing is drawn below the horizon even when forced")
	# stability across camera rotation, FOV and resolution: the same sky point keeps a bounded pixel footprint
	var widths := []
	for config in [[Vector2i(320, 180), 30.0], [Vector2i(1280, 720), 30.0], [Vector2i(640, 360), 75.0], [Vector2i(640, 360), 5.0]]:
		view.size = config[0]
		camera.fov = config[1]
		put(mars, mars_body)
		aim(20.0, 0.0)
		var found := peak(await shot())
		widths.append(footprint(await shot(), found.at, 0.5))
		check(found.rgb.r > 0.25 and found.rgb.r < 0.55, "equal level, equal brightness at %s fov %s" % [config[0], config[1]])
		aim(20.0, 3.0)  # the planet moves on screen with the camera but stays the same point
		var turned := peak(await shot())
		check(turned.at != found.at and absf(turned.rgb.r - found.rgb.r) < 0.15, "camera rotation moves the point without changing it")
	check(widths.max() <= 14 and widths.min() >= 1, "point footprints stay bounded across resolutions and FOVs %s" % [widths])
	view.free()
