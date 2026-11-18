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
var _chunks_seen := -1  # chunks loaded + queued at the last check
var _chunks_changed_msec := 0
var _long_frames: Array = []  # frames over 33 ms with what ran in them and in the frame before (attribution)
var _frame_work := [0, 0, 0]  # previous frame's [main_process usec total, chunk usec total, pipeline compilations]
var _measure_failures: Array = []
var _npc_max := 0
var _npc_min_moving := 1 << 30  # fewest moving NPC cars in view during the drive
var _speed_max := 0.0
var driving := false  # measuring with `drive_s`: main.gd leaves the controls to this node
var _windshield_pressed := false
var _lane_assist_pressed := false
const CAMERA := {"third": KEY_1, "top": KEY_2, "eye": KEY_3}  # scenario "camera" and "switch": the key that selects it
var _switch_i := 0
var _switch_at := 0.0
var _chase_on_frames := 0
var _chase_last := []  # [camera position, taxi position, camera yaw] last frame in third-person
var _chase := {"max_excess_step_m": 0.0, "max_yaw_step_rad": 0.0, "frames": 0}  # acceptance 10: no camera jumps beyond the taxi's own
var _walk_phase := 0  # "walk" scenarios: 0 in the taxi, 1 getting out, 2 walking, 3 walked, 4 back to the door, 5 getting in, 6 done
var _walk_left := 0.0
var _hud_configured := false
var _hud_expected := ""
var _hud_snapshot := {}
var _indoor_hint: CanvasLayer
var _indoor_draws := 0
var _indoor_snapshot := {}
var _crossbuck_mesh_vertices := {}  # audit-only matching of the mapped crossing mesh
var _tower_mesh_vertices := {}  # audit-only cached 1 mm membership checks against the actual mapped tower mesh
var _felled_occluders := {}  # audit-only cached triangle BVHs for actual drawn buildings
var _coaster_mesh_vertices := {}  # audit-only actual mapped path matching
var _camp_pair_mesh_vertices := {}  # audit-only actual mapped camping combination match


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
		if not main.walk_eye and not main.walk_chase and not walk.get("top_down", false):  # from the windshield view main.gd has switched by itself
			var walk_key := InputEventKey.new()  # 3 on foot, as the player: first person
			walk_key.keycode = KEY_3
			walk_key.pressed = true
			main._unhandled_input(walk_key)
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
			main.look_pitch = 0.0 if walk["back"] == "vehicle" else float(walk.get("pitch", -0.35))  # looking down at the door (or the point); level at a car
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
	if scenario.has("indoor_hint"):
		main.get_window().mode = Window.MODE_WINDOWED
		main.get_window().size = Vector2i(scenario["resolution"][0], scenario["resolution"][1])
	# The driving camera: "camera" (or the last of "switch"); without either the map view as before (3 for "windshield").
	var walk_in: bool = scenario.get("walk", {}).get("back", "") == "in"
	main.camera_modes.select(main.camera_modes.KEYS[CAMERA[scenario.get("camera", "eye" if walk_in else "top")]])
	if scenario.has("orbit_deg"):  # docs/specs/3rd-person-mouse.md: the chase orbit as if the mouse had turned it
		main.camera_modes.look(Vector2(-deg_to_rad(float(scenario["orbit_deg"])), 0.0), 1.0)
	if scenario.has("chase_zoom"):  # "min" / "max": the taxi chase distance limit
		main.camera_modes.zoom_step(100.0 if scenario["chase_zoom"] == "min" else -100.0, 1.0)
	if scenario.get("lineup", "") is String and scenario.get("lineup", "") == "coach":  # one coach left of the taxi: its right side faces the camera
		var coach: Array = scenario["lineup_coach"]
		main.entities.extra_trains = [_lineup_train("train coach", coach[0], [coach[1]], coach[2], coach[1] * 0.5, LINEUP_LANE_M + 0.5)]
	elif scenario.get("lineup", false):
		main.entities.extra_npcs = _lineup()
	if scenario.get("fox_orientation", false):
		var at := _on_road(9.0, 0.9)
		scenario["animals"] = [["fox", at.x, at.y, float(scenario["pose"][2]) + PI - 0.3]]
	if scenario.get("reflective_strips", false):
		var at := _on_road(9.0, 0.9)
		var id := ""
		for i in 100:
			id = "vqa_reflective_%d" % i
			if absi(hash(id)) % 8 == 4: break
		main.entities.extra_pedestrians = [{"id":id,"x":at.x,"y":at.y,"heading":float(scenario["pose"][2])+PI-0.25,
			"color":[65,125,190],"radius_m":0.45,"gender":"female","animation_state":"standing","pose":"standing_1"}]
	if scenario.get("coach_roof_vent", false):
		var at := _on_road(18.0, 0.9)
		main.entities.extra_trains = [{"id":"vqa_coach_vent","name":"train coach","width_m":2.89,"state":"STOPPED","speed":0.0,"line":"",
			"cars":[[at.x,at.y,float(scenario["pose"][2]),26.4,"standard"]]}]
	if scenario.has("windscreen_model") or scenario.has("two_wheeler_model"):
		var kind: String = scenario.get("windscreen_model", scenario.get("two_wheeler_model", ""))
		var id := ""
		for i in 100:
			id = "windscreen_%d" % i
			var shape: Array = main.entities.VAN_SHAPE if kind == "panel_van" else main.entities.CAR_SHAPES[absi(hash(id)) % main.entities.CAR_SHAPES.size()]
			if Buildings3D.car_model_kind(shape, 4.6) == kind: break
		var at := _on_road(6.0, 3.5)
		main.entities.extra_npcs = [{"id":id,"x":at.x,"y":at.y,"heading":float(scenario["pose"][2])+PI,"length_m":4.6,"width_m":1.8,
			"color":[175,85,48],"vehicle_type":"van" if kind == "panel_van" else "car","state":"PARKED","speed":0.0,"is_taxi":false}]
	if scenario.get("city_bus_orientation", false):
		var at := _on_road(28.0, 0.9)
		main.entities.extra_npcs = [{"id":"vqa_city_bus","x":at.x,"y":at.y,"heading":float(scenario["pose"][2])+PI*0.95,
			"length_m":12.0,"width_m":2.55,"color":[175,85,48],"vehicle_type":"bus","state":"DRIVING","speed":0.0,"is_taxi":false}]
	if scenario.has("two_wheeler_model"):
		var model: String = scenario["two_wheeler_model"]
		var kind := "bicycle" if model == "mountain_bike" else "e_scooter" if model == "e_scooter_grab3d" else model
		var id := ""
		for i in 100:
			id = "lamp_attachment_%d" % i
			if Buildings3D.model_variant(kind, id) == model: break
		var at := _on_road(9.0, 0.9)
		main.entities.extra_npcs = [{"id":id,"x":at.x,"y":at.y,"heading":float(scenario["pose"][2])+PI*0.75,
			"length_m":2.2 if kind == "motorcycle" else 1.8 if kind == "bicycle" else 1.2,
			"width_m":0.8 if kind == "motorcycle" else 0.6 if kind == "bicycle" else 0.5,
			"color":[175,85,48],"vehicle_type":kind,"state":"DRIVING" if scenario.get("riding",true) else "PARKED","speed":0.0,"is_taxi":false}]
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
	if scenario.has("bench_sitter") and not main.entities.extra_pedestrians.any(func(p): return p["id"] == "bench_sitter"):
		_seat_bench_sitter()
	if scenario.has("animals") and not _animals_placed:
		_place_animals()
	if scenario.has("walk"):
		_walk(delta)
	if scenario.get("windshield", false) and not _windshield_pressed and not main.entities.player_body().is_empty():
		var key := InputEventKey.new()
		key.keycode = KEY_3  # the driver's eyes
		key.physical_keycode = KEY_3
		key.pressed = true
		Input.parse_input_event(key)
		_windshield_pressed = true
	if _switch_i < scenario.get("switch", []).size() and _elapsed >= _switch_at and not main.entities.player_body().is_empty():
		var press := InputEventKey.new()  # 1/2/3 as the player, one a second
		press.keycode = CAMERA[scenario["switch"][_switch_i]]
		press.physical_keycode = press.keycode
		press.pressed = true
		Input.parse_input_event(press)
		print("visual-test: camera key %s" % scenario["switch"][_switch_i])
		_switch_i += 1
		_switch_at = _elapsed + 1.0
	_track_chase()
	if scenario.has("felled_tree"):
		main.map_layer.set_knocked_trees([scenario["felled_tree"]])  # fixed server-state fixture at the sourced mapped tree
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
	if scenario.get("accept_offer", false) and not main.phone.busy and not main.phone.items.is_empty() and main.phone.pending.is_empty():
		main.phone.select(0)  # the first ride offer, as key 1 on the phone: a real fare and its route
		main.phone.accept_selected()
	if main.phone.is_open and not scenario.get("phone", false) and not scenario.get("accept_offer", false):  # ride offers open it: it would cover the scene
		main.phone.close()
	if scenario.has("hud_fixture"):
		_show_hud_fixture()
	if scenario.has("indoor_hint"):
		if not is_instance_valid(_indoor_hint) and check().is_empty():
			_show_indoor_hint()
		_indoor_draws += 1
	var missing := check()
	if scenario.has("indoor_hint"):
		missing.append_array(_indoor_hint_readiness())
	if _measuring:
		if driving and not scenario.has("walk"):  # full throttle down the street, straight on (as --screenshot-drive); a walk sends its own
			main.send({"throttle": 1.0, "brake": 0.0, "steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false})
		_frames.append(delta * 1000.0)
		var work := _work_totals()
		if delta * 1000.0 > 33.3 and _long_frames.size() < 40:
			_long_frames.append({"frame": _frames.size(), "ms": delta * 1000.0, "main_ms": (work[0] - _frame_work[0]) / 1000.0,
				"chunk_ms": (work[1] - _frame_work[1]) / 1000.0, "pipelines_compiled": work[2] - _frame_work[2]})
		_frame_work = work
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
		main.entities.buffer.reset_diagnostics()
		main.entities.buffer.timeline.clear()
		main.entities.buffer.record_timeline = true  # M7: every state's arrival, server time and tile status
		for key in ["lamp_reassigned", "lamp_moved_lit", "lamp_lights_max", "lamps_offered_max"]:
			perf.counters.erase(key)
	elif _elapsed > TIMEOUT_S:
		_write({"status": "failed", "errors": ["not ready after %d s" % TIMEOUT_S] + _missing})
		main.get_tree().quit(1)


## A recorded plan displayed by the existing indoor controller; server entry stays untouched.
func _show_indoor_hint() -> void:
	var fixture: Dictionary = scenario["indoor_hint"]
	var plans: Array = JSON.parse_string(FileAccess.get_file_as_string("res://tests/data/home_plans.json"))
	_indoor_hint = preload("res://home_first_person.gd").new()
	_indoor_hint.language = fixture["language"]
	_indoor_hint._recenter_mouse = false
	main.add_child(_indoor_hint)
	if not _indoor_hint.enter(plans[int(fixture["plan_index"])]):
		return
	_indoor_hint.release_mouse()
	_indoor_hint.is_home = false
	_indoor_draws = 0


func _indoor_hint_readiness() -> Array:
	var missing := []
	var requested := Vector2(scenario["resolution"][0], scenario["resolution"][1])
	if OS.get_user_data_dir().get_file() != str(scenario.get("verification_user_dir", "")):
		missing.append("indoor verification is not using isolated player settings")
	if main.get_viewport().get_visible_rect().size != requested:
		missing.append("indoor viewport size does not match scenario")
	if not is_instance_valid(_indoor_hint) or not _indoor_hint.visible or not is_instance_valid(_indoor_hint.player):
		return missing + ["indoor fixture not entered"]
	var view = _indoor_hint
	if not view.player.camera.current or view._viewport.get_camera_3d() != view.player.camera:
		missing.append("existing indoor camera not current")
	var surfaces: Array = view._viewport.find_children("Surfaces", "MeshInstance3D", true, false)
	if surfaces.is_empty() or surfaces[0].mesh == null or surfaces[0].mesh.get_surface_count() == 0 or surfaces[0].mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX].is_empty():
		missing.append("no loaded nonempty interior geometry")
	if not view.player.is_on_floor() or absf(view.player.position.y) > 0.03:
		missing.append("indoor player not settled on its floor")
	if not view.at_exit() or view.is_home or view.player.controls_enabled:
		missing.append("indoor longest hint state not active")
	var expected: String = view.T.text("home_first_person_hint", view.language)
	for key in ["house_leave_prompt", "home_choose_hint", "home_mouse_resume"]:
		expected += " · " + view.T.text(key, view.language)
	var hint: Label = view._hint
	if hint.text != expected or not hint.is_visible_in_tree():
		missing.append("complete localized indoor hint not shown")
	var rect := hint.get_global_rect()
	if rect.position.x < 12.0 or rect.end.x > requested.x - 12.0 + 0.1 or rect.position.y < 0.0 or rect.end.y > requested.y - 12.0 + 0.1:
		missing.append("indoor hint exceeds viewport margins")
	if hint.get_visible_line_count() != hint.get_line_count() or hint.size.y + 0.1 < hint.get_minimum_size().y:
		missing.append("indoor hint lines clipped")
	if _indoor_draws < 3:
		missing.append("indoor draws not completed")
	return missing


func _indoor_hint_result() -> Dictionary:
	var view = _indoor_hint
	var rect: Rect2 = view._hint.get_global_rect()
	return {"fixture": scenario["indoor_hint"], "language": view.language,
		"text": view._hint.text, "line_count": view._hint.get_line_count(),
		"visible_lines": view._hint.get_visible_line_count(),
		"hint_rect": [rect.position.x, rect.position.y, rect.size.x, rect.size.y],
		"on_floor": view.player.is_on_floor(), "camera": "HomeFirstPerson/HomePlayer3D",
		"camera_position": [view.player.camera.global_position.x, view.player.camera.global_position.y, view.player.camera.global_position.z],
		"completed_draw_frames": _indoor_draws, "verification_user_data_dir": OS.get_user_data_dir(), "readiness": _indoor_hint_readiness()}


## Display-only HUD fixtures leave the authoritative simulation state and commands untouched.
func _show_hud_fixture() -> void:
	if not _hud_configured:
		main.get_window().mode = Window.MODE_WINDOWED
		main.get_window().size = Vector2i(scenario["resolution"][0], scenario["resolution"][1])
		main.hud.layout = preload("res://hud_layout.gd").new(false)
		_hud_configured = true
	var state: Dictionary = main.entities.shown_state().duplicate(true)
	if state.is_empty():
		return
	var taxi: Dictionary = state.get("taxi", {})
	taxi.erase("live_fare_cents")
	taxi.erase("fuel_station_price_cents")
	taxi.erase("refueling")
	taxi["notification_timer"] = 0.0
	state["taxi"] = taxi
	state["on_foot"] = false
	state["home_door"] = {}
	state["interaction"] = {}
	state["data_source_notice"] = ""
	state["player"]["engine_on"] = true
	match scenario["hud_fixture"]:
		"fare":
			taxi.merge({"live_fare_cents":12345,"fare_distance_m":8200}, true)
		"fuel_stop":
			taxi["fuel_station_price_cents"] = 189
			state["player"]["speed"] = 2.0
		"house_hint":
			state["on_foot"] = true
			state["home_door"] = {"available":true,"is_home":false}
	main.hud.show_state(state)
	var text: Dictionary = main.hud.values(state, {}, main.hud.language)
	_hud_expected = text["start_hint"] if scenario["hud_fixture"] == "fuel_stop" else text["hint"]


func _hud_readiness() -> Array:
	var missing := []
	var screen := main.get_viewport().get_visible_rect()
	if screen.size != Vector2(scenario["resolution"][0], scenario["resolution"][1]):
		missing.append("HUD viewport does not match requested resolution")
	if not _hud_configured:
		missing.append("HUD fixture not configured")
		return missing
	var hud: Control = main.hud
	if scenario["hud_fixture"] == "fare":
		var meter: Rect2 = hud._meter.get_global_rect()
		if not hud._meter.visible or hud._meter.cents != 12345 or hud._meter.info != hud.meter_info({"fare_distance_m":8200}):
			missing.append("live fare meter fixture not visible")
		if not screen.encloses(meter):
			missing.append("fare meter clipped")
		for label: Label in [hud._money, hud._clock, hud._weather]:
			if meter.intersects(label.get_global_rect()):
				missing.append("fare meter intersects " + label.name)
	else:
		var label: Label = hud._notice if scenario["hud_fixture"] == "fuel_stop" else hud._hint
		if _hud_expected == "" or label.text != _hud_expected or not label.visible:
			missing.append("exact HUD fixture text not visible")
		if not Rect2(Vector2(20,0),screen.size-Vector2(40,0)).encloses(label.get_global_rect()):
			missing.append("HUD fixture text clipped")
		if scenario["hud_fixture"] == "house_hint" and label.get_global_rect().end.y + 4 > hud.osm_credit.get_global_rect().position.y:
			missing.append("HUD hint overlaps attribution")
	if not hud.osm_credit.visible or not screen.encloses(hud.osm_credit.get_global_rect()):
		missing.append("OSM attribution clipped or hidden")
	return missing


func _hud_result() -> Dictionary:
	var rectangles := {}
	for name in ["_meter", "_money", "_clock", "_weather", "_notice", "_hint", "osm_credit"]:
		var node: Control = main.hud.get(name)
		var rect := node.get_global_rect()
		rectangles[name] = [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
	return {"fixture":scenario["hud_fixture"], "expected_text":_hud_expected, "rectangles":rectangles, "readiness":_hud_readiness()}


var _animals_placed := false


## "animals": [[species, x, y, heading], ...] (server axes; "rider" a person on a horse, "walker" one walking in place):
## held still in view as wildlife records (no vehicle reactions), once the server state is in.
func _place_animals() -> void:
	if main.entities.shown_state().is_empty():
		return
	main.wildlife.vehicle_reactions = false
	var riders := []
	for row: Array in scenario["animals"]:
		var at := MapMath.point(main.entities.origin, row[1], row[2])
		if row[0] in ["rider", "walker"]:
			riders.append({"id": "%s_%d" % [row[0], riders.size()], "x": float(row[1]), "y": float(row[2]), "heading": float(row[3]),
				"animation_state": "riding" if row[0] == "rider" else "walking", "color": [40, 70, 140], "radius_m": 0.45})
			if row[0] == "walker":
				riders[-1]["pose"] = "walk_2"  # held mid-stride (a high-swing phase)
			if row.size() > 4:
				riders[-1]["costume"] = row[4]  # optional 5th field: "santa" / "elf"
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
		main.entities.extra_pedestrians.append({"id": "bench_sitter", "x": float(o[0]), "y": float(o[1]), "heading": float(o[3]) - PI / 2.0,
			"animation_state": "sitting", "color": [200, 110, 20], "radius_m": 0.45})


## What the scenario needs and the scene does not show yet ([] when ready).
func check() -> Array:
	var state: Dictionary = main.entities.shown_state()
	if state.is_empty():
		return ["no state from the server yet"]
	var missing := _hud_readiness() if scenario.has("hud_fixture") else []
	var pose: Array = scenario["pose"]
	var player: Dictionary = state.get("player", {})
	var at := Vector2(float(player.get("x", INF)), float(player.get("y", INF)))
	var walking := scenario.has("walk")
	if scenario.has("bench_sitter") and not main.entities.extra_pedestrians.any(func(p): return p["id"] == "bench_sitter"):
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
		if not state.get("on_foot", false) or (main.walk_eye or main.walk_chase) == bool(scenario["walk"].get("top_down", false)):
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
	if scenario.get("requires", {}).get("route_3d", false) and (main.map_layer.buildings_3d == null or not main.map_layer.buildings_3d.route_3d.visible):
		missing.append("no navigation route in the 3D view yet")
	if scenario.get("requires", {}).get("phone_offers", false) and (not main.phone.is_open or main.phone.items.is_empty()):
		missing.append("no ride offers on the open phone yet")
	if _switch_i < scenario.get("switch", []).size():
		missing.append("still switching cameras")
	var wanted: String = scenario["switch"][-1] if scenario.has("switch") else scenario.get("camera", "")
	if wanted != "" and (main.camera_modes.mode != main.camera_modes.KEYS[CAMERA[wanted]] or main._windshield.visible != (wanted != "top")
			or (main.map_layer.buildings_3d != null and main.map_layer.buildings_3d.chase_on != (wanted == "third"))):
		missing.append("camera %s not shown yet" % wanted)
	if scenario.get("requires", {}).has("lake_ice_holds") and calendar.get("lake_ice_holds", null) != scenario["requires"]["lake_ice_holds"]:
		missing.append("lake_ice_holds %s (%s cm), the scenario needs %s" % [calendar.get("lake_ice_holds", "?"), calendar.get("lake_ice_cm", "?"), scenario["requires"]["lake_ice_holds"]])
	if scenario.get("requires", {}).has("animals_in_view"):
		var view: Rect2 = main.get_viewport().get_canvas_transform().affine_inverse() * main.get_viewport().get_visible_rect()
		var seen: int = main.wildlife.animals.filter(func(a): return view.has_point(a["position"])).size()
		_counts["animals_in_view"] = seen
		if seen < int(scenario["requires"]["animals_in_view"]):
			missing.append("%d animals in view, the scenario needs %d" % [seen, scenario["requires"]["animals_in_view"]])
	if scenario.get("requires", {}).has("carts_in_view"):  # shoppers pushing a cart within 25 m (supermarket-shoppers.md)
		var shop_at := Vector2(float(scenario["pose"][0]), float(scenario["pose"][1]))
		var seen: int = main.entities.shown_state().get("pedestrians", []).filter(
			func(p): return p.get("cart", false) and shop_at.distance_to(Vector2(float(p["x"]), float(p["y"]))) < 25.0).size()
		_counts["carts_in_view"] = seen
		if seen < int(scenario["requires"]["carts_in_view"]):
			missing.append("%d carts in view, the scenario needs %d" % [seen, scenario["requires"]["carts_in_view"]])
	if scenario.get("requires", {}).get("dem_ground", false):  # DEM terrain loaded under the taxi; the camera rides on it
		var ground: float = main.map_layer.deck_height(main.entities.player_position(), 0)
		_counts["dem_ground_m"] = ground
		if ground == 0.0:
			missing.append("no DEM ground under the vehicle (terrain switch off or no dem80/)")
		elif not is_equal_approx(main.map_layer.buildings_3d.ground_elevation, ground):
			missing.append("camera ground offset %.2f m, the ground is %.2f m" % [main.map_layer.buildings_3d.ground_elevation, ground])
	if scenario.get("requires", {}).has("notice_contains"):  # a HUD notice showing this text, wholly on screen
		var notice: Label = main.hud._notice
		# Held like the game clock (--test-time-scale 0): its ~15 s run in wall time, while 60 ready
		# frames at a loaded llvmpipe's ~2 fps take 30 s. Its timing is tested in tests/run_tests.gd.
		if main.hud._source_notice_until > 0:
			main.hud._source_notice_until = Time.get_ticks_msec() + 15000
		if not (notice.visible and str(scenario["requires"]["notice_contains"]) in notice.text):
			missing.append("HUD notice with \"%s\" not shown" % scenario["requires"]["notice_contains"])
		elif not main.get_viewport().get_visible_rect().encloses(notice.get_global_rect()):
			missing.append("HUD notice clipped by the screen edge")
	return missing


## Chunks under the view loaded and built, the required lamps and buildings in view.
func _check_map(centre: Vector2) -> Array:
	var missing := []
	if not main._chunk_queue.is_empty():
		missing.append("%d chunks still queued" % main._chunk_queue.size())
	# Before measuring only (a drive crosses tiles while measuring): the server still streams
	# the outer chunks a while after the view is covered; wait until none came for a moment.
	var arrived: int = main.map_layer.chunk_count() + main._chunk_queue.size()
	if arrived != _chunks_seen:
		_chunks_seen = arrived
		_chunks_changed_msec = Time.get_ticks_msec()
	if not _measuring and Time.get_ticks_msec() - _chunks_changed_msec < 1500:
		missing.append("chunks still arriving")
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
				if chunk._building_task >= 0 or chunk._forest_task >= 0 or chunk._lamp_task >= 0:
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
		if scenario.has("windscreen_model") or scenario.has("two_wheeler_model"): continue  # checked below against its actual pooled mesh, not a 3.5 m truck envelope
		boxes.append([npc["vehicle_type"], _corners(npc["x"], npc["y"], npc["heading"], npc["length_m"], npc["width_m"])])
		if npc.has("trailer"):
			var t: Array = npc["trailer"]
			boxes.append(["caravan", _corners(t[0], t[1], t[2], t[3], t[4])])
	for train in main.entities.extra_trains:
		if scenario.get("coach_roof_vent", false): continue  # exact pooled roof bounds checked below
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
	var coaster := {}
	if scenario.has("coaster_seam") or scenario.has("carousel_supports") or scenario.has("swing_supports") or scenario.has("ferris_supports"):
		var ferris := scenario.has("ferris_supports")
		var swing := scenario.has("swing_supports")
		var carousel := scenario.has("carousel_supports") or swing
		var kind := "ferris_wheel" if ferris else "swing_carousel" if swing else "carousel" if carousel else "roller_coaster"
		var target: Array = scenario["ferris_supports" if ferris else "swing_supports" if swing else "carousel_supports" if carousel else "coaster_seam"]
		if target.size()!=3: return missing+["mapped attraction target needs coordinates and path count"]
		var layer = layer_3d_view()
		var found := false
		for chunk in main.map_layer._chunks.values():
			if layer==null or camera_3d==null: break
			for row: Array in chunk._data.get("attractions", []):
				if row[0] != kind or row[1].is_empty(): continue
				if Vector2(row[1][0][0],row[1][0][1]).distance_to(Vector2(target[0],target[1])) > 0.1: continue
				var loop := PackedVector2Array()
				for point: Array in row[1]: loop.append(MapMath.point(chunk._origin,point[0],point[1]))
				if loop.size() != int(target[2]) or not loop[0].is_equal_approx(loop[-1]):
					missing.append(("carousel " if carousel else "coaster ")+"path differs from expected closed loop")
					continue
				var wanted_path: Array = scenario.get("ferris_path" if ferris else "swing_path" if swing else "carousel_path" if carousel else "coaster_path",[])
				if wanted_path.size() != row[1].size():
					missing.append(("carousel " if carousel else "coaster ")+"path has wrong samples")
					continue
				elif not wanted_path.all(func(point):return point is Array and point.size()==2 and (point[0] is float or point[0] is int) and (point[1] is float or point[1] is int)):
					missing.append("mapped attraction path has malformed samples")
					continue
				else:
					for i in wanted_path.size():
						if Vector2(float(wanted_path[i][0])-float(row[1][i][0]),float(wanted_path[i][1])-float(row[1][i][1])).length()>0.001: missing.append(("carousel " if carousel else "coaster ")+"path sample differs from mapped source")
				var expected := {"deck":PackedVector3Array(),"deck_colors":PackedColorArray()}
				Buildings3D.attractions(expected,[[kind,loop]])
				for i in expected.deck.size(): expected.deck[i].y += Buildings3D.ground_height(chunk.ground_heights,Vector2(expected.deck[i].x,expected.deck[i].z))
				for mesh: MeshInstance3D in chunk.meshes_3d:
					if mesh.material_override != Buildings3D._shared["ground"] or mesh.mesh == null: continue
					if not _coaster_mesh_vertices.has(mesh.mesh):
						var faces := Array(mesh.mesh.get_faces())
						_coaster_mesh_vertices[mesh.mesh] = Array(expected.deck).all(func(w): return faces.any(func(v): return v.distance_squared_to(w)<0.000001))
					if not _coaster_mesh_vertices[mesh.mesh]: continue
					found = true
					if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer==null or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not mesh.is_visible_in_tree() or mesh.layers & camera_3d.cull_mask==0: missing.append(("carousel " if carousel else "coaster ")+"3D view not actively displayed")
					var track := PackedVector3Array()
					for i in expected.deck.size():
						if expected.deck_colors[i]==Color8(211,70,55): track.append(expected.deck[i])
					var seam := []
					if carousel:
						var ride_centre := Vector2.ZERO
						for i in loop.size()-1: ride_centre += loop[i]/(loop.size()-1)
						var inward := (ride_centre-loop[0]).normalized()
						for at:Vector2 in [loop[0]-Vector2(0.6,0.6),loop[0]+Vector2(0.6,0.6),loop[0]+inward*1.0]:
							for height:float in [0.75,0.9,1.6]:
								seam.append(mesh.global_transform*Buildings3D.to_3d(at,height+Buildings3D.ground_height(chunk.ground_heights,at)))
					elif not ferris:
						for point: Vector3 in track.slice(0,6)+track.slice(track.size()-6): seam.append(mesh.global_transform*point)
					if ferris:
						var ride_centre:=Vector2.ZERO
						for i in loop.size()-1:ride_centre+=loop[i]/(loop.size()-1)
						var far:=loop[0]
						for point:Vector2 in loop:
							if point.distance_to(ride_centre)>far.distance_to(ride_centre):far=point
						var radius:=maxf(far.distance_to(ride_centre),3.0)
						var axis:=(far-ride_centre).normalized();var normal:=Buildings3D.to_3d(axis.orthogonal())
						var hub:=Buildings3D.to_3d(ride_centre,radius+2.0)
						var tip:=Buildings3D.to_3d(ride_centre+axis*radius*(1.0+cos(TAU/16.0))*0.5,radius+2.0+radius*sin(TAU/16.0)*0.5+0.1)
						for point:Vector3 in [tip+normal*0.06,hub.lerp(tip,0.5)+normal*0.06,hub+normal*0.5+Buildings3D.to_3d(axis)*0.15+Vector3.UP*0.15]:
							point.y+=Buildings3D.ground_height(chunk.ground_heights,Vector2(point.x,point.z))
							seam.append(mesh.global_transform*point)
						if absf(normal.dot((camera_3d.global_position-seam[1]).normalized()))<0.35:missing.append("Ferris wheel viewed edge-on")
						for side:float in [-1.0,1.0]:
							var foot:=ride_centre+axis.orthogonal()*2.0*side-axis*3.0
							if absf((mesh.global_transform*Buildings3D.to_3d(foot,Buildings3D.ground_height(chunk.ground_heights,foot))).y-main.map_layer.deck_height(foot,0,false))>0.005:missing.append("Ferris wheel foot buried or floating")
						if not _felled_occluders.has(mesh.mesh):_felled_occluders[mesh.mesh]=mesh.mesh.generate_triangle_mesh()
						var inverse:=mesh.global_transform.affine_inverse()
						for point:Vector3 in seam:
							var end:=point+(camera_3d.global_position-point).normalized()*0.08
							if not _felled_occluders[mesh.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*end).is_empty():missing.append("Ferris spoke/rim/axle contact hidden by ride geometry")
					if swing:
						var ride_centre := Vector2.ZERO
						for i in loop.size()-1: ride_centre += loop[i]/(loop.size()-1)
						seam.clear()
						var upper := ride_centre+(loop[0]-ride_centre)*0.4
						for t:float in [0.0,0.5,1.0]:
							var at:Vector2=loop[0].lerp(upper,t)
							seam.append(mesh.global_transform*Buildings3D.to_3d(at,lerpf(3.6,7.0,t)+Buildings3D.ground_height(chunk.ground_heights,at)))
						if not _felled_occluders.has(mesh.mesh): _felled_occluders[mesh.mesh]=mesh.mesh.generate_triangle_mesh()
						var inverse:=mesh.global_transform.affine_inverse()
						for point:Vector3 in seam:
							var end:=point+(camera_3d.global_position-point).normalized()*0.08
							if not _felled_occluders[mesh.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*end).is_empty():missing.append("swing seat/hanger/canopy contact hidden by ride geometry")
						for side:float in [-1.0,1.0]:
							seam.append(seam[0]+Vector3(0,0,0.6*side))
							seam.append(seam[2]+Vector3(0,0,0.03*side))
					if carousel and not swing:
						# Reject a platform hidden under the ride's own canopy or another ground prop.
						if not _felled_occluders.has(mesh.mesh): _felled_occluders[mesh.mesh]=mesh.mesh.generate_triangle_mesh()
						var inverse := mesh.global_transform.affine_inverse()
						for point:Vector3 in [seam[2],seam[-2]]:
							var ray_hit:Dictionary=_felled_occluders[mesh.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*(point+Vector3.UP*0.002))
							if not ray_hit.is_empty():
								missing.append("carousel seat/support hidden behind ride geometry")
					var rect := Rect2(); var first := true
					for point: Vector3 in seam:
						if not camera_3d.is_position_in_frustum(point): missing.append(("carousel " if carousel else "coaster ")+"seam outside frustum")
						var pixel := camera_3d.unproject_position(point)
						rect = Rect2(pixel,Vector2.ZERO) if first else rect.expand(pixel); first=false
						if point.y-main.map_layer.deck_height(Vector2(point.x,point.z),0,false)<(0.7 if carousel else 3.0): missing.append(("carousel " if carousel else "coaster ")+"seam buried")
						for occluder in main.map_layer._chunks.values():
							for solid: MeshInstance3D in occluder.meshes_3d:
								if not solid.is_visible_in_tree() or solid.material_override!=Buildings3D._shared["material"] or solid.layers & camera_3d.cull_mask==0: continue
								if not _felled_occluders.has(solid.mesh): _felled_occluders[solid.mesh]=solid.mesh.generate_triangle_mesh()
								var inverse := solid.global_transform.affine_inverse()
								if not _felled_occluders[solid.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*point).is_empty(): missing.append(("carousel " if carousel else "coaster ")+"seam behind drawn building")
					if not Rect2(Vector2.ZERO,screen_size).encloses(rect) or rect.size.x<12 or rect.size.y<4: missing.append(("carousel " if carousel else "coaster ")+"seam too small or offscreen")
					for panel: Rect2 in hud:
						if panel.intersects(rect): missing.append(("carousel " if carousel else "coaster ")+"seam under HUD")
					var seam_centre: Vector3 = (seam[0]+seam[1])*0.5
					if not swing and not ferris and camera_3d.global_position.y<=seam_centre.y+1.0: missing.append(("carousel " if carousel else "coaster ")+"top face not visible")
					for other: MeshInstance3D in layer._cars_root.find_children("*","MeshInstance3D",true,false):
						if not other.is_visible_in_tree() or camera_3d.is_position_behind(other.global_position) or camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(seam_centre): continue
						var occupied := Rect2()
						for corner in 8:
							var pixel:=camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
							occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
						if occupied.intersects(rect): missing.append(("carousel " if carousel else "coaster ")+"seam obscured by nearer dynamic body")
					coaster={("support" if ferris else "seat" if carousel else "seam"):[row[1][0][0],row[1][0][1]],"path_points":loop.size(),"active_3d":true,("support_rect" if carousel or ferris else "seam_rect"):[rect.position.x,rect.position.y,rect.size.x,rect.size.y],"height_m":seam[2].y if ferris else 7.0 if swing else 0.9 if carousel else 4.5,"ground_m":Buildings3D.ground_height(chunk.ground_heights,loop[0]),"matched_vertices":expected.deck.size()}
		if not found: missing.append("expected mapped attraction path not drawn")
	var swing_glb := _check_swing_glb(camera_3d, screen_size, hud, missing) if scenario.has("swing_target") else {}
	var camp_pair := {}
	if scenario.has("caravan_with_car_target") or scenario.has("tent_target") or scenario.has("bicycle_parking_target") or scenario.has("picnic_table_target"):
		var picnic:=scenario.has("picnic_table_target")
		var tent:=scenario.has("tent_target")
		var rack:=scenario.has("bicycle_parking_target")
		var kind:="picnic_table" if picnic else "bicycle_parking" if rack else "tent" if tent else "caravan_with_car"
		var target:Array=scenario[kind+"_target"]
		var layer=layer_3d_view()
		var found:=false
		for chunk in main.map_layer._chunks.values():
			if layer==null or camera_3d==null:break
			for row:Array in chunk._data.get("scenery_objects",[]):
				if row[2]!=kind or Vector2(row[0],row[1]).distance_to(Vector2(target[0],target[1]))>0.1:continue
				if absf(angle_difference(float(row[3]),float(target[2])))>0.001:missing.append("camping combination has wrong heading")
				var at:=MapMath.point(chunk._origin,row[0],row[1])
				var expected:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()}
				Buildings3D.props(expected,[[at,float(row[3]),kind]])
				for i in expected.deck.size():expected.deck[i].y+=Buildings3D.ground_height(chunk.ground_heights,Vector2(expected.deck[i].x,expected.deck[i].z))
				for mesh:MeshInstance3D in chunk.meshes_3d:
					if mesh.material_override!=Buildings3D._shared["ground"] or mesh.mesh==null:continue
					if not _camp_pair_mesh_vertices.has(mesh.mesh):
						_camp_pair_mesh_vertices[mesh.mesh]=_camp_pair_matches(mesh.mesh.get_faces(),expected.deck)
					if not _camp_pair_mesh_vertices[mesh.mesh]:continue
					found=true
					if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not mesh.is_visible_in_tree() or mesh.layers & camera_3d.cull_mask==0:missing.append("camping combination 3D view not actively displayed")
					var placement:=Transform3D(Basis(Vector3.UP,float(row[3])),Buildings3D.to_3d(at))
					var bounds:=Rect2();var first:=true
					for v:Vector3 in expected.deck:
						var point:Vector3=mesh.global_transform*v
						if not camera_3d.is_position_in_frustum(point):missing.append("camping combination outside frustum");break
						var pixel:=camera_3d.unproject_position(point)
						bounds=Rect2(pixel,Vector2.ZERO) if first else bounds.expand(pixel);first=false
					for panel:Rect2 in hud:
						if panel.intersects(bounds):missing.append("camping combination under HUD")
					var feet:=[Vector3(-1.2,0,-1),Vector3(-1.2,0,1),Vector3(1.2,0,-1),Vector3(1.2,0,1)] if tent else []
					if picnic:
						for x:float in [-0.648,0.648]:
							for z:float in [-0.625,-0.275,0.275,0.625]:feet.append(Vector3(x,0,z))
					elif rack:
						for x:float in [-1.2,-0.4,0.4,1.2]:
							for side:float in [-1.0,1.0]:feet.append(Vector3(x,0,side*0.27))
					elif not tent:
						for axle:float in [-2.6,1.78,4.02]:
							for side:float in [-1.0,1.0]:feet.append(Vector3(axle,0,side*(1.14 if axle<0 else 0.781)))
					for local:Vector3 in feet:
						var foot:Vector3=placement*local
						foot.y+=Buildings3D.ground_height(chunk.ground_heights,Vector2(foot.x,foot.z))
						if absf((mesh.global_transform*foot).y-main.map_layer.deck_height(Vector2(foot.x,foot.z),0,false))>0.005:missing.append("camping base buried or floating")
					var regions:=[]
					var camp_regions:=[AABB(Vector3(1.2,0.03,-0.55),Vector3(0,0.92,1.1)),AABB(Vector3(-1.2,0.65,0),Vector3(2.4,0.65,0.5))] if tent else [AABB(Vector3(-4.6,2.4,-1.15),Vector3(4.8,0,2.3)),AABB(Vector3(2.2,1.5,-0.5),Vector3(0.8,0,1.0)),AABB(Vector3(0.3,0.5,-0.05),Vector3(0.7,0,0.1))]
					if picnic:
						var local_eye:Vector3=placement.affine_inverse()*(mesh.global_transform.affine_inverse()*camera_3d.global_position)
						var front:=1.0 if local_eye.x>0 else -1.0
						var side:=1.0 if local_eye.z>0 else -1.0
						camp_regions=[AABB(Vector3(front*0.91,0.06,-0.2),Vector3(0,0.27,0.4)),AABB(Vector3(front*0.648-0.035,0.25,minf(side*0.666,side*0.751)),Vector3(0.07,0.17,0.085)),AABB(Vector3(-0.8,0.751,-0.3),Vector3(1.6,0,0.6))]
					elif rack:
						var local_eye:Vector3=placement.affine_inverse()*(mesh.global_transform.affine_inverse()*camera_3d.global_position)
						var front:=1.231 if local_eye.x>0 else -1.231
						camp_regions=[AABB(Vector3(front,0.05,-0.175),Vector3(0,0.65,0.35)),AABB(Vector3(front,0.74,-0.3),Vector3(0,0.06,0.6))]
					for box:AABB in camp_regions:
						var rect:=Rect2();var points:=[]
						for corner in 8:
							var point:Vector3=placement*box.get_endpoint(corner)
							point.y+=Buildings3D.ground_height(chunk.ground_heights,Vector2(point.x,point.z))
							point=mesh.global_transform*point
							points.append(point)
							var pixel:=camera_3d.unproject_position(point)
							rect=Rect2(pixel,Vector2.ZERO) if corner==0 else rect.expand(pixel)
						if maxf(rect.size.x,rect.size.y)<8 or not Rect2(Vector2.ZERO,screen_size).encloses(rect):missing.append("camping car/caravan/hitch region too small or offscreen")
						var probe:Vector3=(points[0]+points[-1])*0.5
						for occluder in main.map_layer._chunks.values():
							for solid:MeshInstance3D in occluder.meshes_3d:
								if not solid.is_visible_in_tree() or solid.material_override not in [Buildings3D._shared["material"],Buildings3D._shared["ground"]] or solid.layers & camera_3d.cull_mask==0:continue
								if not _felled_occluders.has(solid.mesh):_felled_occluders[solid.mesh]=solid.mesh.generate_triangle_mesh()
								var inverse:=solid.global_transform.affine_inverse()
								var end:=probe+(camera_3d.global_position-probe).normalized()*0.02
								if not _felled_occluders[solid.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*end).is_empty():missing.append("camping region %d hidden by drawn geometry"%regions.size())
						for other:MeshInstance3D in layer._cars_root.find_children("*","MeshInstance3D",true,false):
							if not other.is_visible_in_tree() or camera_3d.is_position_behind(other.global_position) or camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(probe):continue
							var occupied:=Rect2()
							for corner in 8:
								var pixel:=camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
								occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
							if occupied.intersects(rect):missing.append("camping combination obscured by dynamic body")
						if picnic and regions.is_empty() and (rect.size.x<12 or rect.size.y<12):missing.append("picnic table opening too small or edge-on")
						if picnic and regions.size()==1 and minf(rect.size.x,rect.size.y)<2:missing.append("picnic seat/support contact too small")
						if rack and regions.is_empty() and (rect.size.x<12 or rect.size.y<12):missing.append("bicycle rack opening too small or edge-on")
						if rack and regions.size()==1 and minf(rect.size.x,rect.size.y)<1.0:missing.append("bicycle rack member thinner than one pixel")
						regions.append([rect.position.x,rect.position.y,rect.size.x,rect.size.y])
					camp_pair={"position":[row[0],row[1]],"angle":row[3],"active_3d":true,"region_rects":regions,"rect":[bounds.position.x,bounds.position.y,bounds.size.x,bounds.size.y],"matched_vertices":expected.deck.size(),"ground_m":Buildings3D.ground_height(chunk.ground_heights,at),"envelope_m":[1.8,1.5] if picnic else [3.0,0.6] if rack else [3.2,2.4] if tent else [9.4,2.5]}
		if not found:missing.append("expected mapped camping geometry not drawn")
	var crossbuck := {}
	if scenario.has("crossbuck_target"):
		var target: Array=scenario["crossbuck_target"]
		var layer=layer_3d_view()
		var found:=false
		for chunk in main.map_layer._chunks.values():
			for row: Array in chunk._data.get("scenery_objects",[]):
				if row[2]!="level_crossing" or Vector2(row[0],row[1]).distance_to(Vector2(target[0],target[1]))>0.1:continue
				if absf(angle_difference(float(row[3]),float(target[2])))>0.001:missing.append("mapped crossbuck has wrong road angle")
				var at:=MapMath.point(chunk._origin,row[0],row[1])
				var expected:={"deck":PackedVector3Array(),"deck_colors":PackedColorArray()}
				Buildings3D.props(expected,[[at,float(row[3]),"level_crossing"]])
				for i in expected.deck.size():expected.deck[i].y+=Buildings3D.ground_height(chunk.ground_heights,Vector2(expected.deck[i].x,expected.deck[i].z))
				for mesh: MeshInstance3D in chunk.meshes_3d:
					if mesh.material_override!=Buildings3D._shared["ground"] or mesh.mesh==null:continue
					if not _crossbuck_mesh_vertices.has(mesh.mesh):
						var faces:=Array(mesh.mesh.get_faces())
						_crossbuck_mesh_vertices[mesh.mesh]=Array(expected.deck).all(func(w):return faces.any(func(v):return v.distance_squared_to(w)<0.000001))
					if not _crossbuck_mesh_vertices[mesh.mesh]:continue
					found=true
					if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer==null or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not mesh.is_visible_in_tree() or mesh.layers & camera_3d.cull_mask==0:missing.append("crossbuck 3D view not actively displayed")
					var rects:=[]
					var along:=Vector3(cos(float(row[3])),0,-sin(float(row[3])))
					var across:=Vector2(cos(float(row[3])),-sin(float(row[3]))).orthogonal()
					for side: float in [-1.0,1.0]:
						var post:=at+across*side*4.0
						var ground: float=Buildings3D.ground_height(chunk.ground_heights,post)
						var board_centre:=mesh.global_transform*Buildings3D.to_3d(post,ground+2.225)
						if absf((camera_3d.global_position-board_centre).normalized().dot(along))<0.35:missing.append("crossbuck broad face viewed edge-on")
						if absf((mesh.global_transform*Buildings3D.to_3d(post,ground)).y-main.map_layer.deck_height(post,0,false))>0.005:missing.append("crossbuck post buried or floating")
						var rect:=Rect2();var first:=true
						for i in expected.deck.size():
							if expected.deck_colors[i]!=Color(235.0/255,235.0/255,235.0/255) or Vector2(expected.deck[i].x,expected.deck[i].z).distance_to(post)>1.0:continue
							var point: Vector3=mesh.global_transform*expected.deck[i]
							if not camera_3d.is_position_in_frustum(point):missing.append("crossbuck board outside frustum")
							var pixel:=camera_3d.unproject_position(point)
							rect=Rect2(pixel,Vector2.ZERO) if first else rect.expand(pixel);first=false
						if first or not Rect2(Vector2.ZERO,screen_size).encloses(rect) or minf(rect.size.x,rect.size.y)<18:missing.append("crossbuck boards too small or offscreen")
						for panel: Rect2 in hud:
							if panel.intersects(rect):missing.append("crossbuck under HUD")
						for occluder in main.map_layer._chunks.values():
							for solid: MeshInstance3D in occluder.meshes_3d:
								if not solid.is_visible_in_tree() or solid.material_override!=Buildings3D._shared["material"] or solid.layers & camera_3d.cull_mask==0:continue
								if not _felled_occluders.has(solid.mesh):_felled_occluders[solid.mesh]=solid.mesh.generate_triangle_mesh()
								var inverse:=solid.global_transform.affine_inverse()
								if not _felled_occluders[solid.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*board_centre).is_empty():missing.append("crossbuck behind drawn building")
						for other: MeshInstance3D in layer._cars_root.find_children("*","MeshInstance3D",true,false):
							if not other.is_visible_in_tree() or camera_3d.is_position_behind(other.global_position) or camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(board_centre):continue
							var occupied:=Rect2()
							for corner in 8:
								var pixel:=camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
								occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
							if occupied.intersects(rect):missing.append("crossbuck obscured by nearer dynamic body")
						rects.append([rect.position.x,rect.position.y,rect.size.x,rect.size.y])
					crossbuck={"position":[row[0],row[1]],"angle":row[3],"active_3d":true,"board_rects":rects,"ground_m":Buildings3D.ground_height(chunk.ground_heights,at),"matched_vertices":expected.deck.size()}
		if not found:missing.append("expected mapped crossbuck not drawn")
	var tower := {}
	if scenario.has("power_tower_target"):
		var target: Array = scenario["power_tower_target"]
		var layer = layer_3d_view()
		var found := false
		for chunk in main.map_layer._chunks.values():
			for row: Array in chunk._data.get("scenery_objects", []):
				if row[2] != "power_tower" or Vector2(row[0],row[1]).distance_to(Vector2(target[0],target[1])) > 0.1: continue
				var height: float = row[4] if row.size() > 4 else Buildings3D.PROPS.power_tower[2]
				if absf(height-float(target[2]))>0.001: missing.append("mapped power tower has wrong height")
				var at := MapMath.point(chunk._origin,row[0],row[1])
				var expected := {"deck":PackedVector3Array(),"deck_colors":PackedColorArray()}
				Buildings3D.props(expected,[[at,float(row[3]),"power_tower",height]])
				for i in expected.deck.size(): expected.deck[i].y += Buildings3D.ground_height(chunk.ground_heights,Vector2(expected.deck[i].x,expected.deck[i].z))
				for mesh: MeshInstance3D in chunk.meshes_3d:
					if mesh.material_override != Buildings3D._shared["ground"] or mesh.mesh == null: continue
					if not _tower_mesh_vertices.has(mesh.mesh):
						var faces := Array(mesh.mesh.get_faces())
						_tower_mesh_vertices[mesh.mesh]=Array(expected.deck).all(func(w): return faces.any(func(v): return v.distance_squared_to(w)<0.000001))
					if not _tower_mesh_vertices[mesh.mesh]: continue
					found=true
					if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer==null or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not mesh.is_visible_in_tree() or mesh.layers & camera_3d.cull_mask==0:
						missing.append("power tower 3D view is not actively displayed")
					var rect := Rect2()
					for i in expected.deck.size():
						var point: Vector3 = mesh.global_transform*expected.deck[i]
						if not camera_3d.is_position_in_frustum(point): missing.append("power tower outside frustum")
						var pixel := camera_3d.unproject_position(point)
						rect=Rect2(pixel,Vector2.ZERO) if i==0 else rect.expand(pixel)
					if not Rect2(Vector2.ZERO,screen_size).encloses(rect) or rect.size.x<75 or rect.size.y<75: missing.append("power tower too small or offscreen")
					for panel: Rect2 in hud:
						if panel.intersects(rect): missing.append("power tower under HUD")
					var joint_pixels := INF
					for corner: Vector2 in [Vector2(-1,-1),Vector2(1,-1),Vector2(1,1),Vector2(-1,1)]:
						var foot := at+corner*2.0
						var ground: float=Buildings3D.ground_height(chunk.ground_heights,foot)
						var rendered_foot := mesh.global_transform*Buildings3D.to_3d(foot,ground)
						if absf(rendered_foot.y-main.map_layer.deck_height(foot,0,false))>0.005: missing.append("power tower foot buried or floating")
						for fraction: float in [1.0/3.0,2.0/3.0]:
							var joint := mesh.global_transform*Buildings3D.to_3d(at+corner*(2.0-1.2*fraction),ground+height*fraction)
							joint_pixels=minf(joint_pixels,camera_3d.unproject_position(joint).distance_to(camera_3d.unproject_position(joint+Vector3(0.24,0,0.24))))
							for occluder in main.map_layer._chunks.values():
								for solid: MeshInstance3D in occluder.meshes_3d:
									if not solid.is_visible_in_tree() or solid.material_override!=Buildings3D._shared["material"] or solid.layers & camera_3d.cull_mask==0: continue
									if not _felled_occluders.has(solid.mesh): _felled_occluders[solid.mesh]=solid.mesh.generate_triangle_mesh()
									var inverse := solid.global_transform.affine_inverse()
									if not _felled_occluders[solid.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*joint).is_empty(): missing.append("power tower joint behind drawn building")
					if joint_pixels<2.0: missing.append("power tower leg joints too small")
					for other: MeshInstance3D in layer._cars_root.find_children("*","MeshInstance3D",true,false):
						if not other.is_visible_in_tree() or camera_3d.is_position_behind(other.global_position) or camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(mesh.global_transform*Buildings3D.to_3d(at,height*0.5)): continue
						var occupied := Rect2()
						for corner in 8:
							var pixel := camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
							occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
						if occupied.intersects(rect): missing.append("power tower obscured by nearer dynamic body")
					tower={"position":[row[0],row[1]],"height_m":height,"active_3d":true,"rect":[rect.position.x,rect.position.y,rect.size.x,rect.size.y],"joint_width_px":joint_pixels,"ground_m":Buildings3D.ground_height(chunk.ground_heights,at),"matched_vertices":expected.deck.size()}
		if not found: missing.append("expected mapped power tower not drawn")
	var felled := {}
	if scenario.has("felled_tree"):
		var target: Array = scenario["felled_tree"]
		var key := MapChunkScript.obstacle_key(target[0],target[1])
		var layer = layer_3d_view()
		var found := false
		for chunk in main.map_layer._chunks.values():
			if not chunk._fallen.has(key) or not chunk._dynamic_3d.has("trees"): continue
			if absf(float(chunk._fallen[key])-float(target[2]))>0.001: missing.append("felled tree has wrong angle")
			var at := MapMath.point(chunk._origin,target[0],target[1])
			var rows := []
			for tree: Array in chunk._data.get("trees",[]):
				if MapChunkScript.obstacle_key(tree[0],tree[1])!=key: continue
				var row: Array=chunk._tree_row(str(tree[2]),float(tree[3]))
				row[0]=at; row[5]=float(target[2]); rows.append(row)
			if rows.is_empty(): continue
			var expected := Buildings3D.tree_parts(rows,PackedVector2Array(),chunk.ground_heights)
			var rects := []
			for name: String in ["trunk","crown"]:
				var matched := false
				for batch: MultiMeshInstance3D in chunk._dynamic_3d.trees.get_children():
					if batch.multimesh.mesh!=Buildings3D._tree_mesh(name): continue
					for i in batch.multimesh.instance_count:
						var xf := batch.global_transform*batch.multimesh.get_instance_transform(i)
						var want: Transform3D=expected[name][0][0]
						if not xf.is_equal_approx(want): continue
						matched=true
						if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer==null or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not batch.is_visible_in_tree() or batch.layers & camera_3d.cull_mask==0:
							missing.append("felled tree 3D view is not actively displayed")
						var rect:=Rect2()
						var lowest:=INF
						for vertex: Vector3 in batch.multimesh.mesh.get_faces(): lowest=minf(lowest,(xf*vertex).y)
						var ground: float=Buildings3D.ground_height(chunk.ground_heights,at)
						if lowest<ground-0.005 or lowest>ground+0.005: missing.append("felled tree buried or floating")
						for corner in 8:
							var point:=xf*batch.multimesh.mesh.get_aabb().get_endpoint(corner)
							if not camera_3d.is_position_in_frustum(point): missing.append("felled tree outside frustum")
							var pixel:=camera_3d.unproject_position(point)
							rect=Rect2(pixel,Vector2.ZERO) if corner==0 else rect.expand(pixel)
						if rect.size.length()<(45 if name=="trunk" else 55): missing.append("felled tree %s too small" % name)
						for panel: Rect2 in hud:
							if panel.intersects(rect): missing.append("felled tree under HUD")
						for occluder in main.map_layer._chunks.values():
							for solid: MeshInstance3D in occluder.meshes_3d:
								if not solid.is_visible_in_tree() or solid.material_override!=Buildings3D._shared["material"] or solid.layers & camera_3d.cull_mask==0: continue
								if not _felled_occluders.has(solid.mesh): _felled_occluders[solid.mesh]=solid.mesh.generate_triangle_mesh()
								var inverse:=solid.global_transform.affine_inverse()
								var hit: Dictionary=_felled_occluders[solid.mesh].intersect_segment(inverse*camera_3d.global_position,inverse*xf.origin)
								if not hit.is_empty(): missing.append("felled tree sightline crosses drawn building")
						for other: MeshInstance3D in layer._cars_root.find_children("*","MeshInstance3D",true,false):
							if not other.visible or camera_3d.is_position_behind(other.global_position) or camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(xf.origin): continue
							var occupied:=Rect2()
							for corner in 8:
								var pixel:=camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
								occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
							if occupied.intersects(rect): missing.append("felled tree obscured by nearer dynamic body")
						rects.append([rect.position.x,rect.position.y,rect.size.x,rect.size.y])
				if not matched: missing.append("expected felled %s instance not drawn" % name)
			found=rects.size()==2
			if found: felled={"key":key,"angle":target[2],"active_3d":true,"kind":rows[0][1],"radius_m":rows[0][2],"ground_m":Buildings3D.ground_height(chunk.ground_heights,at),"trunk_rect":rects[0],"crown_rect":rects[1]}
		if not found: missing.append("expected mapped felled tree not drawn")
	var fox := {}
	if scenario.get("fox_orientation", false):
		var target: Array = scenario["animals"][0]
		var local := MapMath.point(main.entities.origin, float(target[1]), float(target[2]))
		var layer = layer_3d_view()
		var found := false
		for key: String in ([] if layer == null else layer._animal_rows.keys()):
			if not key.begins_with("a|fox|"): continue
			if not key.ends_with("|stand|1.00|1"): missing.append("fox target has wrong pose/size/detail")
			var node: MultiMeshInstance3D = layer._animal_batches[key]
			for i in node.multimesh.visible_instance_count:
				var xf := node.global_transform * node.multimesh.get_instance_transform(i)
				if Vector2(xf.origin.x,xf.origin.z).distance_to(local)>0.1: continue
				found = true
				if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not node.is_visible_in_tree() or node.layers & camera_3d.cull_mask==0:
					missing.append("fox target 3D view is not actively displayed")
				var forward := Vector3(cos(float(target[3])),0,-sin(float(target[3])))
				if xf.basis.x.dot(forward)<0.999: missing.append("fox instance has wrong heading")
				var box := node.multimesh.mesh.get_aabb()
				var ground: float = main.map_layer.deck_height(local,0,false)
				if absf(xf.origin.y+box.position.y-ground)>0.05: missing.append("fox target not standing on visible ground")
				var rects := []
				for bounds: AABB in [box, AABB(Vector3(0.20,0.35,-0.12),Vector3(0.23,0.25,0.24))]:
					var rect := Rect2()
					for corner in 8:
						var point := xf*bounds.get_endpoint(corner)
						if not camera_3d.is_position_in_frustum(point): missing.append("fox target outside frustum")
						var pixel := camera_3d.unproject_position(point)
						rect=Rect2(pixel,Vector2.ZERO) if corner==0 else rect.expand(pixel)
					rects.append(rect)
				if rects[0].size.y<60 or minf(rects[1].size.x,rects[1].size.y)<15: missing.append("fox target/head too small")
				for panel: Rect2 in hud:
					if panel.intersects(rects[0]): missing.append("fox target under HUD")
				for footprint: PackedVector2Array in footprints:
					for step in 17:
						var sight := Vector2(camera_3d.global_position.x,camera_3d.global_position.z).lerp(local,step/16.0)
						if Geometry2D.is_point_in_polygon(sight,footprint): missing.append("fox target sightline crosses building")
				for other: MeshInstance3D in layer._cars_root.find_children("*","MeshInstance3D",true,false):
					if not other.visible or camera_3d.is_position_behind(other.global_position): continue
					if camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(xf.origin): continue
					var occupied:=Rect2()
					for corner in 8:
						var pixel:=camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
						occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
					if occupied.intersects(rects[1]): missing.append("fox head obscured by nearer dynamic body")
				fox={"species":"fox","heading":target[3],"pose":"stand","active_3d":true,"ground_m":ground,"model_y_m":xf.origin.y,
					"rect":[rects[0].position.x,rects[0].position.y,rects[0].size.x,rects[0].size.y],"head_rect":[rects[1].position.x,rects[1].position.y,rects[1].size.x,rects[1].size.y]}
		if not found: missing.append("expected fox instance not drawn")
	var reflective := {}
	if scenario.get("reflective_strips", false):
		var target: Dictionary = main.entities.extra_pedestrians[0]
		var local := MapMath.point(main.entities.origin, float(target.x), float(target.y))
		var layer = layer_3d_view()
		var key := "p|%s|standing_1|1.00||4|0|1|0|0" % Color8(65,125,190).to_html(false)
		if absi(hash(target.id)) % 8 != 4: missing.append("reflective target is not clothing variant 4")
		var found := false
		for pair: Array in ([] if layer == null else layer._car_nodes):
			var node: MeshInstance3D = pair[0]
			if not node.visible or Vector2(node.position.x,node.position.z).distance_to(local)>0.2: continue
			found = true
			if not layer._car_meshes.has(key) or node.mesh != layer._car_meshes[key][0]: missing.append("reflective target mesh has wrong variant/pose/detail/winter state")
			if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer._view.get_camera_3d()!=camera_3d or not layer._sprite.is_visible_in_tree() or not node.is_visible_in_tree() or node.layers & camera_3d.cull_mask==0:
				missing.append("reflective target 3D view is not actively displayed")
			if node.global_position.y + node.get_aabb().position.y < main.map_layer.deck_height(local,0,false)-0.02: missing.append("reflective target buried below terrain")
			var forward := Vector3(cos(float(target.heading)),0,-sin(float(target.heading)))
			if node.basis.x.dot(forward)<0.999 or forward.dot((camera_3d.global_position-node.global_position).normalized())<0.5: missing.append("reflective target chest does not face camera")
			var rects := []
			for box: AABB in [node.get_aabb(), AABB(Vector3(0.0,1.02,-0.20)*1.02,Vector3(0.21,0.28,0.40)*1.02)]:
				var rect := Rect2()
				for corner in 8:
					var point := node.global_transform*box.get_endpoint(corner)
					if not camera_3d.is_position_in_frustum(point): missing.append("reflective target outside frustum")
					var pixel := camera_3d.unproject_position(point)
					rect=Rect2(pixel,Vector2.ZERO) if corner==0 else rect.expand(pixel)
				rects.append(rect)
			if rects[0].size.y<100 or minf(rects[1].size.x,rects[1].size.y)<15: missing.append("reflective target/chest too small")
			for panel: Rect2 in hud:
				if panel.intersects(rects[0]): missing.append("reflective target under HUD %s / person %s" % [panel,rects[0]])
			for footprint: PackedVector2Array in footprints:
				if Geometry2D.is_point_in_polygon(local,footprint): missing.append("reflective target under building")
			for other_pair: Array in layer._car_nodes:
				var other: MeshInstance3D=other_pair[0]
				if other==node or not other.visible or camera_3d.is_position_behind(other.global_position): continue
				if camera_3d.global_position.distance_to(other.global_position)>=camera_3d.global_position.distance_to(node.global_position): continue
				var occupied:=Rect2()
				for corner in 8:
					var pixel:=camera_3d.unproject_position(other.global_transform*other.get_aabb().get_endpoint(corner))
					occupied=Rect2(pixel,Vector2.ZERO) if corner==0 else occupied.expand(pixel)
				if occupied.intersects(rects[1]): missing.append("reflective chest obscured by nearer dynamic body")
			reflective={"id":target.id,"variant":4,"pose":"standing_1","active_3d":true,"ground_m":main.map_layer.deck_height(local,0,false),"model_y_m":node.global_position.y,
				"person_rect":[rects[0].position.x,rects[0].position.y,rects[0].size.x,rects[0].size.y],"chest_rect":[rects[1].position.x,rects[1].position.y,rects[1].size.x,rects[1].size.y]}
		if not found: missing.append("expected reflective pedestrian not drawn")
	var windscreen := {}
	if scenario.has("windscreen_model") or scenario.has("two_wheeler_model") or scenario.get("coach_roof_vent", false):
		var kind: String = "train_coach" if scenario.get("coach_roof_vent", false) else scenario.get("windscreen_model", scenario.get("two_wheeler_model", ""))
		var pool: Array = [] if layer_3d_view() == null else layer_3d_view()._model_nodes.get(kind, [])
		var target: Dictionary
		if scenario.get("coach_roof_vent", false):
			var car: Array = main.entities.extra_trains[0]["cars"][0]
			target = {"id":"vqa_coach_vent","x":car[0],"y":car[1],"heading":car[2],"length_m":car[3],"width_m":2.89,"state":"PARKED"}
		else:
			target = main.entities.extra_npcs[0]
		var local := MapMath.point(main.entities.origin, float(target.x), float(target.y))
		var found := false
		for node: Node3D in pool:
			if not node.visible or Vector2(node.position.x,node.position.z).distance_to(local)>0.2: continue
			found = true
			var mesh: MeshInstance3D = node.get_child(0)
			var rect := Rect2()
			for corner in 8:
				var point := mesh.global_transform * mesh.get_aabb().get_endpoint(corner)
				if not camera_3d.is_position_in_frustum(point): missing.append("windscreen target outside camera frustum")
				var pixel := camera_3d.unproject_position(point)
				rect = Rect2(pixel,Vector2.ZERO) if corner==0 else rect.expand(pixel)
			if minf(rect.size.x,rect.size.y)<80: missing.append("windscreen target too small: %s" % rect.size)
			for panel: Rect2 in hud:
				if panel.intersects(rect): missing.append("windscreen target under HUD")
			for footprint: PackedVector2Array in footprints:
				for corner: Vector2 in _corners(float(target.x),float(target.y),float(target.heading),float(target.length_m),float(target.width_m)):
					if Geometry2D.is_point_in_polygon(corner,footprint): missing.append("windscreen target under building")
			var focus_rect := rect
			if scenario.get("coach_roof_vent", false):
				var layer = layer_3d_view()
				if not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer._view.get_camera_3d() != camera_3d or not layer._sprite.is_visible_in_tree() or not mesh.is_visible_in_tree() or mesh.layers & camera_3d.cull_mask == 0:
					missing.append("coach 3D view is not actively displayed")
				if node.global_position.y + mesh.get_aabb().position.y * node.scale.y < main.map_layer.deck_height(local,0,false) - 0.02:
					missing.append("coach buried below terrain")
				var forward := Vector3(cos(float(target.heading)),0,-sin(float(target.heading)))
				if node.basis.x.normalized().dot(forward)<0.999: missing.append("coach heading differs from fixture")
				var vent := AABB(Vector3(-1.275,3.57,-0.637),Vector3(2.55,0.345,1.274))
				var vent_rect := Rect2()
				for corner in 8:
					var point := node.global_transform * vent.get_endpoint(corner)
					if not camera_3d.is_position_in_frustum(point): missing.append("coach vent outside frustum")
					var pixel := camera_3d.unproject_position(point)
					vent_rect = Rect2(pixel,Vector2.ZERO) if corner==0 else vent_rect.expand(pixel)
				if minf(vent_rect.size.x,vent_rect.size.y)<10: missing.append("coach vent too small")
				if camera_3d.global_position.y < (node.global_transform * vent.end).y + 0.5: missing.append("coach roof not visible from above")
				focus_rect = vent_rect
			if scenario.has("two_wheeler_model") or scenario.get("city_bus_orientation", false) or scenario.get("coach_roof_vent", false):
				for pair: Array in layer_3d_view()._car_nodes:
					var other: MeshInstance3D = pair[0]
					if not other.visible or other.global_position.distance_to(node.global_position) < 0.2 or camera_3d.is_position_behind(other.global_position): continue
					if camera_3d.global_position.distance_to(other.global_position) >= camera_3d.global_position.distance_to(node.global_position): continue
					var occupied := Rect2()
					for corner in 8:
						var pixel := camera_3d.unproject_position(other.global_transform * other.get_aabb().get_endpoint(corner))
						occupied = Rect2(pixel, Vector2.ZERO) if corner == 0 else occupied.expand(pixel)
					if occupied.intersects(focus_rect): missing.append("target obscured by a nearer dynamic body")
			if scenario.get("city_bus_orientation", false):
				var forward := Vector3(cos(float(target.heading)), 0, -sin(float(target.heading)))
				if (-node.basis.x.normalized()).dot(forward) < 0.999: missing.append("city bus nose does not match requested heading")
				if int(node.get_meta("lamps",0)) != Buildings3D.LAMPS_ON: missing.append("city bus lamps are not lit")
			if scenario.has("two_wheeler_model") and int(node.get_meta("lamps", 0)) != (Buildings3D.LAMPS_ON if scenario.get("riding", true) else 0):
				missing.append("two-wheeler live lamp state does not match parked/ridden fixture")
			windscreen = {"kind":kind,"id":target.id,"rect":[rect.position.x,rect.position.y,rect.size.x,rect.size.y],"visible":true,"lamps":node.get_meta("lamps",0),"riding":target.state != "PARKED"}
			if scenario.get("coach_roof_vent", false):
				windscreen["vent_rect"] = [focus_rect.position.x,focus_rect.position.y,focus_rect.size.x,focus_rect.size.y]
				windscreen["ground_m"] = main.map_layer.deck_height(local,0,false)
				windscreen["model_origin_m"] = [node.global_position.x,node.global_position.y,node.global_position.z]
				windscreen["camera_3d_m"] = [camera_3d.global_position.x,camera_3d.global_position.y,camera_3d.global_position.z]
				windscreen["active_3d"] = layer_3d_view()._view.get_camera_3d() == camera_3d
		if not found: missing.append("expected windscreen model %s not placed at target" % kind)

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
	if needs.get("outdoor_3d", false) and not MapChunkScript.outdoor_3d:
		missing.append("the client is not in the 3D outdoor view")
	if needs.has("car_models_in_view"):  # GLB vehicles shown by the 3D layer (the player's taxi counts)
		var cars := 0
		if layer_3d != null:
			for kind in layer_3d._model_used:
				cars += int(layer_3d._model_used[kind])
		if cars < int(needs["car_models_in_view"]):
			missing.append("%d 3D car models in view, the scenario needs %d" % [cars, needs["car_models_in_view"]])
	if needs.has("train_models_in_view"):
	for body: String in ["sun", "moon"]:  # sun-moon-in-sky: the disc above the horizon and inside the camera's view
		if needs.get(body + "_in_view", false):
			var alt := Daylight.moon_value(main.entities.shown_state(), body + "_altitude_deg", -90.0)
			var az := Daylight.moon_value(main.entities.shown_state(), body + "_azimuth_deg", 0.0)
			var cam: Camera3D = layer_3d._camera if layer_3d != null else null
			if alt <= 0.0 or cam == null or not cam.is_position_in_frustum(cam.global_position + Daylight.sun_direction(alt, az, -90.0) * minf(1000.0, cam.far * 0.5)):
				missing.append("the %s (alt %.1f, az %.1f) is not in view" % [body, alt, az])
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
	if not reflective.is_empty(): _counts["reflective_strips"] = reflective
	if not fox.is_empty(): _counts["fox"] = fox
	if not felled.is_empty(): _counts["felled_tree"] = felled
	if not tower.is_empty(): _counts["power_tower"] = tower
	if not coaster.is_empty(): _counts["ferris_wheel" if scenario.has("ferris_supports") else "swing_carousel" if scenario.has("swing_supports") else "carousel" if scenario.has("carousel_supports") else "coaster"] = coaster
	if not swing_glb.is_empty(): _counts["swing_glb"] = swing_glb
	if not crossbuck.is_empty(): _counts["crossbuck"] = crossbuck
	if not camp_pair.is_empty(): _counts["picnic_table" if scenario.has("picnic_table_target") else "bicycle_parking" if scenario.has("bicycle_parking_target") else "tent" if scenario.has("tent_target") else "caravan_with_car"] = camp_pair
	if not windscreen.is_empty():
		_counts["coach_vent" if scenario.get("coach_roof_vent", false) else "city_bus" if scenario.get("city_bus_orientation", false) else "two_wheeler" if scenario.has("two_wheeler_model") else "windscreen"] = windscreen
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


## Audit-only spatial buckets keep large camping chunks from blocking readiness on every vertex pair.
func _camp_pair_matches(faces:PackedVector3Array,wanted:PackedVector3Array)->bool:
	var cells:={}
	for v:Vector3 in faces:
		var cell:=Vector3i((v*1000.0).floor())
		if not cells.has(cell):cells[cell]=[]
		cells[cell].append(v)
	for v:Vector3 in wanted:
		var cell:=Vector3i((v*1000.0).floor());var found:=false
		for x in range(-1,2):
			for y in range(-1,2):
				for z in range(-1,2):
					for other:Vector3 in cells.get(cell+Vector3i(x,y,z),[]):
						if other.distance_squared_to(v)<0.000001:found=true
		if not found:return false
	return not wanted.is_empty()


func layer_3d_view():
	return main.map_layer.buildings_3d
var _counts := {}


func _finish() -> void:
	if scenario.has("indoor_hint"):
		_indoor_snapshot = _indoor_hint_result()
	if scenario.has("hud_fixture"):
		_hud_snapshot = _hud_result()  # keep capture-time state while the server debug request awaits
	set_process(false)  # awaits below: finish once
	var path := out_dir.path_join("screenshot.png")
	main.get_viewport().get_texture().get_image().save_png(path)
	if scenario.has("second_shot_s"):  # motion check: the same view a moment later
		await main.get_tree().create_timer(float(scenario["second_shot_s"])).timeout
		main.get_viewport().get_texture().get_image().save_png(out_dir.path_join("screenshot_2.png"))
	var rejections := await _spawn_rejections()
	var perf := preload("res://perf.gd")
	var sections := {}
	for name in ["render_3d_gpu", "render_3d_cpu", "render_gpu", "render_cpu",
			"chunk_add", "chunk_prepare_main", "chunk_layers", "chunk_ground_dict", "chunk_lamps_3d", "chunk_lamps_main", "chunk_wildlife", "chunk_meshes_main", "chunk_mesh_surface", "chunk_build_worker", "chunk_buildings_build", "chunk_unload"]:
		if perf.sections.has(name):
			var s: Array = perf.sections[name]
			sections[name] = {"avg_ms": s[1] / 1000.0 / maxi(1, s[0]), "max_ms": s[2] / 1000.0}
	sections["long_frames"] = _long_frames
	sections["state_timeline"] = _state_timeline_summary(main.entities.buffer)
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


## Third-person: the camera's step per frame against the taxi's, and its yaw step.
func _track_chase() -> void:
	var layer = main.map_layer.buildings_3d
	var body: Dictionary = main.entities.player_body()
	if layer == null or not layer.chase_on or body.is_empty() or layer._eye_blend < 1.0:  # not during a 1/3 glide
		_chase_on_frames = 0
		return
	_chase_on_frames += 1  # the switching frame still reads the previous camera: compared from the third on
	var cam: Transform3D = layer._camera.global_transform
	var yaw := atan2(-cam.basis.z.x, -cam.basis.z.z)
	var at: Vector2 = body["position"]
	var taxi := Vector3(at.x, main.map_layer.deck_height(at, int(body["layer"])), at.y)  # with its ground: DEM chunks arriving lift both
	if _chase_on_frames >= 3:
		var excess: float = cam.origin.distance_to(_chase_last[0]) - taxi.distance_to(_chase_last[1])
		if excess > _chase["max_excess_step_m"]:
			_chase["max_excess_step_m"] = excess
			_chase["worst_at_s"] = _elapsed
		_chase["max_yaw_step_rad"] = maxf(_chase["max_yaw_step_rad"], absf(angle_difference(_chase_last[2], yaw)))
		_chase["frames"] += 1
	_chase_last = [cam.origin, taxi, yaw]


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
		"scene": _counts, "elapsed_s": _elapsed, "chase": _chase, "route_3d_visible": main.map_layer.buildings_3d != null and main.map_layer.buildings_3d.route_3d.visible, "forest": _forest_stats(),
		"lake_ice": {"cm": state.get("calendar", {}).get("lake_ice_cm") if typeof(state.get("calendar")) == TYPE_DICTIONARY else null,
			"holds": state.get("calendar", {}).get("lake_ice_holds") if typeof(state.get("calendar")) == TYPE_DICTIONARY else null}})
	if scenario.get("isolated_settings", false):
		result["verification_user_data_dir"] = OS.get_user_data_dir()
	if scenario.has("indoor_hint"):
		result["indoor_hint"] = _indoor_snapshot
	if scenario.has("hud_fixture"):
		result["hud"] = _hud_snapshot
	result["weather"].erase("plowed_paths")
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


