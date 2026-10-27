## rrt-018-shadows visual check: the building_scene.gd buildings under fixed
## suns and skies, one screenshot each. Fixed camera, fixed buildings; the
## sun comes from Daylight like in the game (set_sun), so what this shows is
## the real renderer's shadows, not a mock-up.
##   godot --path godot --script res://tests/shadow_scene.gd -- OUT_PREFIX
## Expected (see docs/building-shadows.md):
##   morning   shadows point west (away from the east sun), long
##   noon      shorter, pointing north
##   evening   rotated: pointing east
##   winter    low noon sun: longer than noon, faint
##   partly    noon with 60 % cloud: the same shadows, paler
##   overcast  none
##   night     none
extends SceneTree

const MapLayer := preload("res://map_layer.gd")
const MapChunk := preload("res://map_chunk.gd")
const MapMath := preload("res://map_math.gd")
const STYLE_WALL := [158, 105, 82]
const CASES := [  # name, altitude, azimuth (from grid north), cloud cover
	["morning", 20.0, 100.0, 0.0],
	["noon", 50.0, 180.0, 0.0],
	["evening", 15.0, 280.0, 0.0],
	["winter", 6.0, 180.0, 0.0],
	["partly", 50.0, 180.0, 0.6],
	["overcast", 50.0, 180.0, 1.0],
	["night", -10.0, 0.0, 0.0],
	["full_moon", 35.0, 120.0, -1.0],
]


func _box(x: float, y: float, w: float, h: float) -> Array:
	return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


func _initialize() -> void:
	MapChunk.build_async = false
	MapChunk.buildings_3d = true
	var args := OS.get_cmdline_user_args()
	var prefix: String = args[0] if not args.is_empty() else "user://shadows"
	RenderingServer.set_default_clear_color(Color8(120, 128, 110))
	var buildings := [
		_box(0, 30, 16, 10), _box(30, 30, 16, 12),
		[[60, 30], [84, 30], [84, 40], [70, 40], [70, 52], [60, 52]],
		_box(95, 30, 18, 10), _box(0, 70, 40, 14), _box(55, 70, 20, 12),
		[[100, 70], [110, 60], [120, 70], [110, 80]],
	]
	var styles := [
		[[92, 57, 48], 0, 4.0, [], STYLE_WALL, 1, 1],
		[[83, 86, 87], 0, 30.0, [], STYLE_WALL, 10, 0],
		[[92, 57, 48], 0, 12.0, [], STYLE_WALL, 4, 0],
		[[120, 60, 50], 1, 8.0, [], STYLE_WALL, 2, 1],
		[[83, 86, 87], 0, 15.0, [], [190, 186, 176], 5, 2],
		[[92, 57, 48], 0, 9.0, [], STYLE_WALL, 3, 0],
		[[92, 57, 48], 0, 18.0, [], STYLE_WALL, 6, 0],
	]
	var chunk := {"chunk_id": "0_0", "bounds": [-50, -50, 200, 150], "buildings": buildings, "building_styles": styles,
		"roads": [{"points": [[-40, 22], [190, 22]], "half_width_m": 4.0, "drivable": true, "layer": 0},
			{"points": [[-40, 62], [190, 62]], "half_width_m": 3.0, "drivable": true, "layer": 0},
			{"points": [[50, -40], [50, 140]], "half_width_m": 3.0, "drivable": true, "layer": 0}]}
	var map := MapLayer.new()
	root.add_child(map)
	await process_frame
	map.add_chunk(JSON.parse_string(JSON.stringify(chunk)))
	var camera := Camera2D.new()
	camera.position = MapMath.point(Vector2.ZERO, 60, 55)
	camera.zoom = Vector2(5.0, 5.0)
	root.add_child(camera)
	camera.make_current()
	map.set_building_view(camera.position)
	map.set_px_per_m(5.0)
	for case in CASES:
		if case[3] < 0.0:
			map.set_celestial_light(case[1], case[2], Daylight.MOON_MAX_LIGHT)
		else:
			map.set_sun(case[1], case[2], case[3])
		for i in 4:
			await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("%s_%s.png" % [prefix, case[0]])
	quit()
