## A phone offer must not receive keyboard/mouse input through the pause menu.
extends SceneTree
class StubGame:
	extends Node2D
	var _help = null
class MenuShell:
	extends 'res://startup.gd'
	var saves := 0
	func _can_save() -> bool:
		return true
	func _save_game(done: Callable) -> void:
		saves += 1
		await get_tree().create_timer(0.05, true).timeout
		done.call(true)
var requests := 0
func _initialize() -> void:
	call_deferred('run')
func key(code: Key) -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = code
		event.physical_keycode = code
		event.pressed = pressed
		Input.parse_input_event(event)
		await process_frame
func run() -> void:
	var shell := MenuShell.new()
	shell.process_mode = Node.PROCESS_MODE_ALWAYS
	root.add_child(shell)
	var game := preload('res://main.tscn').instantiate()
	game.set_script(StubGame)
	shell._game = game
	shell.add_child(game)
	var phone = game.get_node('Ui/Phone')
	phone.request.connect(func(_action, _item, _id): requests += 1)
	phone.set_connected(true)
	phone.show_phone({'busy':false, 'items':[{'id':'fare','status':'AVAILABLE','name':'Aino','pickup':'Oulu','dropoff':'Raahe','price_cents':1000,'expires_in_s':60.0}]})
	phone.open()
	shell._panel.hide()
	await key(KEY_ESCAPE)
	assert(paused and shell._panel.visible and phone.is_open)
	var save: Button
	for child in shell._body.get_children():
		if child is Button and child.text == shell._t('save_game'):
			save = child
	assert(save != null)
	save.grab_focus()
	await key(KEY_ENTER)
	await create_timer(0.1, true).timeout
	assert(shell.saves == 1 and requests == 0, 'Save must not accept the phone offer')
	for code in [KEY_1, KEY_X, KEY_P, KEY_KP_ENTER]:
		await key(code)
	assert(requests == 0 and phone.is_open, 'paused phone must ignore fare and toggle keys')
	for pressed in [true, false]:
		var click := InputEventMouseButton.new()
		click.button_index = MOUSE_BUTTON_LEFT
		click.position = phone._accept.get_global_rect().get_center()
		click.pressed = pressed
		Input.parse_input_event(click)
		await process_frame
	assert(requests == 0, 'paused phone must ignore mouse clicks too')
	for i in 3:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png('/tmp/rrt-pause-phone.png')
	shell._resume()
	await key(KEY_ENTER)
	assert(requests == 1, 'phone accepts normally after resuming')
	print('PAUSE_PHONE: Save received Enter; phone ignored paused input and resumed normally')
	quit()
