## Write Godot's licence and its third-party components' notices to a file.
##     godot --headless -s tools/godot_licenses.gd -- OUT_FILE
## windows-release.yml ships the result as licenses/godot/LICENSES.txt.
extends SceneTree


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		push_error("usage: godot --headless -s tools/godot_licenses.gd -- OUT_FILE")
		quit(1)
		return
	var lines := PackedStringArray(["Godot Engine %s" % Engine.get_version_info()["string"], "", Engine.get_license_text(), "",
		"Third-party components in Godot Engine:", ""])
	for component in Engine.get_copyright_info():
		for part in component["parts"]:
			lines.append("%s - %s - %s" % [component["name"], "; ".join(part["copyright"]), part["license"]])
	var licences: Dictionary = Engine.get_license_info()
	for name in licences:
		lines.append_array(["", "---- %s ----" % name, "", licences[name]])
	var file := FileAccess.open(args[0], FileAccess.WRITE)
	if file == null:
		push_error("cannot write %s" % args[0])
		quit(1)
		return
	file.store_string("\n".join(lines) + "\n")
	file.close()
	quit(0)
