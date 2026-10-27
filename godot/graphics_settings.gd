extends RefCounted
## Client-only options; building geometry is chosen once per session.
const DEFAULTS := {
	"shadows": true,
	"buildings_3d": true,
	"forest_canopy": true,
	"water_ripples": true,
	"precipitation": true,
	"splashes": true,
	"vehicle_smoke": true,
	"lightning_flashes": true,
}


static func read(config: ConfigFile) -> Dictionary:
	var options := DEFAULTS.duplicate()
	for key in DEFAULTS:
		var value = config.get_value("graphics", key, DEFAULTS[key])
		if value is bool:
			options[key] = value
	return options
