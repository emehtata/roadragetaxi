## Run: godot --headless --path godot --script res://tests/dem_terrain.gd
## The experimental 80 m DEM terrain switch is off by default, and a chunk with
## no (or empty) ground data renders flat instead of failing.
extends SceneTree

const Startup := preload("res://startup.gd")
const MapChunk := preload("res://map_chunk.gd")
const B3 := preload("res://buildings_3d.gd")

var failed := false

func _initialize() -> void:
	var settings := ConfigFile.new()
	check(Startup.terrain_args(settings) == ["--terrain-dem80"], "no setting: terrain on")
	settings.set_value("game", "terrain_dem80", true)
	check(Startup.terrain_args(settings) == ["--terrain-dem80"], "setting on: --terrain-dem80")
	settings.set_value("game", "terrain_dem80", false)
	check(Startup.terrain_args(settings) == ["--no-terrain-dem80"], "setting off: --no-terrain-dem80")
	for message in [{}, {"ground_heights": {}}]:  # server sent no grid (switch off, no dem80/, all NoData)
		MapChunk.prepare(message, Vector2.ZERO)
		var grid: Dictionary = message["prepared"]["ground_heights"]
		check(grid.is_empty(), "missing data: empty grid")
		check(B3.ground_height(grid, Vector2(120, -40)) == 0.0, "missing data: flat ground")
	var with_grid := {"ground_heights": {"origin": [0, 0], "step": 20.0, "cols": 2, "heights": [5.0, 5.0, 5.0, 5.0]}}
	MapChunk.prepare(with_grid, Vector2.ZERO)
	check(is_equal_approx(B3.ground_height(with_grid["prepared"]["ground_heights"], Vector2(10, -10)), 5.0), "grid: its height")
	var taxi := Vector2(15, -5)
	var ground := B3.ground_height(with_grid["prepared"]["ground_heights"], taxi)
	check(is_equal_approx(B3.top_camera_position(Vector2(15, -5), 300.0, ground).y - ground, 300.0), "camera: same height above the ground under the taxi")
	check(B3.top_camera_position(Vector2(15, -5), 300.0, B3.ground_height({}, taxi)) == Vector3(15, 300.0, -5), "switch off: camera unchanged")
	test_eye_follows_ground()
	test_lamp_stands_on_ground()
	print("dem_terrain: ", "FAIL" if failed else "PASS")
	quit(1 if failed else 0)

## The first-person eye (car or on foot) sits eye_height above the DEM ground under it.
func test_eye_follows_ground() -> void:
	var grid := {"ground_heights": {"origin": [0, 0], "step": 100.0, "cols": 2, "heights": [6.0, 12.0, 6.0, 12.0]}}
	MapChunk.prepare(grid, Vector2.ZERO)
	for point in [[Vector2(0, 0), 6.0], [Vector2(100, 0), 12.0]]:
		var elevation := B3.deck_height(point[0], 0, PackedVector2Array(), grid["prepared"]["ground_heights"])
		var eye := B3.windshield_camera_position(point[0], 0.0, 1.7, elevation, 0.0)
		check(absf(eye.y - (point[1] + 1.7)) < 0.01, "eye at %s follows the ground: %.2f" % [point[0], eye.y])

## A street lamp's pole base sits on the DEM ground at the pole.
func test_lamp_stands_on_ground() -> void:
	var grid := {"ground_heights": {"origin": [0, 0], "step": 100.0, "cols": 2, "heights": [6.0, 12.0, 6.0, 12.0]}}
	MapChunk.prepare(grid, Vector2.ZERO)
	var ground: Dictionary = grid["prepared"]["ground_heights"]
	var lamp := Vector2(51.2, -10.0)
	var verts: PackedVector3Array = B3.lamp_posts_arrays([[lamp, Vector2(1, 0)]], ground)["verts"]
	var lowest := INF
	for v in verts:
		lowest = minf(lowest, v.y)
	var pole := lamp - Vector2(1.2, 0)
	check(absf(lowest - B3.ground_height(ground, pole)) < 0.01, "lamp base %.2f on the ground %.2f" % [lowest, B3.ground_height(ground, pole)])

func check(ok: bool, message: String) -> void:
	if not ok:
		printerr("FAIL: ", message)
		failed = true
