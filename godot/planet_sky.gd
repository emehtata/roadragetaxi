extends RefCounted
## Mercury..Uranus in the sky shader (docs/planet-sky.md): the server's directions, magnitudes and
## altitudes become six display levels. No nodes, lights or textures; one uniform array.

const IDS := ["mercury", "venus", "mars", "jupiter", "saturn", "uranus"]
## Johnson B-V of the six planets, Mallama, Krobusek and Pavlov 2017 (Icarus 282, Table 3: B minus V).
const B_MINUS_V := [0.97, 0.70, 1.36, 0.86, 1.07, 0.50]
## Linear sRGB, the Sun's white (B-V 0.65) balanced to 1: tests/test_planet_sky.py derives these
## from B-V (Ballesteros blackbody, CIE 1931) and fails when they drift.
const COLORS := [Color(1.0, 0.878, 0.709), Color(1.0, 0.98, 0.948), Color(1.0, 0.752, 0.465),
	Color(1.0, 0.918, 0.798), Color(1.0, 0.844, 0.636), Color(0.851, 0.904, 1.0)]
## Naked-eye limiting magnitude at a dark site by the Sun's altitude (the stars' night multiplier is not reused):
## Venus (-4) survives sunset, Jupiter and Mars civil twilight, Uranus only astronomical night.
const TWILIGHT := [Vector2(-18.0, 6.0), Vector2(-12.0, 4.0), Vector2(-6.0, 1.5), Vector2(0.0, -3.0), Vector2(6.0, -5.0)]
const StarSky := preload("res://star_sky.gd")


static func twilight_limit(sun_alt: float) -> float:
	if sun_alt <= TWILIGHT[0].x: return TWILIGHT[0].y
	for i in range(1, TWILIGHT.size()):
		if sun_alt <= TWILIGHT[i].x:
			return lerpf(TWILIGHT[i - 1].y, TWILIGHT[i].y, smoothstep(TWILIGHT[i - 1].x, TWILIGHT[i].x, sun_alt))
	return TWILIGHT[-1].y


## The stars' pollution and Moon-light losses (6 - their limit) lower the planets' limit as well.
static func limiting_magnitude(sun_alt: float, pollution: float, moon_alt: float, illumination: float) -> float:
	return twilight_limit(sun_alt) - (6.0 - StarSky.limiting_magnitude(sun_alt, pollution, moon_alt, illumination))


## Display brightness: the stars' 0.2 dex/magnitude slope, compressed to (0, 1) so Venus never clips
## the colour to white; strictly increasing with brightness.
static func brightness(magnitude: float) -> float:
	var flux := 0.12 * pow(2.5118864, (6.0 - magnitude) * 0.5)
	return flux / (1.0 + flux)


## A planet shows once its magnitude passes the limit, fully 0.4 magnitudes inside it, then fades with the horizon.
static func level(magnitude: float, altitude: float, limit: float) -> float:
	return brightness(magnitude) * smoothstep(0.0, 0.4, limit - magnitude) * smoothstep(0.0, 5.0, altitude)


## Six display levels and unit directions from the server state; a missing, unsupported or
## unavailable body is 0 (hidden, never stale).
static func levels(state: Dictionary, limit: float) -> Array:
	var out := [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
	if not state.get("supported", false): return out
	for body: Dictionary in state.get("bodies", []):
		var index: int = IDS.find(body.get("id", ""))
		if index < 0 or not body.has("dir") or not (body["mag"] is float or body["mag"] is int): continue
		out[index] = level(float(body["mag"]), float(body["alt"]), limit)
	return out


static func directions(state: Dictionary) -> PackedVector4Array:
	var out := PackedVector4Array()
	out.resize(6)
	for body: Dictionary in state.get("bodies", []):
		var index: int = IDS.find(body.get("id", ""))
		if index >= 0 and body.has("dir"):
			var d: Array = body["dir"]
			out[index] = Vector4(d[0], d[1], d[2], 0.0)
	return out
