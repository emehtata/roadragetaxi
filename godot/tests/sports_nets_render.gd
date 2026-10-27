## Render rotated soccer and hockey goal nets near and far from the map origin.
extends SceneTree
const MapLayer = preload('res://map_layer.gd')
func _initialize() -> void:
	call_deferred('run')
func run() -> void:
	for panel in 2:
		var offset := 0.0 if panel == 0 else 60000.0
		var map := MapLayer.new()
		map.position = Vector2(320 + panel * 640 - offset * 4, 360 - offset * 4)
		map.scale = Vector2(4, 4)
		root.add_child(map)
		var pitches := []
		var rinks := []
		for row in 3:
			var y := -offset + (row - 1) * 52
			pitches.append([offset - 30, y, row * 0.25, 52.5, 34.0])
			rinks.append([offset + 35, y, row * 0.25, 30.0, 15.0])
		map.add_chunk({'chunk_id':str(panel),'bounds':[offset-80,-offset-90,offset+80,-offset+90],
			'soccer_pitches':pitches})
		map.add_chunk({'chunk_id':str(panel) + 'ice','bounds':[offset-80,-offset-90,offset+80,-offset+90], 'rinks':rinks})
		map._chunks[str(panel) + 'ice']._season = [1.0, 0.0, 0.0, 0.0]
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	shot.save_png('/tmp/rrt-sports-nets.png')
	var failures := 0
	for panel in 2:
		for x in [91, 309]:
			if shot.get_pixel(x + panel * 640, 568).r < 0.6:
				failures += 1
	print('SPORTS_NETS failures=', failures)
	quit(1 if failures else 0)
