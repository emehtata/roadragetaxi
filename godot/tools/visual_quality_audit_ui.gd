## Finite UI presentation branches missing from earlier audit fixtures. No player I/O callbacks.
extends 'res://tools/visual_quality_audit_runtime.gd'
const Context := preload('res://tools/visual_quality_audit_context.gd')
class Menus extends Context.Shell:
	var slots: Array=[]
	func _server_query(_flag: String) -> Array:return slots
	func _thumb(_name: String) -> Texture2D:return null
class OfflineMap extends 'res://map_browser.gd':
	func _fetch() -> void:pass

func shot(asset: String,state: String,target: CanvasItem) -> void:
	assert(is_instance_valid(target) and target.is_visible_in_tree(),'UI branch not visible: '+state)
	await take(asset,state,'runtime-ui-branches',{'condition':'Actual production UI methods, isolated local state; no destructive/save callbacks invoked','state_source':'Client/server inputs traced in gap-matrix.json'})

func run() -> void:
	var args:=OS.get_cmdline_user_args();fixture=JSON.parse_string(FileAccess.get_file_as_string(args[0]));output=args[1]
	root.size=Vector2i(800,600);RenderingServer.set_default_clear_color(Color('303b46'))
	await hud_branches();await phone_branches();await menus();await small_components();await labels_and_route()
	flush();quit()

func hud_branches() -> void:
	var base:={'player':{'speed':0,'engine_on':true,'fuel_l':30},'on_foot':false,'game_time_seconds':46800,'taxi':{'balance_cents':75000,'completed_fares':3,'total_score':42},'calendar':{'date':'2026-11-15','time_scale':60},'weather':{'weather_type':'clear','cloud_cover':.1,'temperature_c':3,'wetness':0}}
	for state_name in ['notice','speed_camera','source_wrap','start_on_foot','engine_off','meet','train_board','abroad','loading_start','loading_camera','fare','subtitle_wrap','summary_next','summary_final','house_door','home_door','building_hint','fuel_stop','fuel_engine','fuel_exit','fuel_ready','fuel_active']:
		var packed:=preload('res://main.tscn').instantiate();var hud:Control=packed.get_node('Ui/Hud');packed.get_node('Ui').remove_child(hud);hud.owner=null
		for child in hud.find_children('*','',true,false):child.owner=hud
		packed.free();root.add_child(hud);hud.size=Vector2(800,600)
		var state:Dictionary=base.duplicate(true);var toggles:={}
		match state_name:
			'notice','speed_camera':state.taxi.merge({'notification_msg':'Audit notice: please wait safely','notification_timer':10,'speed_camera_notice':state_name=='speed_camera'})
			'source_wrap':state['data_source_notice']='Audit source-status fixture: the configured local map dataset is unavailable; the existing map service supplies the area. This deliberately long line exercises the production wrapping branch.'
			'start_on_foot':state['on_foot']=true;toggles['entered_taxi']=false
			'engine_off':state.player['engine_on']=false
			'meet':state['meet']={'lines':['AUDIT VISITOR','Arriving passenger: Market Square']}
			'train_board':state['railway']={'nearest_station':'Oulu','arrivals':[{'time':'13:05','track':'2','train_type':'IC','number':'22','origin':'Helsinki'}],'departures':[{'time':'13:15','track':'1','train_type':'P','number':'55','destination':'Rovaniemi'}]};toggles['next_train']=true
			'abroad':state['abroad']='Sweden · Finnish game rules remain active'
			'loading_start','loading_camera':state['map_loading']='start' if state_name=='loading_start' else 'camera';state['map_loading_detail']='Preparing mapped buildings and road meshes'
			'fare':state.taxi.merge({'live_fare_cents':12345,'fare_distance_m':8200,'passenger_happiness':.85})
			'house_door','home_door':state['on_foot']=true;state['home_door']={'available':true,'is_home':state_name=='home_door'}
			'building_hint':state['on_foot']=true;state['interaction']={'kind':'building','label':'Audit apartment building'}
		if state_name.begins_with('fuel_'):
			state.taxi['fuel_station_price_cents']=189
			state.player['engine_on']=state_name in ['fuel_stop','fuel_engine'];state.player['speed']=2 if state_name=='fuel_stop' else 0
			state['on_foot']=state_name in ['fuel_ready','fuel_active']
			if state_name=='fuel_active':state.taxi['refueling']={}
		hud.show_state(state,toggles)
		if state_name=='subtitle_wrap':hud.show_subtitle({'speaker_name':'Audit passenger','text':'This long passenger subtitle exercises production word wrapping across the available screen width, with a normal dialogue duration.','duration_s':10})
		if state_name.begins_with('summary_'):hud.show_summary(hud.summary_text({'city_summary':['Oulu',420,12,'Helsinki' if state_name=='summary_next' else '',1234]}))
		for frame in 4:
			await process_frame
			hud.show_state(state,toggles)
		await shot('A-273' if state_name.begins_with('loading_') else 'A-261','hud_'+state_name,hud);hud.free()

