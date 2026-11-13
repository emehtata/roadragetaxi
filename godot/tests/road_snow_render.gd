## Rendered pixel regression (needs a display, not --headless):
## godot --path godot --script res://tests/road_snow_render.gd --audio-driver Dummy --resolution 400x240
extends SceneTree

const MapLayer := preload("res://map_layer.gd")
var failures := 0
var map: Node2D

func _initialize() -> void:
	call_deferred("run")

func capture() -> Image:
	for i in 3:
		await process_frame
	await RenderingServer.frame_post_draw
	return root.get_texture().get_image()

func pixel(image: Image, at: Vector2i, expected: Color, label: String) -> void:
	var actual := image.get_pixelv(at)
	if absf(actual.r - expected.r) + absf(actual.g - expected.g) + absf(actual.b - expected.b) > 0.06:
		failures += 1
		printerr("FAIL ", label, " actual=", actual, " expected=", expected)

func run() -> void:
	map = MapLayer.new()
	map.position = Vector2(40, 120)
	map.scale = Vector2(10, 10)
	root.add_child(map)
	map.add_chunk({"chunk_id": "visual", "bounds": [-1, -10, 31, 10], "roads": [
		{"points": [[0, 0], [30, 0]], "half_width_m": 2.0, "drivable": true, "center": [255, 200, 0, 2]},
		{"points": [[15, -5], [15, 5]], "half_width_m": 1.0, "drivable": true, "layer": 1, "color": [60, 100, 60]},
		{"points": [[0, -8], [30, -8]], "half_width_m": 0.5, "drivable": false},
	]})
	var image: Image = await capture()
	pixel(image, Vector2i(90, 125), Color(0.33, 0.33, 0.35), "dry road")
	map.set_road_snow(3.0, [], true)
	image = await capture()
	pixel(image, Vector2i(90, 125), Color8(230, 236, 240), "snowy road")
	pixel(image, Vector2i(195, 80), Color8(230, 236, 240), "snowy bridge")
	pixel(image, Vector2i(90, 119), Color8(255, 200, 0), "markings above snow")
	pixel(image, Vector2i(90, 200), Color(0.55, 0.52, 0.45), "footway unchanged")
	map.set_road_snow(3.0, [[0, 0, 10, 0, 3.0]], true)
	image = await capture()
	pixel(image, Vector2i(90, 125), Color(0.33, 0.33, 0.35), "ploughed segment")
	pixel(image, Vector2i(90, 139), Color8(230, 236, 240), "beyond the blade (1.9 m off the lane) stays snowy")
	pixel(image, Vector2i(290, 125), Color8(230, 236, 240), "untouched segment")
	map.set_road_snow(4.5, [[0, 0, 10, 0, 3.0]], true)
	image = await capture()
	pixel(image, Vector2i(90, 125), Color(0.33, 0.33, 0.35).lerp(Color8(230, 236, 240), 0.5), "reaccumulation")
	map.set_road_snow(0.0, [], false)
	image = await capture()
	pixel(image, Vector2i(90, 125), Color(0.33, 0.33, 0.35), "melted road")
	test_plough_mask_is_feathered_corridor()
	print("SNOW_VISUAL failures=", failures)
	map.free()
	quit(1 if failures else 0)


## Criterion 5: the 3D mask is a feathered capsule round the lane, 1 m a texel.
func test_plough_mask_is_feathered_corridor() -> void:
	var chunk = map._chunks["visual"]
	var road := MeshInstance3D.new()
	road.material_override = ShaderMaterial.new()
	road.material_override.set_meta("snow_cells", true)
	chunk.meshes_3d.append(road)
	map.set_road_snow(3.0, [[0, 0.5, 30, 0.5, 3.0]], true)  # world (0, 0.5) -> (30, 0.5), on texel centres
	var mask: Image = road.material_override.get_shader_parameter("snow_cells").get_image()
	var low := Vector2i(floori(chunk._bounds_rect.position.x + chunk._origin.x), floori(chunk._origin.y - chunk._bounds_rect.end.y))
	var texel := func(x: float, y: float) -> float: return mask.get_pixel(int(x) - low.x, int(y) - low.y).r
	var centre: float = texel.call(15.5, 0.5)
	var off_3: float = texel.call(15.5, 3.5)
	var off_2: float = texel.call(15.5, 2.5)
	if not (centre == 0.0 and off_3 > 0.99 and off_2 > 0.05 and off_2 < 0.95):
		failures += 1
		printerr("FAIL plough mask centre=", centre, " 3 m=", off_3, " 2 m=", off_2)
	chunk.meshes_3d.erase(road)
	road.free()
