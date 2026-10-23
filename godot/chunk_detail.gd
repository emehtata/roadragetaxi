## The rest of a chunk's static world (godot-16), drawn into the chunk's canvas items (map_chunk.gd creates
## the layers; this holds the drawing). Batched: one call per style where
## a chunk has many of a thing (multiline, triangle arrays), never a node
## per object. Sizes in metres, with minimum pixel sizes where
## needed (chunk._px). Everything here is drawing only.
extends RefCounted

const RAIL_COLOR := Color8(150, 145, 135)
const TIE_COLOR := Color8(90, 65, 45)
const BALLAST_COLOR := Color8(108, 100, 92)
const GUARDRAIL_COLOR := Color8(196, 200, 204)
const HALF_GAUGE := 1.435 / 2.0
const HALF_TIE := 2.6 / 2.0
const TIE_SPACING := 2.0
const BUMP_LENGTHS := {"table": 2.2, "bump": 0.6, "cushion": 0.4, "hump": 0.6}
const B3 := preload("res://buildings_3d.gd")
const OPEN_ROOF := Color8(138, 145, 148, 185)
const OPEN_ROOF_EDGE := Color8(65, 69, 71, 235)
const OPEN_ROOF_POLE := Color8(105, 110, 112)


static func _rgb(values: Array) -> Color:
	return Color8(int(values[0]), int(values[1]), int(values[2]))


static func _valid(polygon: PackedVector2Array) -> bool:
	return polygon.size() >= 3 and not Geometry2D.triangulate_polygon(polygon).is_empty()


const RINK_ICE := Color8(196, 222, 236)  # a flooded, frozen sports field
const FIELDS_FROZEN_WINTER_WEIGHT := 0.5  # map_style.py: the same, for the ice grip


## Landuse fills: each piece in its kind's colour, green kinds through the
## season (area[1] 1), sports fields frozen to ice in winter (2).
static func draw_areas(chunk, node: Node2D, key: String) -> void:
	for area in chunk._data.get(key, []):
		var polygon: PackedVector2Array = chunk._points(area[2])
		if _valid(polygon):
			var color := _rgb(area[0])
			match int(area[1]):
				1: color = chunk.seasonal_color(color, chunk._season)
				2: color = RINK_ICE if chunk._season[0] >= FIELDS_FROZEN_WINTER_WEIGHT else chunk.seasonal_color(color, chunk._season)
			if key == "landuse" and area.size() > 3 and str(area[3]) in ["forest", "wood"]:
				var uv := PackedVector2Array()
				uv.resize(polygon.size())
				uv.fill(Vector2(1.0 + float(chunk._season[0]), float(chunk._season[3])))
				node.draw_polygon(polygon, PackedColorArray([color]), uv)
			else:
				node.draw_colored_polygon(polygon, color)


## Above all ground fills: smaller grass plots must not paint over headstones.
static func draw_site_details(chunk, node: Node2D) -> void:
	var areas: Array = chunk._data.get("landuse", [])
	for index in areas.size():
		var area = areas[index]
		if area.size() <= 3:
			continue
		if not chunk._site_details.has(index):
			chunk._site_details[index] = site_detail_positions(chunk._points(area[2]), str(area[3]), chunk._origin)
		for at in chunk._site_details[index]:
			draw_site_detail(node, at, str(area[3]), float(chunk._season[0]))


## World-aligned decorative rows, bounded per clipped chunk and kept inside its polygon.
static func site_detail_positions(polygon: PackedVector2Array, kind: String, origin: Vector2) -> PackedVector2Array:
	var positions := PackedVector2Array()
	if kind not in ["biergarten", "grave_yard", "cemetery"] or not _valid(polygon):
		return positions
	var bounds := Rect2(polygon[0], Vector2.ZERO)
	for point in polygon:
		bounds = bounds.expand(point)
	var spacing := 6.0 if kind == "biergarten" else 4.0
	spacing *= maxf(1.0, ceilf(sqrt(bounds.get_area() / (spacing * spacing * 192.0))))
	var half := 1.8 if kind == "biergarten" else 1.1
	var x0 := ceili((bounds.position.x + origin.x) / spacing)
	var x1 := floori((bounds.end.x + origin.x) / spacing)
	var y0 := ceili((origin.y - bounds.end.y) / spacing)
	var y1 := floori((origin.y - bounds.position.y) / spacing)
	for row in range(y0, y1 + 1):
		for column in range(x0, x1 + 1):
			var at := MapMath.point(origin, column * spacing, row * spacing)
			var inside := Geometry2D.is_point_in_polygon(at, polygon)
			for offset in [Vector2(-half, -half), Vector2(half, -half), Vector2(half, half), Vector2(-half, half)]:
				inside = inside and Geometry2D.is_point_in_polygon(at + offset, polygon)
			if inside:
				positions.append(at)
				if positions.size() >= 256:
					return positions
	return positions


