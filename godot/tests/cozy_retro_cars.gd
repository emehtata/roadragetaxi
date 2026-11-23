extends SceneTree
const B3:=preload("res://buildings_3d.gd")
const E:=preload("res://entity_layer.gd")
const Startup:=preload("res://startup.gd")
const FAMILIES:=["saloon","city_car","hatchback","estate","sports","suv","pickup","panel_van"]
var failures:=0
func _initialize()->void:call_deferred("run")
func check(ok:bool,message:String)->void:
	if not ok:failures+=1;printerr("FAIL: ",message)
func test_identity_states_and_reuse()->void:
	B3.use_shaded();var renderer:=B3.new();renderer._cars_root=Node3D.new();root.add_child(renderer._cars_root)
	for family:String in FAMILIES:
		if not B3.MODEL_VARIANTS.has(family):continue
		var width:float=2.0 if family=="panel_van" else 1.8
		var length:float={"city_car":3.8,"pickup":5.0,"panel_van":5.2}.get(family,4.6)
		var shape:Array=E.VAN_SHAPE if family=="panel_van" else []
		if shape.is_empty():
			for candidate:Array in E.CAR_SHAPES:
				if B3.car_model_kind(candidate,length)==family:shape=candidate;break
		check(not shape.is_empty(),"family shape found "+family)
		if shape.is_empty():continue
		var id:=0
		for candidate in 1000:
			if B3.model_variant(family,"retro|"+str(candidate))!=family:id=candidate;break
		var kind:String=B3.model_variant(family,"retro|"+str(id));var reused:Node3D
		var conditional:={}
		for candidate in 2000:
			var candidate_shape:Array=E.VAN_SHAPE if family=="panel_van" else E.CAR_SHAPES[absi(hash(candidate))%E.CAR_SHAPES.size()]
			if B3.car_model_kind(candidate_shape,length)==family:conditional[B3.model_variant(family,"retro|"+str(candidate))]=true
		check(conditional.size()==2,"variant salt independent of body-shape identity hash "+family)
		for bits:int in [0,1,3,4,8,16,31]:
			renderer.begin_cars();renderer.car(Vector2(3,8),0.73,length,width,Color.YELLOW,shape,0,bits,12.0,Vector2(.1,-.06),id)
			renderer.car(Vector2(9,8),0.73,length,width,Color.RED,shape,0,0,12.0,Vector2.ZERO,id)
			var node:Node3D=renderer._model_nodes[kind][0];var mesh:MeshInstance3D=node.get_child(0)
			var other:MeshInstance3D=renderer._model_nodes[kind][1].get_child(0)
			check(mesh.mesh==other.mesh and other.get_instance_shader_parameter("body_paint")==Color.RED and other.get_instance_shader_parameter("lamp_bits")==0,"simultaneous paint/lamps isolated "+kind)
			check(node.basis.orthonormalized().is_equal_approx(Basis(Vector3.UP,.73)*Basis(Vector3.BACK,.1)*Basis(Vector3.RIGHT,-.06)*Basis(Vector3.UP,PI/2)),"heading/pitch/roll preserved "+kind)
			check(mesh.mesh==B3.merged_model(kind),"identity chooses expected source "+kind)
			check(mesh.get_instance_shader_parameter("lamp_bits")==bits,"live lamp bits "+kind)
			check(mesh.get_instance_shader_parameter("body_paint")==Color.YELLOW,"instance paint "+kind)
			check(is_equal_approx(node.position.y,12+B3.ROAD_M+.016),"road deck elevation "+kind)
			if reused!=null:check(reused==node,"pooled node survives parked/moving lamp redraw "+kind)
			reused=node;renderer.end_cars()
		renderer.begin_cars();renderer.car(Vector2.ZERO,0,length,width,Color.WHITE,shape,0)
		check(renderer._model_used[family]==1,"no identity retains primary "+family);renderer.end_cars()
		var overlays:=B3.cozy_car_details(kind,length,width,0,31);var scale:=B3.model_scale(kind,length,width).x
		for first in range(0,overlays.verts.size(),36):
			var centre:=Vector3.ZERO
			for i in range(first,first+36):centre+=overlays.verts[i]/(36.0*scale)
			var point:=Vector3(-centre.z,centre.y,centre.x);var ray:=Vector3(0,0,signf(centre.x)*.05)
			check(not B3._cozy_contact_meshes[kind].intersect_segment(point+ray,point-ray).is_empty(),"reverse/indicator contacts source "+kind)
		var box:=B3.merged_model(kind).get_aabb();var factor:=B3.model_scale(kind,length,width).x
		check(box.size.x*factor>=width*.85 and box.size.z*factor>=length*.85,"representative dimensions within15percent "+kind)
	renderer.begin_cars();renderer.car(Vector2.ZERO,0,4.6,1.8,Color.WHITE,E.CAR_SHAPES[0],2,1,0,Vector2.ZERO,1)
	check(renderer._model_used.saloon==1,"taxi sign forces primary saloon")
	renderer.end_cars();renderer._cars_root.free();renderer.route_3d.free();renderer.free()
func run()->void:
	test_identity_states_and_reuse()
	for family:String in FAMILIES:
		var variants:Array=B3.MODEL_VARIANTS.get(family,[])
		check(variants.size()==2,family+" has primary plus retro variant")
		if variants.size()!=2:continue
		check(variants[0]==family,"primary retained "+family)
		var seen:={}
		for i in 1000:seen[B3.model_variant(family,"retro|"+str(i))]=true
		check(seen.size()==2,"both identity variants reachable "+family)
		var kind:String=variants[1];var source:Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://assets/vehicles/cozy_retro_cars/"+kind+".json"))
		check(FileAccess.get_sha256(B3.MODEL_SCENES[kind].resource_path)==source.sha256,"unchanged source hash "+kind)
		var mesh:=B3.merged_model(kind);var triangles:=0
		for s in mesh.get_surface_count():
			var a:=mesh.surface_get_arrays(s);triangles+=a[Mesh.ARRAY_INDEX].size()/3
			check(a[Mesh.ARRAY_NORMAL].size()==a[Mesh.ARRAY_VERTEX].size(),"normals retained "+kind)
			var material:StandardMaterial3D=mesh.surface_get_material(s)
			if material.albedo_texture!=null:check(a[Mesh.ARRAY_TEX_UV].size()==a[Mesh.ARRAY_VERTEX].size(),"texture UVs retained "+kind)
			if material.normal_texture!=null:check(a[Mesh.ARRAY_TANGENT].size()==a[Mesh.ARRAY_VERTEX].size()*4,"source tangents retained "+kind)
		check(triangles==int(source.triangles),"complete source triangles "+kind)
		var scale:=B3.model_scale(kind,4.6,1.8);var box:=mesh.get_aabb()
		check(is_equal_approx(scale.x,scale.y) and is_equal_approx(scale.y,scale.z),"uniform scale "+kind)
		check(box.size.x*scale.x<=1.801 and box.size.z*scale.z<=4.601,"footprint fit "+kind)
		check(absf(box.position.y)<0.001,"source wheels grounded "+kind)
	for language:String in ["fi","en","de"]:check(Startup.credits_text(language).contains("Cozy Retro Cars"),"displayed retro credits "+language)
	print("COZY_RETRO_CARS failures=",failures);quit(1 if failures else 0)
