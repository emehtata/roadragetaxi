## rrt-018-shadows cost: one process, a synthetic city of BUILDINGS houses
## and blocks, the building layer's frame time with the sun's shadows on and
## off in alternating blocks of frames (so drift hits both alike).
##   godot --path godot --resolution 1920x1080 --script res://tests/shadow_bench.gd -- [BLOCKS] [FRAMES] [ATLAS]
## ATLAS: try another directional shadow map size (project: 2048).
## Prints SHADOW_BENCH {"off_ms": [...], "on_ms": [...]} per block.
extends SceneTree

const MapLayer := preload("res://map_layer.gd")
const MapChunk := preload("res://map_chunk.gd")
const MapMath := preload("res://map_math.gd")
const SIDE := 55  # SIDE x SIDE buildings ~ the 3 000 of a central Oulu view


func _initialize() -> void:
	MapChunk.build_async = false
	MapChunk.buildings_3d = true
	var args := OS.get_cmdline_user_args()
	var blocks := int(args[0]) if args.size() > 0 else 6
	var frames := int(args[1]) if args.size() > 1 else 90
	if args.size() > 2:
		RenderingServer.directional_shadow_atlas_set_size(int(args[2]), true)
	var buildings := []
	var styles := []
	for i in SIDE * SIDE:
		var x := (i % SIDE) * 14.0
		var y := (i / SIDE) * 14.0
		buildings.append([[x, y], [x + 10, y], [x + 10, y + 9], [x, y + 9]])
		styles.append([[92, 57, 48], 0, 6.0 + (i * 7) % 25, [], [158, 105, 82], 2 + (i % 6), i % 3])
	var map := MapLayer.new()
	root.add_child(map)
	await process_frame
	map.add_chunk({"chunk_id": "0_0", "bounds": [0, 0, SIDE * 14, SIDE * 14], "buildings": buildings, "building_styles": styles})
	var camera := Camera2D.new()
	camera.position = MapMath.point(Vector2.ZERO, SIDE * 7.0, SIDE * 7.0)
	camera.zoom = Vector2(5.0, 5.0)
	root.add_child(camera)
	camera.make_current()
	map.set_building_view(camera.position)
	map.set_px_per_m(5.0)
	var result := {"off_ms": [], "on_ms": []}
	for block in blocks * 2:
		var on := block % 2 == 1
		map.set_sun(40.0, 180.0 + block, 0.0 if on else 1.0)
		for i in 10:  # settle
			await process_frame
		var started := Time.get_ticks_usec()
		for i in frames:
			camera.position.x += 0.5 if i % 2 == 0 else -0.5  # a moving view, as when driving
			await RenderingServer.frame_post_draw
		result["on_ms" if on else "off_ms"].append(snappedf((Time.get_ticks_usec() - started) / 1000.0 / frames, 0.01))
	print("SHADOW_BENCH ", JSON.stringify(result))
	quit()
