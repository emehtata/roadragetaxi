extends SceneTree
const B3:=preload("res://buildings_3d.gd")
const Chunk:=preload("res://map_chunk.gd")
const Map:=preload("res://map_layer.gd")
const Startup:=preload("res://startup.gd")
const T:=preload("res://i18n.gd")
var failures:=0
func _initialize()->void:call_deferred("run")
func check(ok:bool,message:String)->void:
	if not ok:failures+=1;printerr("FAIL: ",message)
func faces(out:Dictionary)->PackedVector3Array:
	var result:=PackedVector3Array()
	for part:Dictionary in out.get("prop_surfaces",{}).values():result.append_array(part.verts)
	return result
func test_selected_source_geometry()->void:
	for kind in ["picnic_table"]:
		var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.props(out,[[Vector2.ZERO,0.0,kind]])
		check(out.deck.is_empty() and faces(out).size()==5544*3,"actual full kit geometry: "+kind)
		for part:Dictionary in out.get("prop_surfaces",{}).values():
			check(part.normals.size()==part.verts.size() and part.uv.size()==part.verts.size() and part.tangents.size()==part.verts.size()*4,"source attributes retained")
func test_fit_heading_and_contacts()->void:
	for kind in ["picnic_table"]:
		var invalid:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.props(invalid,[[Vector2.INF,0.0,kind],[Vector2.ZERO,INF,kind]])
		check(faces(invalid).is_empty() and invalid.deck.is_empty(),"nonfinite placement rejected")
		var source:=faces({"prop_surfaces":B3.prop_model_surfaces(kind)})
		if kind=="picnic_table":
			for v:Vector3 in source:check(absf(v.x)<=0.90001 and absf(v.z)<=0.75001 and v.y>=-0.00001 and v.y<=0.75001,"complete table envelope")
		for angle:float in [0.0,0.73,PI]:
			var at:=Vector2(17,-23);var grid:={"origin":Vector2(-50,-50),"step":100.0,"cols":2,"heights":PackedFloat32Array([10,20,15,25])}
			var actual:=faces(B3.build([],[],Vector2.ZERO,[],[],{"rect":Rect2(-50,-50,100,100),"props":[[at,angle,kind]],"ground_heights":grid}))
			check(actual.size()==source.size(),"grounded count retained")
			for i in actual.size():
				var local:=actual[i];local.y-=B3.ground_height(grid,Vector2(local.x,local.z));local-=Vector3(at.x,0,at.y);local=Basis(Vector3.UP,-angle)*local
				check(local.distance_to(source[i])<0.002,"heading and terrain retain source proportions")
func test_mixed_chunk_lifecycle_and_controls()->void:
	var flags:=[Chunk.buildings_3d,Chunk.outdoor_3d,Chunk.build_async];Chunk.buildings_3d=true;Chunk.outdoor_3d=true;Chunk.build_async=false
	var map:=Map.new();root.add_child(map)
	var row:={"chunk_id":"0_0","bounds":[0,0,100,100],"scenery_objects":[[20.0,20.0,"picnic_table",0.73],[40.0,40.0,"level_crossing",0.73],[65.0,20.0,"picnic_table",0.0],[70.0,60.0,"seesaw",0.0]]};var first:=[]
	for action in ["add","replace","reload"]:
		if action=="add":map.add_chunk(row.duplicate(true))
		elif action=="replace":map.replace_chunk(row.duplicate(true))
		else:map.clear();map.add_chunk(row.duplicate(true))
		var geometry:=[];var count:=0
		for node:MeshInstance3D in map._chunks["0_0"].meshes_3d:
			if not node.has_meta("prop_material"):continue
			geometry.append(node.mesh.get_faces());count+=node.mesh.get_faces().size();check(node.layers==B3.LAYER_BUILDINGS and node.cast_shadow==GeometryInstance3D.SHADOW_CASTING_SETTING_ON,"layers/shadows retained")
		check(count==(5544*2+10940)*3,"mixed exact geometry retained")
		if action=="add":first=geometry
		else:check(first==geometry,"replace/reload stable")
	map.free();Chunk.buildings_3d=flags[0];Chunk.outdoor_3d=flags[1];Chunk.build_async=flags[2]
	for kind in ["bicycle_parking","level_crossing","level_crossing_barrier"]:
		var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.props(out,[[Vector2.ZERO,0.0,kind]])
		check(not out.deck.is_empty() and faces(out).is_empty(),"unsuitable kit retains corrected procedural kind")
func test_generic_crossing_has_no_warning_apparatus()->void:
	var out:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};B3.props(out,[[Vector2.ZERO,0.0,"level_crossing"]])
	check(faces(out).is_empty() and not out.deck.is_empty(),"generic crossing without equipment evidence draws only corrected crossbuck posts/boards")
	var expected:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()};var across:Vector2=Vector2.DOWN
	for side in [-1.0,1.0]:
		var post:Vector2=across*side*4.0
		B3._box3d(expected,"deck",post,0.05,0.0,2.6,Color8(70,70,70))
		B3._sloped_wall(expected,post-across*0.6,post+across*0.6,0.03,1.8,2.5,0.15,Color8(235,235,235))
		B3._sloped_wall(expected,post-across*0.6,post+across*0.6,0.03,2.5,1.8,0.15,Color8(235,235,235))
	check(out.deck.size()==expected.deck.size(),"generic crossing triangle count excludes warning apparatus")
	check(Array(out.deck_colors).all(func(c):return c==Color8(70,70,70) or c==Color8(235,235,235)),"generic crossing contains only post/board material")
func test_provenance_credits_and_retained_kinds()->void:
	for file in ["picnic_table"]:
		var path:String="res://assets/props/"+file;check(FileAccess.file_exists(path+".json"),"provenance present")
		if not FileAccess.file_exists(path+".json"):continue
		var provenance:Dictionary=JSON.parse_string(FileAccess.get_file_as_string(path+".json"));check(FileAccess.get_sha256(path+".glb")==provenance.sha256 and provenance.license=="CC0-1.0","unchanged source hash/license")
		for language in ["fi","en","de"]:
			var notice:String=T.text("credits_"+file,language);check(notice.contains("Grab3D") and notice.contains("CC0") and Startup.credits_text(language).contains(notice),"displayed translated source notice")
func run()->void:
	test_generic_crossing_has_no_warning_apparatus();test_selected_source_geometry();test_fit_heading_and_contacts();test_mixed_chunk_lifecycle_and_controls();test_provenance_credits_and_retained_kinds();print("OUTDOOR_INFRASTRUCTURE_GLB failures=",failures);quit(1 if failures else 0)
