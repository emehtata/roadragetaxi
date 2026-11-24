extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const MapChunk := preload("res://map_chunk.gd")
const Startup := preload("res://startup.gd")
var failures := 0
func _initialize() -> void: call_deferred("run")
func check(ok: bool, message: String) -> void:
	if not ok: failures += 1; printerr("FAIL: ", message)
func triangles(mesh: Mesh) -> int:
	var count := 0
	for surface in mesh.get_surface_count(): count += mesh.surface_get_array_index_len(surface) / 3
	return count
func run() -> void:
	var source := "res://assets/props/street_light.glb"
	check(FileAccess.file_exists(source), "downloaded street light exists")
	var b := B3.new()
	if not b.has_method("street_light_mesh"):
		check(false, "street lamps use kit source"); b.route_3d.free();b.free()
	else:
		B3.use_shaded()
		b._view=SubViewport.new();B3.current=b
		var host:=Node2D.new();host.add_child(b)
		for i in B3.STREET_POOL:b._street_lights.append(SpotLight3D.new())
		var mesh: ArrayMesh = b.call("street_light_mesh")
		check(triangles(mesh) == 5280 and mesh.get_surface_count() == 2, "all source pole and LED triangles")
		for surface in mesh.get_surface_count():
			var arrays := mesh.surface_get_arrays(surface)
			check(arrays[Mesh.ARRAY_NORMAL].size() == arrays[Mesh.ARRAY_VERTEX].size(), "source normals")
			if mesh.surface_get_material(surface).albedo_texture != null:
				check(arrays[Mesh.ARRAY_TEX_UV].size() == arrays[Mesh.ARRAY_VERTEX].size(), "source UV")
		var grid := {"origin":Vector2.ZERO,"step":100.0,"cols":2,"rows":2,"heights":PackedFloat32Array([6,12,6,12])}
		for angle in [0.0,0.73,PI]:
			var at := Vector2(51.2,10)
			var direction := Vector2(cos(angle),-sin(angle))
			var data: Dictionary = B3.lamp_posts_arrays([[at,direction]],grid)
			check(data.transforms.size()==1,"one transform per lamp")
			var transform: Transform3D = data.transforms[0]
			check(absf(transform.basis.x.length()-transform.basis.y.length())<.00001 and absf(transform.basis.y.length()-transform.basis.z.length())<.00001,"uniform pole fit")
			var panel: Vector3 = b.call("street_light_position",at,direction,grid)
			check(Vector2(panel.x,panel.z).distance_to(at)<.00001,"panel horizontal anchor")
			var base: Vector3 = transform*Vector3(0,0,-0.9071458578109741)
			check(absf(base.y-B3.ground_height(grid,Vector2(base.x,base.z)))<.00001,"source base on DEM")
			var node: Node3D = B3.lamp_posts_node([[at,direction]],grid)
			check(node.get_child_count()==1 and (node.get_child(0) as MultiMeshInstance3D).multimesh.mesh==mesh,"cached shared lamp mesh")
			node.free()
		check(B3.lamp_posts_node([])==null,"empty lamps return no node")
		b.call("set_street_light_emission",0.0)
		var panel_material: StandardMaterial3D = mesh.surface_get_material(1)
		check(not panel_material.emission_enabled,"day panel dark")
		b.call("set_street_light_emission",0.5)
		check(panel_material.emission_enabled and is_equal_approx(panel_material.emission_energy_multiplier,1.5),"dusk panel follows existing artificial level")
		b.call("set_street_light_emission",1.0)
		check(is_equal_approx(panel_material.emission_energy_multiplier,3.0),"night panel on")
		check(mesh==b.call("street_light_mesh"),"emission update reuses geometry")
		var light_point:=B3.street_light_position(Vector2(51.2,10),Vector2.RIGHT,grid)
		b.set_area_lights(.5,[[Vector2(51.2,10),11.0,0.0,light_point]],[],[])
		check(b._street_lights[0].position.is_equal_approx(light_point),"pooled light uses source panel DEM position")
		b.fade_lamps(.5)
		check(b._street_lights[0].visible ,"pool light visibility follows existing fade")
		b.set_area_lights(.5,[],[],[]);b.fade_lamps(.5)
		check(not b._street_lights[0].visible and b._lamp_keys[0]==Vector2.INF,"removed lamp releases faded pool entry")

		var chunk := MapChunk.new()
		chunk._data={"street_lights":[[0,0,0,10],[5,0,0,10]]}
		chunk.street_lights=PackedVector2Array([Vector2.ZERO,Vector2(5,0)])
		chunk._broken=PackedInt32Array([0]);chunk.build_async=false
		chunk._lamps_3d()
		var lamps:Node3D=chunk._dynamic_3d.get("lamps")
		check(lamps!=null and (lamps.get_child(0) as MultiMeshInstance3D).multimesh.instance_count==1,"broken lamp removed, neighbor retained")
		var reused=lamps
		chunk._lamps_ready({"transforms":[]},chunk._lamp_build-1)
		check(chunk._dynamic_3d.get("lamps")==reused,"stale worker cannot replace current batch")
		var bollards:=B3.trees_node([],PackedVector2Array([Vector2(13,8)]),grid)
		check(bollards.get_child_count()==1 and bollards.get_child(0).get_meta("urban_kind","")=="bollard","mapped bollard uses kit")
		var batch:MultiMesh=bollards.get_child(0).multimesh
		check(triangles(batch.mesh)==1180 and absf(batch.mesh.get_aabb().size.y*B3.bollard_transform(Vector2(13,8),grid).basis.y.length()-.9)<.0001,"complete uniformly fitted bollard")
		bollards.free()
		var path:="res://assets/props/"
		for kind in ["street_light","bollard"]:
			var provenance:Dictionary=JSON.parse_string(FileAccess.get_file_as_string(path+kind+".json"))
			check(FileAccess.get_sha256(path+kind+".glb")==provenance.sha256,"original downloaded source hash")
		chunk.free()
		for lamp in b._street_lights:lamp.free()
		b._view.free();b.route_3d.free();host.free();B3.current=null
	for language in ["fi","en","de"]:check(Startup.credits_text(language).contains("Street Light"),"displayed source attribution "+language)
	print("STREET_LIGHT_GLB failures=",failures)
	quit(1 if failures else 0)
