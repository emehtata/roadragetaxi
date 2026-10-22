## Regression: tiny Santa hats must triangulate even far from the map origin.
## godot --headless --path godot --script res://tests/pedestrian_render.gd
extends SceneTree

const Entities := preload("res://entity_layer.gd")
var entities: Node2D


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	assert(Geometry2D.triangulate_polygon(PackedVector2Array(Entities.SANTA_HAT)).size() == 3)
	entities = Entities.new()
	for distance in [0.0, 5000.0, 100000.0]:
		var canvas := Node2D.new()
		root.add_child(canvas)
		canvas.position = -Vector2(distance, distance)
		canvas.draw.connect(func():
			entities._canvas = canvas
			for i in 36:
				entities._pedestrian(Vector2(distance, distance), i * TAU / 36, {"costume": "santa"}, 0.0))
		canvas.queue_redraw()
	await process_frame
	await process_frame
	entities.free()
	# Golf balls follow their owner ids, even outside the visible pedestrian area.
	var golf := Entities.new()
	root.add_child(golf)
	golf.origin = Vector2(60000, 60000)
	golf.view_rect = Rect2(-20, -20, 40, 40)
	var visible := {"id": 1, "x": 60000.0, "y": 60000.0, "heading": 0.0, "activity": "golf",
		"golf": {"ball": [60004.0, 60001.0, 2.0], "pin": [60006.0, 60004.0], "club": "driver", "phase": "flight"}}
	var offscreen := {"id": 2, "x": 61000.0, "y": 61000.0, "heading": 0.0,
		"golf": {"ball": [60012.0, 60000.0, 0.0], "pin": [60015.0, 60000.0], "club": "putter", "phase": "roll"}}
	var later := visible.duplicate(true)
	later.golf.ball = [60006.0, 60003.0, 6.0]
	var player := {"x": 59000.0, "y": 59000.0, "heading": 0.0}
	golf._frame = {"a": {"pedestrians": [visible, offscreen], "player": player},
		"b": {"pedestrians": [offscreen, later], "player": player}, "t": 0.5}
	golf.queue_redraw()
	await process_frame
	await process_frame
	assert(golf._people_rows.size() == 1)
	assert(golf._golf_rows.size() == 2)
	assert(golf._golf_rows[0][0] == Vector2(5, -2))
	assert(golf._golf_rows[0][1] == 4.0)
	assert(golf._golf_rows[1][0] == Vector2(12, 0))
	golf.queue_free()
	print("Pedestrian render regression completed")
	quit()
