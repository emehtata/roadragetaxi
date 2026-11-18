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

func test_slide_uses_kit_geometry() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "slide"]])
	check(out.deck.is_empty(), "slide must not use the old solid cuboid")
	var surfaces: Dictionary = out.get("prop_surfaces", {})
	check(surfaces.size() == 1, "slide's textured material is retained")
	var faces := PackedVector3Array()
	for part: Dictionary in surfaces.values():
		faces.append_array(part.verts)
		check(part.normals.size() == part.verts.size() and part.uv.size() == part.verts.size(), "source normals and UVs survive batching")
		check(part.material is BaseMaterial3D and part.material.albedo_texture != null, "source texture retained")
		for v: Vector3 in part.verts:
			check(absf(v.x) <= 1.601 and absf(v.z) <= 0.451 and v.y >= -0.001 and v.y <= 1.801, "uniform asset fits existing envelope")
	check(faces.size() == 15988 * 3, "production contains all source triangles")
	if not faces.is_empty():
		var mesh := TriangleMesh.new(); mesh.create_from_faces(faces)
		check(mesh.intersect_segment(Vector3(0,0.1,-1),Vector3(0,0.1,1)).is_empty(), "open space under the slide is not a solid wall")
		var upper := mesh.intersect_segment(Vector3(-0.2,2,0),Vector3(-0.2,0,0))
		var lower := mesh.intersect_segment(Vector3(1.1,2,0),Vector3(1.1,0,0))
		check(not upper.is_empty() and not lower.is_empty() and upper.position.y > lower.position.y+0.4, "chute descends toward local +X and includes run-out")
		var deck := mesh.intersect_segment(Vector3(-0.65,2,0),Vector3(-0.65,0,0))
		var ladder := mesh.intersect_segment(Vector3(-1.5,2,0),Vector3(-1.5,0,0))
		check(not deck.is_empty() and absf(deck.position.y-0.9931)<0.001, "raised source deck survives batching")
		check(not ladder.is_empty() and absf(ladder.position.y-0.1655)<0.001, "rear ladder lower rung survives batching")

func test_slide_placement_and_lifecycle() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "slide"]])
	var at := Vector2(17, -23)
	var angle := 0.73
	var grid := {"origin": Vector2(-50,-50), "step": 100.0, "cols": 2, "heights": PackedFloat32Array([13.5,13.5,13.5,13.5])}
	var input := {"rect": Rect2(-50,-50,100,100), "props": [[at,angle,"slide"],[at,angle,"bench"]], "ground_heights": grid}
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
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[25.0,25.0,"slide",0.73],[35.0,25.0,"swing",0.0],[45.0,25.0,"slide",0.0]]}
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
		check(materials.size()==4,"mixed slide/swing materials do not overwrite each other")
		var count := 0
		for part in faces: count+=part.size()
		check(count==(2*15988+19740)*3,"mixed chunk retains two complete slides and one swing")
		if action=="add":first=faces
		else:check(first==faces,"replacement/reload neither duplicates nor loses triangles")
	map.free()
	Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_slide_source_and_credits() -> void:
	check(ResourceLoader.exists("res://assets/props/playground_slide.glb"), "Playground Slide asset is shipped")
	var path := "res://assets/props/playground_slide.json"
	check(FileAccess.file_exists(path),"slide source manifest shipped")
	if FileAccess.file_exists(path):
		var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
		check(FileAccess.get_sha256("res://assets/props/playground_slide.glb") == provenance.sha256, "shipped GLB matches source manifest hash")
	check(FileAccess.get_file_as_string("res://assets/props/SOURCES.md").contains("Playground Slide"),"source attribution shipped")
	check(FileAccess.file_exists("res://assets/props/CC0-1.0.txt"),"CC0 legal text shipped")
	for language in ["fi","en","de"]:
		var notice: String = T.text("credits_slide",language)
		check(notice.contains("Playground Slide") and notice.contains("Grab3D") and notice.contains("CC0"),"localized slide credit: "+language)
		check(Startup.credits_text(language).contains(notice),"credits menu shows slide notice: "+language)

func run() -> void:
	test_slide_uses_kit_geometry()
	test_slide_placement_and_lifecycle()
	test_slide_source_and_credits()
	print("SLIDE_GLB failures=",failures)
	quit(1 if failures else 0)
