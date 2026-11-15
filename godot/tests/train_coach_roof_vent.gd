## VQA-012: the HVAC feet touch the coach roof through the production merged/pool path.
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
var failures := 0
var checks := 0

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(message)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	B3.opaque = true
	test_vent_attaches_to_roof()
	test_coach_geometry_preserved()
	print("train coach vent: %d checks, %d failed" % [checks, failures])
	quit(int(failures > 0))

func test_vent_attaches_to_roof() -> void:
	var mesh := B3.merged_model("train_coach")
	for surface in mesh.get_surface_count():
		var arrays := mesh.surface_get_arrays(surface)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var name: String = mesh.surface_get_material(surface).resource_name
		if name != "Original black finished iron": continue
		var samples: Array = [arrays[Mesh.ARRAY_INDEX]]
		for lod: Dictionary in RenderingServer.mesh_get_surface(mesh.get_rid(),surface).get("lods",[]).slice(0,3):
			var ids := PackedInt32Array()
			var bytes: PackedByteArray = lod.index_data
			for offset in range(0,bytes.size(),2): ids.append(bytes.decode_u16(offset))
			samples.append(ids)
		check(samples.size() > 1,"coach has generated LOD samples")
		for ids: PackedInt32Array in samples:
			var low := INF
			for i: int in ids:
				var v := vertices[i]
				if absf(v.x)<1.3 and v.y>3.45: low=minf(low,v.y)
			check(absf(low-3.57)<0.01,"coach HVAC feet touch 3.57 m roof in base/LOD (base %.4f)" % low)
	var renderer := B3.new()
	renderer._cars_root = Node3D.new()
	root.add_child(renderer._cars_root)
	for heading: float in [0.0,PI/2,PI,0.73]:
		renderer.begin_cars()
		renderer.vehicle("train",Vector2(13,-7),heading,26.4,2.89,Color.RED,1,2.3,{"profile":"standard"})
		renderer.end_cars()
		var node: Node3D = renderer._model_nodes["train_coach"][0]
		check(node.get_child(0).mesh == mesh,"coach uses production merged mesh after pool reuse")
		var roof := node.transform * Vector3(0,3.57,0.47)
		var foot_y := INF
		for surface in mesh.get_surface_count():
			if mesh.surface_get_material(surface).resource_name != "Original black finished iron": continue
			for v: Vector3 in mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
				if absf(v.x)<1.3 and v.y>3.45: foot_y=minf(foot_y,v.y)
		var foot := node.transform * Vector3(0,foot_y,0.47)
		check(roof.distance_to(foot)<0.01 and node.position.is_equal_approx(Vector3(13,B3.ROAD_M+0.016+2.3,-7)),"coach attachment and elevated placement follow pooled transform")
		check(node.basis.x.normalized().dot(Vector3(cos(heading),0,-sin(heading)))>0.999,"coach orientation preserved")
	renderer._cars_root.free()
	renderer.route_3d.free()
	renderer.free()

func test_coach_geometry_preserved() -> void:
	var mesh := B3.merged_model("train_coach")
	check(mesh.get_surface_count()==8,"coach retains all eight materials")
	var box := mesh.get_aabb()
	check(absf(box.position.x+13.2)<0.001 and absf(box.size.x-26.4)<0.001 and absf(box.size.z-2.89)<0.001 and absf(box.position.y)<0.001,"coach length/width/rail contact preserved")
	var cap := []
	for surface in mesh.get_surface_count():
		if mesh.surface_get_material(surface).resource_name != "Original warm white outdoor paint": continue
		for v: Vector3 in mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
			if absf(v.x)<1.3 and absf(v.z)<0.64 and v.y>3.60: cap.append(v)
	check(cap.size()>=16 and cap.any(func(v): return absf(v.y-3.89)<0.001),"coach vent cap remains recognizable above roof")
	check(B3.merged_model("train_locomotive").get_surface_count()>0,"unaffected locomotive still merges")
