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
const PROGRESS_S := 10.0  # a readiness line in godot.log this often
const STALL_S := 60.0  # the same missing list this long: stalled, fail with it
var _progress_at := 0.0
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
var _walk_phase := 0  # "walk" scenarios: 0 in the taxi, 1 getting out, 2 walking, 3 walked, 4 back to the door, 5 getting in, 6 done
var _walk_left := 0.0


## A "walk" scenario (fps-3d-view phase 1): out of the parked taxi, first
## person (I), then walk `walk.s` seconds with `walk.forward`/`walk.strafe`
## (sprint optional) towards `walk.yaw` rad left of the pose heading; the
## server moves the player, this only presses the keys. `walk.back`: then
## walk back to the driver's door until the server offers it ("door"), and
## press E there ("in").
func _walk(delta: float) -> void:
	var state: Dictionary = main.entities.shown_state()
	if state.is_empty():
		return
	var walk: Dictionary = scenario["walk"]
	var pose: Array = scenario["pose"]
	var player: Dictionary = state.get("player", {})
	if _walk_phase == 0 and not state.get("on_foot", true) and (_windshield_pressed or not scenario.get("windshield", false)) \
			and Vector2(float(player.get("x", INF)), float(player.get("y", INF))).distance_to(Vector2(pose[0], pose[1])) <= POSE_M:
		main._interact_pending = true  # F: out of the taxi
		_walk_phase = 1
	elif _walk_phase == 1 and state.get("on_foot", false):
		if not main.walk_eye and not walk.get("top_down", false):  # from the windshield view main.gd has switched by itself
			main._set_windshield(true, true)
		main.look_yaw = wrapf(float(pose[2]) + float(walk.get("yaw", 0.0)), -PI, PI)
		main.look_pitch = float(walk.get("pitch", 0.0))
		main.map_layer.buildings_3d.eye_pitch = main.look_pitch
		_walk_left = float(walk.get("s", 3.0))
		driving = true  # main.gd leaves the commands to this node
		_walk_phase = 2
	elif _walk_phase == 2 or (_walk_phase == 6 and walk.get("keep", false)):
		_walk_left -= delta
		var keep: bool = walk.get("keep", false)  # still walking in the screenshot: the figure mid-stride
		var on := _walk_left > 0.0 or keep
		var controls := {"throttle": 0.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0,
			"forward": float(walk.get("forward", 1.0)) if on else 0.0, "turn": -float(walk.get("strafe", 0.0)) if on else 0.0,
			"sprint": on and bool(walk.get("sprint", false))}
		main.send(main.walk_controls(controls, main.look_yaw) if walk.get("top_down", false) else controls)  # top_down: the figure seen from above
		if _walk_phase == 6:
			pass
		elif keep and _walk_left <= 0.0:
			_walk_phase = 6
		elif _walk_left <= -1.0:  # a second to stop
			_walk_phase = 4 if walk.has("back") else 6
			driving = _walk_phase == 4
	elif _walk_phase == 4:
		var c := cos(float(player["heading"]))
		var sn := sin(float(player["heading"]))
		var door := Vector2(float(player["x"]) + c * float(player.get("length_m", 4.0)) * 0.2 - sn * float(player.get("width_m", 1.8)) * 0.85,
			float(player["y"]) + sn * float(player.get("length_m", 4.0)) * 0.2 + c * float(player.get("width_m", 1.8)) * 0.85)
		var walker: Dictionary = state["player_pedestrian"]
		if walk["back"] in ["vehicle", "point"]:  # to the parked car (or the map point) at walk.target instead
			door = Vector2(walk["target"][0], walk["target"][1])
		var to_door := door - Vector2(float(walker["x"]), float(walker["y"]))
		main.look_yaw = to_door.angle()  # server axes: the angle is the heading
		var arrived: bool = to_door.length() < APPROACH_M if walk["back"] in ["vehicle", "point"] \
			else state.get("taxi_door", false) and to_door.length() < 1.2  # a step back: the taxi in view
		if arrived:
			main.look_pitch = 0.0 if walk["back"] == "vehicle" else -0.35  # looking down at the door (or the point); level at a car
			main.map_layer.buildings_3d.eye_pitch = main.look_pitch
		main.send({"throttle": 0.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0, "forward": 0.0 if arrived else 1.0, "turn": 0.0, "sprint": false})
		if arrived:
			driving = false
			if walk["back"] == "in":
				var key := InputEventKey.new()  # E at the door, as the player
				key.keycode = KEY_E
				key.physical_keycode = KEY_E
				key.pressed = true
				Input.parse_input_event(key)
				_walk_phase = 5
			else:
				_walk_phase = 6
	elif _walk_phase == 5 and not state.get("on_foot", true):
		_walk_phase = 6


