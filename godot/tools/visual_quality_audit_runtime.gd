## Audit-only runtime transitions; production renderers, controller and UI remain unchanged.
extends 'res://tools/visual_quality_audit.gd'

class AuditHost extends Node:
	var _visual_test := true
	var _screenshot_path := ''

var output := ''
var fixture: Dictionary
var homes: Array = []
var lod: Array = []
var indoor: CanvasLayer
var current_home: Dictionary
var current_plan: Dictionary
var legacy_materials: Dictionary

func flush() -> void:
	var file := FileAccess.open(output.path_join(fixture.get('runtime_result_file','results.json')), FileAccess.WRITE)
	file.store_string(JSON.stringify({'captures':results,'homes':homes,'lod':lod,'lod_expected':fixture.get('lod_expected',[]),'renderer':RenderingServer.get_current_rendering_method(),'adapter':RenderingServer.get_video_adapter_name()},'\t'))
	file.close()

func take(asset: String, name_: String, family: String, extra: Dictionary = {}) -> void:
	for i in 4: await process_frame
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image() if is_instance_valid(viewport) else root.get_texture().get_image()
	var filename := asset + '_' + name_.validate_filename() + '.png'
	assert(image.save_png(output.path_join(filename)) == OK)
	var record := {'asset':asset,'file':filename,'angle':name_,'family':family,'ready':true,'target_confirmed':true}
	record.merge(extra, true); results.append(record)
	flush()

func primitives() -> int:
	return viewport.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE,Viewport.RENDER_INFO_PRIMITIVES_IN_FRAME)

func mesh_levels(node: Node3D) -> Array:
	var levels: Array = []
	for visual: Node in node.find_children('*','GeometryInstance3D',true,false) + ([node] if node is GeometryInstance3D else []):
		var mesh: Mesh = visual.mesh if visual is MeshInstance3D else visual.multimesh.mesh if visual is MultiMeshInstance3D else null
		if mesh == null: continue
		for surface in mesh.get_surface_count():
			var raw: Dictionary = RenderingServer.mesh_get_surface(mesh.get_rid(),surface)
			var options: Array = []
			for level: Dictionary in raw.get('lods',[]):
				options.append({'edge_length':level.get('edge_length',-1),'index_bytes':level['index_data'].size()})
			levels.append({'base_vertices':mesh.surface_get_array_len(surface),'base_indices':mesh.surface_get_array_index_len(surface),'lods':options})
	return levels

func run() -> void:
	var args := OS.get_cmdline_user_args()
	fixture = JSON.parse_string(FileAccess.get_file_as_string(args[0])); output=args[1]
	for key: String in B3._shared:legacy_materials[key]=B3._shared[key].duplicate(true)
	B3.use_shaded(); root.size=Vector2i(640,480)
	viewport=SubViewport.new(); viewport.size=Vector2i(640,480); viewport.own_world_3d=true
	viewport.render_target_update_mode=SubViewport.UPDATE_ALWAYS; root.add_child(viewport)
	camera=Camera3D.new(); camera.fov=60; camera.near=.05; camera.far=4000; viewport.add_child(camera); camera.current=true
	environment=Environment.new(); environment.background_mode=Environment.BG_COLOR; environment.background_color=Color('303b46')
	environment.ambient_light_source=Environment.AMBIENT_SOURCE_COLOR; environment.ambient_light_color=Color.WHITE; environment.ambient_light_energy=.65; camera.environment=environment
	sun=DirectionalLight3D.new(); sun.rotation_degrees=Vector3(-45,25,0); viewport.add_child(sun)
	var stages: Array=fixture.get('runtime_stages',['lod','effects','rooms','ui'])
	if stages.has('lod'):await inspect_lod()
	if stages.has('legacy'):await inspect_legacy()
	if stages.has('effects'):await inspect_effects()
	viewport.free(); viewport=null
	if stages.has('rooms'):await inspect_rooms()
	if stages.has('ui'):await inspect_ui()
	flush(); quit()

