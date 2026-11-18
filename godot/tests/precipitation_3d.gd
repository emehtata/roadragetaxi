## Falling precipitation (docs/specs/precipitation-falling.md).
extends SceneTree
const P3 = preload("res://precipitation_3d.gd")
const WeatherLayer = preload("res://weather_layer.gd")

var failures := 0
var host: Node  # where test nodes go: this tree's root, or run_tests.gd's


func check(ok: bool, what: String) -> void:
	if not ok:
		failures += 1
		print("FAIL ", what)


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	host = root
	run()
	print("PRECIPITATION_3D failures=", failures)
	quit(1 if failures else 0)


## Also called from run_tests.gd.
func run() -> void:
	test_fall_velocity_down_and_with_wind()
	test_layers_near_faster()
	test_drop_count_matches_intensity_and_cap()
	test_hidden_when_underground_or_clear()
	test_overlay_hidden_when_3d_active()
	test_snow_volume_follows_ground_height()
	test_snow_reentry_initialization()


func test_fall_velocity_down_and_with_wind() -> void:
	for layer in [0.0, 0.5, 1.0]:
		var rain: Vector3 = P3.fall_velocity("rain", layer, Vector2.ZERO)
		check(rain.y <= -6.0 and rain.y >= -9.0 and rain.x == 0.0 and rain.z == 0.0, "rain falls straight down at 6-9 m/s (%s)" % rain)
		var snow: Vector3 = P3.fall_velocity("snow", layer, Vector2.ZERO)
		check(snow.y <= -0.8 and snow.y >= -1.6, "snow falls at 0.8-1.6 m/s (%s)" % snow)
	check(is_equal_approx(snappedf(-P3.fall_velocity("slush", 0.5, Vector2.ZERO).y, 0.01), 3.0), "slush falls at 3 m/s")
	var wind := Vector2(4.0, -2.0)
	var r: Vector3 = P3.fall_velocity("rain", 0.5, wind)
	check(is_equal_approx(r.x, 2.0) and is_equal_approx(r.z, -1.0), "rain drifts 0.5x downwind (%s)" % r)
	var s: Vector3 = P3.fall_velocity("snow", 0.5, wind)
	check(is_equal_approx(s.x, 3.6) and is_equal_approx(s.z, -1.8), "snow drifts 0.9x downwind (%s)" % s)


func test_layers_near_faster() -> void:
	for kind in ["rain", "snow", "slush"]:
		var far: Vector3 = P3.fall_velocity(kind, 0.0, Vector2.ZERO)
		var near: Vector3 = P3.fall_velocity(kind, 1.0, Vector2.ZERO)
		check(near.y < far.y and is_equal_approx(near.y / far.y, 1.3), "%s: near layer 1.3x faster" % kind)


func test_drop_count_matches_intensity_and_cap() -> void:
	var last := 0
	for intensity in [0.35, 0.7, 1.0]:
		var rain: int = P3.drop_count("rain", intensity)
		check(rain == P3.drop_count("snow", intensity), "same count for rain and snow at %s" % intensity)
		check(rain > last and rain <= 8000 and rain != 220, "monotonic, capped, not the old 220 (%d)" % rain)
		last = rain
	check(P3.drop_count("rain", 5.0) == P3.MAX_PARTICLES and P3.MAX_PARTICLES == 8000, "never above 8000")


func test_hidden_when_underground_or_clear() -> void:
	var p: Node3D = P3.new()
	host.add_child(p)
	p.set_weather("rain", 0.7, Vector2.ZERO)
	check(p.visible and p.particles.emitting, "rain: shown and emitting")
	p.set_weather("", 0.7, Vector2.ZERO)  # underground and clear sky both arrive as ""
	check(not p.visible and not p.particles.emitting, "no kind: hidden, emitting off")
	p.free()


func test_overlay_hidden_when_3d_active() -> void:
	var weather := WeatherLayer.new()
	var sky := CanvasLayer.new()
	var world := Node2D.new()
	host.add_child(sky)
	host.add_child(world)
	weather.setup(sky, world)
	weather.precipitation_3d = true
	weather.update(0.016, {"weather": {"weather_type": "rain", "wetness": 1.0}}, Vector2.ZERO, false)
	check(weather.precipitation.visible == false, "the 2D overlay is hidden while the 3D view draws the drops")
	weather.precipitation_3d = false
	weather.update(0.016, {"weather": {"weather_type": "rain", "wetness": 1.0}}, Vector2.ZERO, false)
	check(weather.precipitation.visible, "the overlay stays the fallback without 3D")
	sky.free()
	world.free()
	weather.free()


func test_snow_volume_follows_ground_height() -> void:
	var p: Node3D = P3.new()
	var camera := Camera3D.new()
	host.add_child(camera)
	camera.current = true
	host.add_child(p)
	for height: float in [0.0, 24.0, 70.0]:
		if "ground_elevation" in p: p.ground_elevation = height
		camera.position = Vector3(120.0, height + 1.35, 80.0)
		p.set_weather("snow", 0.7, Vector2.ZERO)
		p._process(0.016)
		check(not p._update_volume(), "stable snow volume does not restart")
		for step in 30:
			camera.position.x += 1.0
			check(not p._update_volume(), "ordinary camera travel does not repeatedly restart snow")
		camera.position.x += 100.0
		check(p._update_volume(), "camera teleport requests a filled volume")
		check(is_equal_approx(p.particles.global_position.y, height), "snow emitter follows sampled ground at %s m" % height)
		check(absf(p.collision.global_position.y - height) <= P3.COLLISION_STEP_M * 0.5, "snow collision grid covers sampled ground at %s m" % height)
		check(absf(height + P3.EMIT_HEIGHT_M - p.collision.global_position.y) < p.collision.size.y * 0.5, "collision grid covers full falling volume between elevation steps")
		check(p.particles.global_position.x == camera.global_position.x and p.particles.global_position.z == camera.global_position.z, "snow volume follows relocated camera")
		check(p._process_material.get_shader_parameter("extent") is Vector2 and p._process_material.get_shader_parameter("extent").length() > 10.0, "first snow volume has nonzero extent")
	p.free()
	camera.free()


func test_snow_reentry_initialization() -> void:
	var p: Node3D = P3.new()
	host.add_child(p)
	for kind in ["snow", "", "snow", "rain", "snow"]:
		p.set_weather(kind, 0.7, Vector2(2, -1))
		if kind == "": continue
		check(p.particles.emitting and p.particles.amount == 5600, "weather reentry restores emission and count")
		check(p._process_material.get_shader_parameter("extent") is Vector2 and p._process_material.get_shader_parameter("extent").length() > 10.0, "weather starts only with valid emission extent")
		check(p.particles.draw_pass_1.material != null, "weather starts with drawing material")
	var material: Material = p.particles.draw_pass_1.material
	var lifetime: float = p.particles.lifetime
	p.set_weather("snow", 0.7, Vector2.ZERO)
	check(p.particles.amount == 5600 and p.particles.lifetime == lifetime and p.particles.draw_pass_1.material == material, "unchanged weather retains particle allocation/material")
	p.free()