## "lineup": every kind the 2D view draws, in rows east of the pose, heading east, at the sizes
## tools/visual_test.py takes from the simulation (lineup_rows, lineup_trailer, lineup_tram); the tram west of the taxi.
func _lineup() -> Array:
	var pose: Array = scenario["pose"]
	var out := []
	var rows: Array = scenario["lineup_rows"]
	var along: bool = scenario.get("lineup_along_road", false)  # 3D: end to end in a lane left of the taxi, clear of buildings
	var heading: float = pose[2] if along else 0.0
	var trailer: Array = scenario["lineup_trailer"]
	var total := 0.0
	for row: Array in rows:
		total += float(row[1]) + LINEUP_GAP_M + (float(trailer[0]) + float(trailer[2]) if row[0] == "car_caravan" else 0.0)
	var s := -total * 0.5 + LINEUP_SHIFT_M  # forward a little: the back end clear of the dashboard
	for i in rows.size():
		var row: Array = rows[i]
		var x: float = pose[0] + 6.0 + row[1] * 0.5
		var y: float = pose[1] + 13.5 - i * 3.0
		if along:
			if row[0] == "car_caravan":
				s += float(trailer[0]) + float(trailer[2])
			var at := _on_road(s + row[1] * 0.5, LINEUP_LANE_M)
			x = at.x
			y = at.y
			s += float(row[1]) + LINEUP_GAP_M
		var npc := {"id": "lineup_%d" % i, "x": x, "y": y, "heading": heading, "length_m": row[1], "width_m": row[2],
			"color": [60 + i * 18, 110, 200 - i * 12], "vehicle_type": row[0], "state": "DRIVING", "speed": 0.0,
			"is_taxi": i == 0}
		if row[0] == "car_caravan":
			npc["vehicle_type"] = "car"
			var back: Vector2 = Vector2(cos(heading), sin(heading)) * -(float(row[1]) * 0.5 + float(trailer[2]) + float(trailer[0]) * 0.5)
			npc["trailer"] = [x + back.x, y + back.y, heading, trailer[0], trailer[1], "caravan"]
		out.append(npc)
		if along and Buildings3D.MODEL_VARIANTS.has(row[0]):  # 3D: more ids beside it until each model shows
			var shown := {Buildings3D.model_variant(row[0], npc["id"]): true}
			var k := 0
			while shown.size() < Buildings3D.MODEL_VARIANTS[row[0]].size() and k < 32:
				k += 1
				var id := "lineup_%d_%d" % [i, k]
				if not shown.has(Buildings3D.model_variant(row[0], id)):
					shown[Buildings3D.model_variant(row[0], id)] = true
					var side := _on_road(s - row[1] * 0.5 - LINEUP_GAP_M, LINEUP_LANE_M + 1.2 * shown.size() - 1.2)
					var more := npc.duplicate()
					more.merge({"id": id, "x": side.x, "y": side.y}, true)
					out.append(more)
	return out


const LINEUP_GAP_M := 1.5
const LINEUP_LANE_M := 3.5
const LINEUP_SHIFT_M := 6.0
const Buildings3D := preload("res://buildings_3d.gd")


## A point `s` metres along the pose's heading, `lane` metres to its left, in the server's metres.
func _on_road(s: float, lane: float) -> Vector2:
	var pose: Array = scenario["pose"]
	var d := Vector2(cos(pose[2]), sin(pose[2]))
	return Vector2(pose[0], pose[1]) + d * s + Vector2(-d.y, d.x) * lane


func _lineup_train(name: String, look: String, lengths: Array, width: float, y: float, lane := -LINEUP_LANE_M - 0.5) -> Dictionary:
	var pose: Array = scenario["pose"]
	var cars := []
	var front: float = pose[0] - 2.5  # west of the taxi: clear of the HUD
	for length: float in lengths:  # front first, heading east
		cars.append([front - length * 0.5, pose[1] + y, 0.0, length, look])
		front -= length
	if scenario.get("lineup_along_road", false):  # 3D: end to end in the lane right of the taxi (y: the start along it)
		cars = []
		front = y
		for length: float in lengths:
			var at := _on_road(front - length * 0.5, lane)
			cars.append([at.x, at.y, float(pose[2]), length, look])
			front -= length
	return {"id": "lineup_" + name, "name": name, "width_m": width, "state": "STOPPED", "speed": 0.0, "line": "", "cars": cars}


