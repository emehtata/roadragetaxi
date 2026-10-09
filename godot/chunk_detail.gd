## The rest of a chunk's static world (godot-16), drawn as Pygame's
## renderers draw it, into the chunk's canvas items (map_chunk.gd creates
## the layers; this holds the drawing). Batched: one call per style where
## a chunk has many of a thing (multiline, triangle arrays), never a node
## per object. Sizes in metres, with Pygame's minimum pixel sizes where it
## has them (chunk._px). Everything here is drawing only.
extends RefCounted

const RAIL_COLOR := Color8(150, 145, 135)  # render/roads.py
const TIE_COLOR := Color8(90, 65, 45)
const BALLAST_COLOR := Color8(108, 100, 92)
const GUARDRAIL_COLOR := Color8(196, 200, 204)
const HALF_GAUGE := 1.435 / 2.0
const HALF_TIE := 2.6 / 2.0
const TIE_SPACING := 2.0
const BUMP_LENGTHS := {"table": 2.2, "bump": 0.6, "cushion": 0.4, "hump": 0.6}
const B25 := preload("res://buildings_25d.gd")
const B3 := preload("res://buildings_3d.gd")
const OPEN_ROOF := Color8(138, 145, 148, 185)  # render/buildings.py
const OPEN_ROOF_EDGE := Color8(65, 69, 71, 235)
const OPEN_ROOF_POLE := Color8(105, 110, 112)


static func _rgb(values: Array) -> Color:
	return Color8(int(values[0]), int(values[1]), int(values[2]))


static func _valid(polygon: PackedVector2Array) -> bool:
	return polygon.size() >= 3 and not Geometry2D.triangulate_polygon(polygon).is_empty()


## render/scenery.py draw_scenery (fills; the speckle texture is not
## drawn): each piece in its kind's colour, green kinds through the season.
static func draw_areas(chunk, node: Node2D, key: String) -> void:
	for area in chunk._data.get(key, []):
		var polygon: PackedVector2Array = chunk._points(area[2])
		if _valid(polygon):
			var color := _rgb(area[0])
			node.draw_colored_polygon(polygon, chunk.seasonal_color(color, chunk._season) if area[1] else color)


## render/scenery.py draw_parking_spaces: asphalt bays with a light edge.
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


## Ground track (render/roads.py draw_railways): ballast bed (zoomed in),
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
## tracks, all above the vehicles (render/roads.py only_bridges pass).
static func draw_rail_bridges(chunk, node: Node2D) -> void:
	for deck in chunk._data.get("rail_decks", []):
		var polygon: PackedVector2Array = chunk._points(deck)
		if _valid(polygon):
			node.draw_colored_polygon(polygon, BALLAST_COLOR)
			var ring := polygon.duplicate()
			ring.append(polygon[0])
			node.draw_polyline(ring, GUARDRAIL_COLOR, maxf(chunk._px(2.0), 0.15))
	draw_tracks(chunk, node, "rail_bridges")


## render/roads.py draw_ways' bridge guardrails: outer side edges only.
static func draw_guardrails(chunk, node: Node2D) -> void:
	var lines := PackedVector2Array()
	for r in chunk._data.get("guardrails", []):
		lines.append_array(PackedVector2Array([MapMath.point(chunk._origin, r[0], r[1]), MapMath.point(chunk._origin, r[2], r[3])]))
	if not lines.is_empty():
		node.draw_multiline(lines, GUARDRAIL_COLOR, maxf(chunk._px(2.0), 0.18))


