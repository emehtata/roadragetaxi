## Audit-only targeted production draw paths; never loaded by gameplay.
extends SceneTree
const Chunk := preload('res://map_chunk.gd')
const EL := preload('res://entity_layer.gd')
const Home := preload('res://home_interior.gd')
var captures: Array = []
var destination: String

class Effect extends 'res://entity_layer.gd':
	var audit_kind := ''
	var phase := 0.5
	func _process(_delta: float) -> void: pass
	func _draw() -> void:
		_font = ThemeDB.fallback_font
		_canvas = self
		view_rect = Rect2(-100,-100,200,200)
		match audit_kind:
			'exhaust smoke', 'engine smoke': _smoke(Vector2.ZERO,0,0,phase,audit_kind == 'exhaust smoke',1.0)
			'vomit puddle', 'vomit splashes': _vomit_puddle(Vector2.ZERO,Vector2(10,20))
			'hockey stick': _hockey_stick(Vector2.ZERO,Vector2.RIGHT,Vector2.DOWN,0.45,phase*0.3)
			'golf club': _golf_club(Vector2.ZERO,Vector2.RIGHT,Vector2.DOWN,0.45,{'phase':'swing','swing':phase,'club':'driver'})
			'golf ball': _golf_ball([Vector2.ZERO,phase*2.0,Vector2(3,1),false])
			'dog leash': _dog(Vector2(-1,0),Vector2(1,0),0,{'color':[170,115,65]})
			'bottle': _bottle(Vector2.ZERO,Vector2.RIGHT,Vector2.DOWN,0.45,{'bottle':true},Vector2(.3,0))
			'rage face': _rage_face(Vector2.ZERO,0,1.0,false)
			'speed limit sign': _speed_sign(Vector2.ZERO,50)
			'speech bubble':
				_canvas = _overlay
				_overlays = [_bubble.bind(Vector2.ZERO,'Audit: taxi please!',Color.BLACK,Color.ORANGE,1.0,18,true)]
				_overlay.queue_redraw()
			'puck', 'soccer ball':
				_canvas = _people
				_puck_frame = [{'pucks':[[0,0]]} if audit_kind == 'puck' else {'balls':[[0,0]]},{},0.0]
				_people.queue_redraw()
			'booked passenger arrow': _booked_arrow({'meet':{'arrow':{'x':0,'y':0,'radius_m':.45}}},{},0,{})
			'headlight beams':
				for polygon in beam_polygons(Vector2(-8,0),0,1.8,15.0): draw_colored_polygon(polygon,Color(1,.95,.72,.12))
			'brake glow', 'taxi sign glow':
				glow_points.clear(); glow_colors.clear(); glow_triangles.clear()
				lamp_glow(Vector2.ZERO,BRAKE_GLOW if audit_kind == 'brake glow' else TAXI_SIGN_GLOW,1.0,glow_points,glow_colors,glow_triangles)
				_glow.queue_redraw()
			'tyre tracks':
				var points := []
				for i in 9: points.append([Vector2(i-4,sin(i*.4)),0.1*i,1.0,true,0.0])
				_tracks.draw.connect(_draw_trail.bind(['rubber',points,_tracks]),CONNECT_ONE_SHOT)
				_tracks.queue_redraw()
			'route ribbon':
				_route_now = PackedVector2Array([Vector2(-10,5),Vector2(-2,5),Vector2(1,0),Vector2(8,0)])
				_route_node.queue_redraw()

class WeatherWorld extends Node2D:
	var px_per_m := 20.0
	var _chunks := {}
class Shell extends 'res://startup.gd':
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_ALWAYS
		_language = 'en'
		_cities = ['Helsinki','Oulu']
		AudioManager.ensure_buses()
		_build_shell()
	func _play_menu_music() -> void: pass
	func _notification(_what: int) -> void: pass
class AuditHost extends Node:
	var _visual_test := true
	var _screenshot_path := ''

func _initialize() -> void:
	create_timer(240).timeout.connect(func(): quit(1))
	call_deferred('run')