func inspect_effects() -> void:
	camera.projection=Camera3D.PROJECTION_PERSPECTIVE;camera.fov=60
	var house: Dictionary=fixture['assets'].filter(func(a):return a['mode']=='building' and a['kind']=='house')[0]
	var body:=build(house);viewport.add_child(body)
	var ground:=MeshInstance3D.new();ground.mesh=PlaneMesh.new();ground.mesh.size=Vector2(100,100)
	var material:=StandardMaterial3D.new();material.albedo_color=Color('47535b');ground.material_override=material;viewport.add_child(ground)
	camera.position=Vector3(18,8,18);camera.look_at(Vector3(0,3,0))
	var precipitation:=preload('res://precipitation_3d.gd').new();viewport.add_child(precipitation)
	precipitation.particles.use_fixed_seed=true;precipitation.particles.seed=1
	for kind in ['rain','snow','slush']:
		var asset: String='A-243' if kind=='rain' else 'A-244' if kind=='snow' else 'A-245'
		for wind in [0.0,12.0]:
			precipitation.set_weather(kind,.85,Vector2(wind,wind*.25))
			for frame in 30:await process_frame
			assert(precipitation.visible and precipitation.particles.emitting and precipitation.particles.amount==6800)
			await take(asset,'%s_3d_wind_%02d' % [kind,int(wind)],'runtime-effects',{'particle_count':precipitation.particles.amount,'seed':1,'wind_mps':[wind,wind*.25],'condition':'actual GPU precipitation and roof height-field collision around production house','limitation':'Isolated production GPU renderer; full moving real-map weather integration remains representative, not every map condition.'})
	precipitation.free();body.free()
	var smoke_root:=Node3D.new();viewport.add_child(smoke_root)
	var helper:=B3.new();helper._cars_root=smoke_root
	for phase in [0.0,.5,1.0]:
		helper.puff(Vector2(phase*2,0),.5+phase*2,.2+phase*.6,Color(.2,.2,.2,.7-phase*.4))
	camera.position=Vector3(5,3,5);camera.look_at(Vector3(1,1,0))
	for condition in ['day','night']:
		environment.ambient_light_energy=.65 if condition=='day' else .08;sun.light_energy=1 if condition=='day' else .02
		await take('A-226','smoke_3d_'+condition,'runtime-effects',{'condition':'production smoke shader; three spatial age/size samples; '+condition,'limitation':'Samples exercise billboard/transparency, not continuous simulation smoke lifetime.'})
	helper.route_3d.free();helper.free();smoke_root.free();ground.free()

