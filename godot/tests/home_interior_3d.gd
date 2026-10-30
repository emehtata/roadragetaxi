## Real generated plans, including concave/rotated houses, plus collision at each doorway.
extends SceneTree

const Interior := preload("res://home_interior_3d.gd")
var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var plans: Array = JSON.parse_string(FileAccess.get_file_as_string("res://tests/data/home_plans.json"))
	var interior := Interior.new()
	root.add_child(interior)
	for plan in plans:
		var original := JSON.stringify(plan)
		check(interior.load_plan(plan), "loads " + str(plan["building_id"]))
		check(JSON.stringify(plan) == original, "source plan unchanged")
		check(interior.get_child_count() == 2, "one combined mesh and one collision body")
		var mesh: ArrayMesh = interior.get_node("Surfaces").mesh
		var vertices: PackedVector3Array = mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
		var area := 0.0
		for i in range(0, vertices.size(), 3):
			area += (vertices[i + 1] - vertices[i]).cross(vertices[i + 2] - vertices[i]).length() / 2.0
		check(absf(area - float(plan["area_m2"])) < 0.11, "floors cover source footprint area")
		for surface in mesh.get_surface_count():
			for vertex in mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
				check(vertex.is_finite() and vertex.y >= 0 and vertex.y <= interior.wall_height, "finite vertices within wall height")
		await physics_frame
		await physics_frame
		for room in plan["rooms"]:
			var p := Vector3(room["label_at"][0], 0.0, -room["label_at"][1])
			check(not _ray(p + Vector3.UP, p + Vector3.DOWN).is_empty(), "room has a collidable floor")
		for door in plan["doors"]:
			var a := Vector2(door["points"][0][0], door["points"][0][1])
			var b := Vector2(door["points"][1][0], door["points"][1][1])
			var middle := (a + b) / 2.0
			var n := (b - a).orthogonal().normalized() * 0.3
			for height in [0.25, 1.0, 1.95]:
				check(_ray(Vector3(middle.x + n.x, height, -middle.y - n.y), Vector3(middle.x - n.x, height, -middle.y + n.y)).is_empty(), "doorway stays open below lintel")
			check(not _ray(Vector3(middle.x + n.x, 2.25, -middle.y - n.y), Vector3(middle.x - n.x, 2.25, -middle.y + n.y)).is_empty(), "door has a collidable lintel")
		interior.clear()
		check(interior.get_child_count() == 0, "leaving releases meshes and collision")
	# Two adjacent rooms: the shared wall exists once in the source network.
	var paired := {"rooms": [{"points": [[0, 0], [2, 0], [2, 4], [0, 4]]}, {"points": [[2, 0], [4, 0], [4, 4], [2, 4]]}],
		"walls": [[[0, 1.6], [0, 0], [4, 0], [4, 4], [0, 4], [0, 2.4]], [[2, 0], [2, 1.6]], [[2, 2.4], [2, 4]]],
		"doors": [{"points": [[0, 1.6], [0, 2.4]]}, {"points": [[2, 1.6], [2, 2.4]]}]}
	check(interior.load_plan(paired), "adjacent rooms load")
	var caps := 0.0
	var triangles: PackedVector3Array = interior.get_node("Surfaces").mesh.surface_get_arrays(1)[Mesh.ARRAY_VERTEX]
	for i in range(0, triangles.size(), 3):
		if is_equal_approx(triangles[i].y, 2.5) and is_equal_approx(triangles[i + 1].y, 2.5) and is_equal_approx(triangles[i + 2].y, 2.5):
			caps += (triangles[i + 1] - triangles[i]).cross(triangles[i + 2] - triangles[i]).length() / 2.0
	check(absf(caps - 2.3856) < 0.001, "shared wall and junction tops have no overlapping area")
	interior.free()
	print("HOME_INTERIOR_3D: %d plans, %d failures" % [plans.size(), failures])
	quit(1 if failures else 0)


func _ray(from: Vector3, to: Vector3) -> Dictionary:
	var query := PhysicsRayQueryParameters3D.create(from, to)
	query.hit_back_faces = true
	return root.world_3d.direct_space_state.intersect_ray(query)
