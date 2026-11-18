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

func test_seesaw_uses_kit_geometry() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "seesaw"]])
	check(out.deck.is_empty(), "seesaw must not use the old solid cuboid")
	var surfaces: Dictionary = out.get("prop_surfaces", {})
	check(surfaces.size() == 2, "beam and body materials retained")
	var faces := PackedVector3Array()
	for part: Dictionary in surfaces.values():
		faces.append_array(part.verts)
		check(part.normals.size() == part.verts.size() and part.uv.size() == part.verts.size() and part.tangents.size() == part.verts.size()*4, "source normals, UVs and tangents survive batching")
		check(part.material is BaseMaterial3D and part.material.albedo_texture != null, "source texture retained")
		for v: Vector3 in part.verts:
			check(absf(v.x)<=1.501 and absf(v.z)<=0.151 and Vector2(v.x,v.z).length()<=1.7001 and v.y>=-0.001 and v.y<=0.601,"uniform model fits envelope and clearance")
	check(faces.size() == 10940*3,"all source triangles survive production")
	if not faces.is_empty():
		var bounds:=AABB(faces[0],Vector3.ZERO)
		for v:Vector3 in faces:bounds=bounds.expand(v)
		check(bounds.size.is_equal_approx(Vector3(1.4947629,0.6,0.2299635)),"uniform fit retains measured proportions")
		var mesh:=TriangleMesh.new();mesh.create_from_faces(faces)
		check(mesh.intersect_segment(Vector3(0.35,0.08,-0.3),Vector3(0.35,0.08,0.3)).is_empty(),"open space below raised beam remains")
		check(not mesh.intersect_segment(Vector3(0,0.5,0),Vector3(0,0.05,0)).is_empty(),"central fulcrum supports the beam")
		check(not mesh.intersect_segment(Vector3(-0.6,0.65,0),Vector3(-0.6,0.02,0)).is_empty(),"lower seat and handle remain")
		check(not mesh.intersect_segment(Vector3(0.6,0.65,0),Vector3(0.6,0.02,0)).is_empty(),"raised seat and handle remain")

func test_seesaw_placement_and_lifecycle() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "seesaw"]])
	var at := Vector2(17, -23)
	var angle := 0.73
	var grid := {"origin": Vector2(-50,-50), "step": 100.0, "cols": 2, "heights": PackedFloat32Array([13.5,13.5,13.5,13.5])}
	var input := {"rect": Rect2(-50,-50,100,100), "props": [[at,angle,"seesaw"],[at,angle,"bench"]], "ground_heights": grid}
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
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[25.0,25.0,"seesaw",0.73],[35.0,25.0,"swing",0.0],[45.0,25.0,"slide",0.0],[55.0,25.0,"seesaw",0.0],[65.0,25.0,"spring_rider",0.0],[75.0,25.0,"climbing_frame",0.0]]}
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
		check(materials.size()==9,"mixed seesaw/frame/rider/slide/swing materials do not overwrite each other")
		var count := 0
		for part in faces: count+=part.size()
		check(count==(2*10940+13734+17858+15988+19740)*3,"mixed chunk retains two seesaws, frame, rider, slide and swing")
		if action=="add":first=faces
		else:check(first==faces,"replacement/reload neither duplicates nor loses triangles")
	map.free()
	Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_seesaw_source_and_credits() -> void:
	check(ResourceLoader.exists("res://assets/props/seesaw.glb"), "Seesaw asset is shipped")
	var path := "res://assets/props/seesaw.json"
	check(FileAccess.file_exists(path),"seesaw source manifest shipped")
	if FileAccess.file_exists(path):
		var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
		check(FileAccess.get_sha256("res://assets/props/seesaw.glb") == provenance.sha256, "shipped GLB matches source manifest hash")
		check(provenance.triangles==10940 and provenance.materials==2,"verified source geometry shipped")
	check(FileAccess.get_file_as_string("res://assets/props/SOURCES.md").contains("Seesaw"),"source attribution shipped")
	check(FileAccess.file_exists("res://assets/props/CC0-1.0.txt"),"CC0 legal text shipped")
	for language in ["fi","en","de"]:
		var notice: String = T.text("credits_seesaw",language)
		check(notice.contains("Seesaw") and notice.contains("Grab3D") and notice.contains("CC0"),"localized seesaw credit: "+language)
		check(Startup.credits_text(language).contains(notice),"credits menu shows seesaw notice: "+language)

func run() -> void:
	test_seesaw_uses_kit_geometry()
	test_seesaw_placement_and_lifecycle()
	test_seesaw_source_and_credits()
	print("SEESAW_GLB failures=",failures)
	quit(1 if failures else 0)
