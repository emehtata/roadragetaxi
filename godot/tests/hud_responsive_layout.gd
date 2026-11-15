## Production HUD layout with an unsaved HudLayout; no player settings are read or written.
extends SceneTree

var failures: Array[String] = []
var hud: Control
const BASE := {'player':{'speed':0.0,'engine_on':true,'fuel_l':30.0},'on_foot':false,'game_time_seconds':46800,'taxi':{'balance_cents':75000,'completed_fares':3,'total_score':42},'calendar':{'date':'2026-06-20','time_scale':60},'weather':{'weather_type':'clear','cloud_cover':0.1,'temperature_c':17.0,'wetness':0.0}}

func _initialize() -> void:
	call_deferred('run')

func check(ok: bool, message: String) -> void:
	if not ok:
		failures.append(message)
		print('FAIL: ', message)

func settle(state: Dictionary) -> void:
	for frame in 4:
		hud.show_state(state)
		await process_frame

func run() -> void:
	var packed := preload('res://main.tscn').instantiate()
	hud = packed.get_node('Ui/Hud')
	packed.get_node('Ui').remove_child(hud)
	hud.owner = null
	for child in hud.find_children('*', '', true, false):
		child.owner = hud
	packed.free()
	root.add_child(hud)
	for language in ['en', 'fi', 'de']:
		hud.language = language
		for dimensions in [Vector2i(1280,720), Vector2i(800,600), Vector2i(1280,720)]:
			root.size = dimensions
			await process_frame
			await test_live_fare_status_bounds()
			await test_fuel_notice_wrap_and_reset()
			await test_control_hint_credit_clearance()
	await test_resize_and_custom_layout_preserved()
	hud.free()
	print('HUD_RESPONSIVE_LAYOUT: %d failures' % failures.size())
	quit(0 if failures.is_empty() else 1)

func test_live_fare_status_bounds() -> void:
	var state := BASE.duplicate(true)
	state.taxi.merge({'live_fare_cents':12345,'fare_distance_m':8200})
	await settle(state)
	var meter: Rect2 = hud._meter.get_global_rect()
	check(Rect2(Vector2.ZERO,hud.size).encloses(meter), 'meter wholly on screen')
	for label in [hud._money,hud._clock,hud._weather]:
		check(not meter.intersects(label.get_global_rect()), 'meter clears '+label.name+' at '+str(hud.size))
	check(hud.layout.rects.has('status') and hud.layout.rects.has('meter'), 'draggable panel registration retained')

func test_fuel_notice_wrap_and_reset() -> void:
	var state := BASE.duplicate(true)
	state.taxi['fuel_station_price_cents'] = 189
	state.player['speed'] = 2.0
	await settle(state)
	check(hud._notice.text == hud.T.text('fuel_hint_stop',hud.language), 'full localized fuel instruction retained')
	check(Rect2(Vector2(20,0),hud.size-Vector2(40,0)).encloses(hud._notice.get_global_rect()), 'fuel notice fits horizontal margins '+hud.language)
	state.taxi = {'notification_msg':'OK','notification_timer':10.0}
	await settle(state)
	check(hud._notice.size.x < 100 and hud._notice.size.y < 60, 'short notice restores natural dimensions')
	await settle(BASE)
	check(not hud._notice.visible, 'empty notice hidden')
	check(not hud._hint.visible, 'empty control hint hidden')

func test_control_hint_credit_clearance() -> void:
	for kind in ['house','home','building']:
		var state := BASE.duplicate(true)
		state.on_foot = true
		if kind == 'building':
			state['interaction'] = {'kind':'building','label':'Market Square Apartments'}
		else:
			state['home_door'] = {'available':true,'is_home':kind=='home'}
		await settle(state)
		check(hud._hint.visible and Rect2(Vector2(20,0),hud.size-Vector2(40,0)).encloses(hud._hint.get_global_rect()), 'control hint wholly on screen '+kind+' '+hud.language)
		check(hud._hint.get_global_rect().end.y+4 <= hud.osm_credit.get_global_rect().position.y, 'control hint above credit '+kind)
		state.taxi['notification_msg'] = 'Priority notice'
		state.taxi['notification_timer'] = 10
		await settle(state)
		check(not hud._hint.visible, 'notice priority hides control hint')

func test_resize_and_custom_layout_preserved() -> void:
	root.size = Vector2i(800,600)
	await process_frame
	var fare := BASE.duplicate(true)
	fare.taxi['live_fare_cents'] = 12345
	await settle(fare)
	var before: Vector2 = hud._meter.position
	hud.layout.offsets['meter'] = Vector2(10,10)
	await settle(fare)
	check(hud._meter.position.is_equal_approx(before+Vector2(10,10)), 'dragging starts from the responsive default without a jump')
	hud.layout.offsets = {'meter':Vector2(-200,80),'status':Vector2(-100,80)}
	hud.layout.scales = {'meter':0.8,'status':0.8}
	var offsets: Dictionary = hud.layout.offsets.duplicate()
	var scales: Dictionary = hud.layout.scales.duplicate()
	var state := BASE.duplicate(true)
	state.taxi['live_fare_cents'] = 12345
	for dimensions in [Vector2i(1280,720),Vector2i(800,600),Vector2i(1280,720)]:
		root.size = dimensions
		await process_frame
		await settle(state)
		check(hud.layout.offsets == offsets and hud.layout.scales == scales, 'explicit offsets/scales retained')
