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

func test_spring_rider_uses_kit_geometry() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "spring_rider"]])
	check(out.deck.is_empty(), "spring_rider must not use the old solid cuboid")
	var surfaces: Dictionary = out.get("prop_surfaces", {})
	check(surfaces.size() == 2, "base and ladybug materials retained")
	var faces := PackedVector3Array()
	var base := 0; var spring := 0; var seat := 0; var high := 0
	for part: Dictionary in surfaces.values():
		faces.append_array(part.verts)
		check(part.normals.size() == part.verts.size() and part.uv.size() == part.verts.size(), "source normals and UVs survive batching")
		check(part.material is BaseMaterial3D and part.material.albedo_texture != null, "source texture retained")
		for v: Vector3 in part.verts:
			check(Vector2(v.x,v.z).length() <= 0.8001 and v.y >= -0.001 and v.y <= 0.801, "uniform asset fits reserved clearance and height")
			if v.y < 0.03: base += 1
			elif v.y < 0.3: spring += 1
			elif v.y < 0.68: seat += 1
			else: high += 1
	check(faces.size() == 17858 * 3, "production contains all source triangles")
	check(base > 100 and spring > 100 and seat > 100 and high > 100, "base plate, spring, body/seat and upper grips survive batching")
	if not faces.is_empty():
		var bounds := AABB(faces[0],Vector3.ZERO)
		for v: Vector3 in faces: bounds=bounds.expand(v)
		check(bounds.size.is_equal_approx(Vector3(0.7741582,0.8,0.608769)), "uniform height fit retains actual model proportions")
		var mesh := TriangleMesh.new(); mesh.create_from_faces(faces)
		check(mesh.intersect_segment(Vector3(0,0.3,0),Vector3(0,0.05,0)).is_empty(), "open spring centre does not become a solid cuboid")

		var front := mesh.intersect_segment(Vector3(0.28,1,0),Vector3(0.28,0.35,0))
		var rear := mesh.intersect_segment(Vector3(-0.28,1,0),Vector3(-0.28,0.35,0))
		check(not front.is_empty() and not rear.is_empty() and front.position.y > rear.position.y+0.005, "ladybug head sample faces +X while rear shell remains behind")

func test_spring_rider_placement_and_lifecycle() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.props(out, [[Vector2.ZERO, 0.0, "spring_rider"]])
	var at := Vector2(17, -23)
	var angle := 0.73
	var grid := {"origin": Vector2(-50,-50), "step": 100.0, "cols": 2, "heights": PackedFloat32Array([13.5,13.5,13.5,13.5])}
	var input := {"rect": Rect2(-50,-50,100,100), "props": [[at,angle,"spring_rider"],[at,angle,"bench"]], "ground_heights": grid}
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
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[25.0,25.0,"spring_rider",0.73],[35.0,25.0,"swing",0.0],[45.0,25.0,"slide",0.0],[55.0,25.0,"spring_rider",0.0]]}
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
		check(materials.size()==6,"mixed spring-rider/slide/swing materials do not overwrite each other")
		var count := 0
		for part in faces: count+=part.size()
		check(count==(2*17858+15988+19740)*3,"mixed chunk retains two complete spring riders, one slide and one swing")
		if action=="add":first=faces
		else:check(first==faces,"replacement/reload neither duplicates nor loses triangles")
	map.free()
	Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_spring_rider_source_and_credits() -> void:
	check(ResourceLoader.exists("res://assets/props/spring_rider.glb"), "Spring Rider asset is shipped")
	var path := "res://assets/props/spring_rider.json"
	check(FileAccess.file_exists(path),"spring_rider source manifest shipped")
	if FileAccess.file_exists(path):
		var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
		check(FileAccess.get_sha256("res://assets/props/spring_rider.glb") == provenance.sha256, "shipped GLB matches source manifest hash")
	check(FileAccess.get_file_as_string("res://assets/props/SOURCES.md").contains("Spring Rider"),"source attribution shipped")
	check(FileAccess.file_exists("res://assets/props/CC0-1.0.txt"),"CC0 legal text shipped")
	for language in ["fi","en","de"]:
		var notice: String = T.text("credits_spring_rider",language)
		check(notice.contains("Spring Rider") and notice.contains("Grab3D") and notice.contains("CC0"),"localized spring_rider credit: "+language)
		check(Startup.credits_text(language).contains(notice),"credits menu shows spring_rider notice: "+language)

func run() -> void:
	test_spring_rider_uses_kit_geometry()
	test_spring_rider_placement_and_lifecycle()
	test_spring_rider_source_and_credits()
	print("SPRING_RIDER_GLB failures=",failures)
	quit(1 if failures else 0)