static func draw_site_detail(node: Node2D, at: Vector2, kind: String, snow: float) -> void:
	var snowy := Color8(215, 224, 232)
	if kind == "biergarten":
		var wood := Color8(140, 94, 52).lerp(snowy, snow * 0.7)
		node.draw_rect(Rect2(at - Vector2(1.1, 0.45), Vector2(2.2, 0.9)), wood)
		for side in [-1.0, 1.0]:
			node.draw_rect(Rect2(at + Vector2(-1.1, side * 0.95 - 0.16), Vector2(2.2, 0.32)), wood.darkened(0.15))
		if fposmod(sin(at.dot(Vector2(0.73, 0.37))) * 43758.0, 1.0) < 0.4:
			node.draw_circle(at + Vector2(0.15, -0.15), 1.4, Color8(84, 78, 62, 80))
			node.draw_circle(at, 1.25, Color8(185, 67, 45).lerp(snowy, snow * 0.8))
			node.draw_line(at - Vector2(1.1, 0), at + Vector2(1.1, 0), Color8(236, 209, 161), 0.08)
			node.draw_line(at - Vector2(0, 1.1), at + Vector2(0, 1.1), Color8(236, 209, 161), 0.08)
	else:
		node.draw_rect(Rect2(at - Vector2(0.65, 0.9), Vector2(1.3, 1.8)), Color8(68, 80, 57).lerp(snowy, snow * 0.85))
		node.draw_rect(Rect2(at - Vector2(0.75, 1.0), Vector2(1.5, 0.4)), Color8(57, 59, 60))
		node.draw_rect(Rect2(at - Vector2(0.65, 1.0), Vector2(1.3, 0.25)), Color8(155, 157, 150).lerp(snowy, snow * 0.5))
		node.draw_circle(at + Vector2(0.1, 0.45), 0.18, Color8(173, 76, 79).lerp(snowy, snow))


## Ice hockey markings (IIHF, laid out on a 60 x 30 m rink and scaled to
## each rink's own rectangle, state chunk "rinks"): centre and blue lines,
## goal lines, the centre circle and faceoff circles and spots, goal
## creases and goals. Only on frozen ice, like the ice itself.
const RINK_RED := Color8(200, 32, 44)
const RINK_BLUE := Color8(32, 84, 190)
const RINK_CREASE := Color8(126, 184, 236)
const RINK_NET := Color8(236, 238, 240)
const IIHF_LENGTH := 60.0
const IIHF_WIDTH := 30.0
const GOAL_LINE_U := 26.0  # 4 m from the end boards
const BLUE_LINE_U := 8.75
const GOAL_LINE_HALF_V := 12.5  # inside the corner rounding (OSM rinks often have sharper corners than 8.5 m)
const FACEOFF_V := 7.0
const FACEOFF_RADIUS := 4.5


static func draw_rink_markings(chunk, node: Node2D) -> void:
	if chunk._season[0] < FIELDS_FROZEN_WINTER_WEIGHT:
		return  # gravel in summer: no markings
	for rink in chunk._data.get("rinks", []):
		var frame := RinkFrame.new(chunk, rink, float(rink[3]) / IIHF_LENGTH, float(rink[4]) / IIHF_WIDTH)
		var r := frame.radius_scale
		var half_width := IIHF_WIDTH / 2.0
		frame.line(node, 0.0, -half_width, 0.0, half_width, RINK_RED, 0.3)
		for side: float in [-1.0, 1.0]:
			var blue: float = side * BLUE_LINE_U
			var goal: float = side * GOAL_LINE_U
			frame.line(node, blue, -half_width, blue, half_width, RINK_BLUE, 0.3)
			frame.line(node, goal, -GOAL_LINE_HALF_V, goal, GOAL_LINE_HALF_V, RINK_RED, 0.1)
			# The goal crease: a light blue half circle in front of the goal, toward centre ice.
			frame.fill_arc(node, goal, 0.0, 1.8 * r, PI if side > 0.0 else 0.0, RINK_CREASE)
			# The goal: 1.83 m wide, 1.12 m deep behind the goal line.
			var back: float = goal + side * 1.12 / frame.scale_u
			frame.fill_quad(node, goal, -0.915, back, 0.915, RINK_NET)
			frame.polyline(node, [[goal, -0.915], [back, -0.915], [back, 0.915], [goal, 0.915]], RINK_RED, 0.12)
			for v: float in [-FACEOFF_V, FACEOFF_V]:
				frame.circle(node, side * (GOAL_LINE_U - 6.0), v, FACEOFF_RADIUS * r, RINK_RED, 0.1)
				frame.spot(node, side * (GOAL_LINE_U - 6.0), v, 0.3 * r, RINK_RED)
				frame.spot(node, side * (BLUE_LINE_U - 1.5), v, 0.3 * r, RINK_RED)
		frame.circle(node, 0.0, 0.0, FACEOFF_RADIUS * r, RINK_BLUE, 0.1)
		frame.spot(node, 0.0, 0.0, 0.15 * r, RINK_BLUE)


