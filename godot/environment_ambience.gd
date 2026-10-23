## Location beds use existing streamed geometry; weather and placed sounds stay independent.
extends RefCounted

const CHUNK_M := 500.0
const BEACH_RANGE_M := 80.0
const NATURAL := ["forest", "wood", "farmland", "meadow", "grassland", "wetland", "scrub"]
const KEYS := ["city_day", "city_night", "rural_day", "rural_night", "beach"]
var _sample_left := 0.0
var _place := {"rural": 0.0, "beach": 0.0, "known": 0.0}
var _gains := {}


func clear() -> void:
	_sample_left = 0.0
	_place = {"rural": 0.0, "beach": 0.0, "known": 0.0}
	for key in KEYS:
		_gains[key] = 0.0


static func polygon_distance(at: Vector2, polygon: PackedVector2Array) -> float:
	if polygon.size() < 3:
		return INF
	if Geometry2D.is_point_in_polygon(at, polygon):
		return 0.0
	var distance := INF
	for i in polygon.size():
		distance = minf(distance, at.distance_to(Geometry2D.get_closest_point_to_segment(at, polygon[i], polygon[(i + 1) % polygon.size()])))
	return distance


static func sample(chunks: Dictionary, origin: Vector2, listener: Vector2) -> Dictionary:
	var world := Vector2(listener.x + origin.x, origin.y - listener.y)
	var grid := world / CHUNK_M - Vector2(0.5, 0.5)
	var base := Vector2i(floori(grid.x), floori(grid.y))
	var fraction := grid - Vector2(base)
	var rural := 0.0
	var known := 0.0
	# Blend adjacent chunk densities instead of switching at the 500 m border.
	for x in 2:
		for y in 2:
			var chunk = chunks.get("%d_%d" % [base.x + x, base.y + y])
			if chunk == null:
				continue
			var weight := (fraction.x if x else 1.0 - fraction.x) * (fraction.y if y else 1.0 - fraction.y)
			known += weight
			rural += weight * (1.0 - smoothstep(5.0, 18.0, float(chunk._data.get("buildings", []).size())))
	var beach := 0.0
	var natural := false
	var cell := Vector2i(floori(world.x / CHUNK_M), floori(world.y / CHUNK_M))
	# Only the listener's chunk and eight neighbours, twice a second.
	for x in range(-1, 2):
		for y in range(-1, 2):
			var chunk = chunks.get("%d_%d" % [cell.x + x, cell.y + y])
			if chunk == null:
				continue
			for area in chunk._data.get("landuse", []):
				if area.size() < 4:
					continue
				var kind := str(area[3])
				if kind == "beach":
					beach = maxf(beach, 1.0 - smoothstep(0.0, BEACH_RANGE_M, polygon_distance(listener, area[2])))
				elif kind in NATURAL and Geometry2D.is_point_in_polygon(listener, area[2]):
					natural = true
	if natural:
		rural = known
	return {"rural": rural, "beach": beach, "known": known}


func mix(chunks: Dictionary, origin: Vector2, listener: Vector2, night: float, winter: float, rain: float, surface: bool, delta: float) -> Dictionary:
	if not surface:
		clear()
		return _gains
	_sample_left -= delta
	if _sample_left <= 0.0:
		_place = sample(chunks, origin, listener)
		_sample_left = 0.5
	var rural: float = _place.rural
	var beach: float = _place.beach * (1.0 - winter)
	var birds := (1.0 - night) * (1.0 - winter) * (1.0 - rain * 0.8)
	var targets := {
		"city_day": (_place.known - rural) * (1.0 - night) * (1.0 - beach * 0.85) * 0.5,
		"city_night": (_place.known - rural) * night * (1.0 - beach * 0.85) * 0.5,
		"rural_day": rural * birds * (1.0 - beach * 0.7) * 0.35,
		"rural_night": rural * (1.0 - birds) * (1.0 - beach * 0.7) * 0.22,
		"beach": beach * 0.45,
	}
	var fade := 1.0 - exp(-delta / 2.0)
	for key in KEYS:
		_gains[key] = lerpf(float(_gains.get(key, 0.0)), float(targets[key]), fade)
	return _gains
