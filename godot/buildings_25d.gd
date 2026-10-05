## Buildings in 2.5D (godot-17): the map stays top-down; only a building's
## volume is projected. A point at height h on the building is drawn at its
## ground position plus lift(h):
##
##   lift(h) = LEAN * min(h * HEIGHT_SCALE, MAX_DEPTH_M)
##
## in map metres (layer coordinates, y down), the same for every building -
## independent of the player, the camera position and the zoom (the zoom
## scales it like everything else). LEAN, HEIGHT_SCALE and the cap are
## Pygame's oblique roof offset (render/buildings.py: roof = (x - 0.7 d,
## y - d), d = 0.35 h px/m, at most 100 px = 11.1 m at the default 9 px/m).
##
## The footprint stays where the map has it. Of its walls, those facing
## away from LEAN (outward normal . LEAN < 0: the south and east sides)
## are visible, drawn far to near, then the roof - the footprint lifted by
## the full height - and its gabled facets. Windows and doors lie on the
## visible walls. Everything for one chunk is built once, at load, into
## one coloured triangle list in painter's order (shadow, base, walls,
## windows, doors, roof), plus a small list of the lit windows' glow.
extends RefCounted

const LEAN := Vector2(-0.7, -1.0)  # screen direction of "up"
const HEIGHT_SCALE := 0.35  # metres of lift per metre of height
const MAX_DEPTH_M := 100.0 / 9.0  # Pygame's 100 px cap at its 9 px/m
const SHADOW := Color8(45, 42, 39, 110)
const RIDGE := Color8(58, 55, 52)
const WINDOW := Color8(58, 80, 94)
const STOREFRONT := Color8(84, 106, 122)
const DOOR := Color8(58, 48, 42)
const WINDOW_LIT := Color8(232, 189, 108)  # render/buildings.py WINDOW_LIT_COLOR
const LIT_PROBABILITY := [0.12, 0.08, 0.03]  # other / house / storefront (render/buildings.py)
const CANOPY_POST := Color8(105, 110, 112)


## The screen offset of height h (metres) above the ground.
static func lift(height: float) -> Vector2:
	return LEAN * minf(maxf(height, 0.0) * HEIGHT_SCALE, MAX_DEPTH_M)


static func signed_area(polygon: PackedVector2Array) -> float:
	var area := 0.0
	for i in polygon.size():
		area += polygon[i].cross(polygon[(i + 1) % polygon.size()])
	return area / 2.0


## Indices of the walls (edge i: point i to i + 1) seen from above-front:
## outward normal against the lean. Works for any simple polygon, either winding.
static func visible_walls(footprint: PackedVector2Array) -> PackedInt32Array:
	var walls := PackedInt32Array()
	var outward_sign := -1.0 if signed_area(footprint) > 0.0 else 1.0  # y-down canvas: positive area = clockwise on screen, outward = -perpendicular
	for i in footprint.size():
		var edge := footprint[(i + 1) % footprint.size()] - footprint[i]
		if edge.length_squared() < 1e-6:
			continue
		var normal := Vector2(-edge.y, edge.x).normalized() * outward_sign
		if normal.dot(LEAN) < -1e-6:
			walls.append(i)
	return walls


## A deterministic unit value per window (render/buildings.py
## _pseudo_random_unit), seeded by the building's position - the same after
## every reload (Pygame seeds by id(), which changes every run).
static func unit(seed: float) -> float:
	var f := sin(seed * 12.9898) * 43758.5453
	return f - floor(f)


## One chunk's buildings as triangle lists: {"points", "colors", "indices"}
## for the buildings, {"lit_points", "lit_indices"} for the lit windows'
## glow, and per building the screen hull (headlights skip it).
## `buildings`: footprints (layer coordinates); `styles`: the server's
## [roof, gabled, height, entrances, wall, floors, category].
static func build(buildings: Array, styles: Array, origin: Vector2) -> Dictionary:
	var out := {"points": PackedVector2Array(), "colors": PackedColorArray(), "indices": PackedInt32Array(),
		"lit_points": PackedVector2Array(), "lit_indices": PackedInt32Array(), "hulls": []}
	var order: Array = []
	for i in buildings.size():
		var footprint: PackedVector2Array = buildings[i]
		if footprint.size() >= 3 and not Geometry2D.triangulate_polygon(footprint).is_empty():
			var centre := Vector2.ZERO
			for p in footprint:
				centre += p
			order.append([centre / footprint.size(), i])
	order.sort_custom(func(a, b): return a[0].dot(LEAN) > b[0].dot(LEAN))  # far (along the lean) first
	for entry in order:
		var style: Array = styles[entry[1]] if entry[1] < styles.size() else []
		_building(out, buildings[entry[1]], style, entry[0], origin)
	return out


