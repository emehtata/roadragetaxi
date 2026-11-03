## Real HUD lifecycle and optional render checks: --state PATH (generated server state).
extends SceneTree
const SignPanel := preload('res://electronic_signs.gd')
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	assert(SignPanel.reading_text({'speed_limit_kmh':60,'distance_m':200}, 'en') == '60 km/h')
	assert(SignPanel.reading_text({'code':'144','distance_m':100},'fi').begins_with('Liukas tie'))
	assert(SignPanel.reading_text({'text':['[tie_4] +5 min'],'distance_m':90},'en').contains('[4] +5 min'))
	var args := OS.get_cmdline_user_args()
	var at := args.find('--state')
	if at < 0:
		var panel := SignPanel.new()
		root.add_child(panel)
		panel.show_state([{'speed_limit_kmh':60,'distance_m':100}], 'en')
		assert(panel.visible and panel._rows[0].text == '60 km/h')
		panel.show_state([], 'en')
		assert(not panel.visible)
		panel.free()
	else:
		var state: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[at+1]))
		var viewport := SubViewport.new()
		viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		root.add_child(viewport)
		var game := preload('res://main.tscn').instantiate()
		viewport.add_child(game)
		game.set_process(false)
		game.sim.set_process(false)
		game.hud.visible = true
		for dimensions in [Vector2i(1280,720),Vector2i(800,600)]:
			viewport.size = dimensions
			game.hud.show_state(state)
			game.instruments.show_state(state)
			for i in 4:
				await process_frame
			game.hud._layout()
			var panel: Control = game.hud._electronic
			assert(panel.visible)
			assert(panel.get_rect().end.x < viewport.size.x - 79)
			assert(panel.get_rect().position.y >= game.hud._weather.get_rect().end.y)
			if DisplayServer.get_name() != 'headless':
				await RenderingServer.frame_post_draw
				var shot := viewport.get_texture().get_image()
				assert(shot.get_width() == dimensions.x and shot.get_height() == dimensions.y)
				shot.save_png('/tmp/rrt-electronic-%d.png' % dimensions.x)
		game.hud.show_state({})
		assert(not game.hud._electronic.visible)
		viewport.queue_free()
		await process_frame
	print('ELECTRONIC_SIGNS: readings, localisation, hiding and layout checks passed')
	quit(0)
