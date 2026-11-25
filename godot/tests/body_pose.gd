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
	test_wheels_on_the_ground()
	test_far_bodies_stay_level()
	test_train_on_dem()
	test_ferry_on_water()
	test_animals_on_dem()
	test_walker_layer()
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


## Criterion 7: the wheel contact points of every non-car body are within 0.05 m of the road surface (the model's
## 0.028 m ride height is in); tilted bodies on a 6 % slope, at two headings.
func test_wheels_on_the_ground() -> void:
	_ground(0.06)
	for kind: String in ["bus", "truck", "tractor", "camper_van", "bicycle", "e_scooter", "motorcycle"]:
		for heading: float in [0.0, 0.7]:
			var c := Vector2(200, -100)
			var length := 12.0 if kind == "bus" else 7.5 if kind == "truck" else 4.0 if kind == "tractor" else 6.2 if kind == "camper_van" else 1.8 if kind == "bicycle" else 1.2 if kind == "e_scooter" else 2.2
			var width := 2.55 if kind == "bus" else 2.3 if kind in ["truck", "tractor", "camper_van"] else 0.6
			var pose := _settle(c, heading, length, width, kind + str(heading))
			renderer.begin_cars()
			renderer.vehicle(kind, c, heading, length, width, Color.RED, 0, pose.x, {}, Vector2(pose.y, pose.z))
			var model_kind := B3.vehicle_model_kind(kind, 0)
			var node: Node3D = renderer._model_nodes[model_kind][0]
			var box := B3.merged_model(model_kind).get_aabb()
			var long_z := box.size.z >= box.size.x
			var worst := 0.0
			for fwd: float in [-0.35, 0.35]:
				for side: float in [-0.4, 0.4]:
					var spot := box.get_center() + (Vector3(side * box.size.x, 0, fwd * box.size.z) if long_z else Vector3(fwd * box.size.x, 0, side * box.size.z))
					spot.y = box.position.y
					var world := node.transform * spot
					worst = maxf(worst, absf(world.y - layer.deck_height.call(Vector2(world.x, world.z), 0) - B3.ROAD_M - 0.016))
			renderer.end_cars()
			print("%s heading %.1f: wheels off the surface by %.4f m" % [kind, heading, worst])
			check(worst <= 0.05, "%s heading %.1f: wheel points %.3f m from the road surface" % [kind, heading, worst])


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


func _map_with_dem(slope: float, water := false) -> Map:
	var flags := [Chunk.buildings_3d, Chunk.outdoor_3d, Chunk.build_async]
	Chunk.buildings_3d = true
	Chunk.outdoor_3d = true
	Chunk.build_async = false
	var map := Map.new()
	root.add_child(map)
	var heights := []
	for r in 8:
		for c in 8:
			heights.append(c * 20.0 * slope)
	map.add_chunk({"chunk_id": "0_0", "bounds": [0, 0, 100, 100], "ground_heights": {"origin": [0, 0], "step": 20.0, "cols": 8, "heights": heights}})
	Chunk.buildings_3d = flags[0]
	Chunk.outdoor_3d = flags[1]
	Chunk.build_async = flags[2]
	return map


## Criterion 8: a train on a slope has a nonzero pitch, sits on the ground (DEM), and up DECK_M on a rail deck.
func test_train_on_dem() -> void:
	var map := _map_with_dem(0.06)
	B3.current = renderer
	B3.view_centre = Vector2(50, -50)
	var at := Vector2(50, -50)
	var ground := func(p: Vector2) -> float: return map.rail_height(p, false)
	layer.deck_height = func(p: Vector2, lay: int, road := true) -> float: return map.deck_height(p, lay, road)
	var pose := _settle(at, 0.0, 20.0, 2.9, "rail_t_0", ground)
	print("train on 6 %%: pitch %.4f rad, rail %.3f m" % [pose.y, pose.x])
	check(absf(pose.y - atan(0.06)) < 0.01, "train pitch %.4f rad on a 6 %% grade" % pose.y)
	check(absf(pose.x - map.deck_height(at, 0, false) - B3.RAIL_M * B3.DEM_GAP_SCALE) < 0.05, "train rails %.3f m over the DEM ground %.3f m" % [pose.x, map.deck_height(at, 0, false)])
	check(pose.x > 0.5, "the train rides the hill's height, not 0")
	map.free()


