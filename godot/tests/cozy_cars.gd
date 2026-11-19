extends SceneTree
const B3:=preload("res://buildings_3d.gd")
const E:=preload("res://entity_layer.gd")
const T:=preload("res://i18n.gd")
const Startup:=preload("res://startup.gd")
const SOURCES:={"saloon":"electric-car","city_car":"compact-car","hatchback":"rally-car","estate":"station-wagon","sports":"coupe","suv":"off-road-4x4","pickup":"vintage-truck"}
const TRIANGLES:={"saloon":17770,"city_car":17338,"hatchback":19726,"estate":19308,"sports":16856,"suv":19882,"pickup":19709}
const SIZES:={"saloon":Vector2(4.6,1.8),"city_car":Vector2(3.8,1.7),"hatchback":Vector2(4.5,1.8),"estate":Vector2(4.8,1.85),"sports":Vector2(4.7,1.8),"suv":Vector2(4.8,1.9),"pickup":Vector2(5.0,1.9)}
var failures:=0
func _initialize()->void:call_deferred("run")
func check(ok:bool,message:String)->void:
	if not ok:failures+=1;printerr("FAIL: ",message)
func test_primary_models_use_kit_sources()->void:
	for kind:String in SOURCES:
		var path:String=B3.MODEL_SCENES[kind].resource_path
		check(path.contains(SOURCES[kind].replace("-","_")) and (path.contains("cozy_cars") or kind=="estate"),kind+" production mapping uses kit GLB")
		var mesh:=B3.merged_model(kind);var count:=0;var textured:=0
		for surface in mesh.get_surface_count():
			var data:=mesh.surface_get_arrays(surface);count+=data[Mesh.ARRAY_INDEX].size()/3
			check(data[Mesh.ARRAY_NORMAL].size()==data[Mesh.ARRAY_VERTEX].size(),"source normals retained")
			var material:StandardMaterial3D=mesh.surface_get_material(surface)
			if material.albedo_texture!=null:textured+=1;check(data[Mesh.ARRAY_TEX_UV].size()==data[Mesh.ARRAY_VERTEX].size(),"source UV retained")
		check(count==TRIANGLES[kind],kind+" all source parts/triangles retained")
		check(textured>=2 and mesh.get_surface_count()<10,kind+" textured body/tires and equivalent wheel batching retained")
	check(B3.MODEL_SCENES.panel_van.resource_path=="res://assets/vehicles/panel_van.glb","passenger minivan does not replace cargo-van role")
func test_front_glass_remains_open()->void:
	for kind:String in SOURCES:
		var mesh:=B3.merged_model(kind);var opaque:=PackedVector3Array();var windows:=PackedVector3Array()
		for surface in mesh.get_surface_count():
			var data:=mesh.surface_get_arrays(surface);var target:PackedVector3Array=windows if "window_glass" in mesh.surface_get_material(surface).resource_name else opaque
			for index:int in data[Mesh.ARRAY_INDEX]:target.append(data[Mesh.ARRAY_VERTEX][index])
			if "window_glass" in mesh.surface_get_material(surface).resource_name:windows=target
			else:opaque=target
		var body:=TriangleMesh.new();body.create_from_faces(opaque);var samples:=0;var hidden:=0
		for i in range(0,windows.size(),3):
			var normal:Vector3=(windows[i+1]-windows[i]).cross(windows[i+2]-windows[i]).normalized();if normal.z<0:normal=-normal
			var point:Vector3=(windows[i]+windows[i+1]+windows[i+2])/3
			if normal.z<0.5 or point.z<0 or point.y<0.8 or absf(point.x)>B3.COZY_CARS[kind].size.x*0.3:continue
			samples+=1
			if not body.intersect_segment(point+normal*0.3,point+normal*0.005).is_empty():hidden+=1
		# The coupe has an authored wiper crossing one centroid ray.
		check(samples>=4 and hidden<=(1 if kind=="sports" else 0),"kit front glass clear of body triangles "+kind+" blocked="+str(hidden))

