extends RefCounted
## Offline SAO atlas; runtime work is one basis and seven band weights.

const STARS_0 := preload("res://assets/sky/stars_0.png")
const STARS_1 := preload("res://assets/sky/stars_1.png")
static var _stars: Array = []

static func stars() -> Array:
	if _stars.is_empty():
		_stars = JSON.parse_string(FileAccess.get_file_as_string("res://assets/sky/stars.json"))
	return _stars

static func direction(row: Array) -> Vector3:
	var ra := deg_to_rad(float(row[1]))
	var dec := deg_to_rad(float(row[2]))
	var p := Vector3(cos(dec)*cos(ra),cos(dec)*sin(ra),sin(dec))
	var east := Vector3(-sin(ra),cos(ra),0)
	var north := Vector3(-sin(dec)*cos(ra),-sin(dec)*sin(ra),cos(dec))
	return (p + 26.0*(east*deg_to_rad(float(row[4])*15.0/3600.0)*cos(dec)+north*deg_to_rad(float(row[5])/3600.0))).normalized()

static func basis(state: Dictionary) -> Basis:
	var columns: Array = state.get("basis",[])
	if columns.size()!=3: return Basis.IDENTITY
	return Basis(Vector3(columns[0][0],columns[0][1],columns[0][2]),Vector3(columns[1][0],columns[1][1],columns[1][2]),Vector3(columns[2][0],columns[2][1],columns[2][2]))

static func night_visibility(sun_alt: float) -> float:
	return 1.0-smoothstep(-18.0,-6.0,sun_alt)

static func limiting_magnitude(_sun_alt: float, pollution: float, moon_alt: float, illumination: float) -> float:
	return clampf(6.0-4.0*clampf(pollution,0,1)-2.0*illumination*smoothstep(0.0,45.0,moon_alt),0.0,6.0)

static func band_weight(band: int, limit: float) -> float:
	return clampf(limit-float(band)+1.0,0,1)*.12*pow(2.5118864,(6.0-float(band))*.5)
