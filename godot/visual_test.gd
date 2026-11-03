## Developer visual tests (docs/visual-testing.md): main.gd adds this node
## only for `--visual-test SCENARIO.json`, which tools/visual_test.py writes
## from tools/visual_scenarios.json. It waits until every condition the
## scenario needs holds (pose, clock, weather, loaded and built chunks,
## required lamps and buildings in view, the camera), holds them for
## STABLE_FRAMES, measures `measure_s` of frames, saves the screenshot and
## writes result.json next to it - or, at the timeout, a failed result with
## the conditions still missing and no screenshot.
extends Node

const TIMEOUT_S := 240.0
const STABLE_FRAMES := 60
const POSE_M := 1.0
const HEADING_RAD := 0.02
const CLOCK_S := 120.0  # game seconds: the start minute, plus the server's first ticks

var main: Node
var scenario: Dictionary
var out_dir: String
var _elapsed := 0.0
var _stable := 0
var _missing: Array = []
var _measuring := false
var _measure_left := 0.0
var _frames := PackedFloat32Array()
var _measure_failures: Array = []
var driving := false  # measuring with `drive_s`: main.gd leaves the controls to this node
var _windshield_pressed := false


func _ready() -> void:
	if scenario.has("graphics"):  # graphics settings under test (brightness, contrast...), over the player's saved ones
		var options: Dictionary = main.graphics.duplicate()
		options.merge(scenario["graphics"], true)
		main.set_graphics.call_deferred(options)