## render/buildings.py open roofs, under the vehicles: the canopy's shadow
## and its corner posts (the roof itself is drawn above them: draw_canopies).
static func draw_canopy_supports(chunk, node: Node2D) -> void:
	for canopy in chunk._data.get("canopies", []):
		var polygon: PackedVector2Array = chunk._points(canopy)
		if not _valid(polygon):
			continue
		var shadow := polygon.duplicate()
		for i in shadow.size():
			shadow[i] += Vector2(0.35, 0.35)
		node.draw_colored_polygon(shadow, Color8(30, 32, 33, 75))
		var centre := Vector2.ZERO
		for p in polygon:
			centre += p
		centre /= polygon.size()
		var height := canopy_height(chunk, canopy)
		var up := B25.lift(height, centre, chunk._building_view)
		for point in polygon:
			node.draw_line(point, _lift(chunk, point, height, up), OPEN_ROOF_POLE, maxf(chunk._px(1.0), 0.24))
			node.draw_circle(point, maxf(chunk._px(1.0), 0.18) + chunk._px(1.0), OPEN_ROOF_EDGE)
			node.draw_circle(point, maxf(chunk._px(1.0), 0.18), OPEN_ROOF_POLE)


## A canopy point raised to `height`: with the 3D buildings, exactly where
## their camera shows that height (godot-23); otherwise the 2D radial lift.
static func _lift(chunk, point: Vector2, height: float, radial: Vector2) -> Vector2:
	return B3.lift_point(point, height) if chunk.buildings_3d else point + radial


## A canopy's height (chunk canopy_heights, in step with canopies; 6 m without).
static func canopy_height(chunk, canopy) -> float:
	var index: int = chunk._data.get("canopies", []).find(canopy)
	var heights: Array = chunk._data.get("canopy_heights", [])
	return float(heights[index]) if index >= 0 and index < heights.size() else 6.0


## The see-through canopy above the vehicles (draw_open_roof_overlays):
## fuel pumps and the taxi stay visible under it.
static func draw_canopies(chunk, node: Node2D) -> void:
	for canopy in chunk._data.get("canopies", []):
		var polygon: PackedVector2Array = chunk._points(canopy).duplicate()
		var centre := Vector2.ZERO
		for p in polygon:
			centre += p
		centre /= polygon.size()
		var height := canopy_height(chunk, canopy)
		var up := B25.lift(height, centre, chunk._building_view)
		for i in polygon.size():
			polygon[i] = _lift(chunk, polygon[i], height, up)
		if _valid(polygon):
			node.draw_colored_polygon(polygon, OPEN_ROOF)
			var ring := polygon.duplicate()
			ring.append(polygon[0])
			node.draw_polyline(ring, OPEN_ROOF_EDGE, maxf(chunk._px(1.0), 0.1))


## Curbs, zebra crossings and speed bumps (render/roads.py).
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


## Stop and yield signs and speed cameras, in pixels like Pygame's (scale
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
			var triangle := PackedVector2Array([f * r, -f * r - s * r, -f * r + s * r])
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


## render/roads.py draw_bus_stops: the bay, a shelter, "BUS" along the road.
static func draw_bus_stops(chunk, node: Node2D) -> void:
	var font := ThemeDB.fallback_font
	for stop in chunk._data.get("bus_stops", []):
		var bay: PackedVector2Array = chunk._points(stop["bay"])
		if _valid(bay):
			node.draw_colored_polygon(bay, Color8(82, 82, 78))
		if stop["shelter"] != null and _valid(chunk._points(stop["shelter"])):
			var shelter: PackedVector2Array = chunk._points(stop["shelter"])
			node.draw_colored_polygon(shelter, Color8(190, 190, 180))
			shelter.append(shelter[0])
			node.draw_polyline(shelter, Color8(45, 45, 42), maxf(chunk._px(1.0), 0.25))
		var size := clampi(roundi(2.0 * chunk._px_per_m), 8, 32)
		var text_size := font.get_string_size("BUS", HORIZONTAL_ALIGNMENT_LEFT, -1, size)
		node.draw_set_transform(MapMath.point(chunk._origin, stop["label"][0], stop["label"][1]), -float(stop["angle"]), Vector2.ONE / chunk._px_per_m)
		node.draw_string(font, Vector2(-text_size.x / 2.0, text_size.y / 3.0), "BUS", HORIZONTAL_ALIGNMENT_LEFT, -1, size, Color8(25, 25, 25))
	node.draw_set_transform(Vector2.ZERO)


## render/roads.py draw_ways' markings over one road: the centre line on a
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
