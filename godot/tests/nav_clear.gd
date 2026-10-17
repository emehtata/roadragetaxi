## Rendered regression: godot --path godot --rendering-method gl_compatibility --script res://tests/nav_clear.gd
extends SceneTree

const Overlay := preload("res://nav_overlay.gd")


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var failures := 0
	for compass in [false, true]:
		var overlay := Overlay.new()
		overlay.size = root.size
		overlay.show_compass = compass
		root.add_child(overlay)
		overlay.update_view({"x": 1000.0, "y": 0.0, "is_pickup": false}, Vector2(2000, 360), Vector2.ZERO, 0.0)
		for frame in 3:
			await process_frame
			await RenderingServer.frame_post_draw
		var at := Vector2i(Overlay.edge_point(0.0, root.size))
		var before := root.get_texture().get_image().get_pixelv(at)
		overlay.update_view({}, Vector2.ZERO, Vector2.ZERO, 0.0)
		for frame in 3:
			await process_frame
			await RenderingServer.frame_post_draw
		var shot := root.get_texture().get_image()
		var after := shot.get_pixelv(at)
		if Vector3(before.r, before.g, before.b).distance_to(Vector3(after.r, after.g, after.b)) < 0.15:
			failures += 1
			printerr("FAIL cleared destination arrow, compass=%s before=%s after=%s" % [compass, before, after])
		shot.save_png("/tmp/rrt-nav-cleared-%s.png" % compass)
		overlay.free()
	print("Rendered navigation clearing checks: 2, failures: ", failures)
	quit(1 if failures else 0)
