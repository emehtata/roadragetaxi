## Render canopy shadows/posts near and 60 km from the map origin.
extends SceneTree
const MapLayer = preload('res://map_layer.gd')
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	for panel in 2:
		var offset := 0.0 if panel == 0 else 60000.0
		var map := MapLayer.new()
		map.position = Vector2(70 + panel * 640 - offset * 12, 70 - offset * 12)
		map.scale = Vector2(12, 12)
		root.add_child(map)
		var canopies := []
		for row in 5:
			for col in 6:
				var x := offset + col * 8
				var y := -offset - row * 10
				canopies.append([[x,y],[x+5,y+1],[x+4,y-5],[x-1,y-4]])
		map.add_chunk({'chunk_id': str(panel), 'bounds':[offset-5,-offset-50,offset+50,-offset+5], 'canopies':canopies})
		# Inspect supports without the overlaid roof hiding the shadow.
		for child in map._chunks[str(panel)].get_children():
			if child is CanvasItem and child.z_index == 13:
				child.hide()
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	shot.save_png('/tmp/rrt-canopy-supports.png')
	var failures := 0
	for panel in 2:
		for row in 5:
			for col in 6:
				var pixel := shot.get_pixel(94 + panel * 640 + col * 96, 94 + row * 120)
				if pixel.r > 0.25:
					failures += 1
	print('CANOPY_SUPPORTS failures=', failures)
	quit(1 if failures else 0)
