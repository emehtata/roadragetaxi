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


# --- Direct sunlight and building shadows (rrt-018-shadows) ---------------
# The server's sun: `calendar.sun_azimuth_deg`, clockwise from the map's grid
# north; the 3D building view has +x east, +y up, -z north (2D y is south).
const SUN_LOW_DEG := 1.0  # direct sunlight (shadows) begin at this altitude...
const SUN_FULL_DEG := 12.0  # ...and are at full strength from here up
# The light never comes from lower than this, so a low sun's shadow is at
# most 1 / tan(8 deg) ~ 7x the building's height, not tens of times (the
# shadows are faint down there anyway: see sunlight()).
const SHADOW_MIN_ELEVATION_DEG := 8.0
const CLOUD_CLEAR := 0.3  # cloud cover at or below: full sunlight
const CLOUD_OVERCAST := 0.9  # at or above: no direct sun, no shadows
const MOON_MIN_ILLUMINATION := 0.8
const MOON_MAX_LIGHT := 0.30


## How strongly the sun shines directly, 0..1: rises smoothly with the
## altitude and falls smoothly with the cloud cover (0 clear .. 1 overcast).
## Its shadows' contrast follows it; 0 at night and under an overcast sky.
static func sunlight(altitude_deg: float, cloud_cover: float) -> float:
	return _smoother(SUN_LOW_DEG, SUN_FULL_DEG, altitude_deg) * (1.0 - _smoother(CLOUD_CLEAR, CLOUD_OVERCAST, cloud_cover))


## A nearly full Moon lights only a dark sky, and remains much dimmer than the Sun.
static func moonlight(sun_altitude_deg: float, moon_altitude_deg: float, illumination: float, cloud_cover: float) -> float:
	return MOON_MAX_LIGHT * _smoother(-2.0, -8.0, sun_altitude_deg) \
		* _smoother(SUN_LOW_DEG, SUN_FULL_DEG, moon_altitude_deg) \
		* _smoother(MOON_MIN_ILLUMINATION, 1.0, illumination) \
		* (1.0 - _smoother(CLOUD_CLEAR, CLOUD_OVERCAST, cloud_cover))


static func moon_value(state: Dictionary, key: String, fallback: float) -> float:
	var calendar = state.get("calendar")
	var value = calendar.get(key) if calendar is Dictionary else null
	return float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(value) else fallback


static func moon_ambient(color: Color, strength: float) -> Color:
	# Moonlight is a neutral, nearly white light: no blue night tint.
	return color.lerp(Color(0.6, 0.6, 0.6), clampf(strength / MOON_MAX_LIGHT, 0.0, 1.0))


## How far moonlight washes the colours out (0..1, from moonlight()): the eye
## sees a moonlit scene almost in grey.
static func moon_desaturation(strength: float) -> float:
	return clampf(strength / MOON_MAX_LIGHT, 0.0, 1.0) * 0.8


static func moon_shadow(strength: float, artificial_light: float) -> float:
	return strength * (1.0 - _smoother(0.0, 0.15, artificial_light))


## A unit vector towards the sun in the 3D building view's axes.
static func sun_direction(altitude_deg: float, azimuth_deg: float) -> Vector3:
	var elevation := deg_to_rad(maxf(altitude_deg, SHADOW_MIN_ELEVATION_DEG))
	var azimuth := deg_to_rad(azimuth_deg)
	return Vector3(sin(azimuth) * cos(elevation), sin(elevation), -cos(azimuth) * cos(elevation))


## The sun's azimuth from a state; an older server without one: due south.
static func azimuth(state: Dictionary) -> float:
	var calendar = state.get("calendar")
	var value = calendar.get("sun_azimuth_deg") if calendar is Dictionary else null
	return float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(value) else 180.0


## The sky's cloud cover from a state (weather.cloud_cover); unknown: clear.
static func cloud_cover(state: Dictionary) -> float:
	var weather = state.get("weather")
	var value = weather.get("cloud_cover") if weather is Dictionary else null
	return clampf(float(value), 0.0, 1.0) if typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(value) else 0.0