func phone_branches() -> void:
	var phone:=Phone.new();root.add_child(phone);phone.set_connected(true);phone.open()
	for state in ['PENDING','ACCEPTED','CANCELLED','COMPLETED']:
		phone.show_phone({'busy':false,'items':[{'id':'booking','kind':'booking','status':state,'name':'Audit passenger','train':'IC 22','arrival':'13:05','pickup':'Oulu station','dropoff':'Market Square','surcharge_cents':1500}]})
		await shot('A-262','booking_'+state,phone)
	var rows:=[]
	for i in 3:rows.append({'id':'offer'+str(i),'kind':'offer','status':'AVAILABLE','name':['Henri Lindberg','Eeva Haataja','Antti Hyytia'][i],'pickup':'Market Square','dropoff':'Railway Station','pickup_distance_m':178+400*i,'trip_distance_m':1930,'time_remaining_s':30*(i+1)})
	phone.show_phone({'busy':false,'items':rows});phone.select(2);await shot('A-262','three_offers_known_distances',phone)
	assert(phone.reject_selected());phone.handle_result({'request_id':phone._next_request-1,'ok':false,'reason':'other'});await shot('A-262','answer_failed',phone)
	phone.protest_active=true;phone._refresh();await shot('A-262','protest_notice',phone);phone.free()

func menus() -> void:
	var shell:=Menus.new();root.add_child(shell);shell.career_status=func():return [true]
	for method in ['_main_menu','_settings_menu','_graphics_menu','_city_menu','_pause_menu','_language_menu','_career_menu','_credits_menu','_general_menu','_gameplay_menu','_experimental_menu','_maps_menu','_audio_menu','_pbf_menu','_time_menu','_confirm_reset_career','_confirm_clear_cache','_confirm_reset_home','_confirm_delete_pbf']:
		shell.call(method);paused=false
		await shot('A-265' if method in ['_language_menu','_career_menu','_credits_menu','_time_menu'] else 'A-274','menu'+method,shell)
	for count in [0,1,5]:
		shell.slots=[]
		for i in count:shell.slots.append({'name':'gig-audit'+str(i),'city':'Oulu','completed_fares':i,'balance_cents':75000,'saved_at':'2026-11-15','path':'audit-only/gig-audit'+str(i)+'.json'})
		shell._slot_menu();await shot('A-265','slots_'+str(count),shell)
		if count==5:shell._replace_slot_menu(shell.slots);await shot('A-265','replace_slot_list',shell);shell._delete_slot_menu(shell.slots);await shot('A-265','delete_slot_list',shell)
	paused=false;shell.free()

