## Walking in the home (home_walk.gd) on plans from the Python generator
## (tests/data/home_plans.json: tests/test_home_interior.py's footprints and real houses, at 0
## and 31 degrees). Headless: godot --headless --path godot --script res://tests/home_walk.gd
extends SceneTree

const Walk := preload("res://home_walk.gd")
const GRID_M := 0.1

var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		print("FAIL: ", message)


func _initialize() -> void:
	var plans: Array = JSON.parse_string(FileAccess.get_file_as_string("res://tests/data/home_plans.json"))
	var walk := Walk.new()
	root.add_child(walk)
	var children := walk.get_child_count()
	for plan in plans:
		var name := str(plan["building_id"])
		check(walk.enter(plan), name + ": enters")
		check(walk.fits(walk.at), name + ": starts on the floor, clear of walls")
		check(walk.at_exit(), name + ": starts at the front door, where E goes out")
		var outline := Walk._points(plan["footprint"])
		check(Geometry2D.is_point_in_polygon(walk.at, outline), name + ": starts inside")
		var reached := _flood(walk)
		for i in plan["rooms"].size():
			var room := Walk._points(plan["rooms"][i]["points"])
			var inside := false
			for cell in reached:
				if Geometry2D.is_point_in_polygon(reached[cell], room):
					inside = true
					break
			check(inside, "%s: room %d (%s) is reachable through the doors" % [name, i, plan["rooms"][i]["kind"]])
		for cell in reached:  # nothing walked through a wall to outside
			check(Geometry2D.is_point_in_polygon(reached[cell], outline), name + ": never outside the footprint")
		# Walk straight at every wall's middle from the inside: the walker stops short of it.
		for wall in plan["walls"]:
			var line := Walk._points(wall)
			for i in line.size() - 1:
				var middle := (line[i] + line[i + 1]) / 2.0
				var normal := (line[i + 1] - line[i]).orthogonal().normalized()
				for side in [-1.0, 1.0]:
					var start: Vector2 = middle + normal * side * 0.5
					if not walk.fits(start):
						continue
					walk.at = start
					for k in 40:
						walk.move(-normal * side * 0.05)
					check(walk.at.distance_to(middle) >= Walk.RADIUS_M + Walk.WALL_HALF_M - 0.01 or
						(walk.at - middle).dot(normal * side) > 0.0, name + ": a wall stops the walker")
		walk.leave()
	# Leaving and entering again: the same nodes, the walker back at the door.
	for i in 5:
		walk.enter(plans[0])
		walk.at = Vector2(1e6, 1e6)
		walk.leave()
	check(walk.enter(plans[0]) and walk.at_exit() and walk.get_child_count() == children, "repeat visits keep one view")
	check(not walk.enter({"error": "home_unavailable"}), "no plan, no interior")
	walk.free()
	print("home_walk: %d failures" % failures)
	quit(1 if failures > 0 else 0)


## Every grid point reachable from the start by short moves the walker fits (4-neighbour).
func _flood(walk) -> Dictionary:
	var origin: Vector2 = walk.at
	var reached := {Vector2i.ZERO: origin}
	var queue: Array[Vector2i] = [Vector2i.ZERO]
	while not queue.is_empty():
		var cell: Vector2i = queue.pop_back()
		for step in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var next: Vector2i = cell + step
			if reached.has(next):
				continue
			var p: Vector2 = origin + Vector2(next) * GRID_M
			if walk.fits(p) and walk.fits((p + reached[cell]) / 2.0):
				reached[next] = p
				queue.append(next)
	return reached
