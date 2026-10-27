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
		if saves == 2:
			print('PAUSE_SAVE: Save and Quit both awaited completion')
		done.call(true)
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	var shell := MenuShell.new()
	root.add_child(shell)
	await process_frame
	shell._pause_menu()
	for i in 3:
		await process_frame
	await RenderingServer.frame_post_draw
	if DisplayServer.get_name() != 'headless':
		root.get_texture().get_image().save_png('/tmp/rrt-pause-save.png')
	var save: Button
	var leave: Button
	for child in shell._body.get_children():
		if child is Button:
			if child.text == shell._t('save_game'):
				save = child
			if child.text == shell._t('quit'):
				leave = child
	assert(save != null and leave != null)
	save.pressed.emit()
	await create_timer(0.1, true).timeout
	assert(shell.saves == 1 and shell._pause_status.text == shell._t('saved'))
	leave.pressed.emit()
	await create_timer(0.2, true).timeout
	printerr('FAIL: Quit did not finish after saving')
	quit(1)
