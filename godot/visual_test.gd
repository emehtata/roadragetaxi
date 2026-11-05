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
var _npc_max := 0
var _npc_min_moving := 1 << 30  # fewest moving NPC cars in view during the drive
var _speed_max := 0.0
var driving := false  # measuring with `drive_s`: main.gd leaves the controls to this node
var _windshield_pressed := false
var _lane_assist_pressed := false


## "lineup": every kind the 2D view draws, in rows east of the pose, heading east, at the sizes
## tools/visual_test.py takes from the simulation (lineup_rows, lineup_trailer, lineup_tram); the tram west of the taxi.
func _lineup() -> Array:
	var pose: Array = scenario["pose"]
	var out := []
	var rows: Array = scenario["lineup_rows"]
	for i in rows.size():
		var row: Array = rows[i]
		var x: float = pose[0] + 6.0 + row[1] * 0.5
		var y: float = pose[1] + 13.5 - i * 3.0
		var npc := {"id": "lineup_%d" % i, "x": x, "y": y, "heading": 0.0, "length_m": row[1], "width_m": row[2],
			"color": [60 + i * 18, 110, 200 - i * 12], "vehicle_type": row[0], "state": "DRIVING", "speed": 0.0,
			"is_taxi": i == 0}
		if row[0] == "car_caravan":
			var trailer: Array = scenario["lineup_trailer"]
			npc["vehicle_type"] = "car"
			npc["trailer"] = [x - row[1] * 0.5 - trailer[2] - trailer[0] * 0.5, y, 0.0, trailer[0], trailer[1], "caravan"]
		out.append(npc)
	return out


func _lineup_tram() -> Dictionary:
	var pose: Array = scenario["pose"]
	var tram: Array = scenario["lineup_tram"]  # [look, section lengths, width]
	var cars := []
	var front: float = pose[0] - 2.5  # west of the taxi, level with the first row: clear of the HUD
	for length: float in tram[1]:  # front first, heading east
		cars.append([front - length * 0.5, pose[1] + 13.5, 0.0, length, tram[0]])
		front -= length
	return {"id": "lineup_tram", "state": "STOPPED", "speed": 0.0, "line": "", "cars": cars}


