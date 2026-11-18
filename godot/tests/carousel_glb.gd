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

func loop_at(at := Vector2.ZERO, radius := 8.0, angle := 0.0) -> PackedVector2Array:
	var loop:=PackedVector2Array()
	for i in 48: loop.append(at+Vector2(cos(i*TAU/48),sin(i*TAU/48)).rotated(angle)*radius)
	loop.append(loop[0]);return loop

func test_carousel_uses_kit_geometry() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.attractions(out, [["carousel", loop_at()]])
	check(out.deck.is_empty(), "carousel must not use the old solid cuboid")
	var surfaces: Dictionary = out.get("prop_surfaces", {})
	check(surfaces.size() == 3, "fixed body, spinning section and bulb materials retained")
	var faces := PackedVector3Array()
	for part: Dictionary in surfaces.values():
		faces.append_array(part.verts)
		check(part.normals.size() == part.verts.size() and part.uv.size() == part.verts.size() and part.tangents.size() == part.verts.size()*4, "source normals, UVs and tangents survive batching")
		check(part.material is BaseMaterial3D and (part.material.albedo_texture != null or part.material.emission_enabled), "source texture retained")
	check(faces.size() == 21956*3,"all selected source triangles survive production")
	if not faces.is_empty():
		var bounds:=AABB(faces[0],Vector3.ZERO)
		for v:Vector3 in faces:bounds=bounds.expand(v)
		check(bounds.size.x>7.0 and bounds.size.y>6.0 and bounds.size.z>7.0,"authored roof, poles, seats and deck bounds retained")
		check(absf(bounds.position.y)<0.0001,"authored base grounded")

func test_carousel_placement_and_lifecycle() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3.attractions(out, [["carousel", loop_at()]])
	for radius:float in [8.0,1.0]:
		var at := Vector2(17,-23)
		var input := {"rect":Rect2(-50,-50,100,100),"attractions":[["carousel",loop_at(at,radius,0.73)]],"ground_heights":{"origin":Vector2(-50,-50),"step":100.0,"cols":2,"heights":PackedFloat32Array([13.5,13.5,13.5,13.5])}}
		var built := B3.build([],[],Vector2.ZERO,[],[],input)
		for key in out.get("prop_surfaces",{}):
			var ratio := -1.0
			var source:Dictionary=out.prop_surfaces[key]
			var part:Dictionary=built.prop_surfaces[key]
			for i in part.verts.size():
				var v:Vector3=part.verts[i]-Vector3(at.x,13.5,at.y)
				var original:Vector3=source.verts[i]
				if original.length()>0.01:
					var scale := v.length()/original.length()
					if ratio<0: ratio=scale
					check(absf(scale-ratio)<0.0001,"uniform source proportions retained")
				check(v.y>=-0.0001 and Vector2(v.x,v.z).length()<=radius+0.001,"base grounded and footprint fit retained")
	for loop in [PackedVector2Array([Vector2.ZERO,Vector2.ONE]),PackedVector2Array([Vector2.ZERO,Vector2.ZERO,Vector2.ZERO,Vector2.ZERO])]:
		var empty:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.attractions(empty,[["carousel",loop]])
		check(empty.get("prop_surfaces",{}).is_empty(),"degenerate loop skipped")
	var flags := [Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async]
	Chunk.buildings_3d=true;Chunk.outdoor_3d=true;Chunk.build_async=false
	var map := Map.new(); root.add_child(map)
	var points:=[]
	for p:Vector2 in loop_at(Vector2(50,50)):points.append([p.x,p.y])
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"attractions":[["carousel",points],["carousel",points]],"scenery_objects":[[25.0,25.0,"seesaw",0.0]]}
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
				check((node.material_override.albedo_texture != null or node.material_override.emission_enabled), "final chunk keeps source texture")
				check(node.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_ON, "kit casts shadows")
				faces.append(node.mesh.get_faces()); materials[node.material_override]=true
		check(materials.size()==5,"carousel and seesaw materials do not overwrite each other")
		var count := 0
		for part in faces: count+=part.size()
		check(count==(2*21956+10940)*3,"mixed chunk retains two carousels and seesaw")
		if action=="add":first=faces
		else:check(first==faces,"replacement/reload neither duplicates nor loses triangles")
	map.free()
	Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_carousel_source_and_credits() -> void:
	check(ResourceLoader.exists("res://assets/props/carousel.glb"), "Fairground Carousel asset is shipped")
	var path := "res://assets/props/carousel.json"
	check(FileAccess.file_exists(path),"carousel source manifest shipped")
	if FileAccess.file_exists(path):
		var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
		check(FileAccess.get_sha256("res://assets/props/carousel.glb") == provenance.sha256, "shipped GLB matches source manifest hash")
		check(provenance.triangles==21956 and provenance.materials==3,"verified source geometry shipped")
	check(FileAccess.get_file_as_string("res://assets/props/SOURCES.md").contains("Fairground Carousel"),"source attribution shipped")
	check(FileAccess.file_exists("res://assets/props/CC0-1.0.txt"),"CC0 legal text shipped")
	for language in ["fi","en","de"]:
		var notice: String = T.text("credits_carousel",language)
		check(notice.contains("Fairground Carousel") and notice.contains("Grab3D") and notice.contains("CC0"),"localized carousel credit: "+language)
		check(Startup.credits_text(language).contains(notice),"credits menu shows carousel notice: "+language)

func run() -> void:
	test_carousel_uses_kit_geometry()
	test_carousel_placement_and_lifecycle()
	test_carousel_source_and_credits()
	print("CAROUSEL_GLB failures=",failures)
	quit(1 if failures else 0)