## Soccer pitch markings (FIFA, laid out on 105 x 68 m and scaled to each
## pitch's rectangle, state chunk "soccer_pitches"): the boundary, halfway
## line, centre circle and spot, penalty and goal areas, penalty spots and
## arcs, corner arcs and the goals. Only while there is no snow on the
## pitch (server SOCCER_SNOW_WEIGHT, the same weight soccer is played by).
const PITCH_LINE := Color8(244, 246, 240)
const PITCH_NET := Color8(205, 210, 205)
const FIFA_LENGTH := 105.0
const FIFA_WIDTH := 68.0
const PITCH_SNOW_WEIGHT := 0.05
const PITCH_LINE_WIDTH := 0.12


static func draw_soccer_markings(chunk, node: Node2D) -> void:
	if chunk._season[0] >= PITCH_SNOW_WEIGHT:
		return  # under snow
	for pitch in chunk._data.get("soccer_pitches", []):
		var frame := RinkFrame.new(chunk, pitch, float(pitch[3]) / FIFA_LENGTH, float(pitch[4]) / FIFA_WIDTH)
		var r := frame.radius_scale
		var half_u := FIFA_LENGTH / 2.0
		var half_v := FIFA_WIDTH / 2.0
		var w := PITCH_LINE_WIDTH
		frame.polyline(node, [[-half_u, -half_v], [half_u, -half_v], [half_u, half_v], [-half_u, half_v], [-half_u, -half_v]], PITCH_LINE, w)
		frame.line(node, 0.0, -half_v, 0.0, half_v, PITCH_LINE, w)
		frame.circle(node, 0.0, 0.0, 9.15 * r, PITCH_LINE, w)
		frame.spot(node, 0.0, 0.0, 0.2 * r, PITCH_LINE)
		for side: float in [-1.0, 1.0]:
			var goal: float = side * half_u
			var box: float = goal - side * 16.5
			var small: float = goal - side * 5.5
			frame.polyline(node, [[goal, -20.16], [box, -20.16], [box, 20.16], [goal, 20.16]], PITCH_LINE, w)
			frame.polyline(node, [[goal, -9.16], [small, -9.16], [small, 9.16], [goal, 9.16]], PITCH_LINE, w)
			var spot: float = goal - side * 11.0
			frame.spot(node, spot, 0.0, 0.2 * r, PITCH_LINE)
			# The penalty arc: the 9.15 m circle round the spot, outside the area.
			var half_arc := acos(5.5 / 9.15)
			var facing := PI if side > 0.0 else 0.0
			frame.arc(node, spot, 0.0, 9.15 * r, facing - half_arc, facing + half_arc, PITCH_LINE, w)
			for v: float in [-half_v, half_v]:  # corner arcs, into the pitch
				var start := atan2(-signf(v), -side)
				frame.arc(node, goal, v, 1.0 * r, start - PI / 4.0, start + PI / 4.0, PITCH_LINE, w)
			# The goal: 7.32 m between the posts, a net 2 m deep behind the line.
			var back: float = goal + side * 2.0 / frame.scale_u
			frame.fill_quad(node, goal, -3.66, back, 3.66, PITCH_NET)
			frame.polyline(node, [[goal, -3.66], [back, -3.66], [back, 3.66], [goal, 3.66]], PITCH_LINE, 0.2)