func test_car_fit_heading_ground_and_attachments()->void:
	for kind:String in SOURCES:
		var size:Vector2=SIZES[kind];var scale:=B3.model_scale(kind,size.x,size.y);var box:=B3.merged_model(kind).get_aabb()
		check(is_equal_approx(scale.x,scale.y) and is_equal_approx(scale.y,scale.z),"uniform proportions/round wheels "+kind)
		check(box.size.x*scale.x<=size.y+0.001 and box.size.z*scale.z<=size.x+0.001,"fit simulated footprint "+kind)
		check(box.size.x*scale.x>=size.y*0.85 and box.size.z*scale.z>=size.x*0.85,"fit stays within15percent "+kind)
		check(absf(box.position.y)<0.00001,"source wheels at ground zero "+kind)
	for kind:String in SOURCES:
		var size:Vector2=SIZES[kind];var overlays:=B3.cozy_car_details(kind,size.x,size.y,0,31);var factor:=B3.model_scale(kind,size.x,size.y).x
		for first in range(0,overlays.verts.size(),36):
			var centre:=Vector3.ZERO
			for i in range(first,first+36):centre+=overlays.verts[i]/(36.0*factor)
			var source_centre:=Vector3(-centre.z,centre.y,centre.x);var ray:=Vector3(0,0,signf(centre.x)*0.05)
			check(not B3._cozy_contact_meshes[kind].intersect_segment(source_centre+ray,source_centre-ray).is_empty(),"live reverse/indicator overlay contacts authored source within5cm "+kind)
	var details:=B3.cozy_car_details("saloon",4.6,1.8,2,0);var bottom:=INF
	for v:Vector3 in details.verts:
		if v.y>1:bottom=minf(bottom,v.y)
	check(absf(bottom-B3.COZY_CARS.saloon.height*B3.model_scale("saloon",4.6,1.8).x)<0.001,"taxi sign contacts actual roof")
func test_live_material_states_and_pool_reuse()->void:
	B3.use_shaded();var renderer:=B3.new();renderer._cars_root=Node3D.new();root.add_child(renderer._cars_root)
	var tilt:=Vector2(0.12,-0.08);var shape:Array=E.CAR_SHAPES[0];var reused:Node3D
	for bits:int in [0,B3.LAMPS_ON,B3.LAMPS_ON|B3.LAMPS_BRAKE,B3.LAMPS_REVERSE|B3.LAMPS_LEFT,B3.LAMPS_RIGHT]:
		renderer.begin_cars();renderer.car(Vector2(2,3),0.73,4.6,1.8,Color.YELLOW,shape,2,bits,13,tilt);renderer.car(Vector2(8,3),0.73,4.6,1.8,Color.RED,shape,0,0)
		var nodes:Array=renderer._model_nodes.saloon;check(nodes.size()==2,"pool warms once and reuses source meshes")
		if reused!=null:check(nodes[0]==reused,"node reused across lamp states")
		reused=nodes[0]
		var mesh:MeshInstance3D=nodes[0].get_child(0);var other:MeshInstance3D=nodes[1].get_child(0)
		check(mesh.mesh==other.mesh and mesh.mesh==B3.merged_model("saloon"),"cached merged mesh shared")
		check(mesh.get_instance_shader_parameter("body_paint")==Color.YELLOW and other.get_instance_shader_parameter("body_paint")==Color.RED,"paint state isolated")
		check(mesh.get_instance_shader_parameter("lamp_bits")==bits and other.get_instance_shader_parameter("lamp_bits")==0,"lamp states isolated including parked off")
		var stance:=Basis(Vector3.UP,0.73)*Basis(Vector3.BACK,tilt.x)*Basis(Vector3.RIGHT,tilt.y)
		check(nodes[0].basis.orthonormalized().is_equal_approx(stance*Basis(Vector3.UP,PI/2)),"body heading and full road tilt retained")
		check(renderer._car_nodes[0][0].basis.is_equal_approx(stance),"attached signs/indicators/reverse follow body pitch/roll")
		check(is_equal_approx(nodes[0].position.y,13+B3.ROAD_M+0.016),"body uses road/deck elevation")
		renderer.end_cars()
	renderer._cars_root.free();renderer.route_3d.free();renderer.free()
func test_source_credits_and_compatibility()->void:
	for kind:String in SOURCES:
		var file:String=SOURCES[kind].replace("-","_");var base:String="res://assets/vehicles/cozy_cars/"+file
		var source:Dictionary=JSON.parse_string(FileAccess.get_file_as_string(base+".json"));check(source.triangles==TRIANGLES[kind],"provenance counts")
		check(FileAccess.get_sha256(B3.MODEL_SCENES[kind].resource_path)==source.sha256 and source.license=="CC0-1.0","unchanged source hash/license "+kind)
	for language:String in ["fi","en","de"]:check(Startup.credits_text(language).contains(T.text("credits_cozy_cars",language)) and T.text("credits_cozy_cars",language).contains("Cozy Cars"),"displayed kit credit "+language)
	check(not B3.car_arrays(4.6,1.8,Color.RED,E.CAR_SHAPES[0],0).verts.is_empty(),"explicit compatibility renderer retained")
	check(B3.MODEL_SCENES.city_bus.resource_path=="res://assets/vehicles/city_bus.glb" and B3.MODEL_SCENES.camper_van.resource_path=="res://assets/vehicles/camper_van.glb","other vehicles/static camper retain sources")
func run()->void:
	test_primary_models_use_kit_sources();test_front_glass_remains_open();test_car_fit_heading_ground_and_attachments();test_live_material_states_and_pool_reuse();test_source_credits_and_compatibility();print("COZY_CARS failures=",failures);quit(1 if failures else 0)