func _process(delta: float) -> void:
	_elapsed += delta
	if scenario.get("windshield", false) and not _windshield_pressed and not main.entities.player_body().is_empty():
		var key := InputEventKey.new()
		key.keycode = KEY_I
		key.physical_keycode = KEY_I
		key.pressed = true
		Input.parse_input_event(key)
		_windshield_pressed = true
	if main.phone.is_open and not scenario.get("phone", false):  # ride offers open it: it would cover the scene
		main.phone.close()
	var missing := check()
	if _measuring:
		if driving:  # full throttle down the street, straight on (as --screenshot-drive)
			main.send({"throttle": 1.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
		_frames.append(delta * 1000.0)
		for reason in missing:
			if not reason in _measure_failures:
				_measure_failures.append(reason)
		_measure_left -= delta
		if _measure_left <= 0.0:
			_finish()
		return
	_missing = missing
	_stable = _stable + 1 if missing.is_empty() else 0
	if _stable >= STABLE_FRAMES:
		_measuring = true
		_measure_left = float(scenario.get("measure_s", 5.0))
		driving = float(scenario.get("drive_s", 0.0)) > 0.0
		if driving:
			_measure_left = float(scenario["drive_s"])
		var perf := preload("res://perf.gd")
		perf.reset()
		for key in ["lamp_reassigned", "lamp_moved_lit", "lamp_lights_max", "lamps_offered_max"]:
			perf.counters.erase(key)
	elif _elapsed > TIMEOUT_S:
		_write({"status": "failed", "errors": ["not ready after %d s" % TIMEOUT_S] + _missing})
		main.get_tree().quit(1)


## What the scenario needs and the scene does not show yet ([] when ready).
func check() -> Array:
	var state: Dictionary = main.entities.shown_state()
	if state.is_empty():
		return ["no state from the server yet"]
	var missing := []
	var pose: Array = scenario["pose"]
	var player: Dictionary = state.get("player", {})
	var at := Vector2(float(player.get("x", INF)), float(player.get("y", INF)))
	if driving:  # moving on purpose: the clock and weather must hold, the pose and view change
		pass
	elif at.distance_to(Vector2(pose[0], pose[1])) > POSE_M or absf(angle_difference(float(player.get("heading", 0.0)), pose[2])) > HEADING_RAD:
		missing.append("vehicle at %s heading %.3f, not the scenario's %s" % [at, float(player.get("heading", 0.0)), pose])
	if state.get("on_foot", true):
		missing.append("the player is on foot, not in the vehicle")
	var calendar: Dictionary = state.get("calendar", {}) if typeof(state.get("calendar")) == TYPE_DICTIONARY else {}
	var start: String = scenario["start_time"]
	var wanted_s := int(start.substr(11, 2)) * 3600 + int(start.substr(14, 2)) * 60
	if calendar.get("date", "") != start.substr(0, 10) or absf(float(state.get("game_time_seconds", -1e9)) - wanted_s) > CLOCK_S:
		missing.append("game time %s %.0f s, not %s" % [calendar.get("date", "?"), float(state.get("game_time_seconds", -1.0)), start])
	var altitude := float(calendar.get("sun_altitude_deg", NAN))
	var sun: Array = scenario.get("sun_altitude_deg", [-90.0, 90.0])
	if not (altitude >= sun[0] and altitude <= sun[1]):
		missing.append("sun at %.1f deg, the scenario needs %s" % [altitude, sun])
	var weather: Dictionary = state.get("weather", {})
	if weather.get("weather_type", "") != scenario["weather"]:
		missing.append("weather %s, not %s" % [weather.get("weather_type", "?"), scenario["weather"]])
	if absf(float(weather.get("cloud_cover", -1.0)) - float(scenario["cloud"])) > 0.02:
		missing.append("cloud cover %.2f, not %.2f" % [float(weather.get("cloud_cover", -1.0)), float(scenario["cloud"])])
	var wet: Array = scenario.get("wetness", [0.0, 1.0])
	if not (float(weather.get("wetness", -1.0)) >= wet[0] and float(weather.get("wetness", -1.0)) <= wet[1]):
		missing.append("road wetness %.2f, the scenario needs %s" % [float(weather.get("wetness", -1.0)), wet])
	if driving:
		return missing
	missing.append_array(_check_map(at - main.entities.origin))
	if main.camera.position.distance_to(main.entities.player_position()) > 2.0:
		missing.append("camera not on the vehicle yet")
	if scenario.get("windshield", false) and not main._windshield.visible:
		missing.append("windshield view not active yet")
	return missing


## Chunks under the view loaded and built, the required lamps and buildings in view.
func _check_map(centre: Vector2) -> Array:
	var missing := []
	if not main._chunk_queue.is_empty():
		missing.append("%d chunks still queued" % main._chunk_queue.size())
	var view: Rect2 = main.get_viewport().get_canvas_transform().affine_inverse() * main.get_viewport().get_visible_rect()
	var corners := [view.position, view.end, Vector2(view.position.x, view.end.y), Vector2(view.end.x, view.position.y), centre]
	var lamps := 0
	var buildings := 0
	for corner in corners:
		var covered := false
		for chunk in main.map_layer._chunks.values():
			if chunk._bounds_rect.has_point(corner):
				covered = true
				if chunk._building_task >= 0:
					missing.append("a chunk under the view is still building its meshes")
		if not covered:
			missing.append("no chunk loaded at %s" % corner)
	for chunk in main.map_layer._chunks.values():
		if not chunk._bounds_rect.intersects(view):
			continue
		for i in chunk.street_lights.size():
			if view.has_point(chunk.street_lights[i]) and not chunk._broken.has(i):
				lamps += 1
		for footprint in chunk._data.get("buildings", []):
			var points: PackedVector2Array = chunk._points(footprint)
			var box := Rect2(points[0], Vector2.ZERO)
			for p in points:
				box = box.expand(p)
			if box.intersects(view):  # a city block's corners are often all outside a close view
				buildings += 1
	var needs: Dictionary = scenario.get("requires", {})
	if lamps < int(needs.get("lamps_in_view", 0)):
		missing.append("%d street lamps in view, the scenario needs %d" % [lamps, needs["lamps_in_view"]])
	if buildings < int(needs.get("buildings_in_view", 0)):
		missing.append("%d buildings in view, the scenario needs %d" % [buildings, needs["buildings_in_view"]])
	var layer_3d = main.map_layer.buildings_3d
	if MapChunkScript.outdoor_3d and (layer_3d == null or (layer_3d._street_lights.is_empty() and layer_3d.opaque)):
		missing.append("the 3D view's lights are not made yet")
	if needs.has("train_models_in_view"):
		var trains: int = 0 if layer_3d == null else int(layer_3d._model_used.get("train_locomotive", 0)) + int(layer_3d._model_used.get("train_coach", 0))
		if trains < int(needs["train_models_in_view"]):
			missing.append("%d train models in view, the scenario needs %d" % [trains, needs["train_models_in_view"]])
	_counts = {"lamps_in_view": lamps, "buildings_in_view": buildings, "chunks": main.map_layer.chunk_count()}
	return missing


const MapChunkScript := preload("res://map_chunk.gd")
var _counts := {}


func _finish() -> void:
	var path := out_dir.path_join("screenshot.png")
	main.get_viewport().get_texture().get_image().save_png(path)
	var perf := preload("res://perf.gd")
	var sections := {}
	for name in ["render_3d_gpu", "render_3d_cpu", "render_gpu", "render_cpu"]:
		if perf.sections.has(name):
			var s: Array = perf.sections[name]
			sections[name] = {"avg_ms": s[1] / 1000.0 / maxi(1, s[0]), "max_ms": s[2] / 1000.0}
	var ok := _measure_failures.is_empty()
	var lamps := {}
	for key in ["lamp_reassigned", "lamp_moved_lit", "lamp_lights_max", "lamps_offered_max"]:
		lamps[key] = perf.counters.get(key, 0)
	_write({"status": "passed" if ok else "failed", "screenshot": path, "frames": perf.summary(_frames), "render": sections, "lamps": lamps,
		"errors": [] if ok else ["conditions lost while measuring"] + _measure_failures})
	main.get_tree().quit(0 if ok else 1)


func _write(result: Dictionary) -> void:
	var state: Dictionary = main.entities.shown_state()
	var player: Dictionary = state.get("player", {})
	result.merge({"scenario": scenario.get("id", ""), "commit": scenario.get("commit", ""),
		"timestamp": Time.get_datetime_string_from_system(true) + "Z",
		"renderer": "%s on %s" % [RenderingServer.get_current_rendering_method(), RenderingServer.get_video_adapter_name()],
		"resolution": [main.get_viewport().get_visible_rect().size.x, main.get_viewport().get_visible_rect().size.y],
		"game_time": [state.get("calendar", {}).get("date", "") if typeof(state.get("calendar")) == TYPE_DICTIONARY else "", state.get("game_time_seconds", null)],
		"weather": state.get("weather", {}).duplicate(), "vehicle": {"x": player.get("x"), "y": player.get("y"), "heading": player.get("heading")},
		"camera": {"zoom": main.camera.zoom.x, "position": [main.camera.position.x, main.camera.position.y]},
		"scene": _counts, "elapsed_s": _elapsed})
	result["weather"].erase("plowed_cells")
	var file := FileAccess.open(out_dir.path_join("result.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(result, "  "))
	file.close()
	print("VISUAL_TEST ", JSON.stringify({"scenario": result["scenario"], "status": result["status"], "errors": result.get("errors", [])}))
