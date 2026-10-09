## The speed-limit sign for 1-3 digit limits, drawn by the real
## instruments.gd, measured: where the digits' ink sits against the
## sign's centre (prints LIMIT_INK n dx dy, in pixels; exits 1 if any is
## more than half a pixel off - the measurement's own resolution).
##   godot --path godot --script res://tests/limit_sign_shot.gd
extends SceneTree


func _initialize() -> void:
	var gauge: Control = preload("res://instruments.gd").new()
	gauge.size = Vector2(400, 200)
	root.add_child(gauge)
	var worst := 0.0
	for limit in [1, 5, 30, 50, 80, 100, 120]:
		gauge.show_state({"player": {}, "road": {"speed_limit_kmh": limit}})
		gauge.queue_redraw()
		for i in 2:
			await process_frame
		await RenderingServer.frame_post_draw
		var image := root.get_texture().get_image()
		var centre := Vector2(gauge.size.x - 48.0, 76.0)
		var lo := Vector2(INF, INF)
		var hi := -Vector2(INF, INF)
		for y in range(int(centre.y) - 20, int(centre.y) + 20):
			for x in range(int(centre.x) - 22, int(centre.x) + 22):
				if Vector2(x + 0.5, y + 0.5).distance_to(centre) < 22.0 and image.get_pixel(x, y).get_luminance() < 0.3:  # inside the yellow disc: the dark digits
					lo = Vector2(minf(lo.x, x), minf(lo.y, y))
					hi = Vector2(maxf(hi.x, x + 1), maxf(hi.y, y + 1))
		var ink := (lo + hi) / 2.0 - centre
		print("LIMIT_INK %d %.1f %.1f" % [limit, ink.x, ink.y])
		worst = maxf(worst, maxf(absf(ink.x), absf(ink.y)))
	quit(1 if worst > 0.5 else 0)
