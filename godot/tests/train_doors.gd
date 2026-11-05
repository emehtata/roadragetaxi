## Door strips of the procedural rail vehicles (vehicle_arrays): a coach's on
## the right (+y) only, a tram's on both sides, none on a locomotive.
## godot --headless --path godot --script res://tests/train_doors.gd
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const DOOR := Color8(42, 48, 51)


func _initialize() -> void:
	var failures := []
	var coach := _doors("train", {"profile": "standard"})
	if coach != [0, 2]:
		failures.append("test_coach_doors_right_only: [-y, +y] doors %s" % [coach])
	var tram := _doors("tram", {"profile": "standard"})
	if tram != [2, 2]:
		failures.append("test_tram_doors_both_sides: [-y, +y] doors %s" % [tram])
	var loco := _doors("train", {"profile": "locomotive"})
	if loco != [0, 0]:
		failures.append("test_locomotive_no_doors: [-y, +y] doors %s" % [loco])
	for f in failures:
		printerr("FAIL ", f)
	print("train_doors: %s" % ("ok" if failures.is_empty() else "FAILED"))
	quit(1 if failures else 0)


## [door parts on -y, on +y]: each part's top face is 6 verts of the exact door colour.
func _doors(kind: String, extra: Dictionary) -> Array:
	var a: Dictionary = B3.vehicle_arrays(kind, 26.4, 2.89, Color8(200, 200, 200), 0, extra)
	var verts: PackedVector3Array = a["verts"]
	var colors: PackedColorArray = a["colors"]
	var count := [0, 0]
	for i in verts.size():
		if colors[i].is_equal_approx(DOOR) and is_equal_approx(verts[i].y, 2.53):
			count[1 if verts[i].z > 0.0 else 0] += 1
	return [count[0] / 6, count[1] / 6]