func _ready() -> void:
	if scenario.get("lineup", "") is String and scenario.get("lineup", "") == "coach":  # one coach left of the taxi: its right side faces the camera
		var coach: Array = scenario["lineup_coach"]
		main.entities.extra_trains = [_lineup_train("train coach", coach[0], [coach[1]], coach[2], coach[1] * 0.5, LINEUP_LANE_M + 0.5)]
	elif scenario.get("lineup", false):
		main.entities.extra_npcs = _lineup()
	if scenario.get("lineup", false) is bool and scenario.get("lineup", false) and not scenario.has("lineup_kinds"):  # a close lineup: its rows only
		var tram: Array = scenario["lineup_tram"]  # [look, section lengths, width]
		main.entities.extra_trains = [_lineup_train("tram section", tram[0], tram[1], tram[2], 27.0 if scenario.get("lineup_along_road", false) else 13.5)]
		if scenario.has("lineup_coach"):  # [look, length, width]: a train coach under the tram
			var coach: Array = scenario["lineup_coach"]
			main.entities.extra_trains.append(_lineup_train("train coach", coach[0], [coach[1]], coach[2], -2.0 if scenario.get("lineup_along_road", false) else 8.5))
	if scenario.has("graphics"):  # graphics settings under test (brightness, contrast...), over the player's saved ones
		var options: Dictionary = main.graphics.duplicate()
		options.merge(scenario["graphics"], true)
		main.set_graphics.call_deferred(options)


func _process(delta: float) -> void:
	_elapsed += delta
	if scenario.has("bench_sitter") and main.entities.extra_pedestrians.is_empty():
		_seat_bench_sitter()
	if scenario.has("animals") and not _animals_placed:
		_place_animals()
	if scenario.has("walk"):
		_walk(delta)
	if scenario.get("windshield", false) and not _windshield_pressed and not main.entities.player_body().is_empty():
		var key := InputEventKey.new()
		key.keycode = KEY_I
		key.physical_keycode = KEY_I
		key.pressed = true
		Input.parse_input_event(key)
		_windshield_pressed = true
	if scenario.has("eye") and Buildings3D.current != null:  # a camera on foot or turned to a side window
		var eye: Dictionary = scenario["eye"]
		var test_eye := {"height": float(eye.get("height", 1.35)), "yaw": float(eye.get("yaw", 0.0))}
		if eye.has("at"):
			test_eye["at"] = MapMath.point(main.entities.origin, eye["at"][0], eye["at"][1])
			test_eye["ground"] = main.map_layer.deck_height(test_eye["at"], 0)
		Buildings3D.current.test_eye = test_eye
		RenderingServer.viewport_set_measure_render_time(Buildings3D.current._view.get_viewport_rid(), true)
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
		if driving and not scenario.has("walk"):  # full throttle down the street, straight on (as --screenshot-drive); a walk sends its own
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
	if str(missing) != str(_missing):
		_progress_at = _elapsed  # something changed: still getting ready
	_missing = missing
	_stable = _stable + 1 if missing.is_empty() else 0
	if int(_elapsed / PROGRESS_S) != int((_elapsed - delta) / PROGRESS_S):
		print("visual_test: %.0f s, waiting for %s" % [_elapsed, missing])
	if _elapsed - _progress_at > STALL_S:
		_write({"status": "failed", "errors": ["stalled: no readiness change for %d s" % STALL_S] + _missing})
		main.get_tree().quit(1)
		return
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


var _animals_placed := false


## "animals": [[species, x, y, heading], ...] (server axes; "rider" a person on a horse):
## held still in view as wildlife records (no vehicle reactions), once the server state is in.
func _place_animals() -> void:
	if main.entities.shown_state().is_empty():
		return
	main.wildlife.vehicle_reactions = false
	var riders := []
	for row: Array in scenario["animals"]:
		var at := MapMath.point(main.entities.origin, row[1], row[2])
		if row[0] == "rider":
			riders.append({"id": "rider_%d" % riders.size(), "x": float(row[1]), "y": float(row[2]), "heading": float(row[3]),
				"animation_state": "riding", "color": [40, 70, 140], "radius_m": 0.45})
		else:
			main.wildlife.animals.append({"id": -1 - main.wildlife.animals.size(), "species": row[0], "position": at,
				"bounds": Rect2(at - Vector2(5, 5), Vector2(10, 10)), "heading": -float(row[3]), "state": "IDLE", "timer": 1e9, "cycle": 0})
	main.entities.extra_pedestrians.append_array(riders)
	_animals_placed = true


## "bench_sitter": [x, y] of a mapped bench (server axes): once its chunk is
## loaded, a figure sits on it as bench_sitting.py seats one (facing across it).
func _seat_bench_sitter() -> void:
	var at := Vector2(scenario["bench_sitter"][0], scenario["bench_sitter"][1])
	var best: Array = []
	for chunk in main.map_layer._chunks.values():
		for o in chunk._data.get("scenery_objects", []):
			var d := Vector2(float(o[0]), float(o[1])).distance_to(at)
			if str(o[2]) == "bench" and d < 3.0 and (best.is_empty() or d < best[0]):  # the build aligns benches to their path
				best = [d, o]
	if not best.is_empty():
		var o: Array = best[1]
		print("visual_test: bench_sitter on the bench at %s, %.1f m from the given point" % [o, best[0]])
		main.entities.extra_pedestrians = [{"id": "bench_sitter", "x": float(o[0]), "y": float(o[1]), "heading": float(o[3]) - PI / 2.0,
			"animation_state": "sitting", "color": [200, 110, 20], "radius_m": 0.45}]


