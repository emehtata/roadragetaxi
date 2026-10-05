## Visual check: buildings surround the view centre so facades in all four
## directions are visible. Red outlines are the unchanged ground footprints.
## godot-21: the camera also sweeps across the scene (pan_*.png) to show the
## facades changing continuously. RENDERER: 3d (default) or 2d (godot-20).
##   godot --path godot --script res://tests/building_scene.gd -- OUT_PREFIX [RENDERER]
extends SceneTree

const MapLayer := preload("res://map_layer.gd")
const MapChunk := preload("res://map_chunk.gd")
const MapMath := preload("res://map_math.gd")
const STYLE_WALL := [158, 105, 82]


func _box(x: float, y: float, w: float, h: float) -> Array:
	return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


func _initialize() -> void:
	MapChunk.build_async = false
	var args := OS.get_cmdline_user_args()
	var prefix: String = args[0] if not args.is_empty() else "user://buildings"
	MapChunk.buildings_3d = args.size() < 2 or args[1] != "2d"
	RenderingServer.set_default_clear_color(Color8(120, 128, 110))
	var buildings := [
		_box(0, 30, 16, 10),  # low
		_box(30, 30, 16, 12),  # tall
		[[60, 30], [84, 30], [84, 40], [70, 40], [70, 52], [60, 52]],  # L (server y is north-up)
		_box(95, 30, 18, 10),  # pitched
		_box(0, 70, 40, 14),  # commercial
		_box(55, 70, 20, 12),  # entrance on the south wall
		[[100, 70], [110, 60], [120, 70], [110, 80]],  # turned box: two walls
		[[0, 100], [14, 96], [22, 108], [12, 118], [2, 112]],  # irregular
	]
	var styles := [
		[[92, 57, 48], 0, 4.0, [], STYLE_WALL, 1, 1],
		[[83, 86, 87], 0, 60.0, [], STYLE_WALL, 20, 0],
		[[92, 57, 48], 0, 12.0, [], STYLE_WALL, 4, 0],
		[[120, 60, 50], 1, 8.0, [], STYLE_WALL, 2, 1],
		[[83, 86, 87], 0, 15.0, [], [190, 186, 176], 5, 2],
		[[92, 57, 48], 0, 9.0, [[65.0, 70.0]], STYLE_WALL, 3, 0],
		[[92, 57, 48], 0, 18.0, [], STYLE_WALL, 6, 0],
		[[92, 57, 48], 0, 10.0, [], STYLE_WALL, 3, 0],
	]
	var chunk := {"chunk_id": "0_0", "bounds": [-50, -50, 200, 150], "buildings": buildings, "building_styles": styles,
		"roads": [{"points": [[-40, 22], [190, 22]], "half_width_m": 4.0, "kind": "primary", "drivable": true, "layer": 0},
			{"points": [[-40, 62], [190, 62]], "half_width_m": 3.0, "kind": "residential", "drivable": true, "layer": 0},
			{"points": [[50, -40], [50, 140]], "half_width_m": 3.0, "kind": "residential", "drivable": true, "layer": 0}],
		"canopies": [_box(130, 30, 20, 14)], "canopy_heights": [5.5]}
	var map := MapLayer.new()
	root.add_child(map)
	await process_frame  # the map's groups exist after its _ready
	map.add_chunk(JSON.parse_string(JSON.stringify(chunk)))
	for footprint in buildings + chunk["canopies"]:
		var outline := Line2D.new()
		outline.width = 0.25
		outline.default_color = Color(1, 0, 0, 0.9)
		outline.closed = true
		outline.z_index = 100
		for p in footprint:
			outline.add_point(MapMath.point(Vector2.ZERO, p[0], p[1]))
		root.add_child(outline)
	var camera := Camera2D.new()
	camera.position = MapMath.point(Vector2.ZERO, 75, 55)
	root.add_child(camera)
	camera.make_current()
	map.set_building_view(camera.position)
	for zoom: float in [4.0, 7.0, 12.0]:
		camera.zoom = Vector2(zoom, zoom)
		map.set_px_per_m(zoom)
		for i in 4:
			await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("%s_zoom%d.png" % [prefix, zoom])
	camera.zoom = Vector2(7.0, 7.0)
	map.set_px_per_m(7.0)
	for step in 5:  # a pan from left to right across the scene
		camera.position = MapMath.point(Vector2.ZERO, 20 + step * 25, 55)
		map.set_building_view(camera.position)
		for i in 4:
			await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("%s_pan%d.png" % [prefix, step])
	quit()