func inspect_lod() -> void:
	for row: Dictionary in fixture['assets']:
		if row['mode'] != 'vehicle' or row['name']!=row['kind'] or not B3.MODEL_SCENES.has(row['kind']):continue
		if fixture.has('runtime_assets') and not fixture['runtime_assets'].has(row['id']):continue
		var body := build(row); viewport.add_child(body); await process_frame
		var box := bounds(body); var centre := box.get_center(); var span := box.size.length()
		var entry := {'asset':row['id'],'system':'generated imported mesh LOD','surfaces':mesh_levels(body),'samples':[]}
		for factor in [1.5,3.0,6.0,12.0,24.0,48.0]:
			camera.position=centre+Vector3(1,.25,1).normalized()*span*factor; camera.look_at(centre)
			var metres := camera.position.distance_to(centre)
			assert(camera.is_position_in_frustum(centre))
			await take(row['id'],'mesh_lod_%05.1fm' % metres,'runtime-lod',{'distance_m':metres,'mesh_lod_threshold':viewport.mesh_lod_threshold,'camera_projection':'perspective 60 degrees','limitation':'Far silhouettes are small at actual gameplay projection; surface LOD metadata and primitive counts identify the transition.'})
			entry['samples'].append({'distance_m':metres,'primitives':primitives()})
		lod.append(entry); body.free(); print('AUDIT runtime mesh LOD ',row['id'])
	# Hold apparent size for diagnostic visibility-range comparison, at actual camera distances.
	camera.projection=Camera3D.PROJECTION_ORTHOGONAL; camera.size=13
	for species in ['spruce','pine','birch']:
		var row: Dictionary=fixture['assets'].filter(func(a):return a['mode']=='tree' and a['kind']==species and not a.get('far',false) and not a.get('felled',false))[0]
		if fixture.has('runtime_assets') and not fixture['runtime_assets'].has(row['id']):continue
		var body:=B3.forest_node([[Vector2.ZERO,species,1.4,Color8(65,110,60),Color8(100,75,50),NAN]],{})
		viewport.add_child(body); await process_frame
		var centre:=bounds(body).get_center(); var entry:={'asset':row['id'],'system':'forest visibility ranges at 400 m','samples':[]}
		for metres in [399.0,399.9,400.1,401.0]:
			camera.position=Vector3(metres,centre.y,0); camera.look_at(centre)
			await take(row['id'],'forest_boundary_%05.1fm' % metres,'runtime-lod',{'distance_m':metres,'camera_projection':'orthographic fixed 13 m span','limitation':'Diagnostic enlargement at true camera range, not normal perspective appearance.'})
			entry['samples'].append({'distance_m':metres,'primitives':primitives()})
		lod.append(entry); body.free()
	# Exercise the renderer's live 40 m person/animal detail selector, not fixed build arguments.
	for row: Dictionary in fixture['assets']:
		if not row['mode'] in ['person','animal']:continue
		if fixture.has('runtime_assets') and not fixture['runtime_assets'].has(row['id']):continue
		var kind: String=row['kind'];var asset: String=row['id']
		var entry:={'asset':asset,'system':'live 40 m detail selector','samples':[]}
		for metres in [39.9,40.1]:
			var body:=Node3D.new(); viewport.add_child(body)
			var helper:=B3.new(); helper._cars_root=body; helper.windshield_on=true; helper.windshield_at=Vector2(metres,0)
			if kind=='person':helper.person(Vector2.ZERO,0,Color8(65,125,190),row.get('pose','standing'),1,row.get('costume',''),0,int(row.get('variant',0)),row.get('winter',false),int(row.get('beard',0)),row.get('cart',false))
			else:helper.animal(Vector2.ZERO,0,kind,Color8(125,95,65),row.get('pose','stand'))
			helper.end_cars(); await process_frame
			var centre:=bounds(body).get_center(); camera.size=4; camera.position=centre+Vector3(4,1,4); camera.look_at(centre)
			await take(asset,'%s_detail_selector_%04.1fm' % [kind,metres],'runtime-lod',{'selector_distance_m':metres,'camera_projection':'orthographic enlarged diagnostic; selector uses actual view distance','limitation':'Imported animals may share identical geometry across detail keys.'})
			entry['samples'].append({'distance_m':metres,'keys':helper._car_meshes.keys()+helper._animal_batches.keys(),'surfaces':mesh_levels(body)})
			helper.route_3d.free();helper.free();body.free()
		lod.append(entry)

func inspect_legacy() -> void:
	B3._shared=legacy_materials;B3.opaque=false
	camera.projection=Camera3D.PROJECTION_ORTHOGONAL;camera.size=6
	var kinds: Array=['saloon','hatchback','estate','suv','pickup','sports','city_car','panel_van']
	for row: Dictionary in fixture['assets']:
		if row['mode']!='vehicle' or row['name']!=row['kind'] or not kinds.has(row['kind']):continue
		var shape: Array=EL.VAN_SHAPE if row['kind']=='panel_van' else EL.CAR_SHAPES[kinds.find(row['kind'])]
		var entry:={'asset':row['id'],'system':'legacy procedural car 35 m selector','samples':[]}
		for metres in [34.9,35.1]:
			var body:=Node3D.new();viewport.add_child(body)
			var helper:=B3.new();helper._cars_root=body;helper.windshield_on=true;helper.windshield_at=Vector2(metres,0)
			helper.car(Vector2.ZERO,0,row['length'],row['width'],Color8(175,85,48),shape,2,1)
			helper.end_cars();await process_frame
			var centre:=bounds(body).get_center();camera.position=centre+Vector3(5,2,5);camera.look_at(centre)
			await take(row['id'],'legacy_car_detail_selector_%04.1fm' % metres,'runtime-lod',{'selector_distance_m':metres,'condition':'Actual non-opaque procedural car renderer and original fallback materials','camera_projection':'Orthographic enlarged diagnostic; actual selector receives view distance'})
			entry['samples'].append({'distance_m':metres,'surfaces':mesh_levels(body)})
			helper.route_3d.free();helper.free();body.free()
		lod.append(entry)
	B3.use_shaded()

func xy() -> Vector2:
	return Vector2(indoor.player.position.x,-indoor.player.position.z)