## What the scenario needs and the scene does not show yet ([] when ready).
func check() -> Array:
	var state: Dictionary = main.entities.shown_state()
	if state.is_empty():
		return ["no state from the server yet"]
	var missing := []
	var pose: Array = scenario["pose"]
	var player: Dictionary = state.get("player", {})
	var at := Vector2(float(player.get("x", INF)), float(player.get("y", INF)))
	var walking := scenario.has("walk")
	if scenario.has("bench_sitter") and main.entities.extra_pedestrians.is_empty():
		missing.append("no mapped bench at bench_sitter yet")
	var back: String = scenario.get("walk", {}).get("back", "")
	if walking and _walk_phase < 6:
		missing.append("still getting out and walking")
	if driving:  # moving on purpose: the clock and weather must hold, the pose and view change
		pass
	elif at.distance_to(Vector2(pose[0], pose[1])) > POSE_M or absf(angle_difference(float(player.get("heading", 0.0)), pose[2])) > HEADING_RAD:
		missing.append("vehicle at %s heading %.3f, not the scenario's %s" % [at, float(player.get("heading", 0.0)), pose])
	if back == "in":  # back at the wheel, the driver's eyes, the taxi where it was left
		if state.get("on_foot", true) or main.walk_eye or not main._windshield.visible:
			missing.append("not back in the taxi's windshield view")
	elif walking:  # the taxi stays where it was parked (checked above); the walker moved away from it
		var walker: Dictionary = state.get("player_pedestrian", {})
		var walked := Vector2(float(walker.get("x", INF)), float(walker.get("y", INF))).distance_to(Vector2(pose[0], pose[1]))
		if not state.get("on_foot", false) or main.walk_eye == bool(scenario["walk"].get("top_down", false)):
			missing.append("the player is not walking in the scenario's view")
		elif scenario["walk"].has("expect") and state.get("interaction", {}).get("kind", "") != scenario["walk"]["expect"]:
			missing.append("the server offers %s here, not %s" % [state.get("interaction", {}), scenario["walk"]["expect"]])
		elif scenario["walk"].get("cross_chunk", false) and floori(float(walker.get("x", 0.0)) / main.CHUNK_SIZE_M) == floori(pose[0] / main.CHUNK_SIZE_M) \
				and floori(float(walker.get("y", 0.0)) / main.CHUNK_SIZE_M) == floori(pose[1] / main.CHUNK_SIZE_M):
			missing.append("the walker at %s is still in the taxi's map chunk" % [Vector2(float(walker.get("x", 0.0)), float(walker.get("y", 0.0)))])
		elif back == "vehicle" and not _npc_at(state, Vector2(scenario["walk"]["target"][0], scenario["walk"]["target"][1])):
			missing.append("no vehicle parked at walk.target %s" % [scenario["walk"]["target"]])
		elif back == "vehicle" and Vector2(float(walker.get("x", INF)), float(walker.get("y", INF))).distance_to(Vector2(scenario["walk"]["target"][0], scenario["walk"]["target"][1])) >= APPROACH_M:
			missing.append("the walker is not beside the parked car yet")
		elif back == "point" and Vector2(float(walker.get("x", INF)), float(walker.get("y", INF))).distance_to(Vector2(scenario["walk"]["target"][0], scenario["walk"]["target"][1])) >= APPROACH_M:
			missing.append("the walker is not at walk.target yet")
		elif back == "door" and not state.get("taxi_door", false):
			missing.append("the server offers no taxi door here")
		elif back == "" and walked < float(scenario["walk"].get("min_m", 0.0)):
			missing.append("the walker is %.1f m from the taxi, the scenario needs %s" % [walked, scenario["walk"]["min_m"]])
	elif state.get("on_foot", true):
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
	if scenario.has("camera_at"):  # the camera held on a map point (server x, y), the vehicle elsewhere
		var look := MapMath.point(main.entities.origin, scenario["camera_at"][0], scenario["camera_at"][1])
		main._focus = {"kind": "pan", "position": look}
		missing.append_array(_check_map(look))
		if main.camera.position.distance_to(look) > 0.5:
			missing.append("camera not on camera_at yet")
	else:
		missing.append_array(_check_map(at - main.entities.origin))
		if main.camera.position.distance_to(main.entities.player_position()) > 2.0:
			missing.append("camera not on the vehicle yet")
	if scenario.get("windshield", false) and not main._windshield.visible:
		missing.append("windshield view not active yet")
	if scenario.get("requires", {}).has("animals_in_view"):
		var view: Rect2 = main.get_viewport().get_canvas_transform().affine_inverse() * main.get_viewport().get_visible_rect()
		var seen: int = main.wildlife.animals.filter(func(a): return view.has_point(a["position"])).size()
		_counts["animals_in_view"] = seen
		if seen < int(scenario["requires"]["animals_in_view"]):
			missing.append("%d animals in view, the scenario needs %d" % [seen, scenario["requires"]["animals_in_view"]])
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
	var wanted: Dictionary = scenario.get("requires", {}).get("scenery_in_view", {})  # {scenery_objects kind, "trees" or "power_lines": minimum}
	var seen := {}
	var footprints := []
	for corner in corners:
		var covered := false
		for chunk in main.map_layer._chunks.values():
			if chunk._bounds_rect.has_point(corner):
				covered = true
				if chunk._building_task >= 0 or chunk._forest_task >= 0:
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
			footprints.append(points)
			var box := Rect2(points[0], Vector2.ZERO)
			for p in points:
				box = box.expand(p)
			if box.intersects(view):  # a city block's corners are often all outside a close view
				buildings += 1
		for o in chunk._data.get("scenery_objects", []):
			if wanted.has(str(o[2])) and view.has_point(MapMath.point(chunk._origin, o[0], o[1])):
				seen[str(o[2])] = int(seen.get(str(o[2]), 0)) + 1
		for t in (chunk._data.get("trees", []) if wanted.has("trees") else []):
			if view.has_point(MapMath.point(chunk._origin, t[0], t[1])):
				seen["trees"] = int(seen.get("trees", 0)) + 1
		for line in (chunk._data.get("power_lines", []) if wanted.has("power_lines") else []):
			if chunk._points(line).size() > 0 and chunk._points(line)[0].distance_to(view.get_center()) < view.size.length():
				seen["power_lines"] = int(seen.get("power_lines", 0)) + 1
	for kind: String in wanted:
		if int(seen.get(kind, 0)) < int(wanted[kind]):
			missing.append("%d %s in view, the scenario needs %d" % [int(seen.get(kind, 0)), kind, wanted[kind]])
	var boxes := []  # [name, corners]: every lineup body, in view, clear of the HUD (and in 3D of the buildings)
	for npc in main.entities.extra_npcs:
		boxes.append([npc["vehicle_type"], _corners(npc["x"], npc["y"], npc["heading"], npc["length_m"], npc["width_m"])])
		if npc.has("trailer"):
			var t: Array = npc["trailer"]
			boxes.append(["caravan", _corners(t[0], t[1], t[2], t[3], t[4])])
	for train in main.entities.extra_trains:
		for car: Array in train["cars"]:
			boxes.append([train["name"], _corners(car[0], car[1], car[2], car[3], train["width_m"])])
	var to_screen: Transform2D = main.get_viewport().get_canvas_transform()
	var screen_size: Vector2 = main.get_viewport().get_visible_rect().size
	var hud := []
	for control: Control in main.get_node("Ui").find_children("*", "Control", true, false):  # every HUD panel and label
		if control.is_visible_in_tree() and not control is Container and control.size.x < screen_size.x * 0.8 \
				and control.size.y < screen_size.y * 0.8 and not (control is Label and control.text == ""):  # labels, panels, the instruments
			hud.append(control.get_global_rect())
	if main.instruments.visible:  # a full-screen control: the dashboard it draws
		hud.append(main.instruments.get_global_transform() * main.instruments.cluster_rect)
	var camera_3d: Camera3D = null if layer_3d_view() == null else layer_3d_view()._camera
	_lineup_seen = {}
	for i in boxes.size():
		var row: Array = boxes[i]
		var body: PackedVector2Array = row[1]
		var on_screen := Rect2()
		var in_view := true
		var first := true
		for corner: Vector2 in body:
			if MapChunkScript.outdoor_3d and camera_3d != null:  # each corner, on the ground and 3.5 m up, through the 3D camera
				for height: float in [0.0, 3.5]:
					var at := Vector3(corner.x, height, corner.y)
					if camera_3d.is_position_behind(at):
						in_view = false
						continue
					var p := camera_3d.unproject_position(at)
					on_screen = Rect2(p, Vector2.ZERO) if first else on_screen.expand(p)
					first = false
			else:
				in_view = in_view and view.has_point(corner)
				var p: Vector2 = to_screen * corner
				on_screen = Rect2(p, Vector2.ZERO) if first else on_screen.expand(p)
				first = false
		in_view = in_view and Rect2(Vector2.ZERO, screen_size).encloses(on_screen)
		var hidden := false
		if MapChunkScript.outdoor_3d:  # under a building's footprint: hidden in the 3D view
			for footprint: PackedVector2Array in footprints:
				for corner: Vector2 in body:
					if Geometry2D.is_point_in_polygon(corner, footprint):
						hidden = true
		var key := "%d %s" % [i, row[0]]
		if not in_view:
			missing.append("lineup %s not in view" % row[0])
			_lineup_seen[key] = "not in view"
			continue
		if hidden:
			missing.append("lineup %s under a building" % row[0])
			_lineup_seen[key] = "under a building"
			continue
		_lineup_seen[key] = "visible"
		for rect: Rect2 in hud:
			if rect.intersects(on_screen):
				missing.append("lineup %s under the HUD at %s" % [row[0], rect])
				_lineup_seen[key] = "under the HUD"
				break
	var needs: Dictionary = scenario.get("requires", {})
	if lamps < int(needs.get("lamps_in_view", 0)):
		missing.append("%d street lamps in view, the scenario needs %d" % [lamps, needs["lamps_in_view"]])
	if _moving(main.entities.shown_state()) < int(needs.get("moving_npcs", 0)):  # traffic running around the walker
		missing.append("%d moving NPC vehicles, the scenario needs %d" % [_moving(main.entities.shown_state()), needs["moving_npcs"]])
	if needs.has("far_npcs"):  # glb-only-vehicles: traffic 66-200 m from the player (the old procedural range)
		var shown: Dictionary = main.entities.shown_state()
		var me := Vector2(float(shown.get("player", {}).get("x", 0.0)), float(shown.get("player", {}).get("y", 0.0)))
		var far := 0
		for n in shown.get("npcs", []):
			var d := Vector2(float(n["x"]), float(n["y"])).distance_to(me)
			far += 1 if d > 66.0 and d < 200.0 else 0
		if far < int(needs["far_npcs"]):
			missing.append("%d NPC vehicles 66-200 m away, the scenario needs %d" % [far, needs["far_npcs"]])
	if buildings < int(needs.get("buildings_in_view", 0)):
		missing.append("%d buildings in view, the scenario needs %d" % [buildings, needs["buildings_in_view"]])
	var layer_3d = main.map_layer.buildings_3d
	if MapChunkScript.outdoor_3d and (layer_3d == null or (layer_3d._street_lights.is_empty() and layer_3d.opaque)):
		missing.append("the 3D view's lights are not made yet")
	if needs.has("train_models_in_view"):
		var trains: int = 0 if layer_3d == null else int(layer_3d._model_used.get("train_locomotive", 0)) + int(layer_3d._model_used.get("train_coach", 0))
		if trains < int(needs["train_models_in_view"]):
			missing.append("%d train models in view, the scenario needs %d" % [trains, needs["train_models_in_view"]])
	if needs.has("far_car_models_ahead"):  # glb-only-vehicles AC 4: GLB vehicles over 66 m ahead of the windshield, within 30 deg of its heading
		var ahead := 0
		if layer_3d != null:
			var eye: Vector2 = layer_3d.windshield_at
			var forward := Vector2(cos(layer_3d.windshield_heading), -sin(layer_3d.windshield_heading))
			for kind in layer_3d._model_nodes:
				for i in int(layer_3d._model_used.get(kind, 0)):
					var p: Vector3 = layer_3d._model_nodes[kind][i].position
					var off := Vector2(p.x, p.z) - eye
					ahead += 1 if off.length() > 66.0 and absf(forward.angle_to(off)) < deg_to_rad(30.0) else 0
		_counts["far_car_models_ahead"] = ahead
		if ahead < int(needs["far_car_models_ahead"]):
			var models := []
			if layer_3d != null:
				for kind in layer_3d._model_nodes:
					for i in int(layer_3d._model_used.get(kind, 0)):
						var p: Vector3 = layer_3d._model_nodes[kind][i].position
						models.append("%s %s" % [kind, (Vector2(p.x, p.z) - layer_3d.windshield_at).round()])
			missing.append("%d GLB vehicles over 66 m ahead, the scenario needs %d (heading %.2f, models %s)" % [ahead, needs["far_car_models_ahead"],
				0.0 if layer_3d == null else layer_3d.windshield_heading, models])
	if needs.has("roadworks_outside_start_box"):
		var outside := _roadworks_outside_start_box()
		if outside < int(needs["roadworks_outside_start_box"]):
			missing.append("%d roadworks loaded outside the start box, the scenario needs %d" % [outside, needs["roadworks_outside_start_box"]])
	var campers := []
	if needs.has("camper_pitch_in_view"):
		campers = _campers_in_view()
		if campers.size() < int(needs["camper_pitch_in_view"]):
			missing.append("%d camper pitches in view, the scenario needs %d" % [campers.size(), needs["camper_pitch_in_view"]])
		for c: Array in campers:
			if absf(c[1] / c[0] - 1.0) > 0.1:
				missing.append("camper drawn %.2f m, its row %.2f m (over 10 %%)" % [c[1], c[0]])
	_counts = {"lamps_in_view": lamps, "buildings_in_view": buildings, "chunks": main.map_layer.chunk_count(), "scenery_in_view": seen}
	if not campers.is_empty():
		_counts["campers"] = campers  # each: [row length m, drawn body m]
	if scenario.has("pitches"):
		_counts["pitches"] = _pitch_fits()
		for fit: Array in _counts["pitches"]:
			if fit[1] == "" or fit[2] > fit[3]:
				missing.append("pitch %s: %s reaches %.2f m, outline %.1f m" % [fit[0], fit[1] if fit[1] != "" else "nothing", fit[2], fit[3]])
	if not boxes.is_empty():
		_counts["lineup"] = _lineup_seen  # each row: visible, not in view or under the HUD
	return missing


