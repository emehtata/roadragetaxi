## Exercise the actual pause-menu callbacks with an asynchronous save acknowledgement.
extends SceneTree
class MenuShell:
	extends 'res://startup.gd'
	var saves := 0
	func _can_save() -> bool:
		return true
	func _save_game(done: Callable) -> void:
		saves += 1
		await get_tree().create_timer(0.05, true).timeout
		if saves == 3:
			print('PAUSE_SAVE: failed Quit stayed open; retry saved before Quit')
		done.call(saves > 1)
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	var shell := MenuShell.new()
	root.add_child(shell)
	await process_frame
	if DisplayServer.get_name() == 'headless':
		paused = true  # no rendered viewport texture to capture
	shell._pause_menu()
	for i in 3:
		await process_frame
	if DisplayServer.get_name() != 'headless':
		await RenderingServer.frame_post_draw
	var save: Button
	var leave: Button
	for child in shell._body.get_children():
		if child is Button:
			if child.text == shell._t('save_game'):
				save = child
			if child.text == shell._t('quit'):
				leave = child
	assert(save != null and leave != null)
	leave.pressed.emit()
	await create_timer(0.1, true).timeout
	assert(shell.saves == 1 and shell._pause_status.text == shell._t('save_failed'))
	assert(shell._body.has_node("QuitWithoutSaving"))
	if DisplayServer.get_name() != 'headless':
		await RenderingServer.frame_post_draw
	if DisplayServer.get_name() != 'headless':
		for arg in OS.get_cmdline_user_args():
			if arg.begins_with('--shot='):
				assert(root.get_texture().get_image().save_png(arg.trim_prefix('--shot=')) == OK)
	if '--discard' in OS.get_cmdline_user_args():
		print('PAUSE_SAVE: explicit quit without saving')
		shell._body.get_node("QuitWithoutSaving").pressed.emit()
		return
	save.pressed.emit()
	await create_timer(0.1, true).timeout
	assert(shell.saves == 2 and shell._pause_status.text == shell._t('saved'))
	leave.pressed.emit()
	await create_timer(0.2, true).timeout
	printerr('FAIL: Quit did not finish after saving')
	quit(1)
