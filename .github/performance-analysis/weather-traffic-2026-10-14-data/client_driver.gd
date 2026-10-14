extends SceneTree

var main: Node
var settled := 0.0
var reset_done := false

func _initialize() -> void:
	main = load("res://main.tscn").instantiate()
	root.add_child(main)
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

func _process(delta: float) -> bool:
	if main.entities.shown_state().is_empty():
		return false
	settled += delta
	load("res://perf.gd").counters["diagnostic_track_points"] = main.entities._track_points
	if not reset_done and settled >= 5.0:
		load("res://perf.gd").reset()
		var args := OS.get_cmdline_user_args()
		var index := args.find("--diagnostic-tracks")
		if index >= 0:
			var count := int(args[index + 1])
			var points: Array = []
			var centre: Vector2 = main.entities.player_position()
			for i in count:
				var angle := float(i) * 0.05
				points.append([centre + Vector2(cos(angle), sin(angle)) * 25.0, angle + PI / 2.0, 1.0, true, main.entities._snowfall])
			main.entities._trails = [["snow", points]]
			main.entities._track_points = count
			main.entities._tracks.queue_redraw()
		if "--diagnostic-roads" in args:
			for chunk in main.map_layer._chunks.values():
				for layer in chunk._road_layers:
					for connection in layer.draw.get_connections():
						var original: Callable = connection["callable"]
						layer.draw.disconnect(original)
						layer.draw.connect(func():
							var began := Time.get_ticks_usec()
							original.call()
							load("res://perf.gd").add("diagnostic_roads_draw", Time.get_ticks_usec() - began))
		reset_done = true
	return false
