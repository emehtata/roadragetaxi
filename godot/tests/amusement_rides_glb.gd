extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const Chunk := preload("res://map_chunk.gd")
const Map := preload("res://map_layer.gd")
const Startup := preload("res://startup.gd")
const T := preload("res://i18n.gd")
const TRIANGLES := {"swing_carousel":18532,"ferris_wheel":39652}
var failures := 0

func _initialize() -> void: call_deferred("run")
func check(ok:bool,message:String) -> void:
	if not ok: failures+=1;printerr("FAIL: ",message)
func loop_at(at:=Vector2.ZERO,radius:=8.0,angle:=0.0) -> PackedVector2Array:
	var loop:=PackedVector2Array()
	for i in 48:loop.append(at+Vector2(cos(i*TAU/48),sin(i*TAU/48)).rotated(angle)*radius)
	loop.append(loop[0]);return loop
func faces(out:Dictionary) -> PackedVector3Array:
	var result:=PackedVector3Array()
	for part:Dictionary in out.get("prop_surfaces",{}).values():result.append_array(part.verts)
	return result
func test_rides_use_kit_geometry() -> void:
	for kind:String in TRIANGLES:
		var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()}
		B3.attractions(out,[[kind,loop_at()]])
		check(out.deck.is_empty(),kind+" uses the actual kit rather than generated boxes")
		check(faces(out).size()==TRIANGLES[kind]*3,kind+" retains all selected source triangles")
		check(out.get("prop_surfaces",{}).size()==3,kind+" retains all three source materials")
		for part:Dictionary in out.get("prop_surfaces",{}).values():
			check(part.normals.size()==part.verts.size() and part.uv.size()==part.verts.size() and part.tangents.size()==part.verts.size()*4,kind+" retains source surface attributes")
			check(part.material is BaseMaterial3D and (part.material.albedo_texture!=null or part.material.emission_enabled),kind+" retains textured/emissive source material")
func test_rides_fit_and_ground() -> void:
	for kind:String in TRIANGLES:
		var source:=faces({"prop_surfaces":B3.prop_model_surfaces(kind)})
		for radius:float in [8.0,1.0]:
			for angle:float in [0.0,0.73]:
				var at:=Vector2(17,-23)
				var loop:=loop_at(at,radius,angle)
				# An elongated loop makes the Ferris wheel's axis unambiguous.
				for i in loop.size(): loop[i]=at+Vector2((loop[i]-at).rotated(-angle).x*1.2,(loop[i]-at).rotated(-angle).y).rotated(angle)
				var grid:={"origin":Vector2(-50,-50),"step":100.0,"cols":2,"heights":PackedFloat32Array([10,20,15,25])}
				var built:=B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"attractions":[[kind,loop]],"ground_heights":grid})
				var actual:=faces(built)
				check(actual.size()==source.size(),"grounded build retains all ride geometry")
				var yaw:=-angle if kind=="ferris_wheel" else 0.0
				# The opposite far endpoint is equivalent for the wheel axis.
				var reverse:=false
				if kind=="ferris_wheel":
					var a:Vector3=actual[0];a.y-=B3.ground_height(grid,Vector2(a.x,a.z));a-=Vector3(at.x,0,at.y)
					reverse=a.dot(Basis(Vector3.UP,yaw)*source[0])<0
				if reverse:yaw+=PI
				var ratio:=-1.0
				for i in actual.size():
					var v:Vector3=actual[i]
					v.y-=B3.ground_height(grid,Vector2(v.x,v.z));v-=Vector3(at.x,0,at.y)
					v=Basis(Vector3.UP,-yaw)*v
					if source[i].length()>0.01:
						var scale:=v.length()/source[i].length()
						if ratio<0:ratio=scale
						check(absf(scale-ratio)<0.0002 and v.distance_to(source[i]*ratio)<0.002,"uniform proportions and intended ride orientation retained")
					check(v.y>=-0.0002 and Geometry2D.is_point_in_polygon(Vector2(actual[i].x,actual[i].z),loop),"base grounded and footprint contains every vertex")
		for invalid in [PackedVector2Array([Vector2.ZERO,Vector2.ONE]),PackedVector2Array([Vector2.ZERO,Vector2.ONE,Vector2(1,0),Vector2(2,1)]),PackedVector2Array([Vector2.ZERO,Vector2.ZERO,Vector2.ZERO,Vector2.ZERO])]:
			var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.attractions(out,[[kind,invalid]])
			check(faces(out).is_empty() and out.deck.is_empty(),"invalid ride loop skipped")