## A rink's markings space: (u, v) metres on a 60 x 30 m IIHF rink, u along
## its length, mapped onto this rink's rectangle and into chunk points.
class RinkFrame:
	var chunk
	var centre: Vector2
	var axis_u: Vector2
	var axis_v: Vector2
	var scale_u: float
	var scale_v: float
	var radius_scale: float

	func _init(owner, rink: Array, u_scale: float, v_scale: float) -> void:
		chunk = owner
		centre = Vector2(rink[0], rink[1])
		axis_u = Vector2(cos(rink[2]), sin(rink[2]))
		axis_v = Vector2(-axis_u.y, axis_u.x)
		scale_u = u_scale
		scale_v = v_scale
		radius_scale = minf(scale_u, scale_v)

	func at(u: float, v: float) -> Vector2:
		var world := centre + axis_u * u * scale_u + axis_v * v * scale_v
		return MapMath.point(chunk._origin, world.x, world.y)

	## A point `radius` world metres from (u, v), in direction `angle` of the rink's axes.
	func around(u: float, v: float, radius: float, angle: float) -> Vector2:
		var world := centre + axis_u * u * scale_u + axis_v * v * scale_v + (axis_u * cos(angle) + axis_v * sin(angle)) * radius
		return MapMath.point(chunk._origin, world.x, world.y)

	func line(node: Node2D, u0: float, v0: float, u1: float, v1: float, color: Color, width: float) -> void:
		node.draw_line(at(u0, v0), at(u1, v1), color, width)

	func polyline(node: Node2D, uvs: Array, color: Color, width: float) -> void:
		var points := PackedVector2Array()
		for uv in uvs:
			points.append(at(uv[0], uv[1]))
		node.draw_polyline(points, color, width)

	func fill_quad(node: Node2D, u0: float, v0: float, u1: float, v1: float, color: Color) -> void:
		# A net is a rectangle; draw it locally to avoid distant-coordinate triangulation.
		node.draw_set_transform(at(0.0, 0.0), -axis_u.angle())
		node.draw_rect(Rect2(Vector2(u0 * scale_u, -v0 * scale_v),
			Vector2((u1 - u0) * scale_u, -(v1 - v0) * scale_v)).abs(), color)
		node.draw_set_transform(Vector2.ZERO)

	func circle(node: Node2D, u: float, v: float, radius: float, color: Color, width: float) -> void:
		var points := PackedVector2Array()
		for i in 33:
			points.append(around(u, v, radius, TAU * i / 32.0))
		node.draw_polyline(points, color, width)

	## An arc round (u, v) from angle `from` to `to` (rink angles: 0 is +u).
	func arc(node: Node2D, u: float, v: float, radius: float, from: float, to: float, color: Color, width: float) -> void:
		var points := PackedVector2Array()
		for i in 17:
			points.append(around(u, v, radius, lerpf(from, to, i / 16.0)))
		node.draw_polyline(points, color, width)

	func spot(node: Node2D, u: float, v: float, radius: float, color: Color) -> void:
		var points := PackedVector2Array()
		for i in 12:
			var angle := TAU * i / 12.0
			points.append(Vector2(cos(angle), -sin(angle)) * radius)
		node.draw_set_transform(at(u, v))
		node.draw_colored_polygon(points, color)
		node.draw_set_transform(Vector2.ZERO)

	## A filled half circle centred on (u, v), bulging toward `facing` (rink angle: 0 is +u).
	func fill_arc(node: Node2D, u: float, v: float, radius: float, facing: float, color: Color) -> void:
		var points := PackedVector2Array([Vector2.ZERO])
		for i in 17:
			var angle := facing - PI / 2.0 + PI * i / 16.0
			points.append(Vector2(cos(angle), -sin(angle)) * radius)
		node.draw_set_transform(at(u, v), -axis_u.angle())
		node.draw_colored_polygon(points, color)
		node.draw_set_transform(Vector2.ZERO)


## Parking spaces: asphalt bays with a light edge.
static func draw_parking(chunk, node: Node2D) -> void:
	var edges := PackedVector2Array()
	for space in chunk._data.get("parking", []):
		var polygon: PackedVector2Array = chunk._points(space)
		if not _valid(polygon):
			continue
		node.draw_colored_polygon(polygon, Color8(72, 75, 74))
		for i in polygon.size():
			edges.append_array(PackedVector2Array([polygon[i], polygon[(i + 1) % polygon.size()]]))
	if not edges.is_empty():
		node.draw_multiline(edges, Color8(125, 128, 124), _width(chunk, 0.12, 1.0))


## A line width: `metres`, at least `min_px` pixels; a hairline (-1, no
## triangles) when that is a pixel or so anyway.
static func _width(chunk, metres: float, min_px: float) -> float:
	var px: float = maxf(min_px, metres * chunk._px_per_m)
	return -1.0 if px < 1.5 else px / chunk._px_per_m


