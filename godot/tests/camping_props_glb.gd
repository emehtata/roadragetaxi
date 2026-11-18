extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const Chunk := preload("res://map_chunk.gd")
const Map := preload("res://map_layer.gd")
const Startup := preload("res://startup.gd")
const T := preload("res://i18n.gd")
const COUNTS := {"caravan_with_car":38695,"caravan":19387,"tent":14428,"camper_van":45436}
var failures := 0
func _initialize() -> void: call_deferred("run")
func check(ok:bool,message:String) -> void:
	if not ok: failures+=1;printerr("FAIL: ",message)
func faces(out:Dictionary) -> PackedVector3Array:
	var result:=PackedVector3Array()
	for part:Dictionary in out.get("prop_surfaces",{}).values():result.append_array(part.verts)
	return result
func test_camping_uses_source_geometry() -> void:
	for kind in ["caravan_with_car","caravan","tent","camper_van"]:
		var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()}
		B3.props(out,[[Vector2.ZERO,0.0,kind,6.4 if kind=="camper_van" else B3.PROPS[kind][0]]])
		check(out.deck.is_empty() and faces(out).size()==COUNTS[kind]*3,kind+" uses actual source meshes")
		for part:Dictionary in out.get("prop_surfaces",{}).values():
			check(part.normals.size()==part.verts.size() and part.uv.size()==part.verts.size() and part.tangents.size()==part.verts.size()*4,"all source surface attributes retained")
			check(part.material is BaseMaterial3D,"original materials retained")
		if kind=="camper_van":
			var invalid:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.props(invalid,[[Vector2.ZERO,0.0,kind]])
			check(faces(invalid).is_empty() and invalid.deck.is_empty(),"missing camper length rejected")
func test_camping_fit_heading_and_contacts() -> void:
	for kind in ["caravan_with_car","caravan","tent","camper_van"]:
		var length:float=6.4 if kind=="camper_van" else 9.4 if kind=="caravan_with_car" else 6.2 if kind=="caravan" else 3.2
		var width:=2.4 if kind=="tent" else 2.5
		var height:=1.3 if kind=="tent" else 2.9 if kind=="camper_van" else 2.5
		for angle:float in [0.0,0.73]:
			var at:=Vector2(17,-23)
			var grid:={"origin":Vector2(-50,-50),"step":100.0,"cols":2,"heights":PackedFloat32Array([10,20,15,25])}
			var out:=B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"props":[[at,angle,kind,length]],"ground_heights":grid})
			var low:=INF
			var actual:=faces(out)
			var source:=faces({"prop_surfaces":B3.prop_model_surfaces(kind)})
			var scale:=B3.camping_scale(kind,length)
			for i in actual.size():
				var world:Vector3=actual[i]
				var local:=world;local.y-=B3.ground_height(grid,Vector2(local.x,local.z));local-=Vector3(at.x,0,at.y);local=Basis(Vector3.UP,-angle)*local
				check(absf(local.x)<=length/2+0.002 and absf(local.z)<=width/2+0.002 and local.y<=height+0.002,"complete camping model fits existing envelope")
				check(local.distance_to(source[i]*scale)<0.002,"uniform source proportions retained after row heading and terrain")
				low=minf(low,local.y)
			check(absf(low)<0.002,"ground contacts retained on sloped terrain")
func test_camping_mixed_chunk_lifecycle() -> void:
	var flags:=[Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async]
	Chunk.buildings_3d=true;Chunk.outdoor_3d=true;Chunk.build_async=false
	var map:=Map.new();root.add_child(map)
	var message:={"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[30.0,30.0,"caravan_with_car",0.0],[45.0,30.0,"caravan",0.73],[60.0,30.0,"camper_van",0.0,6.4],[75.0,30.0,"tent",0.0],[20.0,50.0,"seesaw",0.0],[50.0,65.0,"caravan_with_car",0.3]]}
	var first:=[]
	for action in ["add","replace","reload"]:
		if action=="add":map.add_chunk(message.duplicate(true))
		elif action=="replace":map.replace_chunk(message.duplicate(true))
		else:map.clear();map.add_chunk(message.duplicate(true))
		var geometry:=[];var count:=0
		for node:MeshInstance3D in map._chunks["0_0"].meshes_3d:
			if not node.has_meta("prop_material"):continue
			geometry.append(node.mesh.get_faces());count+=node.mesh.get_faces().size()
			check(node.layers==B3.LAYER_BUILDINGS and node.cast_shadow==GeometryInstance3D.SHADOW_CASTING_SETTING_ON,"camping layers/shadows retained")
		check(count==(2*38695+19387+45436+14428+10940)*3,"mixed/repeated camping and playground geometry retained exactly")
		if action=="add":first=geometry
		else:check(first==geometry,"replace/reload retain exact source geometry")
	map.free();Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]
func test_camping_source_credits_and_controls() -> void:
	var camper:Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://assets/props/static_camper.json"))
	check(FileAccess.get_sha256("res://assets/vehicles/camper_van.glb")==camper.sha256,"reused camper GLB unchanged")
	for language in ["fi","en","de"]:
		check(Startup.credits_text(language).contains(T.text("credits_static_camper",language)),"displayed translated camper credit")
	for file in ["travel_trailer","station_wagon","a_frame_tent"]:
		var path:String="res://assets/props/"+file
		check(FileAccess.file_exists(path+".json") and FileAccess.file_exists(path+".glb"),"source and provenance retained: "+file)
		if not FileAccess.file_exists(path+".json"):continue
		var provenance:Dictionary=JSON.parse_string(FileAccess.get_file_as_string(path+".json"))
		check(FileAccess.get_sha256(path+".glb")==provenance.sha256 and provenance.license=="CC0-1.0","unchanged licensed source")
		for language in ["fi","en","de"]:
			var notice:String=T.text("credits_"+file,language)
			check(notice.contains("Grab3D") and notice.contains("CC0") and Startup.credits_text(language).contains(notice),"displayed translated camping credit")
func run() -> void:
	test_camping_uses_source_geometry();test_camping_fit_heading_and_contacts();test_camping_mixed_chunk_lifecycle();test_camping_source_credits_and_controls()
	print("CAMPING_PROPS_GLB failures=",failures);quit(1 if failures else 0)
