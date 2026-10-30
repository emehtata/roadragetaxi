## Additional, on-demand view of the server's plan; plan metres -> (x, height, -y).
## Source walls are already deduplicated and cut at door openings (interior.py).
extends Node3D

@export var wall_height := 2.5
@export var wall_thickness := 0.12
@export var door_height := 2.0


func clear() -> void:
	for child in get_children():
		child.free()


func load_plan(plan: Dictionary) -> bool:
	clear()
	if plan.has("error") or plan.get("rooms", []).is_empty() or wall_thickness <= 0 or wall_height <= door_height or door_height <= 0:
		return false
	var mesh := ArrayMesh.new()
	var floors := SurfaceTool.new()
	floors.begin(Mesh.PRIMITIVE_TRIANGLES)
	for room in plan["rooms"]:
		_cap(floors, _points(room["points"]), 0.0, Vector3.UP)
	floors.commit(mesh)
	mesh.surface_set_material(0, _material(Color("c7c1ae")))
	var walls := SurfaceTool.new()
	walls.begin(Mesh.PRIMITIVE_TRIANGLES)
	var occupied: Array[PackedVector2Array] = []
	for line in plan.get("walls", []):
		for outline in Geometry2D.offset_polyline(_points(line, false), wall_thickness / 2.0, Geometry2D.JOIN_MITER, Geometry2D.END_BUTT):
			# Give junctions one owner, including their top faces: no overlapping caps.
			var pieces: Array[PackedVector2Array] = [outline]
			for previous in occupied:
				var remaining: Array[PackedVector2Array] = []
				for piece in pieces:
					remaining.append_array(Geometry2D.clip_polygons(piece, previous))
				pieces = remaining
			for piece in pieces:
				_prism(walls, piece, 0.0, wall_height)
			occupied.append(outline)
	for door in plan.get("doors", []):
		for outline in Geometry2D.offset_polyline(_points(door["points"], false), wall_thickness / 2.0, Geometry2D.JOIN_MITER, Geometry2D.END_BUTT):
			_prism(walls, outline, door_height, wall_height)
	if not occupied.is_empty():
		walls.commit(mesh)
		mesh.surface_set_material(1, _material(Color("dedbd3")))
	var visual := MeshInstance3D.new()
	visual.name = "Surfaces"
	visual.mesh = mesh
	add_child(visual)
	var body := StaticBody3D.new()
	body.name = "Collision"
	var collision := CollisionShape3D.new()
	collision.shape = mesh.create_trimesh_shape()
	body.add_child(collision)
	add_child(body)
	return true


static func _points(values: Array, polygon := true) -> PackedVector2Array:
	var result := PackedVector2Array()
	for value in values:
		var p := Vector2(float(value[0]), float(value[1]))
		if result.is_empty() or p != result[-1]:
			result.append(p)
	if polygon and result.size() > 1 and result[0] == result[-1]:
		result.remove_at(result.size() - 1)
	return result


static func _vertex(p: Vector2, height: float) -> Vector3:
	return Vector3(p.x, height, -p.y)


static func _triangle(tool: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, normal: Vector3) -> void:
	tool.set_normal(normal)
	# Godot front faces wind clockwise when seen from outside.
	tool.add_vertex(a)
	if (b - a).cross(c - a).dot(normal) > 0:
		tool.add_vertex(c)
		tool.add_vertex(b)
	else:
		tool.add_vertex(b)
		tool.add_vertex(c)


static func _cap(tool: SurfaceTool, polygon: PackedVector2Array, height: float, normal: Vector3) -> void:
	var indices := Geometry2D.triangulate_polygon(polygon)
	for i in range(0, indices.size(), 3):
		_triangle(tool, _vertex(polygon[indices[i]], height), _vertex(polygon[indices[i + 1]], height), _vertex(polygon[indices[i + 2]], height), normal)


static func _prism(tool: SurfaceTool, polygon: PackedVector2Array, low: float, high: float) -> void:
	if Geometry2D.is_polygon_clockwise(polygon):
		polygon = polygon.duplicate()
		polygon.reverse()
	_cap(tool, polygon, high, Vector3.UP)
	_cap(tool, polygon, low, Vector3.DOWN)
	for i in polygon.size():
		var a := polygon[i]
		var b := polygon[(i + 1) % polygon.size()]
		var edge := b - a
		var normal := Vector3(edge.y, 0.0, edge.x).normalized()
		_triangle(tool, _vertex(a, low), _vertex(b, low), _vertex(b, high), normal)
		_triangle(tool, _vertex(a, low), _vertex(b, high), _vertex(a, high), normal)


static func _material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.9
	return material
