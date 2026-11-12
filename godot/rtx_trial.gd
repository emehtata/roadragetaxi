extends RefCounted
## Optional NVIDIA fork APIs are discovered at runtime so upstream Godot still loads.


static func requested() -> bool:
	return "--rtx" in OS.get_cmdline_user_args()


static func quality(args := OS.get_cmdline_user_args()) -> String:
	var at: int = args.find("--rtx-quality")
	if at < 0:
		return "native"
	return args[at + 1] if at + 1 < args.size() else ""


static func probe(selected: String) -> Dictionary:
	var info := {"available": false, "error": "", "quality": selected,
		"engine": Engine.get_version_info(), "renderer": RenderingServer.get_current_rendering_method(),
		"driver": RenderingServer.get_current_rendering_driver_name(), "gpu": RenderingServer.get_video_adapter_name(),
		"executable": OS.get_executable_path(), "custom0_patch": OS.has_feature("rrt_rtx_custom0")}
	var manifest_path := OS.get_executable_path().get_base_dir().path_join("rtx-build.json")
	if FileAccess.file_exists(manifest_path):
		var manifest = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
		if manifest is Dictionary:
			info["source_commit"] = manifest.get("source_commit", "unrecorded")
	if selected not in ["native", "quality"]:
		info.error = "Use --rtx-quality native or quality."
	elif not ClassDB.class_has_method("Environment", "set_pathtracing_enabled"):
		info.error = "This engine has no NVIDIA path tracer. Supply the NVIDIA fork with WINDOWS_RTX_GODOT."
	elif not OS.has_feature("rrt_rtx_custom0"):
		info.error = "This trial needs tools/rtx/custom0.patch applied to the pinned NVIDIA fork (procedural building windows)."
	elif info.renderer != "forward_plus" or info.driver != "vulkan":
		info.error = "RTX requires --rendering-method forward_plus --rendering-driver vulkan."
	elif not ClassDB.class_has_integer_constant("RenderingDevice", "SUPPORTS_RAYTRACING_PIPELINE"):
		info.error = "This engine does not expose ray tracing pipeline support."
	else:
		var device := RenderingServer.get_rendering_device()
		var rt := ClassDB.class_get_integer_constant("RenderingDevice", "SUPPORTS_RAYTRACING_PIPELINE")
		if device == null or not device.has_feature(rt):
			info.error = "The selected Vulkan device does not support ray tracing pipelines."
		elif not Engine.has_singleton("Streamline"):
			info.error = "Streamline is unavailable. Use a Windows build with Streamline enabled."
		else:
			var streamline := Engine.get_singleton("Streamline")
			for feature in ["DLSS", "DLSS_RR"]:
				var constant: String = "STREAMLINE_CAPABILITY_" + feature
				if not ClassDB.class_has_integer_constant("Streamline", constant) or not streamline.call("get_capability", ClassDB.class_get_integer_constant("Streamline", constant)):
					info.error = feature + " is unavailable. Check the RTX GPU driver and Streamline runtime DLLs beside the engine."
					break
			if not ClassDB.class_has_integer_constant("Viewport", "SCALING_3D_MODE_DLSS"):
				info.error = "This engine does not expose DLSS viewport scaling."
	info.available = info.error == ""
	return info


static func configure(view: Viewport, environment: Environment, label: String) -> bool:
	var info := probe(quality())
	info["view"] = label
	if not info.available:
		printerr("RTX_TRIAL " + JSON.stringify(info))
		return false
	# Compile before publishing a trial frame instead of capturing placeholder materials.
	ProjectSettings.set_setting("rendering/pathtracing/async_shader_compilation", false)
	var scale := 0.66 if quality() == "quality" else 1.0
	view.set("scaling_3d_mode", ClassDB.class_get_integer_constant("Viewport", "SCALING_3D_MODE_DLSS"))
	view.scaling_3d_scale = scale
	view.set("frame_generation", false)
	environment.call("set_pathtracing_samples_per_pixel", 1)
	environment.call("set_pathtracing_max_bounces", 2)
	environment.call("set_pathtracing_denoiser", ClassDB.class_get_integer_constant("RenderingServer", "PT_DENOISER_DLSS_RAY_RECONSTRUCTION"))
	environment.call("set_pathtracing_enabled", true)
	info["async_shader_compilation"] = false
	info["status"] = "configured"
	info["scale"] = scale
	info["samples_per_pixel"] = 1
	info["max_bounces"] = 2
	info["frame_generation"] = false
	print("RTX_TRIAL " + JSON.stringify(info))
	return true
