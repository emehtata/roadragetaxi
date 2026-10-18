## Flat footprints and palette helpers shared with the 3D renderer.
extends RefCounted

const WINDOW := Color8(58, 80, 94)
const STOREFRONT := Color8(84, 106, 122)
const DOOR := Color8(58, 48, 42)
const WINDOW_LIT := Color8(232, 189, 108)
const LIT_PROBABILITY := [0.12, 0.08, 0.03]  # other / house / storefront
const ROOF_SNOW := Color8(215, 224, 232)  # cooler than ground snow, so roof edges stay visible


static func signed_area(polygon: PackedVector2Array) -> float:
	var area := 0.0
	for i in polygon.size():
		area += polygon[i].cross(polygon[(i + 1) % polygon.size()])
	return area / 2.0


## A deterministic unit value per window, seeded by the building's
## position - the same after every reload.
static func unit(seed: float) -> float:
	var f := sin(seed * 12.9898) * 43758.5453
	return f - floor(f)


## One chunk's buildings as triangle lists: {"points", "colors", "indices"}
## for the buildings, {"lit_points", "lit_indices"} for the lit windows'
## glow, and per building the screen hull (headlights skip it).
## `buildings`: footprints (layer coordinates); `styles`: the server's
## [roof, gabled, height, entrances, wall, floors, category].
static func build(buildings: Array, styles: Array, _origin: Vector2, _view_centre := Vector2.ZERO, snow_cover := 0.0) -> Dictionary:
	var out := {"snow_cover": snow_cover, "points": PackedVector2Array(), "colors": PackedColorArray(), "indices": PackedInt32Array(),
		"lit_points": PackedVector2Array(), "lit_indices": PackedInt32Array(), "hulls": [],
		"arena_points": PackedVector2Array(), "arena_indices": PackedInt32Array(),
		"stats": {"buildings": 0, "walls": 0, "windows": 0, "lit": 0}}  # counts for the performance report
	# Flat mode uses the exact footprint, with no height or view projection.
	for i in buildings.size():
		var footprint: PackedVector2Array = buildings[i]
		if footprint.size() >= 3 and not Geometry2D.triangulate_polygon(footprint).is_empty():
			var style: Array = styles[i] if i < styles.size() else []
			var color := Color8(int(style[0][0]), int(style[0][1]), int(style[0][2])) if not style.is_empty() else Color8(83, 86, 87)
			_polygon(out, footprint, color.lerp(ROOF_SNOW, clampf(snow_cover, 0.0, 1.0)))
			out["hulls"].append(footprint)
			out["stats"]["buildings"] += 1
	return out


static func _polygon(out: Dictionary, polygon: PackedVector2Array, color: Color) -> void:
	var triangles := Geometry2D.triangulate_polygon(polygon)
	if triangles.is_empty():
		return
	var base: int = out["points"].size()
	out["points"].append_array(polygon)
	for i in polygon.size():
		out["colors"].append(color)
	for t in triangles:
		out["indices"].append(base + t)
