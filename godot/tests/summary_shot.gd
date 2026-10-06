## godot-final-02 visual check: the career city summary through the real
## Main scene (both variants), without a server.
##   godot --path godot --script res://tests/summary_shot.gd -- OUT_PREFIX
extends SceneTree


func _initialize() -> void:
	var prefix: String = OS.get_cmdline_user_args()[0]
	for variant in [["next", ["Oulu", 10500, 12, "Tampere", 21000]], ["done", ["Helsinki", 10200, 9, null, 98765]]]:
		var main: Node = load("res://main.tscn").instantiate()
		root.add_child(main)
		await process_frame
		main.show_summary({"should_stop": true, "city_summary": variant[1]})
		for i in 3:
			await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("%s_%s.png" % [prefix, variant[0]])
		main.free()
	quit()
