## Where the game's files and the simulation are, in the repo and in a
## release. In the repo (the editor, make run) the Python package is at
## ../src/theroadragetrip and the server runs from .venv; an exported
## release (windows-release.yml) has the PyInstaller-built server beside the
## game's .exe, and the package's data (sounds, images, assets) inside it:
##
##   RoadRageTrip.exe, RoadRageTrip.pck
##   server/RoadRageServer(.exe)
##   server/_internal/theroadragetrip/{assets,img,sounds}
extends RefCounted


static func exported() -> bool:
	return OS.has_feature("template")


static func release_dir() -> String:
	return OS.get_executable_path().get_base_dir()


## The Python package's directory (assets/, img/, sounds/ under it).
static func package_root() -> String:
	if exported():
		return release_dir().path_join("server/_internal/theroadragetrip")
	return ProjectSettings.globalize_path("res://").path_join("../src/theroadragetrip").simplify_path()


static func package_path(relative: String) -> String:
	return package_root().path_join(relative)


## [program, arguments] that run the simulation server with `args`.
static func server_command(args: Array) -> Array:
	if exported():
		var server := release_dir().path_join("server/RoadRageServer" + (".exe" if OS.get_name() == "Windows" else ""))
		return [server, args]
	var root := ProjectSettings.globalize_path("res://..").simplify_path()
	var python := root.path_join(".venv/Scripts/python.exe" if OS.get_name() == "Windows" else ".venv/bin/python")
	if OS.get_name() == "Windows":  # no /usr/bin/env: the environment goes in through the command line instead
		return ["cmd.exe", ["/c", "set", "PYTHONPATH=" + root.path_join("src"), "&&", python, "-m", "theroadragetrip.server"] + args]
	return ["/usr/bin/env", ["PYGAME_HIDE_SUPPORT_PROMPT=1", "PYTHONPATH=" + root.path_join("src"), python, "-m", "theroadragetrip.server"] + args]
