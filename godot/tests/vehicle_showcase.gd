## Fixed vehicle lineup for visual review. Usage: -- /tmp/vehicles.png day|evening|night close|cars|commercial|bikes|trains|transit|coach_right|coach_left
extends SceneTree
const B3 := preload("res://buildings_3d.gd")
const EntityLayer := preload("res://entity_layer.gd")

func _initialize() -> void:
	call_deferred("capture")

func capture() -> void:
	var args := OS.get_cmdline_user_args()
	var output: String = args[0] if args.size() else "/tmp/vehicles.png"
	var light: String = args[1] if args.size() > 1 else "day"
	var group: String = args[2] if args.size() > 2 else "cars"
	var close := group == "close"
	var coach := group.begins_with("coach_")  # the coaches side on, about 20 deg up: their +y (right) or -y face
	root.size = Vector2i(1400, 800)
	B3.use_shaded()
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 32.0 if coach else 5.5 if close else 9.0 if group == "bikes" else 60.0 if group == "transit" else 32.0 if group == "trains" else 24.0 if group == "commercial" else 18.0
	camera.position = Vector3(6.0, 3.1, 7.0) if close else Vector3(12.0, 15.0, 24.0)
	root.add_child(camera)
	if coach:
		camera.position = Vector3(0.0, 14.6, 40.0 if group == "coach_right" else -40.0)
	camera.look_at(Vector3(0.0, 1.5 if coach else 0.6, 0.0))
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.29, 0.34, 0.39) * (0.3 if light == "night" else 0.65 if light == "evening" else 1.0)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.67, 0.75, 0.95) if light == "night" else Color.WHITE
	env.ambient_light_energy = 0.22 if light == "night" else 0.4 if light == "evening" else 0.7
	# A sky for the glass to reflect, as in the game (the flat colour gave it nothing to mirror)
	env.sky = Sky.new()
	env.sky.sky_material = ProceduralSkyMaterial.new()
	env.background_mode = Environment.BG_SKY
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	camera.environment = env
	camera.make_current()
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45.0, 25.0, 0.0)
	sun.light_energy = 0.08 if light == "night" else 0.5 if light == "evening" else 1.0
	root.add_child(sun)
	var rows := [
		["car", 4.4, 1.8, Color8(235, 177, 30), EntityLayer.CAR_SHAPES[0], 2],
		["car", 3.9, 1.7, Color8(55, 125, 180), EntityLayer.CAR_SHAPES[1], 0],
		["car", 4.8, 1.85, Color8(158, 55, 58), EntityLayer.CAR_SHAPES[2], 0],
		["car", 4.8, 1.9, Color8(80, 100, 94), EntityLayer.CAR_SHAPES[3], 0],
		["car", 4.7, 1.8, Color8(197, 201, 206), EntityLayer.CAR_SHAPES[5], 0],
		["car", 5.1, 2.0, Color8(185, 120, 49), EntityLayer.VAN_SHAPE, 0],
		["bus", 10.0, 2.5, Color8(222, 160, 58), [], 0],
		["truck", 8.0, 2.5, Color8(70, 115, 145), [], 0],
		["motorcycle", 2.1, 0.8, Color8(195, 47, 45), [], 0],
		["bicycle", 1.8, 0.6, Color8(62, 158, 102), [], 0],
		["car", 3.8, 1.7, Color8(95, 175, 132), EntityLayer.CAR_SHAPES[6], 0],
		["car", 5.0, 1.9, Color8(164, 128, 63), EntityLayer.CAR_SHAPES[4], 0],
		["camper_van", 6.0, 2.2, Color8(234, 228, 209), [], 0],
		["tractor", 4.0, 2.0, Color8(205, 120, 35), [], 0],
		["trailer", 5.0, 2.1, Color8(240, 236, 222), [], 0],
		["e_scooter", 1.3, 0.5, Color8(35, 155, 115), [], 0],
		["train", 20.0, 3.0, Color8(230, 230, 225), [], 0],
		["tram", 22.0, 2.6, Color8(120, 175, 205), [], 0],
		["ferry", 32.0, 10.0, Color8(242, 183, 25), [], 0],
		["train_locomotive", 19.0, 3.2, Color8(12, 48, 24), [], 0],
		["train_coach", 24.0, 3.2, Color8(46, 125, 60), [], 0],
	]
	var selected := [16, 20] if coach else [0] if close else [0, 1, 2, 3, 4, 10, 11] if group == "cars" else [5, 6, 7, 12, 13, 14] if group == "commercial" else [19, 20] if group == "trains" else [16, 17, 18] if group == "transit" else [8, 9, 15]
	for j in selected.size():
		var i: int = selected[j]
		var row: Array = rows[i]
		var kind: String = B3.car_model_kind(row[4], row[1]) if row[0] == "car" else "city_bus" if row[0] == "bus" else "box_truck" if row[0] == "truck" else "caravan" if row[0] == "trailer" else row[0]
		var node: Node3D
		var heading := 0.0 if coach else 0.45 if i % 2 else -0.4
		if B3.MODEL_SCENES.has(kind):
			node = B3.MODEL_SCENES[kind].instantiate()
			if kind in ["train_locomotive", "train_coach"]:
				for mesh: MeshInstance3D in node.find_children("*", "MeshInstance3D", true, false):
					for surface in mesh.mesh.get_surface_count():
						var material: Material = mesh.mesh.surface_get_material(surface)
						if material != null and material.resource_name == ("Original teal enamel paint" if kind == "train_locomotive" else "Original warm white outdoor paint"):
							var paint: StandardMaterial3D = material.duplicate()
							paint.albedo_texture = null
							paint.albedo_color = row[3]
							mesh.set_surface_override_material(surface, paint)
			node.scale = B3.model_scale(kind, row[1], row[2])
			for mesh: MeshInstance3D in node.find_children("*", "MeshInstance3D", true, false):
				for surface in mesh.mesh.get_surface_count():
					if mesh.mesh.surface_get_material(surface) != null and mesh.mesh.surface_get_material(surface).resource_name == "glass":
						mesh.set_surface_override_material(surface, B3.car_glazing(mesh.mesh.surface_get_material(surface)))
			node.rotation.y = heading + (0.0 if kind in ["city_bus", "train_locomotive", "train_coach"] else PI / 2.0)
		else:
			var arrays: Dictionary = B3.vehicle_arrays(row[0], row[1], row[2], row[3], B3.LAMPS_ON, {})
			var mesh := B3._mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"])
			node = B3._instance(mesh, B3._shared["car"], B3.LAYER_BUILDINGS)
			node.rotation.y = heading
		var columns := 3 if group == "commercial" else 4 if group == "cars" else 3
		var gap := 16.0 if group == "transit" else 9.0 if group == "commercial" else 5.7 if group == "cars" else 2.4
		node.position = Vector3((j - 0.5) * 26.0, 0.0, 0.0) if coach else Vector3(0.0, 0.0, (j - 1) * 18.0) if group == "transit" else Vector3(0.0, 0.0, (j - 0.5) * 9.0) if group == "trains" else Vector3.ZERO if close else Vector3((j % columns - (columns - 1) * 0.5) * gap, 0.0,
			(j / columns - (selected.size() / columns - 1) * 0.5) * (8.0 if group == "commercial" else gap))
		root.add_child(node)
		if B3.MODEL_SCENES.has(kind):
			var details := B3.model_car_details(row[1], row[2], row[5] if row[0] == "car" else 0, B3.LAMPS_ON,
				0.8 if row[0] in ["bus", "truck", "motorcycle", "tractor"] else 0.5,
				kind in ["saloon", "hatchback", "estate", "suv", "pickup", "sports", "city_car", "panel_van", "box_truck", "motorcycle", "camper_van"])
			var detail_mesh := B3._mesh(details["verts"], details["colors"], details["roof_mask"], PackedVector2Array(), PackedFloat32Array(), details["part"])
			var detail_node := B3._instance(detail_mesh, B3._shared["car"], B3.LAYER_BUILDINGS)
			detail_node.position = node.position
			detail_node.rotation.y = heading
			root.add_child(detail_node)
	for i in 8:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(output)
	quit()
