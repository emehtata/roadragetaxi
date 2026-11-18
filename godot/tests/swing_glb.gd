extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const Chunk := preload("res://map_chunk.gd")
const Map := preload("res://map_layer.gd")
const Startup := preload("res://startup.gd")
const T := preload("res://i18n.gd")
var failures := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)

func test_swing_uses_kit_geometry() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "swing"]])
	check(out.deck.is_empty(), "swing must not use the old solid cuboid")
	var surfaces: Dictionary = out.get("prop_surfaces", {})
	check(surfaces.size() == 3, "kit's three textured materials are retained")
	var count := 0
	for part in surfaces.values():
		count += part.verts.size()
		check(part.normals.size() == part.verts.size() and part.uv.size() == part.verts.size(), "source normals and UVs survive batching")
		check(part.material is BaseMaterial3D and part.material.albedo_texture != null, "source texture retained")
		for v: Vector3 in part.verts:
			check(absf(v.x) <= 1.701 and absf(v.z) <= 0.901 and v.y >= -0.001 and v.y <= 2.201, "uniform asset fits existing envelope")
	check(count == 19740 * 3, "production contains all source triangles")
	var faces := PackedVector3Array()
	for part: Dictionary in surfaces.values(): faces.append_array(part.verts)
	if not faces.is_empty():
		var triangles := TriangleMesh.new()
		triangles.create_from_faces(faces)
		check(triangles.intersect_segment(Vector3(0,1,-1),Vector3(0,1,1)).is_empty(), "open central frame contains no solid wall")
		for x: float in [-0.589,0.589]:
			check(not triangles.intersect_segment(Vector3(x,0.5,0),Vector3(x,0.2,0)).is_empty(), "both suspended seat surfaces exist")
		check(not triangles.intersect_segment(Vector3(0,2.3,0),Vector3(0,1.8,0)).is_empty(), "crossbeam spans frame above seats")

func test_swing_placement_and_lifecycle() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "swing"]])
	var at := Vector2(17, -23)
	var angle := 0.73
	var grid := {"origin": Vector2(-50,-50), "step": 100.0, "cols": 2, "heights": PackedFloat32Array([13.5,13.5,13.5,13.5])}
	var input := {"rect": Rect2(-50,-50,100,100), "props": [[at,angle,"swing"],[at,angle,"bench"]], "ground_heights": grid}
	var built := B3.build([], [], Vector2.ZERO, [], [], input)
	var placement := Transform3D(Basis(Vector3.UP,angle),B3.to_3d(at,13.5))
	for key in out.get("prop_surfaces", {}):
		var a: Dictionary = out.prop_surfaces[key]
		var b: Dictionary = built.prop_surfaces[key]
		check(a.verts.size() == b.verts.size(), "all transformed triangles retained")
		var error := 0.0
		for i in a.verts.size(): error = maxf(error, (placement * a.verts[i]).distance_to(b.verts[i]))
		check(error < 0.00002, "row angle, translation and DEM placement match")
	check(not built.deck.is_empty(), "unrelated bench still draws through original deck path")
	var source_cache: Dictionary = B3.swing_surfaces()
	check(source_cache == B3.swing_surfaces(), "source model cache remains stable")
	var sloped: Dictionary = grid.duplicate(true)
	sloped.heights = PackedFloat32Array([13.5,14.5,13.5,14.5])
	input.ground_heights = sloped
	var slope := B3.build([],[],Vector2.ZERO,[],[],input)
	for part: Dictionary in slope.get("prop_surfaces", {}).values():
		for i in range(0,part.verts.size(),137):
			check(absf(part.normals[i].length()-1.0)<0.001, "terrain-adjusted normals remain normalized")
			var tangent := Vector3(part.tangents[i*4],part.tangents[i*4+1],part.tangents[i*4+2])
			check(absf(tangent.dot(part.normals[i]))<0.01,"terrain-adjusted tangent stays perpendicular to normal")
	var flags := [Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async]
	Chunk.buildings_3d=true;Chunk.outdoor_3d=true;Chunk.build_async=false
	var map := Map.new(); root.add_child(map)
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[25.0,25.0,"swing",0.73],[35.0,25.0,"swing",0.0]]}
	var first := []
	for action in ["add","replace","reload"]:
		if action=="add": map.add_chunk(message.duplicate(true))
		elif action=="replace": map.replace_chunk(message.duplicate(true))
		else:
			map.clear();check(map._chunks.is_empty(),"chunk unload removes old geometry")
			map.add_chunk(message.duplicate(true))
		var faces := []
		for node: MeshInstance3D in map._chunks["0_0"].meshes_3d:
			if node.has_meta("prop_material"):
				check(node.material_override.albedo_texture != null, "final chunk uses source PBR material")
				check(node.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_ON, "kit casts shadows")
				faces.append(node.mesh.get_faces())
		check(not faces.is_empty(),"chunk includes kit mesh batches")
		var vertex_count := 0
		for part in faces: vertex_count += part.size()
		check(vertex_count == 2*19740*3, "two rows draw two complete assets with no duplicate triangles")
		if action=="add":first=faces
		else:check(first==faces,"replacement/reload neither duplicates nor loses triangles")
	map.free()
	Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_swing_source_and_credits() -> void:
	check(ResourceLoader.exists("res://assets/props/swing_set.glb"), "Swing Set asset is shipped")
	if FileAccess.file_exists("res://assets/props/manifest.json"):
		var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://assets/props/manifest.json"))
		check(FileAccess.get_sha256("res://assets/props/swing_set.glb") == provenance.sha256, "shipped GLB matches source manifest hash")
	for file in ["SOURCES.md","manifest.json","CC0-1.0.txt"]:
		check(FileAccess.file_exists("res://assets/props/"+file),"provenance/licence shipped: "+file)
	for language in ["fi","en","de"]:
		var notice: String = T.text("credits_swing",language)
		check(notice.contains("Swing Set") and notice.contains("Grab3D") and notice.contains("CC0"),"localized source credit: "+language)
		check(Startup.credits_text(language).contains(notice),"credits menu shows locale notice: "+language)

func run() -> void:
	test_swing_uses_kit_geometry()
	test_swing_placement_and_lifecycle()
	test_swing_source_and_credits()
	print("SWING_GLB failures=",failures)
	quit(1 if failures else 0)
