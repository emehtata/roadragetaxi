extends SceneTree

const Trial := preload("res://rtx_trial.gd")


func _initialize() -> void:
	assert(Trial.quality(PackedStringArray()) == "native")
	assert(Trial.quality(PackedStringArray(["--rtx-quality"])) == "")
	assert(Trial.quality(PackedStringArray(["--rtx-quality", "quality"])) == "quality")
	assert(Trial.probe("unsupported").error != "")
	var b3 := preload("res://buildings_3d.gd")
	b3.use_shaded()
	var layer := b3.new()
	var road := b3.road_material_copy()
	layer.set_surface_scale(24.0)
	assert(is_equal_approx(road.get_shader_parameter("surface_pixels_per_m"), 24.0))
	var next_road := b3.road_material_copy()
	assert(is_equal_approx(next_road.get_shader_parameter("surface_pixels_per_m"), 24.0))
	layer.set_surface_scale(4.0)
	assert(is_equal_approx(next_road.get_shader_parameter("surface_pixels_per_m"), 4.0))
	layer.free()
	var report := Trial.probe("native")
	if not ClassDB.class_has_method("Environment", "set_pathtracing_enabled"):
		assert(not report.available and "NVIDIA" in report.error)
	elif DisplayServer.get_name() == "headless":
		assert(not report.available)  # API presence alone must not enable an unavailable GPU path.
	else:
		assert(report.available, str(report))
		var view := SubViewport.new()
		var environment := Environment.new()
		assert(Trial.configure(view, environment, "capability-test"))
		assert(environment.call("is_pathtracing_enabled"))
		assert(environment.call("get_pathtracing_max_bounces") == 2)
		assert(is_equal_approx(view.scaling_3d_scale, 0.66 if Trial.quality() == "quality" else 1.0))
		assert(not view.get("frame_generation"))
		view.free()
	print("RTX_TRIAL_TEST: passed")
	quit()
