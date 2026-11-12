## check_export_pck.sh: load the exported pck in a bare project; every res:// path given must exist in it.
extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if not ProjectSettings.load_resource_pack(args[0]):
		printerr("cannot load ", args[0])
		quit(1)
		return
	var missing := Array(args.slice(1)).filter(func(p: String) -> bool: return not ResourceLoader.exists(p))
	print("pck: %d of %d models and textures present" % [args.size() - 1 - missing.size(), args.size() - 1])
	for p in missing:
		printerr("MISSING from the pck: ", p)
	quit(1 if missing else 0)
