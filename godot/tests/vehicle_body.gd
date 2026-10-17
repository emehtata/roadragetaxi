## Render the vehicle-body path at distant coordinates without polygon triangulation.
extends SceneTree

const Entities := preload("res://entity_layer.gd")


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var failures := 0
	for offset in [Vector2.ZERO, Vector2(5000, -5000), Vector2(100000, 100000)]:
		var node := Node2D.new()
		node.position = Vector2(100, 100) - offset
		var points := PackedVector2Array([offset + Vector2(-20, -10), offset + Vector2(20, -10),
			offset + Vector2(20, 10), offset + Vector2(-20, 10)])
		node.draw.connect(func(): Entities._paint(node, [["poly", points, Color.RED, null, -1.0]]))
		root.add_child(node)
		await process_frame
		await RenderingServer.frame_post_draw
		var pixel := root.get_texture().get_image().get_pixel(100, 100)
		if pixel.r < 0.9 or pixel.g > 0.1:
			failures += 1
			push_error("Vehicle body missing at %s: %s" % [offset, pixel])
		node.queue_free()
		await process_frame
	print("vehicle body: 3 rendered positions, %d failed" % failures)
	quit(int(failures > 0))
