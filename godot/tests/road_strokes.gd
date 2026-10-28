## Rendered regression: MapChunk.Strokes (one triangle array) against
## draw_colored_polygon / draw_polyline / draw_multiline, line by line: the same pixels, give or take
## 1/255 of colour rounding. Needs a rendering display:
##   godot --path godot --display-driver x11 --rendering-driver opengl3 --script res://tests/road_strokes.gd
extends SceneTree

const LINES := [  # points, colour, width: bends, a sharp turn (clamped miter), a repeated point, a loop, translucent overlaps
	[[Vector2(10, 20), Vector2(150, 20), Vector2(300, 60)], Color(0.33, 0.33, 0.35), 9.0],
	[[Vector2(20, 200), Vector2(120, 80), Vector2(140, 210), Vector2(280, 150)], Color(0.55, 0.52, 0.45), 6.0],
	[[Vector2(200, 230), Vector2(240, 100), Vector2(250, 235)], Color(0.8, 0.3, 0.2), 12.0],
	[[Vector2(30, 120), Vector2(80, 120), Vector2(80, 120), Vector2(110, 160)], Color(0.2, 0.6, 0.3), 5.0],
	[[Vector2(170, 120), Vector2(220, 120), Vector2(220, 170), Vector2(170, 170), Vector2(170, 120)], Color(0.1, 0.3, 0.7), 4.0],
	[[Vector2(0, 90), Vector2(320, 140)], Color(1, 1, 1, 0.4), 14.0],
	[[Vector2(60, 0), Vector2(90, 240), Vector2(95, 100)], Color(1, 1, 1, 0.4), 7.0],
]
const POLYGONS := [  # draw_colored_polygon: a concave one and a translucent overlap
	[[Vector2(200, 20), Vector2(300, 30), Vector2(260, 70), Vector2(300, 110), Vector2(210, 100)], Color(0.28, 0.29, 0.29)],
	[[Vector2(230, 50), Vector2(290, 60), Vector2(250, 130)], Color(0.6, 0.62, 0.6, 0.5)],
	[[Vector2(-9, -2), Vector2(-1, -10), Vector2(8, -7), Vector2(10, 3), Vector2(1, 9), Vector2(-7, 6)], Color(0.1, 0.4, 0.15), Vector2(40, 60)],  # a tree crown, moved after triangulating
]
const SEGMENTS := [Vector2(10, 230), Vector2(150, 180), Vector2(160, 10), Vector2(300, 220)]


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var images := []
	for batched in [false, true]:
		var view := SubViewport.new()
		view.size = Vector2i(320, 240)
		view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		root.add_child(view)
		var node := Node2D.new()
		view.add_child(node)
		node.draw.connect(func():
			if not batched:
				for line in LINES:
					node.draw_polyline(PackedVector2Array(line[0]), line[1], line[2])
				node.draw_multiline(PackedVector2Array(SEGMENTS), Color(0.9, 0.9, 0.95, 0.7), 5.0)
				return
			var strokes = preload("res://map_chunk.gd").Strokes.new()
			for line in LINES:
				strokes.polyline(PackedVector2Array(line[0]), line[1], line[2])
			strokes.multiline(PackedVector2Array(SEGMENTS), Color(0.9, 0.9, 0.95, 0.7), 5.0)
			strokes.draw(node))
		await RenderingServer.frame_post_draw
		await RenderingServer.frame_post_draw
		images.append(view.get_texture().get_image())
		view.queue_free()
	var a: PackedByteArray = images[0].get_data()
	var b: PackedByteArray = images[1].get_data()
	var changed := 0
	var max_diff := 0
	for i in a.size():
		max_diff = maxi(max_diff, absi(int(a[i]) - int(b[i])))
		changed += int(a[i] != b[i])
	print("PIXELS ", JSON.stringify({"changed_channels": changed, "max_channel_difference": max_diff, "channels": a.size()}))
	quit(0 if max_diff <= 1 and images[0].get_pixel(150, 20) != images[0].get_pixel(300, 5) else 1)
