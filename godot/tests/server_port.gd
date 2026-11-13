## Run with isolated settings: XDG_DATA_HOME=$(mktemp -d) godot --headless --path godot --script res://tests/server_port.gd
## Startup picks a free server port and never stays on another process's server.
extends SceneTree

const Startup := preload("res://startup.gd")

var shell: Control
var failed := false

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, message: String) -> void:
	if not ok:
		printerr("FAIL: ", message)
		failed = true

func hold(first: int, last: int) -> Array:
	var held := []
	for port in range(first, last + 1):
		var server := TCPServer.new()
		server.listen(port, "127.0.0.1")  # already busy elsewhere: busy all the same
		held.append(server)
	return held

func release(held: Array) -> void:
	for server in held:
		server.stop()

func test_busy_default_picks_next() -> void:
	var held := hold(8765, 8765)
	check(Startup.find_free_port() == 8766, "8765 busy: 8766 chosen")
	check(Startup.server_port(PackedStringArray()) == 8766, "8765 busy: the server gets --port 8766")
	release(held)

func test_all_busy_returns_minus_one() -> void:
	var held := hold(8765, 8775)
	check(Startup.find_free_port() == -1, "8765-8775 busy: -1")
	shell._start("free_roam", true)
	var texts: Array = shell._body.get_children().filter(func(c): return c is Label).map(func(c): return c.text)
	check(shell._t("start_failed") in texts and "ports 8765–8775 busy" in texts, "all busy: start_failed shown, got %s" % [texts])
	check(shell._server_pid <= 0 and shell._game == null, "all busy: nothing launched")
	release(held)

func test_manual_port_not_probed() -> void:
	var held := hold(9001, 9001)
	check(Startup.server_port(PackedStringArray(["--port", "9001"])) == 9001, "manual --port 9001 kept although busy")
	release(held)

func test_exited_server_shows_start_failed() -> void:
	var stub := TCPServer.new()
	check(stub.listen(8799, "127.0.0.1") == OK, "stub server listens")
	var pid := OS.create_process("true", [])
	var game := Node.new()
	var sim := SimClient.new()
	sim.name = "SimClient"
	sim.port = 8799
	game.add_child(sim)
	shell.add_child(game)
	shell._game = game
	for i in 200:
		await process_frame
		if stub.is_connection_available():
			stub.take_connection()
		if sim.connected and not OS.is_process_running(pid):
			break
	check(sim.connected, "client connected to the stub")
	shell._server_pid = pid
	shell._loading = true
	shell._startup_path = ""
	shell._startup_stage = Label.new()
	shell._startup_detail = Label.new()
	shell._startup_elapsed = Label.new()
	shell._startup_bar = ProgressBar.new()
	shell._process(1.0)
	check(shell._startup_stage.text == shell._t("start_failed"), "exited server: start_failed shown")
	check(sim._peer.get_status() == StreamPeerTCP.STATUS_NONE, "exited server: client disconnected")
	check(shell._game == null, "exited server: game freed")
	stub.stop()

func run() -> void:
	shell = Startup.new()
	root.add_child(shell)
	await process_frame
	test_busy_default_picks_next()
	test_all_busy_returns_minus_one()
	test_manual_port_not_probed()
	await test_exited_server_shows_start_failed()
	print("server_port: ", "FAIL" if failed else "PASS")
	quit(1 if failed else 0)