## Ground track: ballast bed (zoomed in),
## two rails, a sleeper every 2 m - also the bridge tracks, on their deck.
static func draw_tracks(chunk, node: Node2D, key: String) -> void:
	var ballast := PackedVector2Array()
	var rails := PackedVector2Array()
	var ties := PackedVector2Array()
	for line in chunk._data.get(key, []):
		var points: PackedVector2Array = chunk._points(line)
		var next_tie := 0.0
		var along := 0.0
		for i in points.size() - 1:
			var a := points[i]
			var b := points[i + 1]
			var length := a.distance_to(b)
			if length < 1e-6:
				continue
			var u := (b - a) / length
			var n := Vector2(-u.y, u.x)
			ballast.append_array(PackedVector2Array([a, b]))
			for offset: float in [-HALF_GAUGE, HALF_GAUGE]:
				rails.append_array(PackedVector2Array([a + n * offset, b + n * offset]))
			while next_tie <= along + length:
				var at := a + u * (next_tie - along)
				ties.append_array(PackedVector2Array([at - n * HALF_TIE, at + n * HALF_TIE]))
				next_tie += TIE_SPACING
			along += length
	if key == "railways" and chunk._px_per_m > 1.5 and not ballast.is_empty():
		node.draw_multiline(ballast, BALLAST_COLOR, 2.0 * (HALF_TIE + 0.4))
	if not ties.is_empty():
		node.draw_multiline(ties, TIE_COLOR, _width(chunk, 0.18, 1.0))
	if not rails.is_empty():
		node.draw_multiline(rails, RAIL_COLOR, _width(chunk, 0.08, 1.0))


## Rail bridges: the deck (ballast fill, guardrail edge) under the bridge
## tracks, all above the vehicles.
static func draw_rail_bridges(chunk, node: Node2D) -> void:
	for deck in chunk._data.get("rail_decks", []):
		var polygon: PackedVector2Array = chunk._points(deck)
		if _valid(polygon):
			node.draw_colored_polygon(polygon, BALLAST_COLOR)
			var ring := polygon.duplicate()
			ring.append(polygon[0])
			node.draw_polyline(ring, GUARDRAIL_COLOR, maxf(chunk._px(2.0), 0.15))
	draw_tracks(chunk, node, "rail_bridges")


## Bridge guardrails: outer side edges only.
static func draw_guardrails(chunk, node: Node2D) -> void:
	var lines := PackedVector2Array()
	for r in chunk._data.get("guardrails", []):
		lines.append_array(PackedVector2Array([MapMath.point(chunk._origin, r[0], r[1]), MapMath.point(chunk._origin, r[2], r[3])]))
	if not lines.is_empty():
		node.draw_multiline(lines, GUARDRAIL_COLOR, maxf(chunk._px(2.0), 0.18))


## Open roofs, under the vehicles: the canopy's shadow
## and its corner posts (the roof itself is drawn above them: draw_canopies).
static func draw_canopy_supports(chunk, node: Node2D) -> void:
	for canopy in chunk._data.get("canopies", []):
		var polygon: PackedVector2Array = chunk._points(canopy)
		if polygon.size() < 3:
			continue
		var anchor := polygon[0]
		var shadow := polygon.duplicate()
		for i in shadow.size():
			shadow[i] -= anchor
		if not _valid(shadow):
			continue
		# Keep small shadow edges precise even far from the initial map origin.
		node.draw_set_transform(anchor + Vector2(0.35, 0.35))
		node.draw_colored_polygon(shadow, Color8(30, 32, 33, 75))
		node.draw_set_transform(Vector2.ZERO)
		var height := canopy_height(chunk, canopy)
		for point in polygon:
			node.draw_line(point, _lift(chunk, point, height), OPEN_ROOF_POLE, maxf(chunk._px(1.0), 0.24))
			node.draw_circle(point, maxf(chunk._px(1.0), 0.18) + chunk._px(1.0), OPEN_ROOF_EDGE)
			node.draw_circle(point, maxf(chunk._px(1.0), 0.18), OPEN_ROOF_POLE)


## A canopy point raised to `height`: with the 3D buildings, exactly where
## their camera shows that height (godot-23); otherwise the unchanged flat footprint.
static func _lift(chunk, point: Vector2, height: float) -> Vector2:
	return B3.lift_point(point, height) if chunk.buildings_3d else point


## A canopy's height (chunk canopy_heights, in step with canopies; 6 m without).
static func canopy_height(chunk, canopy) -> float:
	var index: int = chunk._data.get("canopies", []).find(canopy)
	var heights: Array = chunk._data.get("canopy_heights", [])
	return float(heights[index]) if index >= 0 and index < heights.size() else 6.0