static func _quad(out: Dictionary, a: Vector2, b: Vector2, c: Vector2, d: Vector2, color: Color, key := "") -> void:
	var points: PackedVector2Array = out[key + "points"]
	var base := points.size()
	points.append_array(PackedVector2Array([a, b, c, d]))
	if key == "":
		out["colors"].append_array(PackedColorArray([color, color, color, color]))
	out[key + "indices"].append_array(PackedInt32Array([base, base + 1, base + 2, base, base + 2, base + 3]))


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


static func _shade(color: Color, normal: Vector2) -> Color:
	var f := 0.72 + 0.28 * clampf(-normal.dot(LEAN.normalized()), 0.0, 1.0)  # walls facing the viewer are lighter
	return Color(color.r * f, color.g * f, color.b * f, color.a)


static func _building(out: Dictionary, footprint: PackedVector2Array, style: Array, centre: Vector2, origin: Vector2) -> void:
	var roof_color := Color8(int(style[0][0]), int(style[0][1]), int(style[0][2])) if style.size() > 0 else Color8(83, 86, 87)
	var height: float = style[2] if style.size() > 2 else 8.0
	var wall_color := Color8(int(style[4][0]), int(style[4][1]), int(style[4][2])) if style.size() > 4 else Color8(139, 139, 137)
	var floors: int = int(style[5]) if style.size() > 5 else maxi(1, roundi(height / 3.0))
	var category: int = int(style[6]) if style.size() > 6 else 0
	var up := lift(height)
	var depth := up.length()
	var roof := footprint.duplicate()
	for i in roof.size():
		roof[i] += up
	# A soft shadow on the ground, away from the lean (one, under the volume).
	var shadow := footprint.duplicate()
	for i in shadow.size():
		shadow[i] -= LEAN.normalized() * clampf(depth * 0.25, 0.3, 2.0)
	_polygon(out, shadow, SHADOW)
	_polygon(out, footprint, wall_color.darkened(0.25))  # the base: no gap at the wall feet
	var outward_sign := -1.0 if signed_area(footprint) > 0.0 else 1.0
	var walls := Array(visible_walls(footprint))
	walls.sort_custom(func(a, b): return (footprint[a] + footprint[(a + 1) % footprint.size()]).dot(LEAN) > (footprint[b] + footprint[(b + 1) % footprint.size()]).dot(LEAN))
	var stories := mini(floors, maxi(1, int(depth * 9.0 / 3.0)))  # Pygame: at most a floor per 3 px of facade
	var seed_base := roundf(centre.x + origin.x) * 0.0001 + roundf(-centre.y + origin.y) * 0.00013
	for i in walls:
		var a := footprint[i]
		var b := footprint[(i + 1) % footprint.size()]
		var edge := b - a
		var normal := Vector2(-edge.y, edge.x).normalized() * outward_sign
		_quad(out, a, b, b + up, a + up, _shade(wall_color, normal))
		_windows(out, a, b, up, stories, category, seed_base + i * 7.13)
	_doors(out, footprint, style[3] if style.size() > 3 else [], walls, up, stories, origin)
	_polygon(out, roof, roof_color)
	if style.size() > 1 and int(style[1]) == 1:
		_gabled(out, roof, roof_color)
	var hull := Geometry2D.convex_hull(footprint + roof)
	out["hulls"].append(hull)


