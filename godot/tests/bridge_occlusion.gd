## Rendered regression (needs a display, not --headless):
## godot --path godot --rendering-method gl_compatibility --script res://tests/bridge_occlusion.gd
extends SceneTree

const MapLayer := preload("res://map_layer.gd")
const MapChunk := preload("res://map_chunk.gd")


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var camera := Camera2D.new()
	camera.position = Vector2(40, -40)
	camera.zoom = Vector2(6, 6)
	root.add_child(camera)
	MapChunk.build_async = false
	var failures := 0
	for volumes in [false, true]:
		MapChunk.buildings_3d = volumes
		var map := MapLayer.new()
		root.add_child(map)
		map.add_chunk({"chunk_id": "building", "buildings": [[[30, 25], [50, 25], [50, 55], [30, 55]]],
			"building_styles": [[[200, 40, 40], 0, 6.0, [], [150, 60, 50], 1, 0]]})
		map.add_chunk({"chunk_id": "bridge", "roads": [
			{"points": [[0, 40], [80, 40]], "layer": 1, "half_width_m": 4, "drivable": true, "color": [80, 80, 80]}]})
		for frame in 4:
			await process_frame
			await RenderingServer.frame_post_draw
		var image := root.get_texture().get_image()
		var transform := map.get_global_transform_with_canvas()
		var centre: Vector2 = transform * Vector2(40, -40)
		var roof: Vector2 = transform * Vector2(40, -30)
		var deck_color := image.get_pixelv(Vector2i(centre))
		var roof_color := image.get_pixelv(Vector2i(roof))
		var ok := absf(deck_color.r - deck_color.g) < 0.03 and absf(deck_color.r - 80.0 / 255.0) < 0.05
		ok = ok and roof_color.r > roof_color.g + 0.1
		image.save_png("/tmp/rrt-bridge-buildings-%s.png" % ("3d" if volumes else "2d"))
		if not ok:
			failures += 1
			printerr("FAIL bridge covers roof (%s): deck=%s roof=%s" % [volumes, deck_color, roof_color])
		map.free()
	print("Rendered bridge/building checks: 2, failures: ", failures)
	quit(1 if failures else 0)