## The see-through canopy above the vehicles:
## fuel pumps and the taxi stay visible under it.
static func draw_canopies(chunk, node: Node2D) -> void:
	for canopy in chunk._data.get("canopies", []):
		var polygon: PackedVector2Array = chunk._points(canopy).duplicate()
		var height := canopy_height(chunk, canopy)
		for i in polygon.size():
			polygon[i] = _lift(chunk, polygon[i], height)
		if _valid(polygon):
			node.draw_colored_polygon(polygon, OPEN_ROOF)
			var ring := polygon.duplicate()
			ring.append(polygon[0])
			node.draw_polyline(ring, OPEN_ROOF_EDGE, maxf(chunk._px(1.0), 0.1))


## Curbs, zebra crossings and speed bumps.
static func draw_road_features(chunk, node: Node2D) -> void:
	var curbs := PackedVector2Array()
	for curb in chunk._data.get("curbs", []):
		var points: PackedVector2Array = chunk._points(curb)
		for i in points.size() - 1:
			curbs.append_array(PackedVector2Array([points[i], points[i + 1]]))
	if not curbs.is_empty():
		node.draw_multiline(curbs, Color8(145, 145, 140), _width(chunk, 0.15, 1.0))
	var stripes := PackedVector2Array()
	for c in chunk._data.get("crossings", []):  # 0.5 m stripes along the road, 0.9 m apart, across its width
		var at := MapMath.point(chunk._origin, c[0], c[1])
		var along := Vector2(cos(c[2]), -sin(c[2]))
		var across := Vector2(-along.y, along.x)
		var count := maxi(3, int(float(c[3]) / 0.9))
		for i in count:
			var centre: Vector2 = at + across * (-(count - 1) * 0.9 / 2.0 + i * 0.9)
			stripes.append_array(PackedVector2Array([centre - along * float(c[4]) / 2.0, centre + along * float(c[4]) / 2.0]))
	if not stripes.is_empty():
		node.draw_multiline(stripes, Color8(245, 245, 245), maxf(chunk._px(1.0), 0.5))
	for b in chunk._data.get("speed_bumps", []):
		var at := MapMath.point(chunk._origin, b[0], b[1])
		var along: Vector2 = Vector2(cos(b[2]), -sin(b[2])) * float(BUMP_LENGTHS.get(str(b[4]), 0.6)) / 2.0
		var across: Vector2 = Vector2(-along.y, along.x).normalized() * float(b[3]) / 2.0
		var bump := PackedVector2Array([at - along - across, at + along - across, at + along + across, at - along + across])
		if _valid(bump):
			node.draw_colored_polygon(bump, Color8(45, 42, 40))


## Stop and yield signs and speed cameras, in pixels (scale
## with the zoom between 0.7 and 1.5); the flashing camera's flash.
static func draw_signs(chunk, node: Node2D, flash_index) -> void:
	var font := ThemeDB.fallback_font
	var scale := clampf(chunk._px_per_m / 9.0, 0.7, 1.5)
	for sign in chunk._data.get("signs", []):
		node.draw_set_transform(MapMath.point(chunk._origin, sign[0], sign[1]), 0.0, Vector2.ONE / chunk._px_per_m)
		node.draw_line(Vector2.ZERO, Vector2(0, maxf(8.0, 14.0 * scale)), Color8(70, 70, 70), maxf(2.0, 2.0 * scale))
		var r := 9.0 * scale
		if sign[2] == "stop":
			var octagon := PackedVector2Array()
			for i in 8:
				octagon.append(Vector2(cos(TAU * i / 8.0), sin(TAU * i / 8.0)) * r)
			node.draw_colored_polygon(octagon, Color8(220, 30, 30))
			octagon.append(octagon[0])
			node.draw_polyline(octagon, Color8(245, 245, 240), maxf(1.0, scale))
			if r >= 7.0:
				var size := font.get_string_size("STOP", HORIZONTAL_ALIGNMENT_LEFT, -1, int(r))
				node.draw_set_transform(MapMath.point(chunk._origin, sign[0], sign[1]), -float(sign[3]), Vector2.ONE / chunk._px_per_m)
				node.draw_string(font, Vector2(-size.x / 2.0, size.y / 3.0), "STOP", HORIZONTAL_ALIGNMENT_LEFT, -1, int(r), Color8(250, 250, 248))
		else:
			var f := Vector2(cos(sign[3]), -sin(sign[3]))
			var s := Vector2(-f.y, f.x)
			# The tip faces approaching drivers, with the triangle aligned to the road.
			var triangle := PackedVector2Array([-f * r, f * r - s * r, f * r + s * r])
			node.draw_colored_polygon(triangle, Color8(245, 245, 240))
			triangle.append(triangle[0])
			node.draw_polyline(triangle, Color8(220, 30, 30), maxf(2.0, 2.0 * scale))
	for camera in chunk._data.get("speed_cameras", []):
		node.draw_set_transform(MapMath.point(chunk._origin, camera[1], camera[2]), 0.0, Vector2.ONE / chunk._px_per_m)
		node.draw_line(Vector2(0, 2), Vector2(0, maxf(10.0, 18.0 * scale)), Color8(48, 52, 56), maxf(2.0, 2.0 * scale))
		var d := Vector2(-cos(camera[3]), sin(camera[3]))
		var side := Vector2(-d.y, d.x)
		var front := d * 5.5 * scale
		var body := PackedVector2Array([-front + side * 8.0 * scale, front + side * 8.0 * scale, front - side * 8.0 * scale, -front - side * 8.0 * scale])
		node.draw_colored_polygon(body, Color8(35, 40, 44))
		body.append(body[0])
		node.draw_polyline(body, Color8(190, 198, 202), 1.0)
		var lens := front + d * 1.5 * scale
		node.draw_circle(lens, maxf(2.0, 2.5 * scale), Color8(220, 45, 35))
		if flash_index != null and int(flash_index) == int(camera[0]):
			node.draw_circle(lens, 30.0, Color8(255, 255, 235, 150))
			node.draw_circle(lens, 12.0, Color8(255, 255, 255, 235))
		var tip := front + d * 15.0 * scale
		node.draw_line(front + d * 3.0 * scale, tip, Color8(245, 205, 35), maxf(2.0, 2.0 * scale))
		var a := maxf(2.5, 4.0 * scale)
		node.draw_colored_polygon(PackedVector2Array([tip, tip - d * a + side * a, tip - d * a - side * a]), Color8(245, 205, 35))
	node.draw_set_transform(Vector2.ZERO)


