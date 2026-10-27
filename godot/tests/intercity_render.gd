## Visual regression for the opt-in prerequisite and existing navigation phone.
## godot --path godot --script res://tests/intercity_render.gd
extends SceneTree


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	root.size = Vector2i(1280, 720)
	var startup: Control = load("res://startup.gd").new()
	root.add_child(startup)
	await process_frame
	startup._language = "en"
	startup._settings_menu()
	for i in 6:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("/tmp/rrt-intercity-settings.png")
	startup.free()
	var phone := Phone.new()
	root.add_child(phone)
	phone.set_connected(true)
	phone.open()
	phone.show_phone({"busy": true, "items": []})
	phone.show_navigation({"instruction": {"maneuver": "straight", "distance_m": 4800.0, "total_m": 671400.0}}, "Aino → Helsinki")
	for i in 6:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("/tmp/rrt-intercity-navigation.png")
	phone.free()
	quit()
