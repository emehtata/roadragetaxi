## VQA-001–005: frontal glass must not be hidden by body triangles, including generated LODs.
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const CASES := {"hatchback": [1.02,1.38], "estate": [1.05,1.46], "suv": [1.10,1.68], "pickup": [1.10,1.73], "panel_van": [1.20,2.16]}
var failures := 0

func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		push_error(message)

func _initialize() -> void:
	for kind: String in CASES:
		test_front_glazing_geometry(kind)
		test_glazing_at_lod_distances(kind)
		test_model_preservation(kind)
	print("vehicle windscreens: %d failed" % failures)
	quit(int(failures > 0))

func depth(vertices: PackedVector3Array, indices: PackedInt32Array, x: float, y: float) -> float:
	var z := -INF
	for at in range(0,indices.size(),3):
		var a := vertices[indices[at]]
		var u := vertices[indices[at+1]]-a
		var v := vertices[indices[at+2]]-a
		var den := u.x*v.y-v.x*u.y
		if absf(den)<0.00000001: continue
		var s := ((x-a.x)*v.y-(y-a.y)*v.x)/den
		var t := (u.x*(y-a.y)-u.y*(x-a.x))/den
		if s>=0 and t>=0 and s+t<=1: z=maxf(z,a.z+s*u.z+t*v.z)
	return z

func test_front_glazing_geometry(kind: String, generated_lods := false) -> void:
	var mesh := B3.merged_model(kind)
	var glass: Array = []
	var paint: Array = []
	for surface in mesh.get_surface_count():
		var name: String = mesh.surface_get_material(surface).resource_name
		var arrays := mesh.surface_get_arrays(surface)
		if name == "glass":
			var front := PackedInt32Array()
			var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
			var all_ids: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
			for at in range(0,all_ids.size(),3):
				var a:=all_ids[at];var b:=all_ids[at+1];var c:=all_ids[at+2]
				var normal: Vector3=(normals[a]+normals[b]+normals[c]).normalized()
				if normal.z>.3 and normal.y>.2 and (vertices[a].z+vertices[b].z+vertices[c].z)>0:
					front.append_array(PackedInt32Array([a,b,c]))
			arrays[Mesh.ARRAY_INDEX]=front
			glass.append(arrays)
		elif name.begins_with("paint"): paint.append([arrays,RenderingServer.mesh_get_surface(mesh.get_rid(),surface).get("lods",[])])
	check(not glass.is_empty() and not paint.is_empty(), "%s glass and paint exist" % kind)
	if generated_lods:
		check(paint.any(func(row: Array) -> bool: return not row[1].is_empty()), "%s generated paint LODs exist" % kind)
	var blocked := 0
	var samples := 0
	for ix in 9:
		for iy in 9:
			var x := lerpf(-0.70,0.70,float(ix)/8)
			var y := lerpf(CASES[kind][0],CASES[kind][1],float(iy)/8)
			var g := -INF
			for arrays: Array in glass: g=maxf(g,depth(arrays[Mesh.ARRAY_VERTEX],arrays[Mesh.ARRAY_INDEX],x,y))
			if g<=0: continue
			samples+=1
			for row: Array in paint:
				var a: Array=row[0]
				var indices: Array=[] if generated_lods else [a[Mesh.ARRAY_INDEX]]
				for lod: Dictionary in (row[1] if generated_lods else []):
					var bytes: PackedByteArray=lod.index_data
					var ids:=PackedInt32Array()
					var wide: bool=a[Mesh.ARRAY_VERTEX].size()>65535
					for offset in range(0,bytes.size(),4 if wide else 2): ids.append(bytes.decode_u32(offset) if wide else bytes.decode_u16(offset))
					indices.append(ids)
				for ids: PackedInt32Array in indices:
					if depth(a[Mesh.ARRAY_VERTEX],ids,x,y)>g+0.002:
						blocked+=1
	check(samples>=60,"%s has useful glass samples" % kind)
	check(blocked==0,"%s paint intersects front glass at %d base/LOD sample rays" % [kind,blocked])

func test_glazing_at_lod_distances(kind: String) -> void:
	test_front_glazing_geometry(kind, true)

func test_model_preservation(kind: String) -> void:
	var source: Node3D=B3.MODEL_SCENES[kind].instantiate()
	var box:=AABB()
	var first:=true
	var materials:={}
	for mi: MeshInstance3D in source.find_children("*","MeshInstance3D",true,false):
		var xform:=Transform3D()
		var node: Node=mi
		while node!=source:
			xform=(node as Node3D).transform*xform
			node=node.get_parent()
		for surface in mi.mesh.get_surface_count():
			var name: String=mi.mesh.surface_get_material(surface).resource_name
			if name=="interior":continue
			materials[name]=true
			for v: Vector3 in mi.mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
				box=AABB(xform*v,Vector3.ZERO) if first else box.expand(xform*v)
				first=false
	var mesh:=B3.merged_model(kind)
	check(mesh.get_aabb().position.is_equal_approx(box.position) and mesh.get_aabb().size.is_equal_approx(box.size),"%s source/pooled bounds preserved" % kind)
	check(mesh.get_surface_count()==materials.size(),"%s source materials preserved" % kind)
	source.free()
