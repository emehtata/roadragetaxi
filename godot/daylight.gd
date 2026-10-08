## godot-lights-01: how bright the world is, as a smooth function of the
## sun's altitude above the horizon (the server's `calendar.sun_altitude_deg`,
## computed for the map's location and date). There are no day/dusk/night
## states: every value here changes continuously with the altitude, the same
## going down at dusk as coming up at dawn, so long Finnish twilights and a
## sun that never sets (or never rises) come out naturally.
##
## - ambient(alt): 1 in full daylight down to 0 in deep night, smootherstep
##   between AMBIENT_NIGHT_DEG and AMBIENT_DAY_DEG
## - artificial(alt): how strongly street lights, headlights and windows
##   show, the other way round and starting while the sun is still up
## - ambient_color(alt): the world's multiply - white by day, cool blue at
##   night (never black)
class_name Daylight

const AMBIENT_DAY_DEG := 8.0  # full daylight from here up
const AMBIENT_NIGHT_DEG := -16.0  # deep night from here down
const LIGHTS_ON_DEG := 10.0  # artificial light starts to show below this
const LIGHTS_FULL_DEG := -8.0  # and is at full strength from here down
const NIGHT := Color(0.2, 0.25, 0.4)  # cold blue ambient at deep night (multiplied over the world)
const TWILIGHT := Color(0.52, 0.58, 0.78)  # bluish, half way


static func _smoother(edge0: float, edge1: float, x: float) -> float:
	var t := clampf((x - edge0) / (edge1 - edge0), 0.0, 1.0)
	return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)  # smootherstep: flat at both ends, no kink


static func ambient(altitude_deg: float) -> float:
	return _smoother(AMBIENT_NIGHT_DEG, AMBIENT_DAY_DEG, altitude_deg)


static func artificial(altitude_deg: float) -> float:
	return 1.0 - _smoother(LIGHTS_FULL_DEG, LIGHTS_ON_DEG, altitude_deg)


## White by day, through a bluish twilight, to the night blue.
static func ambient_color(altitude_deg: float) -> Color:
	var a := ambient(altitude_deg)
	if a >= 0.5:
		return TWILIGHT.lerp(Color.WHITE, (a - 0.5) * 2.0)
	return NIGHT.lerp(TWILIGHT, a * 2.0)


## The sun's altitude from a state: the server's value, else (an older
## server) back from its darkness, which is linear in altitude between -12
## and +6 degrees; no calendar at all: daylight.
static func altitude(state: Dictionary) -> float:
	var calendar = state.get("calendar")
	if not calendar is Dictionary:
		return 90.0
	var altitude_deg = calendar.get("sun_altitude_deg")
	if typeof(altitude_deg) in [TYPE_INT, TYPE_FLOAT] and is_finite(altitude_deg):
		return altitude_deg
	var darkness = calendar.get("darkness")
	if typeof(darkness) in [TYPE_INT, TYPE_FLOAT]:
		return (1.0 - clampf(darkness, 0.0, 1.0)) * 18.0 - 12.0
	return 90.0
