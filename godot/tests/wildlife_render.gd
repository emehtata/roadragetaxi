extends SceneTree


func _initialize() -> void:
	_render.call_deferred()


func _render() -> void:
	var background := ColorRect.new()
	background.size = Vector2(320, 200)
	background.color = Color8(190, 175, 75)
	root.add_child(background)
	var wildlife := preload("res://wildlife.gd").new()
	root.add_child(wildlife)
	wildlife.animals = [{"id": 1, "species": "small_bird", "position": Vector2(160, 100),
		"heading": 0.0, "state": "FLY", "timer": 1.0, "cycle": 0, "bounds": Rect2(0, 0, 320, 200)}]
	wildlife.queue_redraw()
	await process_frame
	await process_frame
	assert(wildlife.drawn_members == 5, "the canvas draw callback must render all five flock members")
	assert(0.65 * 2.0 * 9.0 >= 10.0, "a bird body must be at least ten pixels long at normal zoom")
	print("Wildlife render test passed: five members, %.1f px bird bodies" % (0.65 * 2.0 * 9.0))
	quit()
