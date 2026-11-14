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