func take(id: String, pose: String, note: String, confirmed := true) -> void:
	for i in 6: await process_frame
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	var file := '%s_context_%s.png' % [id,pose]
	var changed := 0
	var background := Color("26343e")
	for x in range(0,shot.get_width(),3):
		for y in range(0,shot.get_height(),3):
			if absf(shot.get_pixel(x,y).r-background.r)+absf(shot.get_pixel(x,y).g-background.g)+absf(shot.get_pixel(x,y).b-background.b) > .01: changed += 1
	var ready := changed > 4 and confirmed
	if ready: assert(shot.save_png(destination.path_join(file)) == OK)
	captures.append({'asset':id,'file':file if ready else '', 'angle':pose,'condition':note,'ready':ready,'target_confirmed':confirmed,'nonbackground_samples':changed,'resolution':[shot.get_width(),shot.get_height()]})
	print('AUDIT context ',id,' ',pose,' ready=',ready)

func canvas_case(row: Dictionary) -> void:
	var kind: String = row['name']
	var group := Node2D.new(); root.add_child(group)
	var cam := Camera2D.new(); group.add_child(cam); cam.make_current()
	var chunk := Chunk.new(); chunk._origin=Vector2.ZERO; chunk._font=ThemeDB.fallback_font
	chunk._season=[0.0,0.0,1.0,0.0]; chunk._wetness=1.0
	var node := Node2D.new(); group.add_child(node)
	var effect: Effect
	var weather: Node
	var furniture: Dictionary
	var furniture_canvas: Control
	if row['category']=='Interior furniture':
		var plans = JSON.parse_string(FileAccess.get_file_as_string('res://tests/data/home_plans.json'))
		for plan in plans:
			for item in plan.get('furniture',[]):
				if item['kind']==kind: furniture=item.duplicate(true); break
			if not furniture.is_empty(): break
		assert(not furniture.is_empty(),'expected furniture fixture')
		var centre := Vector2.ZERO
		for point in furniture['points']: centre += Vector2(point[0],point[1])
		centre /= furniture['points'].size()
		for point in furniture['points']: point[0]-=centre.x; point[1]-=centre.y
		furniture_canvas=Home.PlanCanvas.new(); group.add_child(furniture_canvas)
		furniture_canvas.position=Vector2(-400,-300); furniture_canvas.size=Vector2(800,600)
		furniture_canvas.plan={'footprint':[[-3,-2],[3,-2],[3,2],[-3,2]],'furniture':[furniture]}
	elif row['category']=='Effects' or kind in ['speed limit sign','route ribbon']:
		effect=Effect.new(); effect.audit_kind=kind; group.add_child(effect)
	elif row['category']=='Weather':
		weather=preload('res://weather_layer.gd').new(); group.add_child(weather)
		var world := WeatherWorld.new(); group.add_child(world)
		weather.map_layer=world; weather.clock=.35
		if kind in ['rain','snow','slush']:
			var precipitation := Control.new(); precipitation.size=Vector2(800,600); precipitation.position=Vector2(-400,-300)
			group.add_child(precipitation); weather.precipitation=precipitation; weather.kind=kind
			precipitation.draw.connect(weather._draw_precipitation)
		elif kind=='water ripples':
			chunk._bounds_rect=Rect2(-20,-20,40,40)
			chunk._water_ripple_spots=[{'at':Vector2.ZERO,'radius':3.0,'reveal':0.0}]
			world._chunks={'audit':chunk}; weather.ripples=node; node.draw.connect(weather._draw_ripples)
		elif kind in ['vehicle splash','mud overlay']:
			weather.splash_node=node
			if kind=='vehicle splash': weather.splashes=[[Vector2.ZERO,.15,1.0],[Vector2(2,1),.25,.7]]
			else: weather.mud=[[Vector2.ZERO,Vector2.ZERO,.15,.5,false],[Vector2(1,.4),Vector2.ZERO,.3,.3,true]]
			node.draw.connect(weather._draw_splashes)
		else:
			var flash := ColorRect.new(); flash.position=Vector2(-400,-300); flash.size=Vector2(800,600)
			flash.color=Color(1,1,1,EL.lightning_alpha({'weather':{'lightning_intensity':.6}},{},0))
			group.add_child(flash)
	elif kind=='taxi stand sign':
		chunk._data={'taxi_stands':[[0,0]]}; node.draw.connect(chunk._draw_points.bind(node))
	elif kind=='fuel price board':
		chunk._data={'fuel_stations':[{'x':0,'y':0,'name':'Audit fuel','price_cents':189}]}; node.draw.connect(chunk._draw_fuel_boards.bind(node))
	elif kind=='Christmas star':
		var source := FileAccess.get_file_as_string('res://building_snow.gdshader')
		var first := source.find('vec3 star_light(')
		var last := source.find('// Independence Day:',first)
		assert(first>=0 and last>first)
		var shader := Shader.new()
		shader.code='shader_type canvas_item; render_mode unshaded;\n'+source.substr(first,last-first)+"""
void fragment() {
 vec2 cell=floor(UV*4.0); vec2 local=fract(UV*4.0);
 vec4 star=decoration(vec2((local.x-.5)*1.6,(1.0-local.y)*1.4),vec2(.8,1.4),.1,1.0,cell.x/3.0,cell.y/3.0,1.0);
 COLOR=vec4(mix(vec3(.03,.05,.07),star.rgb,star.a),1.0);
}
"""
		var panel := ColorRect.new(); panel.position=Vector2(-300,-240); panel.size=Vector2(600,480)
		var material := ShaderMaterial.new(); material.shader=shader; panel.material=material; group.add_child(panel)
	elif kind=='Christmas eave lights':
		var holiday := preload('res://holiday_layer.gd').new(); group.add_child(holiday)
		holiday.houses=[[PackedVector2Array([Vector2(-5,-2),Vector2(5,-2),Vector2(5,2),Vector2(-5,2)]),0.0,PackedVector2Array([Vector2.ZERO])]]
		holiday.christmas_layer=node; node.draw.connect(holiday._draw_christmas)
	elif kind in ['shore waves','open water shader','ice cover','waterline']:
		chunk._data={'waters':[[[-10,-7],[10,-7],[10,7],[-10,7]]],'water_lines':[[[-8,0],[8,2]]],'shore_waves':[{'distance':2.0,'points':PackedVector2Array([Vector2(-9,-3),Vector2(-3,-1),Vector2(3,-2),Vector2(9,0)])}]}
		if kind=='waterline': chunk._data['waters']=[]
		if kind=='ice cover': chunk._lake_ice=true
		if kind=='shore waves':
			node.material=Chunk.SHORE_MATERIAL; node.material.set_shader_parameter('wind',Vector2(12,0)); node.draw.connect(chunk._draw_shore_waves.bind(node))
		else:
			if kind=='open water shader': node.material=Chunk.WATER_MATERIAL
			node.draw.connect(chunk._draw_water.bind(node))
	elif kind=='door interaction marker' or kind=='building entrance mark':
		var doors := preload('res://door_marks.gd').new(); group.add_child(doors)
		doors.show_doors({'doors':[[0,0,0,true]],'available':true},Vector2.ZERO,20)
	elif kind=='floating map labels':
		var world := WeatherWorld.new(); group.add_child(world)
		chunk._data={'labels':[[0,0,'Audit district',0],[7,-3,'Audit street',4]]}; chunk._bounds_rect=Rect2(-30,-30,60,60)
		world._chunks={'audit':chunk}
		var labels := preload('res://labels.gd').new(); group.add_child(labels); labels.position=Vector2(-400,-300); labels.size=Vector2(800,600)
		labels.map_layer=world; labels.mode=2; labels.update_view(Transform2D(0,Vector2(400,300)),1,false)
	else:
		await take(row['id'],'unsupported','No independent production draw path established',false)
		chunk._wet.free(); chunk._puddles.free(); chunk.free(); group.free(); return
	for zoom in ['normal','close']:
		var ppm := 20.0 if zoom=='normal' else 60.0
		if kind in ['bottle','rage face','golf club','hockey stick','puck','soccer ball']: ppm=80 if zoom=='normal' else 160
		if kind=='headlight beams': ppm=18 if zoom=='normal' else 27
		cam.zoom=Vector2.ONE*ppm; chunk._px_per_m=ppm
		if kind in ['Christmas star','floating map labels']: cam.zoom=Vector2.ONE
		if furniture_canvas!=null:
			cam.zoom=Vector2.ONE
			furniture_canvas.plan['footprint']=[[-3,-2],[3,-2],[3,2],[-3,2]] if zoom=='normal' else [[-1.5,-1.2],[1.5,-1.2],[1.5,1.2],[-1.5,1.2]]
			furniture_canvas.queue_redraw()
		if effect!=null: effect.px_per_m=ppm; effect.phase=.3 if zoom=='normal' else .7; effect.queue_redraw()
		if weather!=null:
			weather.map_layer.px_per_m=ppm
			if kind in ['rain','snow','slush','lightning']: cam.zoom=Vector2.ONE
			if kind in ['rain','snow','slush']: weather.precipitation.queue_redraw()
		node.queue_redraw()
		await take(row['id'],zoom,'isolated production draw; fixed state and '+str(ppm)+' px/m')
	chunk._wet.free(); chunk._puddles.free(); chunk.free(); group.free()

