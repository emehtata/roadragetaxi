## Render crowns far from the initial map origin; polygon triangulation must stay local.
extends SceneTree
const MapLayer = preload('res://map_layer.gd')
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	for panel in 2:
		var offset := 0.0 if panel == 0 else 60000.0
		var map := MapLayer.new()
		map.position = Vector2(60 + panel * 640 - offset * 12, 70 - offset * 12)
		map.scale = Vector2(12, 12)
		root.add_child(map)
		var trees := []
		for row in 6:
			for col in 8:
				trees.append([offset + col * 6, -offset - row * 8, ['spruce', 'pine', 'birch'][col % 3], float(row * 8 + col) / 48.0])
		map.add_chunk({'chunk_id': str(panel), 'bounds': [offset - 5,-offset - 50,offset + 50,-offset + 5], 'trees':trees})
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	shot.save_png('/tmp/rrt-tree-render.png')
	# Every crown must leave coloured pixels, including those 60 km from the origin.
	var failures := 0
	for panel in 2:
		for row in 6:
			for col in 8:
				var pixel := shot.get_pixel(60 + panel * 640 + col * 72, 70 + row * 96)
				if pixel.g - pixel.b < 0.11:
					failures += 1
	print('TREE_RENDER failures=', failures)
	quit(1 if failures else 0)
