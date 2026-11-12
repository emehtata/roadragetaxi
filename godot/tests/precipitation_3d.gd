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