func small_components() -> void:
	var meter:=preload('res://taxi_meter.gd').new();root.add_child(meter);meter.position=Vector2(260,240);meter.scale=Vector2.ONE*1.4
	for digit in 10:meter.cents=111111*digit;meter.info='Audit fare';await shot('A-264','meter_digit_'+str(digit),meter)
	meter.cents=-1;await shot('A-264','meter_negative_clamp',meter);meter.free()
	for date in [{'year':2025,'month':11,'day':15},{'year':2026,'month':11,'day':15},{'year':2026,'month':10,'day':31}]:
		var picker:=preload('res://date_picker.gd').new();root.add_child(picker);picker.position=Vector2(180,60)
		picker.configure(date,{'year':2025,'month':11,'day':15},{'year':2026,'month':11,'day':15},'en');picker.grab_focus();await shot('A-267','date_%04d_%02d_%02d' % [date.year,date.month,date.day],picker)
		picker._move_month(100);await shot('A-267','date_month_clamped_%04d_%02d' % [date.year,date.month],picker);picker.free()
	var signs:=preload('res://electronic_signs.gd').new();root.add_child(signs);signs.position=Vector2(100,150);signs.size.x=600
	var codes:Array=signs.WARNINGS.keys()
	for offset in range(0,codes.size(),3):
		var rows:=[]
		for code in codes.slice(offset,offset+3):rows.append({'id':'audit','code':code,'text':[]})
		signs.show_state(rows,'en');await shot('A-269','warning_codes_'+str(offset),signs)
	signs.show_state([{'speed_limit_kmh':60,'text':['[tie_4] Audit message']},{'code':'999','text':['Unknown warning branch']}],'en');await shot('A-269','electronic_speed_text_unknown',signs);signs.free()
	var doors:=preload('res://door_marks.gd').new();root.add_child(doors);doors.position=Vector2(400,300)
	for home in [false,true]:
		for available in [false,true]:
			doors.show_doors({'doors':[[0,0,0,home]],'available':available},Vector2.ZERO,1);doors._time=.4
			await shot('A-270','door_home_%s_available_%s' % [home,available],doors)
	doors.free()
	var browser:=OfflineMap.new();root.add_child(browser);browser.position=Vector2(40,60);browser.size=Vector2(720,440);browser.set_process(false);browser.show_point(65.012,25.47)
	for state in ['loading','pin','minimum_zoom','maximum_zoom']:
		if state=='pin':browser.pin=Vector2(65.012,25.47)
		if state=='minimum_zoom':browser._zoom_at(-100,browser.size/2)
		if state=='maximum_zoom':browser._zoom_at(100,browser.size/2)
		browser.queue_redraw();await shot('A-266','map_'+state,browser)
	browser.free()

func labels_and_route() -> void:
	var world:=Context.WeatherWorld.new();root.add_child(world)
	var chunk:=preload('res://map_chunk.gd').new()
	chunk._data={'labels':[[0,-100,'Audit district',0],[0,-40,'Audit lake',1],[0,20,'Audit park',2],[0,80,'Audit building',3],[0,140,'Audit street',4]]};chunk._bounds_rect=Rect2(-400,-300,800,600)
	world._chunks={'audit':chunk}
	var labels:=preload('res://labels.gd').new();root.add_child(labels);labels.size=Vector2(800,600);labels.map_layer=world
	for mode in [1,2]:
		labels.mode=mode;labels.update_view(Transform2D(0,Vector2(400,300)),1,false)
		await shot('A-272','labels_mode_'+str(mode),labels)
	labels.free();chunk._wet.free();chunk._puddles.free();chunk.free();world.free()
	viewport=SubViewport.new();viewport.size=Vector2i(800,600);viewport.own_world_3d=true;viewport.render_target_update_mode=SubViewport.UPDATE_ALWAYS;root.add_child(viewport)
	camera=Camera3D.new();viewport.add_child(camera);camera.current=true;camera.position=Vector3(15,20,15);camera.look_at(Vector3.ZERO)
	camera.environment=Environment.new();camera.environment.background_mode=Environment.BG_COLOR;camera.environment.background_color=Color('303b46')
	var ribbon:=preload('res://route_3d.gd').new();viewport.add_child(ribbon)
	var points:=PackedVector2Array([Vector2(-10,0),Vector2(0,0),Vector2(10,5)])
	for raised in [false,true]:
		ribbon.show_route(str(raised),points,PackedInt32Array([0,1,1] if raised else [0,0,0]),func(at:Vector2,layer:int)->float:return clampf((at.x+10)/10,0,1)*3 if layer==1 else 0.0,1,Color.WHITE)
		assert(ribbon.visible and ribbon.mesh.get_surface_count()>0)
		await take('A-271','route_layer_transition' if raised else 'route_ground','runtime-ui-branches',{'condition':'Production route ribbon mesh on ordinary and raised deck height callbacks','limitation':'Isolated renderer; named third_oulu_route provides natural-map integration.'})
	ribbon.free();viewport.free();viewport=null
