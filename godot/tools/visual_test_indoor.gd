## Use disposable settings before the normal startup/main scenes instantiate.
extends SceneTree

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var scenario: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[args.find("--visual-test") + 1]))
	ProjectSettings.set_setting("application/config/name", scenario["verification_user_dir"])
	DirAccess.make_dir_recursive_absolute(OS.get_user_data_dir().path_join("shader_cache"))
	call_deferred("change_scene_to_file", "res://startup.tscn")
