## Development inspection only: no camera or input changes in the game.
## godot --path godot --script res://tools/inspect_home_interior_3d.gd -- --index=0 --screenshot=/tmp/interior.png
extends SceneTree


func _initialize() -> void:
	call_deferred("_show")


func _show() -> void:
	var path := "res://tests/data/home_plans.json"
	var index := 0
	var screenshot := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--plan="):
			path = arg.trim_prefix("--plan=")
		elif arg.begins_with("--index="):
			index = int(arg.trim_prefix("--index="))
		elif arg.begins_with("--screenshot="):
			screenshot = arg.trim_prefix("--screenshot=")
	var data = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (data is Dictionary or (data is Array and index >= 0 and index < data.size())):
		printerr("Expected a plan dictionary or a valid index into a plan array: ", path)
		quit(1)
		return
	var plan: Dictionary = data[index] if data is Array else data
	var interior := preload("res://home_interior_3d.gd").new()
	root.add_child(interior)
	if not interior.load_plan(plan):
		printerr("Invalid floor plan: ", path)
		quit(1)
		return
	root.size = Vector2i(1280, 900)
	var bounds: AABB = interior.get_node("Surfaces").get_aabb()
	var centre := bounds.get_center()
	var span := maxf(bounds.size.x, bounds.size.z)
	var camera := Camera3D.new()
	root.add_child(camera)
	camera.position = centre + Vector3(0.65, 1.2, 0.8) * span
	camera.look_at(centre)
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = span * 1.65
	camera.current = true
	var light := DirectionalLight3D.new()
	root.add_child(light)
	light.rotation_degrees = Vector3(-60, -30, 0)
	light.light_energy = 1.2
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.background_mode = Environment.BG_COLOR
	environment.environment.background_color = Color("24303d")
	environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.environment.ambient_light_color = Color.WHITE
	environment.environment.ambient_light_energy = 0.55
	root.add_child(environment)
	if screenshot != "":
		await RenderingServer.frame_post_draw
		var error := root.get_texture().get_image().save_png(screenshot)
		if error != OK:
			printerr("Could not save screenshot: ", error)
		quit(0 if error == OK else 1)