const MapChunkScript := preload("res://map_chunk.gd")
var _lineup_seen := {}


## A body's four ground corners in the view's coordinates (server x, y; heading counter-clockwise from east).
func _corners(x: float, y: float, heading: float, length: float, width: float) -> PackedVector2Array:
	var c := Vector2(x - main.entities.origin.x, -(y - main.entities.origin.y))
	var f := Vector2(cos(heading), -sin(heading)) * length * 0.5
	var r := Vector2(-f.y, f.x).normalized() * width * 0.5
	return PackedVector2Array([c + f + r, c + f - r, c - f - r, c - f + r])


func layer_3d_view():
	return main.map_layer.buildings_3d
var _counts := {}


func _finish() -> void:
	set_process(false)  # awaits below: finish once
	var path := out_dir.path_join("screenshot.png")
	main.get_viewport().get_texture().get_image().save_png(path)
	if scenario.has("second_shot_s"):  # motion check: the same view a moment later
		await main.get_tree().create_timer(float(scenario["second_shot_s"])).timeout
		main.get_viewport().get_texture().get_image().save_png(out_dir.path_join("screenshot_2.png"))
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
const APPROACH_M := 3.5  # walk.back "vehicle": arrived this near the parked car's centre


## An NPC vehicle stands within 1 m of `at` (server axes).
static func _npc_at(state: Dictionary, at: Vector2) -> bool:
	return state.get("npcs", []).any(func(npc): return Vector2(float(npc.get("x", INF)), float(npc.get("y", INF))).distance_to(at) < 1.0)