## render/buildings.py _iter_building_window_slots on a 2.5D wall: up to 3
## windows a floor (2 on a house, every other floor), centred along the
## wall, a storefront row on a commercial ground floor; lit at night by
## Pygame's probabilities, deterministically.
static func _windows(out: Dictionary, a: Vector2, b: Vector2, up: Vector2, stories: int, category: int, seed: float) -> void:
	var length := a.distance_to(b)
	if length < 12.0 / 9.0 or up.length() < 0.5:
		return
	var house := category == 1
	var along := (b - a) / length
	var count := clampi(int(length / ((44.0 if house else 32.0) / 9.0)), 1, 2 if house else 3)
	var floor_up := up / stories
	for f in stories:
		if house and stories > 1 and f % 2 == 1:
			continue
		var storefront := category == 2 and f == 0
		var size := 0.55 * (1.45 if storefront else 0.75 if house else 1.0)
		var half := length / (count + 2) * 0.45 / 2.0 * (1.35 if storefront else 0.75 if house else 1.0)
		var bottom := up * (0.18 + 0.64 * (f + 0.5) / stories) - floor_up * size * 0.5
		for w in count:
			var centre := a + (b - a) * ((w + 1.0) / (count + 1.0)) + bottom
			var p := [centre - along * half, centre + along * half, centre + along * half + floor_up * size, centre - along * half + floor_up * size]
			_quad(out, p[0], p[1], p[2], p[3], STOREFRONT if storefront else WINDOW)
			if unit(seed + f * 3.71 + w * 1.37) < LIT_PROBABILITY[2 if storefront else category if category == 1 else 0]:
				_quad(out, p[0], p[1], p[2], p[3], WINDOW_LIT, "lit_")


## Doors at the OSM entrances, on the nearest wall if that wall is
## visible (render/buildings.py does the same on its facades): one storey high.
static func _doors(out: Dictionary, footprint: PackedVector2Array, entrances: Array, walls: Array, up: Vector2, stories: int, origin: Vector2) -> void:
	for entrance in entrances:
		var at := MapMath.point(origin, entrance[0], entrance[1])
		var best := -1
		var best_distance := INF
		for i in footprint.size():
			var d := Geometry2D.get_closest_point_to_segment(at, footprint[i], footprint[(i + 1) % footprint.size()]).distance_to(at)
			if d < best_distance:
				best_distance = d
				best = i
		if best < 0 or not walls.has(best):
			continue
		var a := footprint[best]
		var b := footprint[(best + 1) % footprint.size()]
		var along := (b - a).normalized()
		var foot := Geometry2D.get_closest_point_to_segment(at, a, b)
		var half := clampf(a.distance_to(b) * 0.22, 0.33, 1.22) / 2.0
		var top := up / stories * 0.68
		_quad(out, foot - along * half, foot + along * half, foot + along * half + top, foot - along * half + top, DOOR)


## render/buildings.py _draw_gabled_roof on the raised roof: two facets
## along the longest edge, one lighter, one darker, and the ridge.
static func _gabled(out: Dictionary, roof: PackedVector2Array, color: Color) -> void:
	var longest := 0
	for i in roof.size():
		if roof[i].distance_squared_to(roof[(i + 1) % roof.size()]) > roof[longest].distance_squared_to(roof[(longest + 1) % roof.size()]):
			longest = i
	var axis := (roof[(longest + 1) % roof.size()] - roof[longest]).normalized()
	var centre := Vector2.ZERO
	for p in roof:
		centre += p
	centre /= roof.size()
	var normal := Vector2(-axis.y, axis.x)
	var lo := INF
	var hi := -INF
	for p in roof:
		lo = minf(lo, (p - centre).dot(axis))
		hi = maxf(hi, (p - centre).dot(axis))
	var far := 10000.0
	for side: float in [1.0, -1.0]:
		var half := PackedVector2Array([centre - axis * far, centre + axis * far, centre + axis * far + normal * side * far, centre - axis * far + normal * side * far])
		var shade := color.lightened(14.0 / 255.0) if side > 0.0 else color.darkened(12.0 / 255.0)
		for facet in Geometry2D.intersect_polygons(roof, half):
			_polygon(out, facet, shade)
	var r0 := centre + axis * lo
	var r1 := centre + axis * hi
	var n := normal * 0.12
	_quad(out, r0 - n, r1 - n, r1 + n, r0 + n, RIDGE)


## Canopies (open roofs) raised by their height: four thin posts from the
## ground corners up to the roof - drawn under the vehicles; the roof itself
## stays see-through above them (chunk_detail.draw_canopies, lifted).
static func canopy_posts(out: Dictionary, canopy: PackedVector2Array, height: float) -> void:
	var up := lift(height)
	for p in canopy:
		var side := Vector2(-up.y, up.x).normalized() * 0.12
		_quad(out, p - side, p + side, p + up + side, p + up - side, CANOPY_POST)