## Totals for long-frame attribution: main_process and chunk Perf usec, and
## render pipelines compiled (a first-time shader variant stalls the frame).
func _work_totals() -> Array:
	var perf := preload("res://perf.gd")
	var chunk := 0
	for name in ["chunk_add", "chunk_unload", "chunk_mesh_surface", "chunk_meshes_main", "chunk_lamps_main"]:  # top level only: no nesting
		chunk += perf.sections.get(name, [0, 0, 0])[1]
	var pipelines := 0
	for monitor in [Performance.PIPELINE_COMPILATIONS_CANVAS, Performance.PIPELINE_COMPILATIONS_MESH, Performance.PIPELINE_COMPILATIONS_SURFACE,
			Performance.PIPELINE_COMPILATIONS_DRAW, Performance.PIPELINE_COMPILATIONS_SPECIALIZATION]:
		pipelines += int(Performance.get_monitor(monitor))
	return [perf.sections.get("main_process", [0, 0, 0])[1], chunk, pipelines]


## M7: the states' arrival gaps beside their server-time gaps (a long arrival gap with a
## normal server gap is transport or a client stall; both long is the server's tick), and
## whether each long gap fell within 1 s of a tile event (the server's map_loading changing).
func _state_timeline_summary(buffer) -> Dictionary:
	var rows: Array = buffer.timeline
	buffer.record_timeline = false
	if rows.size() < 2:
		return {}
	var arrival := PackedFloat32Array()
	var server := PackedFloat32Array()
	var events := PackedFloat32Array()  # local times the map_loading status changed
	for i in range(1, rows.size()):
		arrival.append((rows[i][0] - rows[i - 1][0]) * 1000.0)
		server.append((rows[i][1] - rows[i - 1][1]) * 1000.0)
		if rows[i][3] != rows[i - 1][3]:
			events.append(rows[i][0])
	var long_gaps: Array = []
	for i in arrival.size():
		if arrival[i] > 66.7:
			var at: float = rows[i + 1][0]
			var near := false
			for t in events:
				if absf(t - at) <= 1.0:
					near = true
			long_gaps.append({"t_s": at - rows[0][0], "arrival_ms": arrival[i], "server_ms": server[i], "near_tile_event": near,
				"map_loading": rows[i + 1][3]})
	var sorted_arrival := arrival.duplicate()
	sorted_arrival.sort()
	var pct := func(p: float) -> float: return sorted_arrival[clampi(int(ceil(p * sorted_arrival.size())) - 1, 0, sorted_arrival.size() - 1)]
	var server_max := 0.0
	for g in server:
		server_max = maxf(server_max, g)
	return {"states": rows.size(), "arrival_p50_ms": pct.call(0.5), "arrival_p95_ms": pct.call(0.95), "arrival_p99_ms": pct.call(0.99),
		"arrival_max_ms": sorted_arrival[-1], "arrival_over_66ms": long_gaps.size(), "server_gap_max_ms": server_max,
		"tile_events": events.size(), "long_gaps_near_tile_events": long_gaps.filter(func(g): return g["near_tile_event"]).size(),
		"long_gaps": long_gaps.slice(0, 40), "underruns": buffer.underruns, "underrun_episodes": buffer.underrun_episodes,
		"render_backsteps": buffer.render_backsteps, "clock_snaps": buffer.clock_snaps}