## Criterion 8: a ferry sits at the drawn water surface within 0.1 m: the road mesh's water area on the same DEM.
func test_ferry_on_water() -> void:
	var map := _map_with_dem(0.06)
	var at := Vector2(50, -50)
	var chunk = map._chunks["0_0"]
	var water := PackedVector2Array([Vector2(20, -20), Vector2(80, -20), Vector2(80, -80), Vector2(20, -80)])
	var out := B3.build([], [], Vector2.ZERO, [], [], {"rect": Rect2(0, -100, 100, 100), "areas": [[water, Color.BLUE, true]], "ground_heights": chunk.ground_heights})
	var top := -INF
	var verts: PackedVector3Array = out["road"]
	for t in range(0, verts.size(), 3):
		var a := Vector2(verts[t].x, verts[t].z)
		var b := Vector2(verts[t + 1].x, verts[t + 1].z)
		var c := Vector2(verts[t + 2].x, verts[t + 2].z)
		var d := (b - a).cross(c - a)
		if absf(d) < 1e-9:
			continue
		var u := (at - a).cross(c - a) / d
		var v := (b - a).cross(at - a) / d
		if u >= -1e-6 and v >= -1e-6 and u + v <= 1.0 + 1e-6:
			top = maxf(top, verts[t].y + u * (verts[t + 1].y - verts[t].y) + v * (verts[t + 2].y - verts[t].y))
	var ferry: float = map.rail_height(at, true)
	print("ferry %.3f m, drawn water %.3f m" % [ferry, top])
	check(top > -INF and absf(ferry - top) <= 0.1, "ferry %.3f m vs the drawn water surface %.3f m" % [ferry, top])
	map.free()


## Elves, dogs and wildlife stand on the DEM ground (deck_height(at, 0, false)); flying animals add their offset.
func test_animals_on_dem() -> void:
	B3.current = renderer
	B3.view_centre = Vector2(200, -100)
	_ground(0.06)
	var wild := GDScript.new()
	wild.source_code = "extends Node\nvar animals := []\nfunc coat(_s): return Color.GRAY\n"
	wild.reload()
	layer.wildlife = wild.new()
	layer.wildlife.set("animals", [{"id": 1, "position": Vector2(150, -60), "species": "pigeon", "state": "FEED", "heading": 0.0},
		{"id": 2, "position": Vector2(300, -90), "species": "gull", "state": "FLY", "heading": 0.0}])
	layer._frame = {"a": {}, "b": {}, "t": 0.0}
	layer.elves = PackedVector2Array([Vector2(250, -40)])
	layer._dog_rows = [[Vector2(100, -30), Vector2(110, -30), 0.0, {"size": "small"}]]
	renderer.begin_cars()
	layer._people_3d()
	var stand := B3.ROAD_M + 0.016
	var elf: Transform3D = renderer._car_nodes[0][0].transform
	check(absf(elf.origin.y - stand - layer.deck_height.call(Vector2(250, -40), 0, false)) < 0.001, "an elf stands on the ground: y %.3f" % elf.origin.y)
	var rows := 0
	for list: Array in renderer._animal_rows.values():
		for row: Array in list:
			var t: Transform3D = row[5]
			var ground: float = layer.deck_height.call(Vector2(t.origin.x, t.origin.z), 0, false)
			var flying: bool = row[0] == "gull"
			var lift := t.origin.y - stand - ground
			print("animal row %s: %.4f m over the ground (flying %s)" % [row[0], lift, flying])
			check(lift >= -0.001 and (lift < 0.001 if not flying else lift > 2.0), "%s: %.3f m over the ground (flying %s)" % [row[0], lift, flying])
			rows += 1
	check(rows >= 4, "dog, pigeons and gulls were placed (%d)" % rows)
	renderer.end_cars()
	layer.wildlife = null


## The walking player's layer: audited, it was dropped (the figure stood on layer 0, under a deck); now carried.
func test_walker_layer() -> void:
	B3.current = renderer
	var seen := []
	layer.deck_height = func(at: Vector2, lay: int, road := true) -> float:
		seen.append(lay)
		return 6.0 * lay
	var walker := Entities.player_walker({"speed": 0.0, "layer": 1})
	check(walker["layer"] == 1 and Entities.player_walker({"speed": 0.0})["layer"] == 0, "player_walker carries the server's layer")
	layer._frame = {"a": {}, "b": {}, "t": 0.0}
	layer._people_rows = [[Vector2(10, -10), 0.0, walker, 0.0]]
	renderer.begin_cars()
	layer._people_3d()
	check(seen.has(1) and absf(renderer._car_nodes[0][0].transform.origin.y - 6.0 - B3.ROAD_M - 0.016) < 0.001, "the walker stands on the layer-1 deck (%s)" % [seen])
	renderer.end_cars()
