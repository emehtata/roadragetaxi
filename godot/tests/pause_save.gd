## Exercise the real pause-menu choices with controlled asynchronous save acknowledgement.
extends SceneTree
class MenuShell:
	extends 'res://startup.gd'
	var saves := 0
	var exits := 0
	var saveable := true
	var pending := Callable()
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_ALWAYS
		_build_shell()
	func _can_save() -> bool:
		return saveable
	func _save_game(done: Callable) -> void:
		saves += 1
		pending = done
		await get_tree().process_frame
	func _quit_game() -> void:
		exits += 1
var failures := 0
func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr('FAIL: ', message)
func button(shell: MenuShell, key: String) -> Button:
	for child in shell._body.get_children():
		if child is Button and child.text == shell._t(key):
			return child
	return null
func escape(shell: MenuShell) -> void:
	var event := InputEventKey.new()
	event.keycode = KEY_ESCAPE
	event.pressed = true
	shell._unhandled_input(event)
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	var shell := MenuShell.new()
	root.add_child(shell)
	paused = true  # no rendered viewport texture to capture headlessly
	shell._pause_menu()
	button(shell, 'quit').pressed.emit()
	await process_frame
	check(shell.saves == 0 and shell.exits == 0 and paused, 'opening Quit only asks confirmation')
	var save := button(shell, 'save_and_quit')
	var discard := button(shell, 'quit_without_saving')
	var cancel := button(shell, 'cancel')
	check(save != null and discard != null and cancel != null, 'three explicit choices')
	if save == null or discard == null or cancel == null:
		quit(1)
		return
	await process_frame
	check(cancel.has_focus(), 'Cancel initially focused')
	cancel.pressed.emit()
	check(button(shell, 'resume') != null and shell.saves == 0, 'Cancel returns to pause menu')
	button(shell, 'quit').pressed.emit()
	escape(shell)
	check(button(shell, 'resume') != null and shell.saves == 0, 'Escape returns to pause menu')
	button(shell, 'quit').pressed.emit()
	save = button(shell, 'save_and_quit')
	discard = button(shell, 'quit_without_saving')
	cancel = button(shell, 'cancel')
	save.pressed.emit()
	save.pressed.emit()  # also guard a queued/repeated activation
	discard.pressed.emit()
	cancel.pressed.emit()
	escape(shell)
	check(shell.saves == 1 and shell.exits == 0, 'one save, no early exit/navigation while pending')
	check(save.disabled and discard.disabled and cancel.disabled and save.is_inside_tree(), 'pending choices disabled')
	shell.pending.call(false)
	check(shell.exits == 0 and shell._pause_status.text == shell._t('save_failed'), 'failure keeps confirmation open')
	check(not save.disabled and not discard.disabled and not cancel.disabled, 'failure permits retry, discard and cancel')
	save.pressed.emit()
	check(shell.saves == 2 and shell.exits == 0, 'retry waits for acknowledgement')
	shell.pending.call(true)
	check(shell.exits == 1, 'acknowledged save exits')
	shell._pause_menu()
	button(shell, 'quit').pressed.emit()
	button(shell, 'quit_without_saving').pressed.emit()
	check(shell.exits == 2 and shell.saves == 2, 'explicit discard does not save')
	shell._pause_menu()
	button(shell, 'quit').pressed.emit()
	button(shell, 'save_and_quit').pressed.emit()
	shell.pending.call(false)
	button(shell, 'quit_without_saving').pressed.emit()
	check(shell.exits == 3 and shell.saves == 3, 'explicit discard works after failed save')
	shell._pause_menu()
	button(shell, 'save_game').pressed.emit()
	shell.pending.call(true)
	check(shell.saves == 4 and shell.exits == 3 and shell._pause_status.text == shell._t('saved'), 'manual Save does not quit')
	shell.saveable = false
	shell._pause_menu()
	button(shell, 'quit').pressed.emit()
	check(shell.exits == 4 and shell.saves == 4, 'non-saveable Quit keeps direct exit')
	for language in ['fi', 'en', 'de']:
		for key in ['confirm_quit', 'save_before_quit', 'save_and_quit']:
			check(shell.T.text(key, language) != key, 'translated %s/%s' % [language, key])
	await process_frame
	shell.queue_free()
	await process_frame
	print('PAUSE_SAVE failures=', failures)
	quit(1 if failures else 0)