func _moving(shown: Dictionary) -> int:
	var count := 0
	for npc in shown.get("npcs", []):
		if absf(float(npc.get("speed", 0.0))) > 0.5:
			count += 1
	return count


## The 3D forest's cost (docs/specs/forests-fps-3d.md section 7): tree instances
## loaded (near detail and far LOD batches), the frame's draw calls and objects,
## memory, the 3D pass's render times and the chunks' forest CPU times.
func _forest_stats() -> Dictionary:
	var near := 0
	var far := 0
	var place := []
	var build := []
	for chunk in main.map_layer._chunks.values():
		var forest = chunk._dynamic_3d.get("forest")
		if forest == null or not is_instance_valid(forest):
			continue
		place.append(chunk.forest_ms[0])
		build.append(chunk.forest_ms[1])
		for batch: MultiMeshInstance3D in forest.get_children():
			if batch.visibility_range_begin > 0.0:
				far += batch.multimesh.instance_count
			elif batch.multimesh.mesh != Buildings3D._tree_mesh("trunk"):
				near += batch.multimesh.instance_count
	var view_3d: RID = Buildings3D.current._view.get_viewport_rid() if Buildings3D.current != null else RID()
	return {"trees_loaded": near, "far_lod_crowns_loaded": far, "forest_chunks": place.size(),
		"place_ms_max": place.max() if place else 0.0, "build_ms_max": build.max() if build else 0.0,
		"build_ms_total": build.reduce(func(a, b): return a + b, 0.0),
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		"objects": Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME),
		"primitives": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME),
		"static_memory_mb": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"video_memory_mb": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"render_3d_cpu_ms": RenderingServer.viewport_get_measured_render_time_cpu(view_3d) if view_3d.is_valid() else null,
		"render_3d_gpu_ms": RenderingServer.viewport_get_measured_render_time_gpu(view_3d) if view_3d.is_valid() else null}


