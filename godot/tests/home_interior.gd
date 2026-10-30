## Lifecycle checks use the real pause-menu callbacks; optional --plan PATH renders Python output.
extends SceneTree

const Viewer := preload("res://home_interior.gd")
const T := preload("res://i18n.gd")

class Client extends SimClient:
	var reply := {"error": "no_home"}
	func _process(_delta: float) -> void:
		pass
	func send_home_interior() -> bool:
		home_plan = reply
		return connected

class Game extends Node:
	var drive := DriveInput.new()
	var sim := Client.new()
	var _help: PanelContainer
	var camera := Camera2D.new()
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_PAUSABLE
		add_child(sim)
		add_child(camera)

class Shell extends 'res://startup.gd':
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_ALWAYS
		_build_shell()

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var shell := Shell.new()
	root.add_child(shell)
	shell._game = Game.new()
	shell.add_child(shell._game)
	shell._game.sim.connected = true
	shell._game.camera.position = Vector2(130, -85)
	var camera_position: Vector2 = shell._game.camera.position
	if DisplayServer.get_name() == "headless":
		paused = true  # the dummy renderer has no image for the pause-menu thumbnail
	shell._pause_menu()
	var button: Button
	for child in shell._body.get_children():
		if child is Button and child.text == T.text("home_floor_plan", "en"):
			button = child
	assert(button != null, "Home action is discoverable in the pause menu")
	var press := InputEventKey.new()
	press.physical_keycode = KEY_W
	press.pressed = true
	shell._game.drive.handle(press)
	button.pressed.emit()
	await process_frame
	assert(shell._home_viewer != null and not shell._panel.visible)
	assert(not shell._game.drive.any_held(), "Opening clears held driving keys")
	assert(shell._home_viewer._description.text == T.text("home_plan_no_home", "en"))
	assert(paused and shell._game.sim.process_mode == Node.PROCESS_MODE_INHERIT)
	var esc := InputEventKey.new()
	esc.keycode = KEY_ESCAPE
	esc.pressed = true
	shell._unhandled_input(esc)
	await process_frame
	assert(shell._home_viewer == null and shell._panel.visible and paused)
	assert(shell._game.camera.position == camera_position)
	# Closing before the reply must also leave the game paused and usable.
	shell._game.sim.reply = {}
	shell._open_home_interior()
	shell._unhandled_input(esc)
	await create_timer(0.1, true).timeout
	assert(shell._home_viewer == null and shell._panel.visible and paused)
	shell._game.sim._buffer = (JSON.stringify({"type": "home_interior", "version": 1,
		"plan": {"error": "no_home"}}) + "\n").to_utf8_buffer()
	shell._game.sim._drain_lines()
	assert(shell._game.sim.home_plan == {"error": "no_home"}, "SimClient decodes the server reply")
	# Failed connection and the visible Back button also preserve pause state.
	shell._game.sim.connected = false
	shell._game.sim.reply = {}
	shell._open_home_interior()
	await process_frame
	assert(shell._home_viewer.plan.get("error") == "disconnected")
	shell._home_viewer._close.pressed.emit()
	await process_frame
	assert(shell._home_viewer == null and shell._panel.visible)
	shell._resume()
	assert(not paused and not shell._panel.visible)
	assert(shell._game.camera.position == camera_position)
	# The same viewer can render a real generator result at multiple sizes.
	var args := OS.get_cmdline_user_args()
	var at := args.find("--plan")
	if at >= 0:
		var plan: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[at + 1]))
		shell._game.sim.connected = true
		shell._game.sim.reply = plan
		if DisplayServer.get_name() == "headless":
			paused = true
		shell._pause_menu()
		shell._open_home_interior()
		for dimensions in [Vector2i(1280, 720), Vector2i(800, 600)]:
			root.size = dimensions
			for i in 4:
				await process_frame
			if DisplayServer.get_name() != "headless":
				await RenderingServer.frame_post_draw
				root.get_texture().get_image().save_png("/tmp/%s-%d.png" % [args[at + 1].get_file().get_basename(), dimensions.x])
			assert(shell._home_viewer._canvas.size.y > 100)
		shell._close_home_interior()
		shell._resume()
	shell.queue_free()
	await process_frame
	print("HOME_INTERIOR: selection guidance, disconnect, Esc, Back, resume, input and camera checks passed")
	quit(0)