func ui_case(row: Dictionary) -> void:
	var group := Control.new(); root.add_child(group); group.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var kind: String=row['name']
	var target: Control
	if kind in ['HUD','loading screen']:
		var packed := preload('res://main.tscn').instantiate()
		var hud: Control=packed.get_node('Ui/Hud'); packed.get_node('Ui').remove_child(hud); hud.owner=null
		for child in hud.find_children('*','',true,false): child.owner=hud
		packed.free(); group.add_child(hud); hud.size=Vector2(800,600)
		hud.show_state({'player':{'speed':12.5},'on_foot':false,'game_time_seconds':46800,'taxi':{'balance_cents':75000,'completed_fares':3,'total_score':42},'calendar':{'date':'2026-06-20'},'map_loading':'camera' if kind=='loading screen' else '', 'map_loading_detail':'Loading audited map tiles','road':{'speed_limit_kmh':50}})
		target=hud
	elif kind in ['phone','navigation phone']:
		var phone := Phone.new(); group.add_child(phone); phone.set_connected(true); phone.open()
		phone.show_phone({'busy':kind=='navigation phone','items':[{'id':'audit','kind':'offer','status':'AVAILABLE','name':'Audit passenger','pickup':'Market Square','dropoff':'Railway Station','trip_distance_m':8200,'time_remaining_s':120}]})
		phone.show_navigation({'instruction':{'maneuver':'left','distance_m':120,'total_m':800,'street':'Audit Street'}},'Drive to station')
		phone.position=Vector2(180,20); target=phone
	elif kind=='taxi meter':
		var meter := preload('res://taxi_meter.gd').new(); group.add_child(meter); meter.position=Vector2(100,200); meter.cents=12345; meter.info='8.2 km'; target=meter
	elif kind=='date picker':
		var picker := preload('res://date_picker.gd').new(); group.add_child(picker)
		picker.position=Vector2(150,40); picker.configure({'year':2026,'month':6,'day':20},{'year':2025,'month':11,'day':14},{'year':2026,'month':11,'day':14},'en'); target=picker
	elif kind=='tutorial':
		var tutorial := preload('res://tutorial.gd').new(); group.add_child(tutorial); target=tutorial
	elif kind=='map browser':
		var browser := preload('res://map_browser.gd').new(); group.add_child(browser); browser.position=Vector2(40,60); browser.size=Vector2(720,440); browser.show_point(65.012,25.47); browser.pin=Vector2(65.012,25.47); target=browser
		for i in 120:
			await process_frame
			if browser._tiles.values().filter(func(t):return t!=null).size()>3: break
	elif kind in ['startup menus','pause and settings']:
		var shell := Shell.new(); group.add_child(shell); target=shell
		if kind=='startup menus': shell._main_menu()
		else:
			shell._pause_menu()
			await take(row['id'],'pause','actual startup pause menu; no live session or save callbacks invoked')
			paused=false
			shell._settings_menu()
	else:
		await take(row['id'],'unsupported','No UI fixture',false); group.free(); return
	await take(row['id'],'normal','actual UI component; 800x600 fixed audit state',target!=null)
	if target!=null and kind not in ['HUD','loading screen','map browser','startup menus','pause and settings']: target.scale*=1.15
	if kind=='pause and settings': target._graphics_menu()
	if kind=='startup menus': target._city_menu()
	await take(row['id'],'close','actual UI component; second state or 1.15x scale',target!=null)
	group.free()

func run() -> void:
	var args := OS.get_cmdline_user_args(); destination=args[1]
	root.size=Vector2i(800,600); RenderingServer.set_default_clear_color(Color('26343e'))
	Chunk.buildings_3d=false; Chunk.outdoor_3d=false
	var fixture=JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	for row: Dictionary in fixture['assets']:
		if row['status']!='uninspected' or row['category']=='Unused assets': continue
		if row['category']=='Interface' and row['name'] not in ['door interaction marker','route ribbon','floating map labels']: await ui_case(row)
		else: await canvas_case(row)
	var file := FileAccess.open(destination.path_join('context-results.json'),FileAccess.WRITE)
	file.store_string(JSON.stringify({'captures':captures,'renderer':RenderingServer.get_current_rendering_method(),'adapter':RenderingServer.get_video_adapter_name()},'\t')); file.close(); quit()
