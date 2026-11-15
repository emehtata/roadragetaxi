## Focused VQA-001–005 source/pooled comparison using the audit's checked cameras.
extends "res://tools/visual_quality_audit.gd"

func build(row: Dictionary) -> Node3D:
	if not row.get("source", false):
		return super.build(row)
	var body := Node3D.new()
	var model: Node3D = B3.MODEL_SCENES[row.kind].instantiate()
	model.rotation.y = PI / 2
	model.scale = B3.model_scale(row.kind, row.length, row.width)
	body.add_child(model)
	for mi: MeshInstance3D in model.find_children("*", "MeshInstance3D", true, false):
		for surface in mi.mesh.get_surface_count():
			var original: Material = mi.mesh.surface_get_material(surface)
			if original.resource_name.begins_with("paint"):
				var material := original.duplicate() as StandardMaterial3D
				material.albedo_texture = null
				material.albedo_color = Color8(175,85,48)
				mi.set_surface_override_material(surface, material)
			elif original.resource_name == "glass":
				mi.set_surface_override_material(surface, B3.car_glazing(original))
			elif original.resource_name == "interior":
				mi.visible = false
	return body