func walk_to(point: Vector2, tolerance := .16) -> bool:
	indoor.player.rotation.y=0
	for frame in 2400:
		var delta:=point-xy()
		if delta.length()<tolerance:
			indoor.player.walk(Vector2.ZERO,1.0/60.0)
			return true
		indoor.player.walk(Vector2(delta.x,-delta.y).normalized()*minf(1,delta.length()/indoor.player.walking_speed*60),1.0/60.0)
		await physics_frame
	current_home['failures'].append({'target':[point.x,point.y],'stopped':[xy().x,xy().y]})
	return false

func clear_segment(a: Vector2,b: Vector2,polygon: PackedVector2Array) -> bool:
	for step in 81:
		var point:=a.lerp(b,step/80.0)
		if Geometry2D.is_point_in_polygon(point,polygon):continue
		var border:=INF
		for i in polygon.size():border=minf(border,point.distance_to(Geometry2D.get_closest_point_to_segment(point,polygon[i],polygon[(i+1)%polygon.size()])))
		if border>.002:return false
	return true

func walk_inside(index: int,target: Vector2) -> bool:
	var polygon:=PackedVector2Array()
	for point: Array in current_plan['rooms'][index]['points']:polygon.append(Vector2(point[0],point[1]))
	# Concave rooms require a route around the notch; all motion still uses move_and_slide.
	if Geometry2D.convex_hull(polygon).size()-1>=polygon.size():return await walk_to(target)
	var inset:=Geometry2D.offset_polygon(polygon,-.37)
	if inset.is_empty():return await walk_to(target)
	polygon=inset[0]
	if clear_segment(xy(),target,polygon):return await walk_to(target)
	var points: Array[Vector2]=[xy(),target]
	for point: Vector2 in polygon:points.append(point)
	var costs: Array[float]=[];var parents: Array[int]=[];var visited: Array[int]=[]
	for i in points.size():costs.append(INF);parents.append(-1)
	costs[0]=0
	for iteration in points.size():
		var best:=-1
		for i in points.size():
			if not visited.has(i) and (best==-1 or costs[i]<costs[best]):best=i
		if best==-1 or costs[best]==INF:break
		if best==1:break
		visited.append(best)
		for next in points.size():
			var cost:=costs[best]+points[best].distance_to(points[next])
			if cost<costs[next] and clear_segment(points[best],points[next],polygon):costs[next]=cost;parents[next]=best
	if parents[1]==-1:
		current_home['failures'].append({'room':index,'reason':'audit waypoint planner found no capsule-clear route'})
		return false
	var path: Array[Vector2]=[];var at:=1
	while at!=0:path.push_front(points[at]);at=parents[at]
	for i in path.size():
		if not await walk_to(path[i],.025 if i<path.size()-1 else .16):return false
	return true

func room_point(index: int) -> Vector2:
	var point: Array=current_plan['rooms'][index]['label_at']
	return Vector2(point[0],point[1])

func visit_room(index: int, previous: int) -> bool:
	if not await walk_inside(index,room_point(index)): return false
	current_home['rooms_visited'].append(index)
	assert(indoor.player.is_on_floor(),'room player not on floor')
	# The real player eye looks across the room and then toward its connecting door.
	indoor.player.rotation.y=.6
	await take(current_home['asset'],'room_%02d_%s' % [index,current_plan['rooms'][index]['kind']],'runtime-rooms',{'room_index':index,'on_floor':true,'camera_height':indoor.player.eye_height,'camera_position':[indoor.player.camera.global_position.x,indoor.player.camera.global_position.y,indoor.player.camera.global_position.z],'condition':'production fixed interior lighting; actual capsule walk from front door'})
	for door_index in current_plan['doors'].size():
		var door: Dictionary=current_plan['doors'][door_index]
		var adjacent: Array=[int(door['rooms'][0]),int(door['rooms'][1])]
		if not adjacent.has(index) or adjacent.has(-1): continue
		var next: int=int(adjacent[1] if int(adjacent[0])==index else adjacent[0])
		if next==previous or current_home['rooms_visited'].has(next): continue
		var a:=Vector2(door['points'][0][0],door['points'][0][1]); var b:=Vector2(door['points'][1][0],door['points'][1][1])
		var middle:=(a+b)/2; var normal:=(b-a).orthogonal().normalized()
		var polygon:=PackedVector2Array()
		for point: Array in current_plan['rooms'][index]['points']: polygon.append(Vector2(point[0],point[1]))
		if not Geometry2D.is_point_in_polygon(middle-normal*.4,polygon): normal=-normal
		if not await walk_inside(index,middle-normal*.4) or not await walk_to(middle+normal*.4,.025): return false
		assert((xy()-middle).dot(normal)>.35,'door did not reach the opposite side')
		current_home['doors_crossed'].append(door_index)
		if not await visit_room(next,index): return false
		if not await walk_inside(next,middle+normal*.4) or not await walk_to(middle-normal*.4,.025) or not await walk_inside(index,room_point(index)): return false
	return true

