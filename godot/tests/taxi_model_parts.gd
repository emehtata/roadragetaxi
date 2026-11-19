## The taxi's GLB (docs/specs/taxi-model-seats.md): no interior surface, every LOD inside the body, the sign on the roof.
extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const Entities := preload("res://entity_layer.gd")
const TAXI_LENGTH := 4.6
const TAXI_WIDTH := 1.8

var failures := 0


func _initialize() -> void:
	test_no_interior_surface()
	test_taxi_parts_inside_body()
	test_roof_sign_on_roof()
	print("taxi model parts: %d failed" % failures)
	quit(int(failures > 0))


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		push_error(message)


func surface_name(mesh: ArrayMesh, surface: int) -> String:
	var material := mesh.surface_get_material(surface)
	return "" if material == null else str(material.resource_name)


func test_no_interior_surface() -> void:
	for kind: String in ["saloon", "city_car"]:
		var mesh := B3.merged_model(kind)
		for surface in mesh.get_surface_count():
			check(surface_name(mesh, surface) != "interior", "%s has an interior surface" % kind)


## The scaled model's paint top (its roof).
func paint_roof(mesh: ArrayMesh, scale: Vector3) -> float:
	if B3.COZY_CARS.has("saloon") and mesh==B3.merged_model("saloon"): return B3.COZY_CARS.saloon.height*scale.y
	var top := -INF
	for surface in mesh.get_surface_count():
		if surface_name(mesh, surface).begins_with("paint"):
			for v: Vector3 in mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
				top = maxf(top, v.y * scale.y)
	return top


func test_taxi_parts_inside_body() -> void:
	var kind := B3.car_model_kind(Entities.CAR_SHAPES[0], TAXI_LENGTH)
	var scale := B3.model_scale(kind, TAXI_LENGTH, TAXI_WIDTH)
	var mesh := B3.merged_model(kind)
	var roof := paint_roof(mesh, scale)
	for surface in mesh.get_surface_count():
		var vertices: PackedVector3Array = mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]
		var used := {}
		for i: int in mesh.surface_get_arrays(surface)[Mesh.ARRAY_INDEX]:
			used[i] = true
		for lod: Dictionary in RenderingServer.mesh_get_surface(mesh.get_rid(), surface).get("lods", []):
			var data: PackedByteArray = lod["index_data"]
			var wide := vertices.size() > 65535
			for at in range(0, data.size(), 4 if wide else 2):
				used[data.decode_u32(at) if wide else data.decode_u16(at)] = true
		var worst := 0.0
		for i: int in (used.keys() if not used.is_empty() else range(vertices.size())):
			var v := vertices[i] * scale
			check(v.y <= roof + 0.01, "%s surface %s vertex %s above the roof %.2f" % [kind, surface_name(mesh, surface), v, roof])
			check(absf(v.x) <= TAXI_WIDTH * 0.5 + 0.06, "%s surface %s vertex %s outside the body" % [kind, surface_name(mesh, surface), v])
			if v.y > roof + 0.01 or absf(v.x) > TAXI_WIDTH * 0.5 + 0.06:
				return


func test_roof_sign_on_roof() -> void:
	var kind := B3.car_model_kind(Entities.CAR_SHAPES[0], TAXI_LENGTH)
	var roof := paint_roof(B3.merged_model(kind), B3.model_scale(kind, TAXI_LENGTH, TAXI_WIDTH))
	var details := B3.cozy_car_details(kind,TAXI_LENGTH,TAXI_WIDTH,2,0)
	var bottom := INF
	for v: Vector3 in details["verts"]:
		if v.y > 1.0:  # the sign, not the lamp lenses
			bottom = minf(bottom, v.y)
	check(absf(bottom - roof) <= 0.05, "roof sign bottom %.3f vs paint roof %.3f" % [bottom, roof])
