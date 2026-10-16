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
	print("Pedestrian render regression completed")
	quit()
