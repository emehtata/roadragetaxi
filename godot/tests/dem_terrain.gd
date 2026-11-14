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
	test_road_lies_on_sloped_ground()
	test_road_above_terrain_mesh_everywhere()
	test_terrain_normals_smooth_and_continuous()
	test_kerb_keeps_flat_normals()
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

## A road across a slope lies on the ground: road within 0.1 m, grass within 0.05 m and under it.
func test_road_lies_on_sloped_ground() -> void:
	var heights := []
	for r in 26:
		for c in 26:
			heights.append(c * 20.0 * 0.1)
	var message := {"ground_heights": {"origin": [0, 0], "step": 20.0, "cols": 26, "heights": heights}}
	MapChunk.prepare(message, Vector2.ZERO)
	var grid: Dictionary = message["prepared"]["ground_heights"]
	var road := [PackedVector2Array([Vector2(50, -100), Vector2(250, -100)]), 4.0, Color.GRAY, 8, null, false]
	var out := B3.build([], [], Vector2.ZERO, [], [], {"rect": Rect2(0, -300, 400, 300), "roads": [road], "ground_heights": grid})
	var top := -INF
	for v: Vector3 in out["road"]:
		top = maxf(top, v.y - B3.ground_height(grid, Vector2(v.x, v.z)))
	check(top <= 0.1, "road %.3f m above the sloped ground" % top)
	var worst := 0.0
	for v: Vector3 in out["ground"]:
		worst = maxf(worst, absf(v.y - B3.ground_height(grid, Vector2(v.x, v.z))))
	check(worst <= 0.05 and worst < top, "grass %.3f m off the ground, under the road %.3f" % [worst, top])

## A curved road over a crest and twisted cells sits above the terrain mesh at every sample point
## (vertices, edge midpoints, centroids, 1 m steps along the edges), not only at its vertices.
func test_road_above_terrain_mesh_everywhere() -> void:
	var heights := []
	for r in 26:
		for c in 26:
			heights.append(5.0 * sin(c * 0.7) + r * c * 0.05)
	var message := {"ground_heights": {"origin": [0, 0], "step": 20.0, "cols": 26, "heights": heights}}
	MapChunk.prepare(message, Vector2.ZERO)
	var grid: Dictionary = message["prepared"]["ground_heights"]
	var road := [PackedVector2Array([Vector2(40, -40), Vector2(200, -100), Vector2(360, -260)]), 4.0, Color.GRAY, 8, null, false]
	var out := B3.build([], [], Vector2.ZERO, [], [], {"rect": Rect2(0, -500, 500, 500), "roads": [road], "ground_heights": grid})
	var verts: PackedVector3Array = out["road"]
	var worst := INF
	for t in range(0, verts.size(), 3):
		var tri := [verts[t], verts[t + 1], verts[t + 2]]
		var points := [(tri[0] + tri[1] + tri[2]) / 3.0]
		for e in 3:
			var a: Vector3 = tri[e]
			var b: Vector3 = tri[(e + 1) % 3]
			var n := maxi(2, ceili(a.distance_to(b)))
			for s in n + 1:
				points.append(a.lerp(b, float(s) / n))
		for p: Vector3 in points:
			worst = minf(worst, p.y - B3.terrain_mesh_height(grid, Vector2(p.x, p.z)))
	check(worst >= 0.03, "road at least %.3f m above the terrain mesh everywhere" % worst)

## A curved slope over two neighbour chunks (server grids with their 1-sample apron): the ground's normals
## are one per position (smooth), mesh heights hit the grid nodes, and the shared edge matches.
func _apron_grid(ix: int) -> Dictionary:
	var heights := []
	for r in 28:
		for c in 28:
			var x := ix * 500.0 - 20.0 + c * 20.0
			var y := -20.0 + r * 20.0
			heights.append(0.00004 * x * x + 0.03 * y + 2.0 * sin(y * 0.02))
	var message := {"ground_heights": {"origin": [ix * 500.0 - 20.0, -20.0], "step": 20.0, "cols": 28, "heights": heights}}
	MapChunk.prepare(message, Vector2.ZERO)
	return message["prepared"]["ground_heights"]

func _ground_normals(ix: int) -> Dictionary:
	var grid := _apron_grid(ix)
	var out := B3.build([], [], Vector2.ZERO, [], [], {"rect": Rect2(ix * 500.0, -500, 500, 500), "ground_heights": grid})
	var verts: PackedVector3Array = out["ground"]
	var normals: PackedVector3Array = out["normals"]["ground"]
	var at := {}  # rounded (x, z) -> [y, normal]
	var smooth := true
	var on_nodes := true
	for i in verts.size():
		var key := Vector2i(roundi(verts[i].x * 100.0), roundi(verts[i].z * 100.0))
		if at.has(key) and (at[key][1] - normals[i]).length() > 1e-4:
			smooth = false
		at[key] = [verts[i].y, normals[i]]
		if is_equal_approx(fmod(verts[i].x, 20.0), 0.0) and is_equal_approx(fmod(verts[i].z, 20.0), 0.0):
			on_nodes = on_nodes and absf(verts[i].y - B3.ground_height(grid, Vector2(verts[i].x, verts[i].z))) < 0.001
	check(verts.size() == 25 * 25 * 6, "terrain: a 20 m grid, %d vertices" % verts.size())
	check(smooth, "terrain %d: one normal per vertex position" % ix)
	check(on_nodes, "terrain %d: mesh height at the grid nodes" % ix)
	return at

func test_terrain_normals_smooth_and_continuous() -> void:
	var left := _ground_normals(0)
	var right := _ground_normals(1)
	var shared := 0
	var worst := 0.0
	for key: Vector2i in left:
		if key.x == 50000 and right.has(key):
			shared += 1
			worst = maxf(worst, maxf(absf(left[key][0] - right[key][0]), (left[key][1] - right[key][1]).length()))
	check(shared == 26 and worst < 1e-4, "terrain: chunk edge %d shared vertices, worst %.6f" % [shared, worst])

## Kerb side faces keep their flat (horizontal) normals on DEM terrain.
func test_kerb_keeps_flat_normals() -> void:
	var grid := _apron_grid(0)
	var curb := PackedVector2Array([Vector2(100, -100), Vector2(200, -130)])
	var out := B3.build([], [], Vector2.ZERO, [], [], {"rect": Rect2(0, -500, 500, 500), "curbs": [curb], "ground_heights": grid})
	var verts: PackedVector3Array = out["ground"]
	var normals: PackedVector3Array = out["normals"]["ground"]
	var sides := 0
	var bent := 0
	for i in range(0, verts.size(), 3):
		var flat := -(verts[i + 1] - verts[i]).cross(verts[i + 2] - verts[i]).normalized()
		if absf(flat.y) < 0.5:
			sides += 1
			for k in 3:
				if (normals[i + k] - flat).length() > 1e-4:
					bent += 1
	check(sides > 0 and bent == 0, "kerb: %d side faces, %d bent normals" % [sides, bent])

func check(ok: bool, message: String) -> void:
	if not ok:
		printerr("FAIL: ", message)
		failed = true