func _ready() -> void:
	if scenario.get("lineup", false):
		main.entities.extra_npcs = _lineup()
		main.entities.extra_trains = [_lineup_tram()]
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
	if scenario.get("lane_assist", false) and not _lane_assist_pressed and not main.entities.player_body().is_empty():
		var lane_key := InputEventKey.new()  # K: "keep car on lane"
		lane_key.keycode = KEY_K
		lane_key.physical_keycode = KEY_K
		lane_key.pressed = true
		Input.parse_input_event(lane_key)
		_lane_assist_pressed = true
	if main.phone.is_open and not scenario.get("phone", false):  # ride offers open it: it would cover the scene
		main.phone.close()
	var missing := check()
	if _measuring:
		if driving:  # full throttle down the street, straight on (as --screenshot-drive)
			main.send({"throttle": 1.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
		_frames.append(delta * 1000.0)
		var shown: Dictionary = main.entities.shown_state()
		_npc_max = maxi(_npc_max, shown.get("npcs", []).size())
		_npc_min_moving = mini(_npc_min_moving, _moving(shown))
		_speed_max = maxf(_speed_max, absf(float(shown.get("player", {}).get("speed", 0.0))))
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
	var boxes := []  # [name, box]: every lineup body east-west, in view and clear of the HUD
	for npc in main.entities.extra_npcs:
		var half := Vector2(float(npc["length_m"]), float(npc["width_m"])) * 0.5
		boxes.append([npc["vehicle_type"], Rect2(Vector2(npc["x"] - main.entities.origin.x, -(npc["y"] - main.entities.origin.y)) - half, half * 2.0)])
	for train in main.entities.extra_trains:
		for car: Array in train["cars"]:
			var half := Vector2(float(car[3]), float(scenario["lineup_tram"][2])) * 0.5
			boxes.append(["tram section", Rect2(Vector2(car[0] - main.entities.origin.x, -(car[1] - main.entities.origin.y)) - half, half * 2.0)])
	var to_screen: Transform2D = main.get_viewport().get_canvas_transform()
	var screen_size: Vector2 = main.get_viewport().get_visible_rect().size
	var hud := []
	for control: Control in main.get_node("Ui").find_children("*", "Control", true, false):  # every HUD panel and label
		if control.is_visible_in_tree() and (control is Label or control is TextureRect or control is Panel or control is PanelContainer) \
				and control.size.x < screen_size.x * 0.8 and not (control is Label and control.text == ""):
			hud.append(control.get_global_rect())
	for row: Array in boxes:
		if not view.encloses(row[1]):
			missing.append("lineup %s not in view" % row[0])
			continue
		var on_screen: Rect2 = to_screen * row[1]
		for rect: Rect2 in hud:
			if rect.intersects(on_screen):
				missing.append("lineup %s under the HUD at %s" % [row[0], rect])
				break
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
	set_process(false)  # awaits below: finish once
	var path := out_dir.path_join("screenshot.png")
	main.get_viewport().get_texture().get_image().save_png(path)
	var rejections := await _spawn_rejections()
	var perf := preload("res://perf.gd")
	var sections := {}
	for name in ["render_3d_gpu", "render_3d_cpu", "render_gpu", "render_cpu"]:
		if perf.sections.has(name):
			var s: Array = perf.sections[name]
			sections[name] = {"avg_ms": s[1] / 1000.0 / maxi(1, s[0]), "max_ms": s[2] / 1000.0}
	var ok := _measure_failures.is_empty()
	var traffic := {"npcs_max": _npc_max, "moving_min": _npc_min_moving if _npc_min_moving < (1 << 30) else 0, "speed_max": _speed_max, "spawn_rejections": rejections}
	var lamps := {}
	for key in ["lamp_reassigned", "lamp_moved_lit", "lamp_lights_max", "lamps_offered_max"]:
		lamps[key] = perf.counters.get(key, 0)
	_write({"status": "passed" if ok else "failed", "screenshot": path, "frames": perf.summary(_frames), "render": sections, "lamps": lamps, "traffic": traffic,
		"errors": [] if ok else ["conditions lost while measuring"] + _measure_failures})
	main.get_tree().quit(0 if ok else 1)


## Planned transit cars dropped per reason this drive, from the server's debug JSON;
## prints one `spawn_rejections:` line.
func _spawn_rejections() -> Dictionary:
	var path := ProjectSettings.globalize_path(out_dir.path_join("server_debug.json"))
	DirAccess.remove_absolute(path)
	if not main.sim.send_debug_snapshot(path):
		return {}
	for i in 300:  # bounded: about 5 s at 60 fps
		await main.get_tree().process_frame
		if FileAccess.file_exists(path):
			var data = JSON.parse_string(FileAccess.get_file_as_string(path))
			if typeof(data) != TYPE_DICTIONARY:
				continue  # still being written
			var reasons: Dictionary = data.get("npc_population", {}).get("diagnostics", {}).get("spawn", {}).get("discard_reasons", {})
			var parts := []
			for reason in reasons:
				if reason != "total" and reason != "share":
					parts.append("%s=%d (%.0f%%)" % [reason, reasons[reason], 100.0 * float(reasons.get("share", {}).get(reason, 0.0))])
			print("spawn_rejections: ", " ".join(parts))
			return reasons
	return {}


## Moving NPC cars in the shown state (the drive's traffic check).
func _moving(shown: Dictionary) -> int:
	var count := 0
	for npc in shown.get("npcs", []):
		if absf(float(npc.get("speed", 0.0))) > 0.5:
			count += 1
	return count


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
