## Run: godot --headless --path godot --script res://tests/camera_modes.gd
## docs/specs/third-person-camera.md: 1/2/3 select the driving camera, I only
## on foot, the chase camera behind, above, upright, clamped to ground and decks.
extends SceneTree

const CameraModes := preload("res://camera_modes.gd")
const Route3D := preload("res://route_3d.gd")
const EntityLayer := preload("res://entity_layer.gd")

var failed := false


func _initialize() -> void:
	test_default_third()
	test_keys_select_deterministic()
	test_chase_pose()
	test_chase_clamped_above_ground()
	test_chase_below_deck()
	test_heading_smoothing()
	test_route_heights_follow_deck()
	test_walk_chase_pose_behind_walker()
	test_chase_pose_defaults_unchanged()
	test_look_orbits_without_button()
	test_pitch_clamped()
	test_orbit_held_when_heading_turns()
	test_reset_frame_rate_independent()
	test_sensitivity_scales()
	test_zoom_in_out_walk()
	test_zoom_in_out_car()
	test_zoom_limits()
	test_zoom_smooth()
	test_zoom_kept_while_rotating()
	test_zoom_enter_exit_smooth()
	test_zoom_clearance()
	print("camera_modes: ", "FAIL" if failed else "ok")
	quit(1 if failed else 0)


func check(ok: bool, what: String) -> void:
	if not ok:
		failed = true
		printerr("FAIL ", what)


