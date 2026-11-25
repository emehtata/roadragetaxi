extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const MapChunk := preload("res://map_chunk.gd")
const Startup := preload("res://startup.gd")
const TRIANGLES := {"pine":8032,"spruce":14248,"birch":22914,"shrub":11570}
var failures := 0
func check(ok: bool, message: String) -> void:
	if not ok: failures += 1; printerr("FAIL: ",message)
func _initialize() -> void: call_deferred("run")
func test_selected_source_geometry() -> void:
	for kind: String in TRIANGLES:
		var node := B3.trees_node([[Vector2(13,-7),kind,0.6 if kind=="shrub" else 2.0,Color.GREEN,Color.BROWN,NAN]],PackedVector2Array())
		var triangles := 0
		for batch: MultiMeshInstance3D in node.get_children():
			var mesh := batch.multimesh.mesh
			for surface in mesh.get_surface_count():
				var arrays := mesh.surface_get_arrays(surface)
				triangles += arrays[Mesh.ARRAY_INDEX].size()/3 if arrays[Mesh.ARRAY_INDEX]!=null else arrays[Mesh.ARRAY_VERTEX].size()/3
		check(triangles==TRIANGLES[kind],kind+" mapped tree uses complete kit source geometry")
		node.free()
func test_fit_seasons_and_felling() -> void:
	var grid := {"origin":Vector2.ZERO,"step":100.0,"cols":2,"heights":PackedFloat32Array([17,17,17,17])}
	for kind: String in TRIANGLES:
		var mesh := B3.nature_mesh(kind)
		for radius: float in [0.6,1.4,2.5]:
			var row := [Vector2(13,-7),kind,radius,Color.GREEN,Color.BROWN,NAN]
			var xf := B3.nature_transform(row,grid)
			check(is_equal_approx(xf.basis.x.length(),xf.basis.y.length()) and is_equal_approx(xf.basis.y.length(),xf.basis.z.length()),"source proportions preserved")
			var low := INF
			for point: Vector3 in mesh.get_faces(): low=minf(low,(xf*point).y)
			check(absf(low-17.0)<0.001,"roots ground-centred on translated DEM")
			check(mesh.get_aabb().size.x*xf.basis.x.length()<=2*radius+0.001 and mesh.get_aabb().size.z*xf.basis.z.length()<=2*radius+0.001,"crown fits original diameter")
			check(B3.nature_transform(row,grid).is_equal_approx(xf),"stable seed yaw/fit")
	var chunk := MapChunk.new()
	chunk._season=PackedFloat32Array([1,0,0,0])
	chunk._trees_leafless=true
	var bare := chunk._tree_row("birch",0.5)
	var snowy := chunk._tree_row("pine",0.5)
	check(bare[6] and not snowy[6] and snowy[3].r>0.8,"leafless/snow state reaches renderer")
	for row: Array in [bare,[Vector2.ZERO,"pine",1.4,Color.GREEN,Color.BROWN,0.73]]:
		var node := B3.trees_node([row],PackedVector2Array())
		check(node.get_children().all(func(n): return not n.has_meta("nature_kind")),"bare/fallen fallback retained")
		node.free()
	chunk.free()

func test_batch_lifecycle_and_lod() -> void:
	var rows := []
	for i in 20: rows.append([Vector2(i*5,0),"pine",2.0,Color.GREEN,Color.BROWN,NAN])
	var shared := B3.nature_mesh("pine")
	for repeat in 3:
		var node := B3.trees_node(rows,PackedVector2Array([Vector2(0,5)]))
		check(node.get_child_count()==2,"twenty trees plus bollard use two batches")
		check(node.get_child(0).multimesh.instance_count==20 and node.get_child(0).multimesh.mesh==shared,"cached mesh shared by instances/rebuilds")
		check(node.get_child(0).layers==B3.LAYER_BUILDINGS,"tree map layer retained")
		node.free()
	var forest := B3.forest_node(rows,{})
	check(forest.get_children().any(func(n):return n.get_meta("nature_kind","")=="pine" and n.multimesh.mesh==shared and n.visibility_range_end==B3.FOREST_NEAR_M),"dense forest near LOD uses the complete cached kit source")
	check(forest.get_children().filter(func(n):return n.visibility_range_begin>0.0).all(func(n):return not n.has_meta("nature_kind")),"dense forest far LOD retains simple geometry")
	check(forest.get_children().filter(func(n):return n.has_meta("nature_kind")).all(func(n):return n.cast_shadow==GeometryInstance3D.SHADOW_CASTING_SETTING_OFF) and forest.get_children().any(func(n):return n.cast_shadow==GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY),"forest GLB visuals reuse bounded original shadow proxies")
	check(forest.get_children().any(func(n):return n.visibility_range_begin==B3.FOREST_NEAR_M),"simple distant LOD retained")
	forest.free()

func test_provenance_and_credits() -> void:
	var names := {"pine":"pine_tree","spruce":"spruce_tree","birch":"birch_tree","shrub":"bush"}
	for kind: String in names:
		var path: String="res://assets/nature/"+names[kind]
		var record:Dictionary=JSON.parse_string(FileAccess.get_file_as_string(path+".json"))
		check(record.sha256==FileAccess.get_sha256(path+".glb") and record.license=="CC0-1.0" and record.triangles==TRIANGLES[kind],"source hash/count/license "+kind)
		var mesh := B3.nature_mesh(kind)
		for surface in mesh.get_surface_count():
			var data := mesh.surface_get_arrays(surface)
			check(data[Mesh.ARRAY_NORMAL].size()==data[Mesh.ARRAY_VERTEX].size() and data[Mesh.ARRAY_TEX_UV].size()==data[Mesh.ARRAY_VERTEX].size() and data[Mesh.ARRAY_TANGENT].size()==4*data[Mesh.ARRAY_VERTEX].size(),"source normal/UV/tangents retained")
	for language:String in ["fi","en","de"]:check(Startup.credits_text(language).contains("Cozy Nature"),"visible source credits "+language)

func test_controlled_profile_population() -> void:
	var visual := preload("res://visual_test.gd").new()
	var state := {"player":{"x":13.0,"y":7.0},"game_time_seconds":46800,"weather":{"kind":"clear"}}
	var collections := ["npcs","pedestrians","trains","protests","brawls"]
	for key: String in collections: state[key]=[{"id":"variable_actor"}]
	var packet := {"state":state}
	check(visual.has_method("_nature_profile_state"),"controlled nature profile has actor isolation fixture")
	if visual.has_method("_nature_profile_state"): visual.call("_nature_profile_state",packet)
	for key: String in collections: check(packet.state[key].is_empty(),"profile removes variable "+key)
	check(packet.state.player=={"x":13.0,"y":7.0} and packet.state.game_time_seconds==46800 and packet.state.weather.kind=="clear","profile retains actual player, clock and weather")
	visual.free()


func run() -> void:
	test_selected_source_geometry();test_fit_seasons_and_felling();test_batch_lifecycle_and_lod();test_provenance_and_credits();test_controlled_profile_population()
	print("COZY_NATURE failures=",failures)
	quit(1 if failures else 0)
