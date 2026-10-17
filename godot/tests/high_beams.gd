## Rendered regression: godot --path godot --rendering-method gl_compatibility --script res://tests/high_beams.gd
extends SceneTree

const Entities := preload("res://entity_layer.gd")
const Night := preload("res://night_layer.gd")


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var camera := Camera2D.new()
	camera.position = Vector2(75, 0)
	camera.zoom = Vector2(5, 5)
	root.add_child(camera)
	var road := Node2D.new()
	road.draw.connect(func():
		road.draw_rect(Rect2(-30, -12, 220, 24), Color(0.35, 0.35, 0.35))
		road.draw_line(Vector2(-30, -1.75), Vector2(190, -1.75), Color.WHITE, 0.12))
	root.add_child(road)
	var darkness := CanvasModulate.new()
	darkness.color = Color(0.12, 0.12, 0.12)
	root.add_child(darkness)
	var night := Night.new()
	night.ambient = darkness.color
	root.add_child(night)
	var failures := 0
	var dipped: Array[float] = []
	for length in [15.0, Entities.HIGH_BEAM_M]:
		night.show_lights(1.0, Rect2(-30, -30, 220, 60), Entities.beam_polygons(Vector2.ZERO, 0.0, 1.8, length))
		for frame in 3:
			await process_frame
			await RenderingServer.frame_post_draw
		var shot := root.get_texture().get_image()
		var transform := road.get_global_transform_with_canvas()
		var index := 0
		for point in [Vector2(30, -3.5), Vector2(90, 0)]:
			var brightness := shot.get_pixelv(Vector2i(transform * point)).get_luminance()
			if length == 15.0:
				dipped.append(brightness)
			elif brightness < dipped[index] + 0.04:
				failures += 1
				printerr("FAIL high beam at %s: low=%s high=%s" % [point, dipped[index], brightness])
			index += 1
		shot.save_png("/tmp/rrt-headlights-%sm.png" % length)
	print("Rendered high-beam checks: 2, failures: ", failures)
	quit(1 if failures else 0)
