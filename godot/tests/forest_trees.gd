## 3D forest (docs/specs/forests-fps-3d.md): deterministic trees inside the
## forest mask only, stable across chunk origins, all three species, no grid,
## rooted on the DEM ground, near/far LOD instances.
extends SceneTree
const MapChunk = preload("res://map_chunk.gd")
const B3 = preload("res://buildings_3d.gd")

var failures := 0


func check(ok: bool, what: String) -> void:
	if not ok:
		failures += 1
		print("FAIL ", what)


func _initialize() -> void:
	# A 200 x 200 m chunk; forest on the left half, a road strip cut out of it.
	var origin := Vector2(477000.0, 7170000.0)
	var rect := Rect2(0, -200, 200, 200)
	var mask := Image.create(200, 200, false, Image.FORMAT_RGB8)
	mask.fill(Color.BLACK)
	mask.fill_rect(Rect2i(0, 0, 100, 200), Color.RED)
	mask.fill_rect(Rect2i(40, 0, 10, 200), Color.BLACK)
	var trees: Array = MapChunk.forest_trees(mask, rect, origin)
	check(trees.size() > 300, "a 1 ha forest gets hundreds of trees (%d)" % trees.size())
	var inside := trees.all(func(t): var p: Vector2 = t[0] - rect.position; return mask.get_pixel(int(p.x), int(p.y)).r > 0.5)
	check(inside, "every tree stands on a forest pixel (not the road, not the field)")
	var kinds := {}
	for t in trees:
		kinds[t[1]] = true
	check(kinds.has("pine") and kinds.has("spruce") and kinds.has("birch"), "pine, spruce and birch all appear")
	var xs := {}
	for t in trees:
		xs[snappedf(fposmod(t[0].x, 5.0), 0.1)] = true
	check(xs.size() > 20, "no grid: positions are jittered")
	# The same world spot from a chunk with another origin: the same trees.
	var shift := Vector2(100.0, 0.0)
	var mask2 := Image.create(200, 200, false, Image.FORMAT_RGB8)
	mask2.fill(Color.RED)
	var a := {}
	for t in MapChunk.forest_trees(mask2, rect, origin):
		a[Vector2(snappedf(origin.x + t[0].x, 0.01), snappedf(origin.y - t[0].y, 0.01))] = t[1]
	var b := {}
	for t in MapChunk.forest_trees(mask2, Rect2(-100, -200, 200, 200), origin + shift):
		b[Vector2(snappedf(origin.x + shift.x + t[0].x, 0.01), snappedf(origin.y - t[0].y, 0.01))] = t[1]
	var shared := 0
	var same := 0
	for key in a:
		if key.x >= origin.x + 10.0 and key.x < origin.x + 190.0 and b.has(key):
			shared += 1
			same += int(b[key] == a[key])
	check(shared > 200 and same == shared, "trees are stable across chunk origins (%d shared)" % shared)
	check(MapChunk.forest_trees(mask, rect, origin) == trees, "deterministic")
	# Rooted on the DEM ground: a 3x3 grid 10 m above zero.
	var grid := {"origin": Vector2(-50, 50), "step": 100.0, "cols": 3, "heights": PackedFloat32Array([10, 10, 10, 10, 10, 10, 10, 10, 10])}
	var t3: Transform3D = B3.tree_parts([[Vector2(5, -5), "pine", 2.0, Color.GREEN, Color.BROWN, NAN]], PackedVector2Array(), grid)["trunk"][0][0]
	var base := t3.origin.y - t3.basis.y.length() * 0.5
	check(absf(base - 10.0) < 0.3, "the trunk stands on the 10 m ground (base %.2f)" % base)
	# LOD: the forest's near part ends where its far part begins.
	var lod := B3.forest_node([[Vector2(5, -5), "spruce", 2.0, Color.GREEN, Color.BROWN, NAN]], {})
	var near: Array = lod.get_children().filter(func(n): return n.visibility_range_end > 0.0)
	var far: Array = lod.get_children().filter(func(n): return n.visibility_range_begin > 0.0)
	check(not near.is_empty() and not far.is_empty() and near[0].visibility_range_end == far[0].visibility_range_begin, "near detail and far simple LOD")
	lod.free()
	print("FOREST_TREES failures=", failures)
	quit(1 if failures else 0)
