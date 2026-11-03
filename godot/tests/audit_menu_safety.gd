## Real menu callbacks preserve replacement slots and send pause/resume over TCP.
extends SceneTree

class Shell extends 'res://startup.gd':
	var chose_city := false
	func _ready() -> void:
		process_mode = Node.PROCESS_MODE_ALWAYS
		_build_shell()
	func _city_menu() -> void:
		chose_city = true

func _initialize() -> void:
	call_deferred("run")

func take_shot(name: String) -> void:
	if DisplayServer.get_name() == "headless":
		return
	await process_frame
	await RenderingServer.frame_post_draw
	assert(root.get_texture().get_image().save_png("/tmp/rrt-audit-" + name + ".png") == OK)

func run() -> void:
	var shell := Shell.new()
	root.add_child(shell)
	var directory := OS.get_cache_dir().path_join("rrt-audit-%d" % OS.get_process_id())
	DirAccess.make_dir_recursive_absolute(directory)
	var path := directory.path_join("audit-slot.json")
	var original := '{"city":"Oulu","saved_at":1}'
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(original)
	file.close()
	var slot := {"name":"audit-slot", "path":path, "city":"Oulu", "game_time":"2026-11-03T12:00"}
	shell._replace_slot_menu([slot])
	await take_shot("replace-slot")
	var replace: Button
	for child in shell._body.get_children():
		if child is Button and child.text == shell.slot_label(slot, shell._t("fare_in_progress")):
			replace = child
	assert(replace != null)
	replace.pressed.emit()
	assert(shell.chose_city and shell._new_save_slot and shell._save_slot == "audit-slot")
	assert(FileAccess.get_file_as_string(path) == original, "replacement selection must preserve old save")
	DirAccess.remove_absolute(path)
	DirAccess.remove_absolute(directory)

	var listener := TCPServer.new()
	assert(listener.listen(0, "127.0.0.1") == OK)
	var game := preload("res://main.tscn").instantiate()
	game.get_node("SimClient").port = listener.get_local_port()
	shell._game = game
	shell.add_child(game)
	var peer: StreamPeerTCP
	for i in 180:
		if listener.is_connection_available():
			peer = listener.take_connection()
		if peer != null and game.sim.connected:
			break
		await process_frame
	assert(peer != null and game.sim.connected)
	shell._settings.set_value("menu", "mode", "gig_driver")
	game.sim.send_command({"throttle":1.0})
	if DisplayServer.get_name() == "headless":
		paused = true  # dummy renderer cannot capture the menu thumbnail
		game.set_interior_paused(true)
	shell._pause_menu()
	assert(paused and game.sim._last_command.is_empty())
	assert(game.sim.process_mode == Node.PROCESS_MODE_ALWAYS)
	await take_shot("pause")
	shell._resume()
	assert(not paused and game.sim.process_mode == Node.PROCESS_MODE_INHERIT)
	await process_frame
	peer.poll()
	var result := peer.get_data(peer.get_available_bytes())
	assert(result[0] == OK)
	var pauses: Array = []
	for line in result[1].get_string_from_utf8().split("\n", false):
		var message = JSON.parse_string(line)
		if message is Dictionary and message.has("paused"):
			pauses.append(message.paused)
			assert(message.command.is_empty())
	assert(pauses == [true, false], "pause and resume reach the server with neutral input")
	game.sim.drop_connection()
	peer.disconnect_from_host()
	listener.stop()
	shell.queue_free()
	await process_frame
	print("AUDIT_MENU_SAFETY: replacement preserved; pause/resume sent with neutral input")
	quit()
