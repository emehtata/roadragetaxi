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
	call_deferred("run")


func run() -> void:
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
	check(near.any(func(n): return n.get_meta("nature_kind", "")=="spruce" and n.multimesh.mesh==B3.nature_mesh("spruce")), "near landuse forest uses the complete Cozy Nature source")
	lod.free()
	await test_reported_forest_pipeline()
	print("FOREST_TREES failures=", failures)
	quit(1 if failures else 0)


func target_rows(chunk: Node, target: Rect2) -> int:
	return chunk._forest_rows.filter(func(row): return target.has_point(row[0])).size()


func forest_population(chunk: Node) -> int:
	var forest = chunk._dynamic_3d.get("forest")
	if not is_instance_valid(forest): return 0
	var count := 0
	for batch: MultiMeshInstance3D in forest.get_children():
		if batch.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY: continue
		if batch.visibility_range_end > 0.0 and (batch.has_meta("nature_kind") or batch.multimesh.mesh == B3._tree_mesh("trunk")):
			count += batch.multimesh.instance_count
	return count


func wait_for_forest(chunk: Node) -> void:
	for frame in 180:
		await process_frame
		if chunk._forest_look == [chunk._season, chunk._trees_leafless, chunk._forest_detail_cell] and chunk._forest_task < 0 and forest_population(chunk) == chunk._forest_rows.size(): return


func test_reported_forest_pipeline() -> void:
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://tests/data/reported_forest.json"))
	var flags := [MapChunk.outdoor_3d, MapChunk.buildings_3d, MapChunk.build_async]
	MapChunk.outdoor_3d = true; MapChunk.buildings_3d = true; MapChunk.build_async = false
	var map := preload("res://map_layer.gd").new()
	root.add_child(map)
	var origin := Vector2(fixture.origin[0], fixture.origin[1])
	map.set_origin(origin)
	map.set_sun(50.0, 120.0, .95)
	var bounds: Array = fixture.target
	var target := Rect2(Vector2(bounds[0] - origin.x, origin.y - bounds[3]), Vector2(bounds[2]-bounds[0],bounds[3]-bounds[1]))
	map.add_chunk(fixture.message.duplicate(true))
	var chunk = map._chunks["850_14433"]
	check(target_rows(chunk,target)==13,"reported OSM forest target prepares its 13 deterministic tree rows")
	var polygon: PackedVector2Array = chunk._points(chunk._data.landuse[0][2])
	for row: Array in chunk._forest_rows:
		var edge := INF
		for i in polygon.size(): edge=minf(edge,Geometry2D.get_closest_point_to_segment(row[0],polygon[i],polygon[(i+1)%polygon.size()]).distance_to(row[0]))
		check(Geometry2D.is_point_in_polygon(row[0],polygon) or edge<=1.0,"reported forest stays within its existing one-pixel raster boundary")
		for road: Dictionary in chunk._data.roads:
			var points: PackedVector2Array = chunk._points(road.points)
			for i in points.size()-1:
				check(Geometry2D.get_closest_point_to_segment(row[0],points[i],points[i+1]).distance_to(row[0]) >= float(road.half_width_m)+1.0,"reported forest retains road clearance after raster rounding")
	await wait_for_forest(chunk)
	check(forest_population(chunk)==chunk._forest_rows.size(),"normal setup builds every forest row without a test-forced redraw")
	var positions: Array = chunk._forest_rows.duplicate(true)
	var source_target := 0
	for point: Vector2 in chunk._dynamic_3d["forest"].get_meta("forest_detail_points"):
		if target.has_point(point): source_target+=1
	check(source_target==13,"the reported 56 m target is inside the actual GLB subset")
	check_glb_subset(chunk)
	var build: int = chunk._forest_build
	map.set_building_view(Vector2(-64,0)); map.set_building_view(Vector2(-96,0))
	await wait_for_forest(chunk)
	check(chunk._forest_build>build,"crossing camera cells refreshes only the bounded GLB subset")
	check_glb_subset(chunk)
	build=chunk._forest_build
	map.set_building_view(Vector2(-97,0))
	check(chunk._forest_build==build,"moving inside a camera cell does not rebuild forest geometry")
	map.replace_chunk(fixture.message.duplicate(true))
	chunk=map._chunks["850_14433"]
	await wait_for_forest(chunk)
	check(chunk._forest_rows==positions and forest_population(chunk)==positions.size(),"replacing the streamed forest retains its population")
	map.set_season([1.0,0.0,0.0,0.0]); map.set_trees_leafless(true)
	await wait_for_forest(chunk)
	check(chunk._forest_rows==positions and forest_population(chunk)==positions.size(),"season changes keep the mapped forest positions")
	map.clear(); map.add_chunk(fixture.message.duplicate(true))
	chunk=map._chunks["850_14433"]
	await wait_for_forest(chunk)
	check(chunk._forest_rows==positions and forest_population(chunk)==positions.size(),"unload/reload restores the mapped forest")
	# Replace the origin while old async work is still queued, as a new world does.
	map.replace_chunk(fixture.message.duplicate(true))
	map.set_origin(origin+Vector2(100,-50)); map.add_chunk(fixture.message.duplicate(true))
	chunk=map._chunks["850_14433"]
	await wait_for_forest(chunk)
	check(forest_population(chunk)==chunk._forest_rows.size(),"origin replacement finishes only the new chunk's forest")
	for row: Array in chunk._forest_rows:
		var world := Vector2(row[0].x+map.origin.x,map.origin.y-row[0].y)
		check(positions.any(func(old): return world.distance_to(Vector2(old[0].x+origin.x,origin.y-old[0].y))<.01),"origin replacement keeps world-space tree placements")
	map.free()
	await process_frame
	MapChunk.outdoor_3d=flags[0];MapChunk.buildings_3d=flags[1];MapChunk.build_async=flags[2]


func check_glb_subset(chunk: Node) -> void:
	var forest: Node3D = chunk._dynamic_3d["forest"]
	var near_rows := 0
	var far_rows := 0
	var kit_rows := 0
	var shared_bounds: AABB = forest.get_child(0).custom_aabb
	check(forest.get_meta("forest_detail_at")==chunk._forest_detail_at,"only the latest camera-cell result is attached")
	for point: Vector2 in forest.get_meta("forest_detail_points"):
		check(point.distance_to(chunk._forest_detail_at)<=B3.FOREST_KIT_RADIUS_M+.001,"selected GLB row stays inside its bounded camera-cell circle")
	check(shared_bounds.size.length()>0.0,"forest LODs share explicit complete bounds")
	for batch: MultiMeshInstance3D in forest.get_children():
		if batch.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY: continue
		check(batch.custom_aabb==shared_bounds,"GLB, middle and far batches use the same distance origin")
		if batch.multimesh.mesh == B3._tree_mesh("trunk"): continue
		if batch.visibility_range_begin>0.0:
			far_rows+=batch.multimesh.instance_count
			continue
		near_rows+=batch.multimesh.instance_count
		if not batch.has_meta("nature_kind"): continue
		kit_rows+=batch.multimesh.instance_count

	check(near_rows==chunk._forest_rows.size() and far_rows==near_rows,"cell swaps preserve one near representation and one matching far row per tree")
	check(kit_rows==forest.get_meta("forest_detail_points").size(),"each selected summer tree has one full-source GLB instance")
	check(kit_rows>0 and kit_rows<1000,"a chunk builds a bounded GLB subset rather than all forest rows")
