## Launches a real game with the saved settings and captures the loading view
## while the one-time intercity database is prepared.
## godot --path godot --script res://tests/intercity_loading_shot.gd
extends SceneTree


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	root.size = Vector2i(1280, 720)
	var startup: Control = load("res://startup.gd").new()
	root.add_child(startup)
	await process_frame
	startup._start("gig_driver", true)
	for shot in [45, 120]:
		await create_timer(shot - (45 if shot == 120 else 0)).timeout
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("res://../screenshots/intercity_loading_%ds.png" % shot)
	OS.kill(startup._server_pid)
	quit()
