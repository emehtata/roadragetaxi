extends SceneTree
const B3:=preload("res://buildings_3d.gd")
const Startup:=preload("res://startup.gd")
var failures:=0
func _initialize()->void:call_deferred("run")
func check(ok:bool,message:String)->void:
	if not ok:failures+=1;printerr("FAIL: ",message)
func run()->void:
	check(B3.MODEL_SCENES.tractor.resource_path=="res://assets/vehicles/cozy_vehicles/tractor.glb","tractor selects kit source")
	var scale:=B3.model_scale("tractor",4.0,2.2)
	check(is_equal_approx(scale.x,scale.y) and is_equal_approx(scale.y,scale.z),"tractor uniformly scaled")
	B3.use_shaded();var renderer:=B3.new();renderer._cars_root=Node3D.new();root.add_child(renderer._cars_root)
	var reused:Node3D
	for plough:bool in [false,true,false,true]:
		for bits:int in [0,1,3,4,8,16,31]:
			renderer.begin_cars();renderer.vehicle("tractor",Vector2(3,8),.73,4.0,2.2,Color.YELLOW,bits,12.0,{"plough":plough,"beacon":plough})
			check(renderer._model_used.get("tractor",0)==1,"ordinary and plough use one source body")
			renderer.vehicle("tractor",Vector2(9,8),.73,4.0,2.2,Color.RED,0,12.0,{"plough":false,"beacon":false})
			var other:MeshInstance3D=renderer._model_nodes.tractor[1].get_child(0)
			check(other.get_instance_shader_parameter("body_paint")==Color.RED and other.get_instance_shader_parameter("lamp_bits")==0,"simultaneous tractor state isolated")
			if renderer._model_used.get("tractor",0)>0:
				var node:Node3D=renderer._model_nodes.tractor[0];var mesh:MeshInstance3D=node.get_child(0)
				check(mesh.mesh==B3.merged_model("tractor"),"source mesh reused")
				check(mesh.get_instance_shader_parameter("lamp_bits")==bits,"lamp state isolated")
				check(mesh.get_instance_shader_parameter("body_paint")==Color.YELLOW,"paint isolated")
				check(is_equal_approx(node.position.y,12+B3.ROAD_M+.016),"road elevation")
				if reused!=null:check(reused==node,"pool reuse across plough transitions")
				reused=node
			renderer.end_cars()
	var details:=B3.model_vehicle_details("tractor",4,2.2,Color.WHITE,0,{})
	var plough:=B3.model_vehicle_details("tractor",4,2.2,Color.WHITE,0,{"plough":true,"beacon":true})
	check(plough.verts.size()-details.verts.size()==7*36,"six blade segments and one beacon only")
	var fallback:=B3._empty_arrays();B3._plough_details(fallback,4,2.2,true,2.75)
	for i in 6*36:check(plough.verts[details.verts.size()+i].is_equal_approx(fallback.verts[i]),"blade retains corrected shape")
	var roof:Dictionary=B3.merged_model("tractor").generate_triangle_mesh().intersect_segment(Vector3(0,4,-1.18),Vector3(0,1,-1.18))
	check(absf(roof.position.y-2.86)<.005,"beacon fitted to authored roof")
	check(B3.MODEL_SCENES.tractor.resource_path=="res://assets/vehicles/cozy_vehicles/tractor.glb","selected source")
	var source:Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://assets/vehicles/cozy_vehicles/tractor.json"))
	check(FileAccess.get_sha256(B3.MODEL_SCENES.tractor.resource_path)==source.sha256,"unchanged download hash")
	check(B3.has_model("tractor") and not B3.has_model("tram") and not B3.has_model("ferry"),"retained no-match vehicle controls")
	var mesh:=B3.merged_model("tractor");var count:=0
	for s in mesh.get_surface_count():
		count+=mesh.surface_get_array_index_len(s)/3
		var arrays:=mesh.surface_get_arrays(s);var material:StandardMaterial3D=mesh.surface_get_material(s)
		check(arrays[Mesh.ARRAY_NORMAL].size()==arrays[Mesh.ARRAY_VERTEX].size(),"source normals retained")
		if material.albedo_texture!=null:check(arrays[Mesh.ARRAY_TEX_UV].size()==arrays[Mesh.ARRAY_VERTEX].size(),"source UVs retained")
		if material.normal_texture!=null:check(arrays[Mesh.ARRAY_TANGENT].size()==arrays[Mesh.ARRAY_VERTEX].size()*4,"source tangents retained")
	check(count==32784,"complete source geometry")
	check(absf(mesh.get_aabb().position.y)<.001,"grounded source wheels")
	var fit:=mesh.get_aabb().size*scale
	check(fit.x<=2.201 and fit.x>=2.2*.85 and fit.z<=4.001 and fit.z>=4*.85,"tractor source fits simulation envelope")
	renderer._cars_root.free();renderer.route_3d.free();renderer.free()
	for language:String in ["fi","en","de"]:check(Startup.credits_text(language).contains("Cozy Vehicles"),"displayed kit credits "+language)
	print("COZY_VEHICLES failures=",failures);quit(1 if failures else 0)
