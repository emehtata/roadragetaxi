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

func test_climbing_frame_uses_kit_geometry() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "climbing_frame"]])
	check(out.deck.is_empty(), "climbing_frame must not use the old solid cuboid")
	var surfaces: Dictionary = out.get("prop_surfaces", {})
	check(surfaces.size() == 1, "light frame material retained")
	var faces := PackedVector3Array()
	for part: Dictionary in surfaces.values():
		faces.append_array(part.verts)
		check(part.normals.size() == part.verts.size() and part.uv.size() == part.verts.size() and part.tangents.size() == part.verts.size()*4, "source normals, UVs and tangents survive batching")
		check(part.material is BaseMaterial3D and part.material.albedo_texture != null, "source texture retained")
		for v: Vector3 in part.verts:
			check(absf(v.x)<=1.201 and absf(v.z)<=1.201 and Vector2(v.x,v.z).length()<=1.8001 and v.y>=-0.001 and v.y<=1.601,"uniform model fits envelope and clearance")
	check(faces.size() == 13734*3,"all light source triangles survive production")
	if not faces.is_empty():
		var bounds:=AABB(faces[0],Vector3.ZERO)
		for v:Vector3 in faces:bounds=bounds.expand(v)
		check(bounds.size.is_equal_approx(Vector3(1.6664234,1.6,1.333177)),"uniform fit retains measured proportions")
		var mesh:=TriangleMesh.new();mesh.create_from_faces(faces)
		check(mesh.intersect_segment(Vector3(-0.35,0.3,0),Vector3(0.35,0.3,0)).is_empty(),"open space below platform does not become a cuboid")
		check(not mesh.intersect_segment(Vector3(0,0.3,0.9),Vector3(0,0.3,0.5)).is_empty(),"front climbing wall remains attached")
		check(not mesh.intersect_segment(Vector3(0,1.42,-0.9),Vector3(0,1.42,-0.5)).is_empty(),"upper rear ladder remains present")
		check(not mesh.intersect_segment(Vector3(0.9,0.9,0),Vector3(0.3,0.9,0)).is_empty(),"right rope-net connector remains present")
		check(not mesh.intersect_segment(Vector3(-0.4,1.42,0),Vector3(0.4,1.42,0)).is_empty(),"overhead monkey bar remains present")

func test_climbing_frame_placement_and_lifecycle() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "climbing_frame"]])
	var at := Vector2(17, -23)
	var angle := 0.73
	var grid := {"origin": Vector2(-50,-50), "step": 100.0, "cols": 2, "heights": PackedFloat32Array([13.5,13.5,13.5,13.5])}
	var input := {"rect": Rect2(-50,-50,100,100), "props": [[at,angle,"climbing_frame"],[at,angle,"bench"]], "ground_heights": grid}
	var built := B3.build([], [], Vector2.ZERO, [], [], input)
	var placement := Transform3D(Basis(Vector3.UP,angle),B3.to_3d(at,13.5))
	for key in out.get("prop_surfaces", {}):
		var a: Dictionary = out.prop_surfaces[key]
		var b: Dictionary = built.prop_surfaces[key]
		check(a.verts.size() == b.verts.size(), "all transformed triangles retained")
		var error := 0.0
		for i in a.verts.size(): error = maxf(error, (placement * a.verts[i]).distance_to(b.verts[i]))
		check(error < 0.00002, "row angle, translation and DEM placement match")
	check(not built.deck.is_empty(), "unrelated bench keeps original geometry")
	var flags := [Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async]
	Chunk.buildings_3d=true;Chunk.outdoor_3d=true;Chunk.build_async=false
	var map := Map.new(); root.add_child(map)
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[25.0,25.0,"climbing_frame",0.73],[35.0,25.0,"swing",0.0],[45.0,25.0,"slide",0.0],[55.0,25.0,"climbing_frame",0.0],[65.0,25.0,"spring_rider",0.0]]}
	var first := []
	for action in ["add","replace","reload"]:
		if action=="add": map.add_chunk(message.duplicate(true))
		elif action=="replace": map.replace_chunk(message.duplicate(true))
		else:
			map.clear();check(map._chunks.is_empty(),"chunk unload removes old geometry")
			map.add_chunk(message.duplicate(true))
		var faces := []
		var materials := {}
		for node: MeshInstance3D in map._chunks["0_0"].meshes_3d:
			if node.has_meta("prop_material"):
				check(node.material_override.albedo_texture != null, "final chunk keeps source texture")
				check(node.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_ON, "kit casts shadows")
				faces.append(node.mesh.get_faces()); materials[node.material_override]=true
		check(materials.size()==7,"mixed frame/rider/slide/swing materials do not overwrite each other")
		var count := 0
		for part in faces: count+=part.size()
		check(count==(2*13734+17858+15988+19740)*3,"mixed chunk retains two frames, rider, slide and swing")
		if action=="add":first=faces
		else:check(first==faces,"replacement/reload neither duplicates nor loses triangles")
	map.free()
	Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_climbing_frame_source_and_credits() -> void:
	check(ResourceLoader.exists("res://assets/props/climbing_frame.glb"), "Climbing Frame asset is shipped")
	var path := "res://assets/props/climbing_frame.json"
	check(FileAccess.file_exists(path),"climbing_frame source manifest shipped")
	if FileAccess.file_exists(path):
		var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
		check(FileAccess.get_sha256("res://assets/props/climbing_frame.glb") == provenance.sha256, "shipped GLB matches source manifest hash")
		check(provenance.variant=="light" and provenance.triangles==13734,"verified Light variant shipped")
	check(FileAccess.get_file_as_string("res://assets/props/SOURCES.md").contains("Climbing Frame"),"source attribution shipped")
	check(FileAccess.file_exists("res://assets/props/CC0-1.0.txt"),"CC0 legal text shipped")
	for language in ["fi","en","de"]:
		var notice: String = T.text("credits_climbing_frame",language)
		check(notice.contains("Climbing Frame") and notice.contains("Grab3D") and notice.contains("CC0"),"localized climbing_frame credit: "+language)
		check(Startup.credits_text(language).contains(notice),"credits menu shows climbing_frame notice: "+language)

func run() -> void:
	test_climbing_frame_uses_kit_geometry()
	test_climbing_frame_placement_and_lifecycle()
	test_climbing_frame_source_and_credits()
	print("CLIMBING_FRAME_GLB failures=",failures)
	quit(1 if failures else 0)
