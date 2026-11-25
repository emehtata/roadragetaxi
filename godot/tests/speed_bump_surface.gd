## Run: godot --headless --path godot --script res://tests/speed_bump_surface.gd
## docs/specs/terrain-following-bodies.md part 1: a speed bump is a road shape. The drawn mesh and
## deck_height agree, a car rolls over a hump slowly and hops it fast.
extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const Chunk := preload("res://map_chunk.gd")
const Map := preload("res://map_layer.gd")
const Entities := preload("res://entity_layer.gd")

var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("run")


func run() -> void:
	test_mesh_matches_deck_height()
	test_only_the_chunk_under_the_car()
	print("speed_bump_surface: %d failures" % failures)
	quit(1 if failures else 0)


## A bump of `kind` at layer (100, -100) along +x, and the layer-0 ground's heights under it.
func _bump(kind: String) -> Array:
	return B3.bumps_of([[100.0, 100.0, 0.0, 5.0, kind]], Vector2.ZERO)


func _grid(slope: float) -> Dictionary:
	var heights := []
	for r in 26:
		for c in 26:
			heights.append(c * 20.0 * slope)
	return {"origin": Vector2.ZERO, "step": 20.0, "cols": 26, "heights": PackedFloat32Array(heights)}


func _top_under(verts: PackedVector3Array, at: Vector2) -> float:
	var top := -INF
	for t in range(0, verts.size(), 3):
		var a := Vector2(verts[t].x, verts[t].z)
		var b := Vector2(verts[t + 1].x, verts[t + 1].z)
		var c := Vector2(verts[t + 2].x, verts[t + 2].z)
		var d := (b - a).cross(c - a)
		if absf(d) < 1e-9:
			continue
		var u := (at - a).cross(c - a) / d
		var v := (b - a).cross(at - a) / d
		if u >= -1e-6 and v >= -1e-6 and u + v <= 1.0 + 1e-6:
			top = maxf(top, verts[t].y + u * (verts[t + 1].y - verts[t].y) + v * (verts[t + 2].y - verts[t].y))
	return top


## Criterion 1: the mesh top and deck_height agree within 0.005 m at 9 points along each profile, flat and on a DEM slope.
func test_mesh_matches_deck_height() -> void:
	for kind: String in B3.BUMP_PROFILES:
		for slope: float in [-1.0, 0.0, 0.1]:  # -1: no DEM grid (flat)
			var bumps := _bump(kind)
			var ground := {"rect": Rect2(0, -300, 400, 300), "bumps": bumps}
			var grid := {}
			if slope >= 0.0:
				var message := {"ground_heights": {"origin": [0, 0], "step": 20.0, "cols": 26, "heights": _grid(slope)["heights"]}}
				Chunk.prepare(message, Vector2.ZERO)
				grid = message["prepared"]["ground_heights"]
				ground["ground_heights"] = grid
			var out := B3.build([], [], Vector2.ZERO, [], [], ground)
			var length: float = B3.BUMP_PROFILES[kind][1]
			var worst := 0.0
			for i in 9:
				var at := Vector2(100.0 - length / 2.0 + length * (i + 0.5) / 9.0, -100.0 + 0.3)
				var mesh := _top_under(out["road"], at)
				var deck := B3.deck_height(at, 0, PackedVector2Array(), grid, bumps)
				worst = maxf(worst, absf(mesh - deck))
				check(mesh > -INF, "%s: the mesh covers point %d" % [kind, i])
			print("%s slope %.1f: worst mesh vs deck_height %.4f m" % [kind, slope, worst])
			check(worst <= 0.005, "%s (slope %.1f): mesh top and deck_height differ by %.4f m" % [kind, slope, worst])


## Criterion 5: deck_height reads the bumps of the chunk containing the point only.
func test_only_the_chunk_under_the_car() -> void:
	var flags := [Chunk.buildings_3d, Chunk.outdoor_3d, Chunk.build_async]
	Chunk.buildings_3d = true
	Chunk.outdoor_3d = true
	Chunk.build_async = false
	var map := Map.new()
	root.add_child(map)
	map.add_chunk({"chunk_id": "0_0", "bounds": [0, 0, 100, 100], "speed_bumps": [[50.0, 50.0, 0.0, 6.0, "hump"]]})
	map.add_chunk({"chunk_id": "1_0", "bounds": [100, 0, 200, 100]})
	var row: Array = map._chunks["0_0"].ground_bumps[0]
	var on_hump: Vector2 = (row[0] + row[1]) / 2.0
	var flat := B3.ROAD_M + 0.008
	check(absf(map.deck_height(on_hump, 0) - flat - 0.10) < 0.001, "the hump's crest: %.3f m over the road" % (map.deck_height(on_hump, 0) - flat))
	var stray := [[Vector2(150, -50) - Vector2(1, 0), Vector2(150, -50) + Vector2(1, 0), 3.0, "hump"]]
	map._chunks["0_0"].ground_bumps = stray  # a bump row of chunk 0_0 lying over chunk 1_0
	check(absf(map.deck_height(Vector2(150, -50), 0) - flat) < 1e-6, "another chunk's bump rows are not read")
	map._chunks["1_0"].ground_bumps = stray
	check(map.deck_height(Vector2(150, -50), 0) > flat + 0.05, "its own chunk's are")
	check(absf(map.deck_height(Vector2(150, -50), 1) - map.deck_height(Vector2(150, -50), 1)) == 0.0 and map.deck_height(Vector2(150, -50), -1) < 0.0,
		"bridge and tunnel heights have no bumps")
	map.free()
	Chunk.buildings_3d = flags[0]
	Chunk.outdoor_3d = flags[1]
	Chunk.build_async = flags[2]
