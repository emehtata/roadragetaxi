## Run: godot --headless --path godot --script res://tests/cyclist_rider.gd
## docs/specs/terrain-following-bodies.md part 4 (criteria 13-15): cyclists, and the motorcycle and e-scooter riders,
## are posed people (person_arrays), not a two-box torso and head.
extends SceneTree

const B3 := preload("res://buildings_3d.gd")

var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("run")


func run() -> void:
	test_rider_is_posed_person()
	test_feet_on_pedals()
	test_hips_on_saddle_hands_on_bars()
	test_rider_is_placed_with_the_bike()
	print("cyclist_rider: %d failures" % failures)
	quit(1 if failures else 0)


func _walker(variant: int) -> int:
	return B3.person_arrays(Color.RED, "walk_0", 1.0, "", variant)["verts"].size()


## Criterion 13: the same limb part count as a walking pedestrian; the old two-box rider is gone from the bike meshes.
func test_rider_is_posed_person() -> void:
	for model: String in B3.RIDER_RIGS:
		for variant in [0, 3, 6]:
			var pose := "rider:%s:%d" % [model, 2]
			var rider: int = B3.person_arrays(Color.RED, pose, 1.0, "", variant)["verts"].size()
			check(rider == _walker(variant), "%s rider (variant %d): %d vertices, a walking person's %d" % [model, variant, rider, _walker(variant)])
	for kind: String in ["bicycle", "motorcycle", "e_scooter"]:
		var parked: int = B3.vehicle_arrays(kind, 1.8, 0.6, Color.RED, 0, {"riding": false})["verts"].size()
		check(B3.vehicle_arrays(kind, 1.8, 0.6, Color.RED, 0, {"riding": true})["verts"].size() == parked, "%s: no box rider in the procedural body" % kind)
		check(B3.model_vehicle_details(kind, 1.8, 0.6, Color.RED, 1, {"riding": true}).verts.size() == B3.model_vehicle_details(kind, 1.8, 0.6, Color.RED, 1, {"riding": false}).verts.size(),
			"%s: no box rider in the GLB overlay" % kind)


## [left, right] centre of the shoe parts (part 4) of a rider mesh.
func _shoes(arrays: Dictionary) -> Array:
	var sums := [Vector3.ZERO, Vector3.ZERO]
	var counts := [0, 0]
	var verts: PackedVector3Array = arrays["verts"]
	var parts: PackedVector2Array = arrays["part"]
	for i in verts.size():
		if int(parts[i].x) == 4:
			var side := 1 if verts[i].z > 0.0 else 0
			sums[side] += verts[i]
			counts[side] += 1
	return [sums[0] / maxf(counts[0], 1), sums[1] / maxf(counts[1], 1)]


## Criterion 14: at 8 crank phases the shoes stand on the pedal circle (radius 0.17 m) within 0.03 m, the feet half a turn apart.
func test_feet_on_pedals() -> void:
	for model: String in ["bicycle", "mountain_bike"]:
		var rig: Dictionary = B3.RIDER_RIGS[model]
		check(is_equal_approx(rig["crank"].z, 0.17), "%s crank radius %.2f" % [model, rig["crank"].z])
		var worst := 0.0
		for phase in 8:
			var arrays := B3.person_arrays(Color.RED, "rider:%s:%d" % [model, phase], 1.0, "", 0)
			var k := 0.96  # variant 0
			var shoes := _shoes(arrays)
			for side_index in 2:
				var side := 1.0 if side_index == 1 else -1.0
				var centre: Vector3 = shoes[side_index]
				var sole := Vector2(centre.x, centre.y - 0.077 * k)  # the shoe's sole under its centre
				var radial := absf(sole.distance_to(Vector2(rig["crank"].x, rig["crank"].y)) - rig["crank"].z)
				worst = maxf(worst, radial)
				check(radial <= 0.03, "%s phase %d, %s foot %.3f m off the pedal circle" % [model, phase, "right" if side > 0 else "left", radial])
			var gap: float = absf(shoes[0].y - shoes[1].y)
			var apart: float = absf(sin(TAU * phase / 8.0)) * 2.0 * rig["crank"].z
			check(absf(gap - apart) <= 0.03, "%s phase %d: feet %.3f m apart in height, the crank gives %.3f" % [model, phase, gap, apart])
		print("%s: worst foot %.4f m off the pedal circle over 8 phases" % [model, worst])