func key(code: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = code
	event.pressed = true
	return event


func test_default_third() -> void:
	var modes := CameraModes.new()
	check(modes.mode == CameraModes.Mode.THIRD, "first entry: third-person")


func test_keys_select_deterministic() -> void:
	var modes := CameraModes.new()
	for code: Key in [KEY_3, KEY_3, KEY_2, KEY_2, KEY_1, KEY_1]:
		check(modes.handle_key(key(code)), "key %d handled" % code)
		check(modes.mode == CameraModes.KEYS[code], "key %d selects its mode, twice too" % code)
	check(not modes.handle_key(key(KEY_I)), "I is no longer a camera key")
	check(modes.mode == CameraModes.Mode.THIRD, "I leaves the mode")


func test_chase_pose() -> void:
	var pose := CameraModes.chase_pose(Vector2(100, 50), 0.0, 10.0, 10.0)  # heading 0: forward +x
	check(pose.origin.is_equal_approx(Vector3(100 - CameraModes.CHASE_BACK_M, 10.0 + CameraModes.CHASE_UP_M, 50)), "behind and above: %s" % pose.origin)
	var look := -pose.basis.z
	check(look.x > 0.9 and look.y < 0.0, "looks forward and down: %s" % look)
	check(absf(pose.basis.x.y) < 1e-5, "upright: no roll")
	var hit := pose.origin + look * ((pose.origin.y - 10.0 - CameraModes.LOOK_UP_M) / -look.y)
	check(is_equal_approx(hit.x, 100.0 + CameraModes.LOOK_AHEAD_M), "aims ahead of the taxi: %s" % hit)


func test_chase_clamped_above_ground() -> void:
	var pose := CameraModes.chase_pose(Vector2.ZERO, 0.0, 0.0, 8.0)  # a hill rising behind the taxi
	check(is_equal_approx(pose.origin.y, 8.0 + CameraModes.CLEARANCE_M), "above the ground under it: %s" % pose.origin)


func test_chase_below_deck() -> void:
	var pose := CameraModes.chase_pose(Vector2.ZERO, 0.0, 0.0, 0.0, 3.0)  # a bridge 3 m over the camera
	check(is_equal_approx(pose.origin.y, 3.0 - CameraModes.DECK_GAP_M), "under the deck: %s" % pose.origin)
	pose = CameraModes.chase_pose(Vector2.ZERO, 0.0, 0.0, 0.0, 1.0)  # too low: the ground wins
	check(is_equal_approx(pose.origin.y, CameraModes.CLEARANCE_M), "never under the ground: %s" % pose.origin)


func test_heading_smoothing() -> void:
	var modes := CameraModes.new()
	check(modes.smooth_heading(1.0, 0.016) == 1.0, "first frame snaps")
	var h := modes.smooth_heading(1.2, 0.016)
	check(h > 1.0 and h < 1.2, "eases towards the taxi: %f" % h)
	check(modes.smooth_heading(-2.0, 0.016) == -2.0, "a turn-around snaps")


func test_route_heights_follow_deck() -> void:
	# Ground rising 0.1 m/m; a layer-1 deck 6 m over it. The route goes onto the bridge at x = 10.
	var height := func(p: Vector2, layer: int) -> float: return p.x * 0.1 + 6.0 * layer
	var source := [[0.0, 0.0], [10.0, 0.0, 0], [30.0, 0.0, 1], [40.0, 0.0, 1]]  # a 2-element point: the ground
	var points := EntityLayer.route_points(source, Vector2.ZERO)
	var layers := EntityLayer.route_layer_values(source)
	check(layers == PackedInt32Array([0, 0, 1, 1]), "layers read, missing = 0: %s" % layers)
	var vertices: PackedVector3Array = Route3D.build(points, layers, height).surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	var worst := 0.0
	for v in vertices:
		var p := Vector2(v.x, v.z)
		var off := INF
		for layer in ([0] if p.x < 9.99 else [1] if p.x > 10.01 else [0, 1]):  # 10..30: the higher layer (deck_height ramps it)
			var want: float = height.call(p, layer) + Route3D.LIFT_M
			off = minf(off, minf(absf(v.y - want), absf(v.y - want - 0.01)))
		worst = maxf(worst, off)
	check(worst < 1e-3, "route on the deck of its layer, %.3f m off" % worst)
	check(vertices.size() > 6 * 2 * 4, "resampled every 2 m: %d vertices" % vertices.size())


func test_walk_chase_pose_behind_walker() -> void:
	var flat := func(_at: Vector2, _layer: int) -> float: return 5.0
	var open := func(_at: Vector2, _layer: int) -> bool: return false
	for heading: float in [0.0, PI / 2.0]:
		var modes := CameraModes.new()
		var pose: Transform3D = modes.walk_chase(Vector2(10, 20), heading, 0.016, flat, open)
		var want := Vector3(10, 5.0 + 1.8, 20) - Vector3(cos(heading), 0.0, -sin(heading)) * 3.0
		check(pose.origin.is_equal_approx(want), "walker chase 3 m behind, 1.8 m up at %f: %s" % [heading, pose.origin])


func test_chase_pose_defaults_unchanged() -> void:
	var pose := CameraModes.chase_pose(Vector2.ZERO, 0.0, 0.0, 0.0)
	check(pose.origin.is_equal_approx(Vector3(-7.5, 3.2, 0)), "taxi chase still 7.5/3.2: %s" % pose.origin)


## docs/specs/3rd-person-mouse.md: the mouse orbits the chase camera.
func _flat(_at: Vector2, _layer: int) -> float:
	return 0.0


func _open(_at: Vector2, _layer: int) -> bool:
	return false


func _taxi(heading: float) -> Dictionary:
	return {"position": Vector2.ZERO, "heading": heading}


## The eye's bearing seen from the taxi (radians, the heading convention).
func _bearing(pose: Transform3D) -> float:
	return atan2(-pose.origin.z, pose.origin.x)


func test_look_orbits_without_button() -> void:
	var modes := CameraModes.new()
	var before := _bearing(modes.chase(_taxi(0.0), 0.016, _flat, _open))
	modes.look(Vector2(100, 0), 0.01)
	var after := _bearing(modes.chase(_taxi(0.0), 0.016, _flat, _open))
	check(absf(angle_difference(before, after)) > 0.5, "mouse motion orbits: %f -> %f" % [before, after])


func test_pitch_clamped() -> void:
	var modes := CameraModes.new()
	modes.look(Vector2(0, 100000), 0.01)
	check(modes.orbit_pitch == CameraModes.PITCH_MAX, "pitch clamped high: %f" % modes.orbit_pitch)
	modes.look(Vector2(0, -100000), 0.01)
	check(modes.orbit_pitch == CameraModes.PITCH_MIN, "pitch clamped low: %f" % modes.orbit_pitch)


func test_orbit_held_when_heading_turns() -> void:
	var modes := CameraModes.new()
	modes.chase(_taxi(0.0), 0.016, _flat, _open)
	modes.look(Vector2(100, 0), 0.01)
	var before := _bearing(modes.chase(_taxi(0.0), 0.016, _flat, _open))
	var after := before
	for i in 120:
		after = _bearing(modes.chase(_taxi(PI / 2.0), 0.016, _flat, _open))
	check(absf(angle_difference(before, after)) < 1e-4, "held in world space: %f -> %f" % [before, after])


func _reset_yaw(fps: float) -> float:
	var modes := CameraModes.new()
	modes.chase(_taxi(0.0), 0.016, _flat, _open)
	modes.look(Vector2(PI / 0.01 - 1.0, 0), 0.01)  # nearly behind the front
	modes.reset_look()
	var pose: Transform3D
	for i in int(fps):
		pose = modes.chase(_taxi(0.0), 1.0 / fps, _flat, _open)
	return _bearing(pose)


func test_reset_frame_rate_independent() -> void:
	var slow := _reset_yaw(30.0)
	var fast := _reset_yaw(144.0)
	check(absf(angle_difference(slow, fast)) < deg_to_rad(1.0), "30 vs 144 fps: %f vs %f" % [slow, fast])
	check(absf(angle_difference(slow, PI)) < deg_to_rad(1.0), "back behind the taxi within 1 deg after 1 s: %f" % slow)


func test_sensitivity_scales() -> void:
	var one := CameraModes.new()
	var two := CameraModes.new()
	one.look(Vector2(10, 0), 0.002)
	two.look(Vector2(10, 0), 0.004)
	check(is_equal_approx(two.orbit_yaw, 2.0 * one.orbit_yaw) and one.orbit_yaw != 0.0, "double sensitivity, double yaw: %f %f" % [one.orbit_yaw, two.orbit_yaw])


## Section 9: wheel zoom. Distance = horizontal eye-to-entity distance.
func _dist(pose: Transform3D) -> float:
	return Vector2(pose.origin.x, pose.origin.z).length()


func _car(modes: CameraModes, frames := 120, height := Callable(self, "_flat"), covered := Callable(self, "_open")) -> Transform3D:
	var pose: Transform3D
	for i in frames:
		pose = modes.chase(_taxi(0.0), 1.0 / 60.0, height, covered)
	return pose


func _walk(modes: CameraModes, frames := 120) -> Transform3D:
	var pose: Transform3D
	for i in frames:
		pose = modes.walk_chase(Vector2.ZERO, 0.0, 1.0 / 60.0, _flat, _open)
	return pose


func test_zoom_in_out_walk() -> void:
	var modes := CameraModes.new()
	var base := _dist(_walk(modes))
	modes.zoom_step(1, 0.1)
	var near := _dist(_walk(modes))
	modes.zoom_step(-3, 0.1)
	var far := _dist(_walk(modes))
	check(near < base - 0.1 and far > base + 0.1, "walk zoom: %f %f %f" % [near, base, far])


func test_zoom_in_out_car() -> void:
	var modes := CameraModes.new()
	var base := _dist(_car(modes))
	modes.zoom_step(1, 0.1)
	var near := _dist(_car(modes))
	modes.zoom_step(-3, 0.1)
	var far := _dist(_car(modes))
	check(near < base - 0.1 and far > base + 0.1, "car zoom: %f %f %f" % [near, base, far])
	var a := CameraModes.new()
	var b := CameraModes.new()
	a.zoom_step(1, 0.05)
	b.zoom_step(1, 0.1)
	check(is_equal_approx(1.0 - b.zoom_car, 2.0 * (1.0 - a.zoom_car)), "double zoom sensitivity, double step")


func test_zoom_limits() -> void:
	var modes := CameraModes.new()
	_walk(modes, 1)
	modes.zoom_step(100, 0.1)
	check(absf(_dist(_walk(modes, 600)) - modes.walk_min_m) < 0.01, "walk min")
	modes.zoom_step(-100, 0.1)
	check(absf(_dist(_walk(modes, 600)) - modes.walk_max_m) < 0.01, "walk max")
	_car(modes, 1)
	modes.zoom_step(100, 0.1)
	check(absf(_dist(_car(modes, 600)) - modes.car_min_m) < 0.01, "car min")
	modes.zoom_step(-100, 0.1)
	check(absf(_dist(_car(modes, 600)) - modes.car_max_m) < 0.01, "car max")


func test_zoom_smooth() -> void:
	var modes := CameraModes.new()
	var before := _dist(_car(modes))
	modes.zoom_step(-100, 0.1)
	var first := _dist(_car(modes, 1))
	check(first > before and first - before < 0.3 * (modes.car_max_m - before), "eased: %f -> %f" % [before, first])


func test_zoom_kept_while_rotating() -> void:
	var modes := CameraModes.new()
	modes.zoom_step(2, 0.1)
	var before := _dist(_car(modes))
	modes.look(Vector2(150, 0), 0.01)
	var after := _dist(_car(modes, 1))
	check(absf(before - after) < 1e-3 and modes.orbit_pitch == 0.0, "look keeps distance: %f %f" % [before, after])
	var yaw := modes.orbit_yaw
	modes.zoom_step(1, 0.1)
	check(modes.orbit_yaw == yaw, "zoom keeps yaw")


func test_zoom_enter_exit_smooth() -> void:
	for notches in [100, -100]:
		var modes := CameraModes.new()
		_walk(modes, 1)
		modes.zoom_step(notches, 0.1)
		var last := _dist(_walk(modes, 600))
		var goal := _dist(_car(CameraModes.new()))
		var worst := 0.0
		for i in 120:
			var d := _dist(_car(modes, 1))
			worst = maxf(worst, absf(d - last))
			last = d
		check(worst < 0.3 * absf(goal - _dist(_walk(CameraModes.new()))) + 0.5 and absf(last - goal) < 0.05, "enter taxi at %d: worst step %f" % [notches, worst])


func _hill(at: Vector2, _layer: int) -> float:
	return 10.0 if at.x < -5.0 else 0.0


func _bridge(_at: Vector2, layer: int) -> float:
	return 5.0 if layer > 0 else 0.0


func _under(_at: Vector2, _layer: int) -> bool:
	return true


func test_zoom_clearance() -> void:
	var modes := CameraModes.new()
	modes.zoom_step(-100, 0.1)
	var pose := _car(modes, 600, _hill)
	check(pose.origin.y >= 10.0 + CameraModes.CLEARANCE_M - 1e-3, "max zoom over hill: %f" % pose.origin.y)
	var deck := CameraModes.new()
	deck.zoom_step(-100, 0.1)
	pose = _car(deck, 600, _bridge, _under)
	check(pose.origin.y <= 5.0 - CameraModes.DECK_GAP_M + 1e-3, "max zoom under deck: %f" % pose.origin.y)