func _write(result: Dictionary) -> void:
	var state: Dictionary = main.entities.shown_state()
	var player: Dictionary = state.get("player", {})
	result.merge({"scenario": scenario.get("id", ""), "commit": scenario.get("commit", ""),
		"timestamp": Time.get_datetime_string_from_system(true) + "Z",
		"renderer": "%s on %s" % [RenderingServer.get_current_rendering_method(), RenderingServer.get_video_adapter_name()],
		"resolution": [main.get_viewport().get_visible_rect().size.x, main.get_viewport().get_visible_rect().size.y],
		"game_time": [state.get("calendar", {}).get("date", "") if typeof(state.get("calendar")) == TYPE_DICTIONARY else "", state.get("game_time_seconds", null)],
		"weather": state.get("weather", {}).duplicate(), "vehicle": {"x": player.get("x"), "y": player.get("y"), "heading": player.get("heading")},
		"walker": state.get("player_pedestrian", {}).duplicate() if state.get("on_foot", false) else {},
		"camera": {"zoom": main.camera.zoom.x, "position": [main.camera.position.x, main.camera.position.y]},
		"scene": _counts, "elapsed_s": _elapsed, "forest": _forest_stats()})
	result["weather"].erase("plowed_cells")
	if scenario.get("lineup", false) is bool and scenario.get("lineup", false):  # each lineup vehicle's close-range model
		result["lineup_models"] = main.entities.extra_npcs.map(func(n: Dictionary) -> Array:
			return [n["id"], n["vehicle_type"], Buildings3D.model_variant(n["vehicle_type"], n["id"])])
	var file := FileAccess.open(out_dir.path_join("result.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(result, "  "))
	file.close()
	print("VISUAL_TEST ", JSON.stringify({"scenario": result["scenario"], "status": result["status"], "errors": result.get("errors", [])}))


## Roadworks in the view whose midpoint is outside the start --bbox
## (start_box_center, default the pose, +- box_km/2): works the map
## extension added, not the opening load.
func _roadworks_outside_start_box() -> int:
	var centre: Array = scenario.get("start_box_center", scenario["pose"])
	var half := float(scenario.get("box_km", 2.0)) * 500.0
	var view: Rect2 = main.get_viewport().get_canvas_transform().affine_inverse() * main.get_viewport().get_visible_rect()
	var count := 0
	for chunk in main.map_layer._chunks.values():
		for work in chunk._data.get("roadworks", []):
			var mx := (float(work["start"][0]) + float(work["end"][0])) / 2.0
			var my := (float(work["start"][1]) + float(work["end"][1])) / 2.0
			var outside := absf(mx - float(centre[0])) > half or absf(my - float(centre[1])) > half
			if outside and view.has_point(Vector2(mx - main.entities.origin.x, -(my - main.entities.origin.y))):
				count += 1
	return count


## Camper rows in the view: [row length, body length the draw path recorded (map_chunk drawn_campers)].
func _campers_in_view() -> Array:
	var view: Rect2 = main.get_viewport().get_canvas_transform().affine_inverse() * main.get_viewport().get_visible_rect()
	var found := []
	for chunk in main.map_layer._chunks.values():
		for o in chunk._data.get("scenery_objects", []):
			if o[2] == "camper_van" and view.has_point(Vector2(float(o[0]) - main.entities.origin.x, -(float(o[1]) - main.entities.origin.y))):
				var length := float(o[4]) if o.size() > 4 else 0.0
				found.append([length, chunk.drawn_campers.get(MapMath.point(chunk._origin, o[0], o[1]), 0.0)])  # 0: not drawn
	return found


## Each scenario pitch [x, y, r] (a point pitch: campsites.py's 5 m envelope) and the camping
## row on it: [pitch, kind or "", farthest footprint corner from the pitch centre m, r].
func _pitch_fits() -> Array:
	const SIZES := {"tent": [3.2, 2.4], "camper_van": [6.2, 2.5], "caravan": [6.2, 2.5], "caravan_with_car": [9.4, 2.5]}  # campsites.py CAMPING_SIZES
	var fits := []
	for pitch: Array in scenario["pitches"]:
		var fit := [pitch, "", 0.0, float(pitch[2])]
		for chunk in main.map_layer._chunks.values():
			for o in chunk._data.get("scenery_objects", []):
				if SIZES.has(o[2]) and Vector2(float(o[0]), float(o[1])).distance_to(Vector2(pitch[0], pitch[1])) < 0.5:
					var length: float = float(o[4]) if o.size() > 4 else SIZES[o[2]][0]
					var centre := MapMath.point(main.entities.origin, pitch[0], pitch[1])
					fit[1] = o[2]
					for corner in _corners(float(o[0]), float(o[1]), float(o[3]), length, SIZES[o[2]][1]):
						fit[2] = maxf(fit[2], corner.distance_to(centre))
		fits.append(fit)
	return fits