func inspect_rooms() -> void:
	Engine.physics_ticks_per_second=240
	var host:=AuditHost.new();root.add_child(host)
	indoor=preload('res://home_first_person.gd').new();host.add_child(indoor);indoor._recenter_mouse=false
	var plans=JSON.parse_string(FileAccess.get_file_as_string('res://tests/data/home_plans.json'))
	for row: Dictionary in fixture['assets']:
		if row['mode']!='interior':continue
		if fixture.has('runtime_assets') and not fixture['runtime_assets'].has(row['id']):continue
		current_plan=plans[int(row['index'])]
		current_home={'asset':row['id'],'rooms_expected':current_plan['rooms'].size(),'rooms_visited':[],'doors_expected':current_plan['doors'].filter(func(d):return int(d['rooms'][0])!=-1 and int(d['rooms'][1])!=-1).size(),'doors_crossed':[],'failures':[]}
		homes.append(current_home)
		assert(indoor.enter(current_plan));indoor.player.controls_enabled=false;indoor.player.set_physics_process(false)
		for i in 15: indoor.player.walk(Vector2.ZERO,1.0/60.0);await physics_frame
		var outside: Dictionary=current_plan['doors'].filter(func(d):return int(d['rooms'][0])==-1)[0]
		var start_room: int=int(outside['rooms'][1])
		current_home['completed']=await visit_room(start_room,-1)
		flush();print('AUDIT rooms ',row['id'],' ',current_home['rooms_visited'].size(),'/',current_home['rooms_expected'])
		indoor.leave()
	host.free();indoor=null;Engine.physics_ticks_per_second=60

func inspect_ui() -> void:
	root.size=Vector2i(640,480)
	var tutorial:=preload('res://tutorial.gd').new();root.add_child(tutorial)
	for step in tutorial.STEPS.size():
		tutorial.step=step;tutorial._show()
		await take('A-268','tutorial_step_%02d' % step,'runtime-ui',{'condition':'actual tutorial step text/layout; fixture progression, no simulation completion credit'})
	for notice in ['tut_nausea','tut_no_trains','tut_no_station']:
		tutorial._show(notice);await take('A-268',notice,'runtime-ui')
	tutorial.free()
	var phone:=Phone.new();root.add_child(phone);phone.set_connected(true);phone.open()
	var offer:={'id':'audit','kind':'offer','status':'AVAILABLE','name':'Audit passenger','pickup':'Market Square','dropoff':'Railway Station','trip_distance_m':8200,'time_remaining_s':120}
	for state in ['empty','available','pending','gone','busy','disconnected']:
		phone.set_connected(false);phone.set_connected(true);phone.show_navigation({});phone.show_phone({'busy':false,'items':[] if state=='empty' else [offer]})
		if state in ['pending','gone']:
			assert(phone.accept_selected())
			if state=='gone':phone.handle_result({'request_id':phone._next_request-1,'ok':false,'reason':'gone'})
		if state=='busy':phone.show_phone({'busy':true,'items':[]})
		if state=='disconnected':phone.set_connected(false)
		await take('A-262','phone_'+state,'runtime-ui',{'condition':'actual phone methods; local state fixture with no requests sent to a simulation'})
	phone.set_connected(true);phone.show_phone({'busy':true,'items':[]})
	for maneuver in ['left','right','uturn','straight','arrive','no_target']:
		phone.show_navigation({'instruction':{'maneuver':maneuver,'distance_m':120 if maneuver!='arrive' else 0,'total_m':8200}},'Pick up audit passenger')
		await take('A-263','navigation_'+maneuver,'runtime-ui')
	for language in ['fi','de']:
		phone.set_language(language);phone.show_phone({'busy':false,'items':[offer]});phone.show_navigation({})
		phone.battery=20;phone.charging=true;phone.set_game_seconds(14*3600)
		await take('A-262','phone_language_'+language+'_low_battery','runtime-ui')
	phone.free()
