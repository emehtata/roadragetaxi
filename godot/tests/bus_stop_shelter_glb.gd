extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const Chunk := preload("res://map_chunk.gd")
const Map := preload("res://map_layer.gd")
const Startup := preload("res://startup.gd")
var failures := 0
func _initialize() -> void: call_deferred("run")
func check(ok: bool, message: String) -> void:
	if not ok: failures += 1; printerr("FAIL: ", message)
func run() -> void:
	var b := B3.new()
	check(b.has_method("shelter_placement"), "mapped shelter uses GLB placement")
	if b.has_method("shelter_placement"):
		test_source_and_provenance()
		test_footprint_placement(b)
		test_controls_and_cache()
		test_chunk_streaming()
	b.route_3d.free(); b.free()
	print("BUS_STOP_SHELTER_GLB failures=", failures)
	quit(1 if failures else 0)
func test_source_and_provenance() -> void:
	var path := "res://assets/props/bus_stop_shelter"
	var provenance: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path+".json"))
	check(FileAccess.get_sha256(path+".glb")==provenance.sha256,"unchanged source hash")
	var count := 0
	var surfaces := B3.prop_model_surfaces("bus_stop_shelter")
	for part: Dictionary in surfaces.values():
		count += part.verts.size()/3
		check(part.material != null,"source material retained")
		if "glass_" in part.material.resource_name:check(part.material.transparency==BaseMaterial3D.TRANSPARENCY_ALPHA and part.material.albedo_color.a < 1,"glass remains see-through")
		check(part.normals.size()==part.verts.size() and part.uv.size()==part.verts.size() and part.tangents.size()==part.verts.size()*4,"source attributes retained")
	check(count==10972 and surfaces.size()==5,"all authored frame, glass and light surfaces")
	for suffix in [".LICENSE.txt",".source.json"]:check(FileAccess.file_exists(path+suffix),"original notice retained")
	for language in ["fi","en","de"]:check(Startup.credits_text(language).contains("Bus Stop Shelter"),"displayed attribution "+language)
func test_footprint_placement(b: Node) -> void:
	for angle in [0.0,0.73,PI]:
		for side in [-1.0,1.0]:
			var footprint := PackedVector2Array()
			for p in [Vector2(-2.5,-.8),Vector2(2.5,-.8),Vector2(2.5,.8),Vector2(-2.5,.8)]:footprint.append(Vector2(17,23)+p.rotated(angle)*Vector2(1,side))
			var placement: Dictionary = b.call("shelter_placement",footprint)
			check(not placement.is_empty(),"valid mapped rectangle")
			if placement.is_empty():continue
			var centre := (footprint[0]+footprint[2])*.5
			var front := (footprint[0]+footprint[1])*.5-centre
			var direction := Vector2(cos(placement.angle),-sin(placement.angle))
			check(-direction.orthogonal().dot(front)>0,"authored front faces first edge")
			for part: Dictionary in B3.prop_model_surfaces("bus_stop_shelter").values():
				for vertex: Vector3 in part.verts:
					var transformed: Vector2 = Vector2(vertex.x,vertex.z).rotated(-placement.angle)*placement.scale+centre
					check(Geometry2D.is_point_in_polygon(transformed,footprint) or footprint[0].distance_to(transformed)<.001,"uniform whole-model containment")
	for footprint in [PackedVector2Array(),PackedVector2Array([Vector2.ZERO,Vector2.ZERO,Vector2.ZERO,Vector2.ZERO])]:check((b.call("shelter_placement",footprint) as Dictionary).is_empty(),"invalid footprint skipped")
