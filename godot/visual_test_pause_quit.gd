## Named UI fixture: render the actual startup confirmation without touching player saves/settings.
extends SceneTree
class MenuShell:
	extends 'res://startup.gd'
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_ALWAYS
		_build_shell()
	func _can_save() -> bool:
		return true

func _initialize() -> void:
	call_deferred('_run')

func _missing(shell: MenuShell) -> Array:
	var missing := []
	if not paused or not shell._panel.is_visible_in_tree():
		missing.append('confirmation is not visible over a paused game')
	for key in ['confirm_quit', 'save_before_quit']:
		if not shell._body.get_children().any(func(child): return child is Label and child.is_visible_in_tree() and child.text == shell._t(key)):
			missing.append('missing visible localized ' + key)
	for key in ['save_and_quit', 'quit_without_saving', 'cancel']:
		var choices := shell._body.get_children().filter(func(child): return child is Button and child.text == shell._t(key))
		if choices.size() != 1 or not choices[0].is_visible_in_tree() or choices[0].disabled:
			missing.append('missing usable ' + key)
		elif key == 'cancel' and not choices[0].has_focus():
			missing.append('Cancel is not focused')
	return missing

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var path := args[args.find('--startup-scenario') + 1]
	var scenario: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	var shell := MenuShell.new()
	root.add_child(shell)
	shell._language = scenario.get('language', 'fi')
	paused = true
	shell._pause_menu()
	for child in shell._body.get_children():
		if child is Button and child.text == shell._t('quit'):
			child.pressed.emit()
	var ready_frames := 0
	var started := Time.get_ticks_msec()
	var missing := []
	while ready_frames < 60 and Time.get_ticks_msec() - started < 30000:
		await process_frame
		missing = _missing(shell)
		ready_frames = ready_frames + 1 if missing.is_empty() else 0
	var result := {'scenario': scenario.id, 'commit': scenario.commit, 'status': 'passed' if missing.is_empty() else 'failed',
		'errors': missing, 'readiness_frames': ready_frames, 'language': shell._language,
		'renderer': '%s on %s' % [RenderingServer.get_current_rendering_method(), RenderingServer.get_video_adapter_name()],
		'resolution': [root.size.x, root.size.y]}
	if missing.is_empty():
		await RenderingServer.frame_post_draw
		var shot := path.get_base_dir().path_join('screenshot.png')
		root.get_texture().get_image().save_png(shot)
		result.screenshot = shot
	var file := FileAccess.open(path.get_base_dir().path_join('result.json'), FileAccess.WRITE)
	file.store_string(JSON.stringify(result, '  '))
	file.close()
	shell.queue_free()
	await process_frame
	print('VISUAL_TEST ', JSON.stringify(result))
	quit(0 if missing.is_empty() else 1)
