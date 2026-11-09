extends SceneTree
## tools/visual_test.py, scenario "kind": "startup_download": the launcher's
## map download screen against a local slow server (RRT_PBF_URL). Captures
## only after the bar and label were ready for 60 consecutive frames.

const TIMEOUT_S := 120.0
var scenario: Dictionary
var out_dir: String


func _initialize() -> void:
	var path: String = OS.get_cmdline_user_args()[OS.get_cmdline_user_args().find("--startup-scenario") + 1]
	scenario = JSON.parse_string(FileAccess.get_file_as_string(path))
	out_dir = path.get_base_dir()
	_run()


func _missing(startup: Node) -> Array:
	var bars := startup.find_children("*", "ProgressBar", true, false)
	var labels := startup.find_children("*", "Label", true, false).filter(func(l: Label) -> bool: return "MiB" in l.text)
	var errors := []
	if bars.is_empty() or bars[0].indeterminate or bars[0].value <= 0.0:
		errors.append("the progress bar shows no determinate progress")
	if labels.is_empty() or RegEx.create_from_string("^\\d+\\.0 / \\d+\\.\\d MiB  -  \\d+\\.\\d MiB/s$").search(labels[0].text) == null:
		errors.append("the label shows no 'X.0 / Z.Z MiB  -  N.N MiB/s' (%s)" % ("none" if labels.is_empty() else labels[0].text))
	return errors


func _run() -> void:
	var startup: Node = load("res://startup.tscn").instantiate()
	root.add_child(startup)
	await process_frame
	startup._download_pbf("")
	var started := Time.get_ticks_msec()
	var ready_frames := 0
	var missing := []
	while ready_frames < 60 and Time.get_ticks_msec() - started < TIMEOUT_S * 1000.0:
		await process_frame
		missing = _missing(startup)
		ready_frames = ready_frames + 1 if missing.is_empty() else 0
	var result := {"scenario": scenario.get("id", ""), "commit": scenario.get("commit", ""),
		"timestamp": Time.get_datetime_string_from_system(true) + "Z",
		"renderer": "%s on %s" % [RenderingServer.get_current_rendering_method(), RenderingServer.get_video_adapter_name()],
		"resolution": [root.size.x, root.size.y], "elapsed_s": (Time.get_ticks_msec() - started) / 1000.0}
	if missing.is_empty():
		await RenderingServer.frame_post_draw
		var shot := out_dir.path_join("screenshot.png")
		root.get_texture().get_image().save_png(shot)
		var bar: ProgressBar = startup.find_children("*", "ProgressBar", true, false)[0]
		result.merge({"status": "passed", "screenshot": shot, "progress_percent": bar.value,
			"label": startup.find_children("*", "Label", true, false).filter(func(l: Label) -> bool: return "MiB/s" in l.text)[0].text})
	else:
		result.merge({"status": "failed", "errors": ["not ready after %d s" % TIMEOUT_S] + missing})
	var file := FileAccess.open(out_dir.path_join("result.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(result, "  "))
	file.close()
	print("VISUAL_TEST ", JSON.stringify({"scenario": result["scenario"], "status": result["status"], "errors": result.get("errors", [])}))
	quit(0 if missing.is_empty() else 1)