func test_controls_and_cache() -> void:
	var footprint := PackedVector2Array([Vector2(-2.5,-.8),Vector2(2.5,-.8),Vector2(2.5,.8),Vector2(-2.5,.8)])
	var out := B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"shelters":[[footprint,"shelter"]]})
	var count := 0
	for part: Dictionary in out.get("prop_surfaces",{}).values():count+=part.verts.size()/3
	var grid := {"origin":Vector2(-50,-50),"step":100.0,"cols":2,"rows":2,"heights":PackedFloat32Array([5,10,8,13])}
	var slope := B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"shelters":[[footprint,"shelter"]],"ground_heights":grid})
	for key in out.prop_surfaces:
		var flat: Dictionary = out.prop_surfaces[key]
		var draped: Dictionary = slope.prop_surfaces[key]
		for i in flat.verts.size():
			var expected: Vector3 = flat.verts[i]
			expected.y += B3.ground_height(grid,Vector2(expected.x,expected.z))
			check(expected.distance_to(draped.verts[i])<0.0001,"source contacts and every surface follow DEM")
	var pavement := B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"roads":[[PackedVector2Array([Vector2(-10,0),Vector2(10,0)]),3.0,Color.GRAY,3,null,false]],"shelters":[[footprint,"shelter"]]})
	var lift := B3.ROAD_M+0.002*3
	check(absf(B3.shelter_surface_lift(pavement.shelter_placements[0].ground,Vector2.ZERO,false)-lift)<0.00001,"base sits on drawn pavement instead of bare DEM")
	for key in out.prop_surfaces:
		for i in out.prop_surfaces[key].verts.size():
			check(absf(pavement.prop_surfaces[key].verts[i].y-out.prop_surfaces[key].verts[i].y-lift)<0.00001,"whole source retains rigid pavement lift")
	var edge := B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"roads":[[PackedVector2Array([Vector2(-10,.65),Vector2(10,.65)]),.25,Color.GRAY,3,null,false]],"shelters":[[footprint,"shelter"]]})
	var front := 0; var back := 0
	for key in out.prop_surfaces:
		for i in out.prop_surfaces[key].verts.size():
			var vertex: Vector3 = out.prop_surfaces[key].verts[i]
			if vertex.y > .005: continue
			var delta: float = edge.prop_surfaces[key].verts[i].y-vertex.y
			if vertex.z > .4 and vertex.z < .9: check(absf(delta-lift)<0.00001,"front support sits on higher pavement"); front += 1
			if vertex.z < -.4: check(absf(delta)<0.00001,"rear support retains lower ground contact"); back += 1
	check(front > 0 and back > 0,"real supports straddle a pavement edge")
	check(count==10972 and out.deck.is_empty(),"source replaces procedural roof/posts exactly once")
	var control := B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"shelters":[[footprint,"bench"]]})
	check(not control.deck.is_empty() and control.get("prop_surfaces",{}).is_empty(),"standalone bench retained")
	check(B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"shelters":[]}).get("prop_surfaces",{}).is_empty(),"unsheltered stop has no model")
	check(is_same(B3.prop_model_surfaces("bus_stop_shelter"),B3.prop_model_surfaces("bus_stop_shelter")),"immutable source cache reused")

func test_chunk_streaming() -> void:
	B3.use_shaded()
	var flags := [Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async]
	Chunk.buildings_3d = true; Chunk.outdoor_3d = true; Chunk.build_async = false
	var map := Map.new(); root.add_child(map)
	var message := {"chunk_id":"0_0","bounds":[0,0,100,100],"bus_stops":[{"bay":[[20,20],[70,20],[65,23],[25,23]],"label":[45,22],"angle":0,"shelter":[[42.5,25],[47.5,25],[47.5,26.6],[42.5,26.6]],"bench":null}]}
	var original := []
	for action in ["add","replace","reload"]:
		if action == "add": map.add_chunk(message.duplicate(true))
		elif action == "replace": map.replace_chunk(message.duplicate(true))
		else: map.clear(); map.add_chunk(message.duplicate(true))
		var count := 0; var geometry := []
		for mesh: MeshInstance3D in map._chunks["0_0"].meshes_3d:
			if not mesh.has_meta("prop_material"): continue
			count += mesh.mesh.get_faces().size(); geometry.append(mesh.mesh.get_faces())
			check(mesh.layers==B3.LAYER_BUILDINGS and mesh.cast_shadow==GeometryInstance3D.SHADOW_CASTING_SETTING_ON,"mapped shelter layer/shadow policy")
		check(count==10972*3,"actual chunk retains all shelter geometry on "+action)
		if action == "add": original = geometry
		else: check(original==geometry,"streamed replacement/reload retains complete source")
	map.free(); Chunk.buildings_3d = flags[0]; Chunk.outdoor_3d = flags[1]; Chunk.build_async = flags[2]