## Bus stops: the bay, a shelter, "BUS" along the road.
static func draw_bus_stops(chunk, node: Node2D) -> void:
	var font := ThemeDB.fallback_font
	for stop in chunk._data.get("bus_stops", []):
		var bay: PackedVector2Array = chunk._points(stop["bay"])
		if not _valid(bay):
			continue
		node.draw_colored_polygon(bay, _rgb(stop["color"]) if stop.has("color") else Color8(82, 82, 78))
		node.draw_polyline(PackedVector2Array([bay[1], bay[2], bay[3], bay[0]]), Color8(175, 175, 168), 0.25)  # the kerb
		for key in ["shelter", "bench"]:
			if stop.get(key) == null:
				continue
			var box: PackedVector2Array = chunk._points(stop[key])
			if not _valid(box):
				continue
			node.draw_colored_polygon(box, Color(0.62, 0.78, 0.88, 0.6) if key == "shelter" else Color8(120, 82, 50))
			box.append(box[0])
			node.draw_polyline(box, Color8(45, 50, 55), 0.15 if key == "shelter" else 0.08)
		# "BUS" painted in the bay, about 1.6 m tall, read on approach.
		var size := clampi(roundi(1.6 * chunk._px_per_m), 8, 48)
		var text_size := font.get_string_size("BUS", HORIZONTAL_ALIGNMENT_LEFT, -1, size)
		node.draw_set_transform(MapMath.point(chunk._origin, stop["label"][0], stop["label"][1]), -float(stop["angle"]), Vector2.ONE / chunk._px_per_m)
		node.draw_string(font, Vector2(-text_size.x / 2.0, text_size.y / 3.0), "BUS", HORIZONTAL_ALIGNMENT_LEFT, -1, size, Color8(235, 235, 225))
		node.draw_set_transform(Vector2.ZERO)
		if stop.has("sign"):
			_draw_stop_sign(node, MapMath.point(chunk._origin, stop["sign"][0], stop["sign"][1]))


## The E6 bus stop sign seen from above, kept upright: a blue plate with a
## white bus, on its pole.
static func _draw_stop_sign(node: Node2D, at: Vector2) -> void:
	var plate := Rect2(at - Vector2(1.0, 1.0), Vector2(2.0, 2.0))  # larger than life: readable from above
	node.draw_rect(plate, Color8(20, 80, 170))
	node.draw_rect(plate, Color.WHITE, false, 0.12)
	node.draw_rect(Rect2(at + Vector2(-0.7, -0.45), Vector2(1.4, 0.75)), Color.WHITE)  # the bus
	for x in [-0.55, -0.15, 0.25]:
		node.draw_rect(Rect2(at + Vector2(x, -0.33), Vector2(0.3, 0.25)), Color8(20, 80, 170))  # its windows
	for x in [-0.4, 0.4]:
		node.draw_circle(at + Vector2(x, 0.35), 0.14, Color.WHITE)  # its wheels


