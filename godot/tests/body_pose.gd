## Run: godot --headless --path godot --script res://tests/body_pose.gd
## docs/specs/terrain-following-bodies.md part 2 (criteria 6-9): every drawn body sits on and tilts with the ground.
extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const Chunk := preload("res://map_chunk.gd")
const Map := preload("res://map_layer.gd")
const Entities := preload("res://entity_layer.gd")
const Perf := preload("res://perf.gd")

var failures := 0
var renderer: B3
var layer: Node2D
var grid := {}


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("run")


func run() -> void:
	B3.use_shaded()
	renderer = B3.new()
	renderer._cars_root = Node3D.new()
	root.add_child(renderer._cars_root)
	B3.current = renderer
	B3.view_centre = Vector2(200, -100)
	layer = Entities.new()
	layer.view_rect = Rect2(-1000, -1000, 3000, 3000)
	test_bus_pitch_on_grade()
	test_far_bodies_stay_level()
	layer.free()
	print("body_pose: %d failures" % failures)
	quit(1 if failures else 0)


## A DEM rising `slope` m per m along +x (empty: flat), as the layer's deck_height sees it.
func _ground(slope: float) -> void:
	grid = {}
	if slope > 0.0:
		var heights := []
		for r in 26:
			for c in 26:
				heights.append(c * 20.0 * slope)
		var message := {"ground_heights": {"origin": [0, 0], "step": 20.0, "cols": 26, "heights": heights}}
		Chunk.prepare(message, Vector2.ZERO)
		grid = message["prepared"]["ground_heights"]
	var g := grid
	layer.deck_height = func(at: Vector2, lay: int, road := true) -> float:
		return B3.road_surface_height(at, lay, PackedVector2Array(), g) if road else B3.deck_base(at, lay, PackedVector2Array(), g)
	layer._tilts.clear()


func _settle(c: Vector2, heading: float, length: float, width: float, id: Variant, ground := Callable()) -> Vector3:
	var pose := Vector3.ZERO
	for i in 40:  # the stance eases over TILT_EASE_S
		pose = layer.body_pose(c, heading, length, width, 0, id, ground, false, 1.0 / 60.0)
	return pose


## Criterion 6: a bus on a 6 % grade pitches atan(0.06) within 0.01 rad; 0 on flat ground.
func test_bus_pitch_on_grade() -> void:
	_ground(0.06)
	var pose := _settle(Vector2(200, -100), 0.0, 12.0, 2.55, "bus")
	print("bus on 6 %%: pitch %.4f rad, want %.4f; roll %.4f" % [pose.y, atan(0.06), pose.z])
	check(absf(pose.y - atan(0.06)) < 0.01 and absf(pose.z) < 0.001, "bus pitch %.4f rad, roll %.4f on a 6 %% grade" % [pose.y, pose.z])
	_ground(0.0)
	pose = _settle(Vector2(200, -100), 0.3, 12.0, 2.55, "flat bus")
	check(pose.y == 0.0 and pose.z == 0.0, "flat ground: no pitch or roll")


## A body seen for the first time stands at its slope at once, and the easing after that takes the same time at any frame rate
## (the lag of a moving car behind its slope was what the slope scenario measured under load).
func test_stance_is_immediate_and_frame_rate_independent() -> void:
	_ground(0.06)
	var first: Vector3 = layer.body_pose(Vector2(200, -100), 0.0, 12.0, 2.55, 0, "new bus", Callable(), false, 1.0 / 60.0)
	check(absf(first.y - atan(0.06)) < 0.001, "a new body's first pose has its slope: %.4f rad" % first.y)
	for fps: float in [30.0, 60.0, 144.0]:
		layer._tilts["mover"] = Vector2.ZERO  # a known body that has been level
		var pose := Vector3.ZERO
		for i in int(fps * 0.2):  # 0.2 s
			pose = layer.body_pose(Vector2(200, -100), 0.0, 4.5, 1.8, 0, "mover", Callable(), false, 1.0 / fps)
		var want := atan(0.06) * (1.0 - exp(-0.2 / Entities.TILT_EASE_S))
		check(absf(pose.y - want) < 0.004, "%.0f fps: after 0.2 s pitch %.4f rad, the time constant gives %.4f" % [fps, pose.y, want])


## Criterion 9: beyond 120 m of the camera a body stays level and costs no wheel lookups; within it 4 per body.
func test_far_bodies_stay_level() -> void:
	_ground(0.06)
	Perf.counters.erase("pose_lookups")
	Perf.counters.erase("bodies_posed")
	var near := _settle(Vector2(230, -100), 0.0, 4.5, 1.8, "near")
	var lookups_near: int = Perf.counters["pose_lookups"]
	var far := _settle(Vector2(200 + Entities.POSE_RANGE_M + 30.0, -100), 0.0, 4.5, 1.8, "far")
	check(near.y > 0.05, "a body 30 m away tilts (%.3f rad)" % near.y)
	check(far.y == 0.0 and far.z == 0.0, "a body %.0f m away stays level" % (Entities.POSE_RANGE_M + 30.0))
	check(Perf.counters["pose_lookups"] == lookups_near, "no wheel lookups beyond the range")
	check(Perf.counters["pose_lookups"] <= 4 * Perf.counters["bodies_posed"], "pose_lookups %d <= 4 x bodies %d" % [Perf.counters["pose_lookups"], Perf.counters["bodies_posed"]])
	print("pose lookups %d for %d body calls" % [Perf.counters["pose_lookups"], Perf.counters["bodies_posed"]])