## Criterion 14: the hips are within 0.05 m of the saddle top measured on the GLB, the hands on its grips.
func test_hips_on_saddle_hands_on_bars() -> void:
	var dims := {"bicycle": [1.8, 0.6], "mountain_bike": [1.8, 0.6], "motorcycle": [2.2, 0.8]}
	for model: String in ["bicycle", "mountain_bike", "motorcycle"]:
		var rig: Dictionary = B3.RIDER_RIGS[model]
		var mesh := B3.merged_model(model)
		var scale := B3.model_scale(model, dims[model][0], dims[model][1])
		var saddle := Vector3(0, -1, 0)
		var bars := Vector3(0, -1, 0)
		for surface in mesh.get_surface_count():
			for v: Vector3 in mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
				var p := v * scale  # the vehicle frame: forward is the model's z
				var is_saddle := p.z > -0.6 and p.z < 0.1 and absf(p.x) < 0.12 and p.y > saddle.y
				if is_saddle:
					saddle = p
				if p.z > -0.05 and absf(p.x) > 0.18 and p.y > bars.y and p.z < 0.7:
					bars = p
		print("%s: saddle top %.3f (rig hip %.3f), grips %.3f (rig %.3f)" % [model, saddle.y, rig["hip"].y, bars.y, rig["grip"].y])
		check(absf(rig["hip"].y - saddle.y) <= 0.05, "%s: hip %.3f within 0.05 m of the saddle top %.3f" % [model, rig["hip"].y, saddle.y])
		check(absf(rig["hip"].x - saddle.z) <= 0.1, "%s: hip x %.3f at the saddle (x %.3f)" % [model, rig["hip"].x, saddle.z])
		check(absf(rig["grip"].y - bars.y) <= 0.03 and absf(rig["grip"].x - bars.z) <= 0.1, "%s: grips at (%.3f, %.3f), the bars' top at (%.3f, %.3f)" % [model, rig["grip"].x, rig["grip"].y, bars.z, bars.y])
		var arrays := B3.person_arrays(Color.RED, "rider:%s:0" % model, 1.0, "", 0)
		var verts: PackedVector3Array = arrays["verts"]
		var parts: PackedVector2Array = arrays["part"]
		for side in [-1.0, 1.0]:
			var grip := Vector3(rig["grip"].x, rig["grip"].y, side * rig["grip"].z)
			var near := INF
			for i in verts.size():
				if int(parts[i].x) == 1 and verts[i].y < rig["hip"].y + 0.6:  # skin below the head: the hands
					near = minf(near, verts[i].distance_to(grip))
			check(near <= 0.09, "%s: a hand within %.3f m of the %s grip" % [model, near, "right" if side > 0 else "left"])


## The rider is its own organic body next to the bike's, with the crank phase and look passed in.
func test_rider_is_placed_with_the_bike() -> void:
	B3.use_shaded()
	var renderer := B3.new()
	renderer._cars_root = Node3D.new()
	root.add_child(renderer._cars_root)
	renderer.begin_cars()
	renderer.vehicle("bicycle", Vector2(5, -5), 0.4, 1.8, 0.6, Color.RED, 1, 0.0, {"riding": false, "id": 4})
	var parked: int = renderer._cars_used
	renderer.vehicle("bicycle", Vector2(9, -5), 0.4, 1.8, 0.6, Color.RED, 1, 0.0, {"riding": true, "id": 4, "phase": 3})
	check(renderer._cars_used - parked == 2, "a ridden bike places its details and a rider (%d bodies)" % (renderer._cars_used - parked))
	check(B3.rider_verts >= _walker(0), "rider mesh %d vertices >= a person's %d" % [B3.rider_verts, _walker(0)])
	var again: int = renderer._cars_used
	renderer.vehicle("motorcycle", Vector2(12, -5), 0.4, 2.2, 0.8, Color.RED, 1, 0.0, {"riding": true, "id": 4})
	renderer.vehicle("e_scooter", Vector2(15, -5), 0.4, 1.2, 0.5, Color.RED, 1, 0.0, {"riding": true, "id": 4})
	check(renderer._cars_used - again == 4, "motorcycle and e-scooter riders are people too (%d bodies)" % (renderer._cars_used - again))
	renderer.end_cars()
	renderer._cars_root.free()
	renderer.route_3d.free()
	renderer.free()
