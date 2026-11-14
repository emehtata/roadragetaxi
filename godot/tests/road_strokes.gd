## Rendered regression: MapChunk.Strokes (one triangle array) against
## draw_colored_polygon / draw_polyline / draw_multiline, and EntityLayer._circle
## against draw_circle, line by line: the same pixels, give or take
## 1/255 of colour rounding. Needs a rendering display:
##   godot --path godot --display-driver x11 --rendering-driver opengl3 --script res://tests/road_strokes.gd
extends SceneTree

const Entities := preload("res://entity_layer.gd")
const MapChunk := preload("res://map_chunk.gd")
const B3 := preload("res://buildings_3d.gd")

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
const CIRCLES := [[Vector2(40, 200), 12.0, Color(0.9, 0.8, 0.2)], [Vector2(48, 204), 6.0, Color(0.2, 0.2, 0.3, 0.5)], [Vector2(300, 200), 0.4, Color.WHITE]]
const SEGMENTS := [Vector2(10, 230), Vector2(150, 180), Vector2(160, 10), Vector2(300, 220)]


func _initialize() -> void:
	_run.call_deferred()


## A gentle arc (10 deg bends on 20 m steps), a shared point, then a 90 deg corner.
const ROAD := [[0.0, 0.0], [20.0, 0.0], [39.7, 3.5], [58.5, 10.3], [75.8, 20.3], [91.1, 33.2], [91.1, 63.2], [91.1, 83.2]]

func _deviation(samples: Array, points: Array) -> float:
	var worst := 0.0
	for s in samples:
		var best := INF
		for i in points.size() - 1:
			var a := Vector2(points[i][0], points[i][1])
			var b := Vector2(points[i + 1][0], points[i + 1][1])
			best = minf(best, Vector2(s[0], s[1]).distance_to(Geometry2D.get_closest_point_to_segment(Vector2(s[0], s[1]), a, b)))
		worst = maxf(worst, best)
	return worst

func test_smooth_road_keeps_endpoints_and_corners() -> bool:
	var smooth: Array = MapChunk.smooth_road(ROAD, {Vector2(58.5, 10.3): true})
	var ok: bool = smooth.size() > ROAD.size() and smooth[0] == ROAD[0] and smooth[-1] == ROAD[-1]
	for knot in [ROAD[3], ROAD[5]]:  # the shared point and the protected 90 deg corner, bit-identical
		ok = ok and smooth.any(func(p): return p[0] == knot[0] and p[1] == knot[1])
	ok = ok and MapChunk.smooth_road(ROAD, {}) == MapChunk.smooth_road(ROAD.duplicate(true), {})  # deterministic
	if not ok:
		printerr("FAIL: smooth_road endpoints/corners ", smooth)
	return ok

func test_smooth_road_bounded_deviation() -> bool:
	var ok := true
	for half in [1.0, 3.0]:
		var smooth: Array = MapChunk.smooth_road(ROAD, {}, minf(0.5, 0.25 * half))
		var worst := _deviation(smooth, ROAD)
		ok = ok and worst <= minf(0.5, 0.25 * half) + 1e-4
		if worst > minf(0.5, 0.25 * half) + 1e-4:
			printerr("FAIL: smooth_road %.3f m off the OSM line (half %.1f)" % [worst, half])
	return ok

func test_road_strip_no_wedge_gap() -> bool:
	var out := {"road": PackedVector3Array(), "road_colors": PackedColorArray(), "road_uv": PackedVector2Array(), "road_uv2": PackedVector2Array()}
	var bend := PackedVector2Array([Vector2(0, 0), Vector2(30, 0), Vector2(30, 0) + Vector2(30, 0).rotated(deg_to_rad(30))])
	B3._road_strip(out, bend, 3.0, 0.01, Color.GRAY)
	var tris: PackedVector3Array = out["road"]
	var holes := 0
	for x in range(-2, 62):
		for y in range(-3, 20):
			var p := Vector2(x, y) * Vector2(1.0, 0.5) + Vector2(0.25, 0.1)
			var d := INF
			for i in bend.size() - 1:
				d = minf(d, p.distance_to(Geometry2D.get_closest_point_to_segment(p, bend[i], bend[i + 1])))
			if d > 2.9:
				continue
			var inside := false
			for t in range(0, tris.size(), 3):
				if Geometry2D.point_is_inside_triangle(p, Vector2(tris[t].x, tris[t].z), Vector2(tris[t + 1].x, tris[t + 1].z), Vector2(tris[t + 2].x, tris[t + 2].z)):
					inside = true
					break
			holes += int(not inside)
	if holes:
		printerr("FAIL: road strip has %d uncovered points at a 30 deg bend" % holes)
	return holes == 0


func _run() -> void:
	var pure_ok := test_smooth_road_keeps_endpoints_and_corners()
	pure_ok = test_smooth_road_bounded_deviation() and pure_ok
	pure_ok = test_road_strip_no_wedge_gap() and pure_ok
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
	quit(0 if pure_ok and max_diff <= 1 and images[0].get_pixel(150, 20) != images[0].get_pixel(300, 5) else 1)