func test_round_ride_axis_stable() -> void:
	var loop:=loop_at(Vector2(50,50),6.5)
	var changed:=loop.duplicate()
	changed[12]+=Vector2(0,0.00001)
	check(absf(angle_difference(B3.ride_angle("ferris_wheel",loop,Vector2(50,50)),B3.ride_angle("ferris_wheel",changed,Vector2(50,50))))<0.001,"equal footprint endpoints keep deterministic axis across chunk rounding")

func test_rides_mixed_chunk_lifecycle() -> void:
	var flags:=[Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async]
	Chunk.buildings_3d=true;Chunk.outdoor_3d=true;Chunk.build_async=false
	var map:=Map.new();root.add_child(map)
	var points:=[]
	for p:Vector2 in loop_at(Vector2(50,50)):points.append([p.x,p.y])
	var message:={"chunk_id":"0_0","bounds":[0,0,100,100],"attractions":[["swing_carousel",points],["ferris_wheel",points],["swing_carousel",points],["carousel",points]],"scenery_objects":[[25.0,25.0,"seesaw",0.0]]}
	var first:=[]
	for action in ["add","replace","reload"]:
		if action=="add":map.add_chunk(message.duplicate(true))
		elif action=="replace":map.replace_chunk(message.duplicate(true))
		else:map.clear();check(map._chunks.is_empty(),"unload clears ride chunks");map.add_chunk(message.duplicate(true))
		var geometry:=[];var count:=0;var materials:={}
		for node:MeshInstance3D in map._chunks["0_0"].meshes_3d:
			if not node.has_meta("prop_material"):continue
			geometry.append(node.mesh.get_faces());count+=node.mesh.get_faces().size();materials[node.material_override]=true
			check(node.layers==B3.LAYER_BUILDINGS and node.cast_shadow==GeometryInstance3D.SHADOW_CASTING_SETTING_ON,"ride layers and shadow preserved")
		check(count==(2*18532+39652+21956+10940)*3 and materials.size()==11,"mixed/repeated rows retain every model and distinct material")
		if action=="add":first=geometry
		else:check(first==geometry,"replace/reload preserves exact batched geometry")
	map.free();Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]

func test_rides_source_and_controls() -> void:
	for kind:String in TRIANGLES:
		var file:="swing_ride" if kind=="swing_carousel" else kind
		var provenance:Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://assets/props/"+file+".json"))
		check(FileAccess.get_sha256("res://assets/props/"+file+".glb")==provenance.sha256,"unchanged GLB source hash")
		check(provenance.triangles==TRIANGLES[kind] and provenance.materials==3 and provenance.license=="CC0-1.0","source geometry/license documented")
		for language in ["fi","en","de"]:
			var notice:String=T.text("credits_"+file,language)
			check(notice.contains("Grab3D") and notice.contains("CC0") and Startup.credits_text(language).contains(notice),"localized displayed source credit: "+file+"/"+language)
	check(FileAccess.get_file_as_string("res://assets/props/CC0-1.0.txt").contains("CC0 1.0 Universal"),"full legal text retained")
	for kind:String in ["roller_coaster","drop_tower"]:
		var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.attractions(out,[[kind,loop_at()]])
		check(not out.deck.is_empty() and out.get("prop_surfaces",{}).is_empty(),"retained procedural control: "+kind)
	var control:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.attractions(control,[["carousel",loop_at()]])
	check(faces(control).size()==21956*3,"carousel GLB preserved")
	for kind in ["swing","slide","spring_rider","climbing_frame","seesaw"]:
		check(not B3.prop_model_surfaces(kind).is_empty(),"playground GLB preserved: "+kind)

func run() -> void:
	test_rides_use_kit_geometry()
	test_rides_fit_and_ground()
	test_round_ride_axis_stable()
	test_rides_mixed_chunk_lifecycle()
	test_rides_source_and_controls()
	print("AMUSEMENT_RIDES_GLB failures=",failures)
	quit(1 if failures else 0)