var _swing_geometry_cache := {}


func _check_swing_glb(camera: Camera3D, screen: Vector2, hud: Array, missing: Array) -> Dictionary:
	if camera == null: return {}
	var target: Array = scenario.swing_target
	var layer = layer_3d_view()
	for chunk in main.map_layer._chunks.values():
		for row: Array in chunk._data.get("scenery_objects", []):
			if row[2] != "swing" or Vector2(row[0],row[1]).distance_to(Vector2(target[0],target[1])) > 0.01: continue
			if absf(angle_difference(row[3],target[2])) > 0.001: missing.append("swing heading differs from target")
			var at := MapMath.point(chunk._origin,row[0],row[1])
			var id: int = chunk.get_instance_id()
			if chunk._building_task >= 0 or chunk.meshes_3d.is_empty():
				missing.append("swing chunk meshes still building")
				return {}
			if not _swing_geometry_cache.has(id):
				var expected := Buildings3D.build([],[],Vector2.ZERO,[],[],{"props":[[at,float(row[3]),"swing"]],"ground_heights":chunk.ground_heights,"rect":chunk._bounds_rect})
				var nodes := []
				var faces := PackedVector3Array()
				var matched := true
				for part: Dictionary in expected.prop_surfaces.values():
					var actual := PackedVector3Array()
					for mesh: MeshInstance3D in chunk.meshes_3d:
						if mesh.mesh != null and mesh.has_meta("prop_material") and mesh.material_override == part.material:
							actual.append_array(mesh.mesh.get_faces());nodes.append(mesh)
					matched = matched and _swing_faces_present(actual,part.verts)
					faces.append_array(part.verts)
				var bounds := AABB(faces[0],Vector3.ZERO)
				for v: Vector3 in faces: bounds=bounds.expand(v)
				var feet := {}
				for part: Dictionary in Buildings3D.swing_surfaces().values():
					for v: Vector3 in part.verts:
						if v.y <= 0.005: feet[Vector2(signf(v.x),signf(v.z))] = v
				_swing_geometry_cache[id] = {"matched":matched,"nodes":nodes,"vertex_count":faces.size(),"bounds":bounds,"feet":feet.values()}
			var cached: Dictionary = _swing_geometry_cache[id]
			if not cached.matched or cached.vertex_count != 19740*3:
				missing.append("exact swing GLB triangles/materials absent from final chunk")
				return {}
			if layer==null or not MapChunkScript.outdoor_3d or not Buildings3D.opaque or layer._view.get_camera_3d()!=camera or not layer._sprite.is_visible_in_tree(): missing.append("swing 3D view not active")
			for mesh: MeshInstance3D in cached.nodes:
				if not mesh.is_visible_in_tree() or mesh.layers & camera.cull_mask == 0: missing.append("swing batch not visible")
			var frame: MeshInstance3D = cached.nodes[0]
			var rect := Rect2()
			var first := true
			for corner in 8:
				var point: Vector3 = frame.global_transform*cached.bounds.get_endpoint(corner)
				if not camera.is_position_in_frustum(point): missing.append("swing outside frustum");break
				var pixel := camera.unproject_position(point)
				rect = Rect2(pixel,Vector2.ZERO) if first else rect.expand(pixel);first=false
			if rect.size.x < 100 or rect.size.y < 80 or not Rect2(Vector2.ZERO,screen).encloses(rect): missing.append("swing too small or offscreen")
			for panel: Rect2 in hud:
				if panel.intersects(rect): missing.append("swing under HUD")
			var placement := Transform3D(Basis(Vector3.UP,float(row[3])),Buildings3D.to_3d(at))
			var foot_error := 0.0
			var probes := [Vector3(-0.589,0.34,0),Vector3(0.589,0.34,0),Vector3(0,2.10,0)]
			for local: Vector3 in cached.feet:
				probes.append(local+Vector3.UP*0.03)
				var foot: Vector3 = placement*local
				foot.y += Buildings3D.ground_height(chunk.ground_heights,Vector2(foot.x,foot.z))
				foot_error = maxf(foot_error,absf((frame.global_transform*foot).y-main.map_layer.deck_height(Vector2(foot.x,foot.z),0,false)))
			if foot_error > 0.01: missing.append("swing feet floating or buried")
			# Seats and crossbeam must be clear of surrounding drawn geometry.
			for local: Vector3 in probes:
				var point: Vector3 = placement*local
				point.y += Buildings3D.ground_height(chunk.ground_heights,Vector2(point.x,point.z))
				point = frame.global_transform*point
				for other in main.map_layer._chunks.values():
					for solid: MeshInstance3D in other.meshes_3d:
						if not solid.is_visible_in_tree() or solid.mesh==null or solid.layers & camera.cull_mask==0 or solid in cached.nodes: continue
						var inverse := solid.global_transform.affine_inverse()
						if solid.get_aabb().intersects_segment(inverse*camera.global_position,inverse*point) == null: continue
						if not _felled_occluders.has(solid.mesh): _felled_occluders[solid.mesh]=solid.mesh.generate_triangle_mesh()
						if not _felled_occluders[solid.mesh].intersect_segment(inverse*camera.global_position,inverse*point).is_empty(): missing.append("swing seat/frame hidden by drawn geometry")
			return {"position":[row[0],row[1]],"angle":row[3],"triangles":cached.vertex_count/3,"materials":3,"matched_final_geometry":true,"rect":[rect.position.x,rect.position.y,rect.size.x,rect.size.y],"foot_error_m":foot_error,"osm_playground_way":893436783}
	missing.append("expected generated swing in mapped playground not loaded")
	return {}


func _swing_faces_present(actual: PackedVector3Array, wanted: PackedVector3Array) -> bool:
	# Chunk batches retain triangle order, even across the bounded upload pieces.
	if wanted.is_empty(): return false
	for start in range(0,actual.size()-wanted.size()+1,3):
		if actual[start].distance_squared_to(wanted[0]) > 0.000001: continue
		var matched := true
		for i in wanted.size():
			if actual[start+i].distance_squared_to(wanted[i]) > 0.000001:
				matched=false;break
		if matched: return true
	return false
