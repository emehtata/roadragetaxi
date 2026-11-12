## Native-GPU material comparison; pass --output=PATH and optionally --rtx.
extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const Trial := preload("res://rtx_trial.gd")
var started := 0
var output := ""
var frames := 0

func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--output="):
			output = arg.trim_prefix("--output=")
	call_deferred("run")

func box(at: Vector3, size: Vector3, color: Color, roughness := 0.5) -> void:
	var mesh := MeshInstance3D.new()
	var shape := BoxMesh.new()
	shape.size = size
	mesh.mesh = shape
	mesh.position = at
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	mesh.material_override = material
	root.add_child(mesh)

func run() -> void:
	root.size = Vector2i(1280, 720)
	B3.use_shaded()
	var camera := Camera3D.new()
	camera.position = Vector3(12, 10, 15)
	root.add_child(camera)
	camera.look_at(Vector3(0, 1, 0))
	camera.environment = Environment.new()
	camera.environment.background_mode = Environment.BG_SKY
	camera.environment.sky = Sky.new()
	camera.environment.sky.sky_material = ProceduralSkyMaterial.new()
	camera.environment.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	if Trial.requested() and not Trial.configure(root, camera.environment, "material-probe"):
		quit(2)
		return
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-40, -35, 0)
	sun.shadow_enabled = true
	root.add_child(sun)
	box(Vector3(0,-0.1,0), Vector3(24,0.2,24), Color(0.12,0.14,0.17), 0.08)
	var v := PackedVector3Array([Vector3(-12,0.01,-12),Vector3(12,0.01,-12),Vector3(12,0.01,12),Vector3(-12,0.01,-12),Vector3(12,0.01,12),Vector3(-12,0.01,12)])
	var colors := PackedColorArray()
	colors.resize(6)
	colors.fill(Color(0.35,0.36,0.38))
	var uv := PackedVector2Array()
	uv.resize(6)
	uv.fill(Vector2(0,1))
	var road := MeshInstance3D.new()
	road.mesh = B3._mesh(v,colors,uv,PackedVector2Array(),PackedFloat32Array(),uv)
	road.material_override = B3._shared.road
	road.material_override.set_shader_parameter("wetness",0.8)
	root.add_child(road)
	box(Vector3(-4,1.5,-2),Vector3(2,3,2), Color(0.85,0.04,0.03))
	var car := B3.car_arrays(4.5, 1.8, Color(0.8,0.55,0.02), [0.7,0.4,-0.4,-0.7,0.75,""], 2, B3.LAMPS_ON)
	var car_mesh := MeshInstance3D.new()
	car_mesh.mesh = B3._mesh(car.verts,car.colors,car.roof_mask,PackedVector2Array(),PackedFloat32Array(),car.part)
	car_mesh.material_override = B3._shared.car
	root.add_child(car_mesh)
	var house := B3.build([PackedVector2Array([Vector2(-3,-6),Vector2(3,-6),Vector2(3,-10),Vector2(-3,-10)])],
		[[[90,100,120],0,5.0,[],[180,160,130],2,0]],Vector2.ZERO)
	for instance in B3.meshes(house):
		root.add_child(instance)
	var label := Label.new()
	label.text = "RTX material probe" if Trial.requested() else "Forward+ material probe"
	label.position = Vector2(20,20)
	label.add_theme_font_size_override("font_size",24)
	root.add_child(label)
	started = Time.get_ticks_msec()

func _process(_delta: float) -> bool:
	if started > 0:
		frames += 1
	if frames > 90 and started > 0 and Time.get_ticks_msec() - started > 10000:
		if output != "":
			assert(root.get_texture().get_image().save_png(output) == OK, "Could not save " + output)
		print("MATERIAL_PROBE_COMPLETE")
		quit()
	return false