## Road markings over one road: the centre line on a
## road at least 6 px wide (dashed 8 m / 6 m, or solid), one-way chevrons
## every 40 m when zoomed in. Collected into `lines` [colour -> points]
## and `chevrons` for one batched call per road layer.
static func road_markings(chunk, road: Dictionary, points: PackedVector2Array, lines: Dictionary, chevrons: PackedVector2Array) -> void:
	var center = road.get("center")
	if center != null and 2.0 * float(road.get("half_width_m", 1.5)) * chunk._px_per_m >= 6.0:
		var color := _rgb(center)
		if not lines.has(color):
			lines[color] = PackedVector2Array()
		if int(center[3]) == 2:
			for i in points.size() - 1:
				lines[color].append_array(PackedVector2Array([points[i], points[i + 1]]))
		else:
			for dash in chunk.dashes(points, maxf(chunk._px(6.0), 8.0), maxf(chunk._px(4.0), 6.0)):
				lines[color].append_array(PackedVector2Array([dash[0], dash[1]]))
	var oneway := int(road.get("oneway", 0))
	if oneway == 0 or chunk._px_per_m <= 1.5:
		return
	var path := points if oneway > 0 else points.duplicate()
	if oneway < 0:
		path.reverse()
	var carry := 0.0
	for i in path.size() - 1:
		var a := path[i]
		var b := path[i + 1]
		var length := a.distance_to(b)
		if length < 1.0:
			continue
		var u := (b - a) / length
		while carry < length:
			if carry > 5.0:
				var at := a + u * carry
				var arm := maxf(chunk._px(3.0), 4.0)
				chevrons.append_array(PackedVector2Array([at - u.rotated(-0.6) * arm, at, at, at - u.rotated(0.6) * arm]))
			carry += 40.0
		carry -= length


static func draw_volleyball_courts(chunk, node: Node2D) -> void:
	if chunk._season[0] >= PITCH_SNOW_WEIGHT:
		return
	for court in chunk._data.get("volleyball_courts", []):
		var frame := RinkFrame.new(chunk, court, float(court[3]), float(court[4]))
		frame.fill_quad(node, -.48, -.48, .48, .48, Color8(220, 203, 156))
		frame.polyline(node, [[-.45,-.43],[.45,-.43],[.45,.43],[-.45,.43],[-.45,-.43]], Color8(55, 105, 195), .08)


static func draw_volleyball_nets(chunk, node: Node2D) -> void:
	for court in chunk._data.get("volleyball_courts", []):
		var frame := RinkFrame.new(chunk, court, float(court[3]), float(court[4]))
		var a := frame.at(0, -.47)
		var b := frame.at(0, .47)
		var lift := Vector2(.3, -2.43 * .7)
		for base: Vector2 in [a, b]:
			node.draw_line(base, base + lift, Color8(65, 85, 115), .14)
		for height: float in [0.0, .25, .5]:
			node.draw_line(a + lift + Vector2(0, height), b + lift + Vector2(0, height), Color8(55, 60, 65), .04)
		for i in 17:
			var top := a.lerp(b, float(i) / 16) + lift
			node.draw_line(top, top + Vector2(0, .5), Color8(55, 60, 65), .035)
		node.draw_line(a + lift, b + lift, PITCH_LINE, .09)


static func draw_tennis_courts(chunk, node: Node2D) -> void:
	if chunk._season[0] >= PITCH_SNOW_WEIGHT:
		return
	for court in chunk._data.get("tennis_courts", []):
		var frame := RinkFrame.new(chunk, court, float(court[3]), float(court[4]))
		frame.fill_quad(node, -.49, -.49, .49, .49, Color8(65, 117, 88))
		frame.fill_quad(node, -.42, -.4, .42, .4, Color8(65, 125, 166))
		frame.polyline(node, [[-.42,-.4],[.42,-.4],[.42,.4],[-.42,.4],[-.42,-.4]], PITCH_LINE, .07)
		for v: float in [-.3, .3]:
			frame.line(node, -.42, v, .42, v, PITCH_LINE, .07)
		for u: float in [-.226, .226]:
			frame.line(node, u, -.3, u, .3, PITCH_LINE, .07)
		frame.line(node, -.226, 0, .226, 0, PITCH_LINE, .07)
		for u: float in [-.42, .42]:
			frame.line(node, u, -.015, u - signf(u)*.015, -.015, PITCH_LINE, .07)
		# A dark mesh net with a bright top tape and posts.
		frame.line(node, 0, -.44, 0, .44, Color8(35, 45, 42), .30)
		frame.line(node, 0, -.44, 0, .44, PITCH_LINE, .08)
		for v: float in [-.44, .44]:
			frame.spot(node, 0, v, .18, Color8(45, 55, 48))
