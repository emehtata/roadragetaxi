## Rendered regression: compare batched wet strokes with the original polylines.
## Run with a rendering display: godot --path godot --script res://tests/wet_road_batching.gd
extends SceneTree


func _initialize():
	call_deferred("run")


func run():
	var images := []
	for batched in [false, true]:
		var view := SubViewport.new()
		view.size = Vector2i(240, 180)
		view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		root.add_child(view)
		var bg := ColorRect.new()
		bg.size = Vector2(240, 180)
		bg.color = Color(0.5, 0.4, 0.3)
		view.add_child(bg)
		var chunk = load("res://map_chunk.gd").new()
		chunk._bounds = PackedVector2Array([Vector2(10, 10), Vector2(220, 10), Vector2(220, 160), Vector2(10, 160)])
		chunk._data = {"roads": [
			{"points": [[-20,-30],[250,-30]], "drivable": true, "half_width_m": 5},
			{"points": [[70,-10],[70,-150]], "drivable": true, "half_width_m": 5},
			{"points": [[20,-80],[180,-80]], "drivable": true, "half_width_m": 3},
			{"points": [[30,-120],[120,-60],[210,-140]], "drivable": true, "half_width_m": 4},
			{"points": [[20,-100],[210,-100]], "drivable": true, "layer": 1, "half_width_m": 5},
			{"points": [[15,-50],[210,-50]], "drivable": false, "half_width_m": 5}]}
		var strokes := Node2D.new()
		strokes.modulate = Color(0.03, 0.04, 0.06, 0.35)
		view.add_child(strokes)
		if batched:
			strokes.draw.connect(func(): chunk._draw_wet(strokes))
		else:
			strokes.draw.connect(func():
				for road in chunk._data.roads:
					if road.drivable and chunk.road_z(int(road.get("layer", 0))) == 1:
						for part in Geometry2D.intersect_polyline_with_polygon(chunk._points(road.points), chunk._bounds):
							if part.size() >= 2:
								strokes.draw_polyline(part, Color.WHITE, road.half_width_m * 2))
		await RenderingServer.frame_post_draw
		await RenderingServer.frame_post_draw
		images.append(view.get_texture().get_image())
		for node in [chunk._wet_darken, chunk._wet_sheen, chunk._puddles]:
			node.free()
		chunk.free()
		view.queue_free()
	await process_frame
	var a: PackedByteArray = images[0].get_data()
	var b: PackedByteArray = images[1].get_data()
	assert(a.size() == 240 * 180 * 4 and b.size() == a.size())
	assert(images[0].get_pixel(30, 30) != images[0].get_pixel(1, 1))
	var max_diff := 0
	var changed := 0
	for i in a.size():
		max_diff = maxi(max_diff, absi(int(a[i]) - int(b[i])))
		if a[i] != b[i]: changed += 1
	print("PIXELS ", JSON.stringify({"max_channel_difference":max_diff,"changed_channels":changed,"channels":a.size()}))
	quit(0 if max_diff <= 1 else 1)
