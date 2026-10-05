## One map chunk, drawn once into a few canvas items (one draw list each,
## never a node per road), stacked by z like Pygame's draw order
## (render/roads.py draw_ways by layer, then wet roads and puddles, then
## railways, then buildings):
##
##   z0  water (this node): another chunk's lake can't cover a bridge
##   z1  roads at ground level and below, lowest layer first
##   z2+ bridges: layer 1, 2, 3 (higher clamps to 3)
##   z5  wet-road darkening and sheen, puddles (weather; alpha follows wetness)
##   z6  railways; trees, bollards, fuel pumps (Pygame draws trees and scenery
##       objects before buildings); a felled tree lies down, a knocked bollard
##       is drawn by MapLayer from the state instead
##   z7  buildings
##   z8  construction-site fences, roadworks, taxi-stand signs; traffic-light posts (own node, redrawn
##       only when one of its lights changes phase - the phase is the server's)
##   z11 fuel price boards: above the vehicles, as draw_fuel_station_signs
##
## The z8+ points are sized in screen pixels as Pygame's, so they redraw
## when the zoom changes (set_px_per_m), never per frame.
##
## Wet overlays are clipped to the chunk's bounds, since a road spanning
## several chunks is in each of them, and overlapping alpha would darken
## twice. Puddles sit at a fixed, deterministic spot per road and are drawn
## only by the chunk containing them.
extends Node2D

const RS := preload("res://render_style.gd")
const BRIDGE_Z_MAX := 3

var _data: Dictionary = {}
var _origin := Vector2.ZERO
var _bounds := PackedVector2Array()  # chunk rectangle in layer coordinates (clipping)
var _bounds_rect := Rect2()
var _roads_by_z: Dictionary = {}  # z -> [road]
var _wet_darken := Node2D.new()
var _wet_sheen := Node2D.new()
var _puddles := Node2D.new()
var _puddle_spots: Array = []  # [{"at", "radius", "reveal", "shape"}]
var _wetness := 0.0
var _px_per_m := 9.0
var _px_layers: Array[Node2D] = []  # point layers drawn in screen-pixel sizes
var _lights: Node2D = null  # traffic-light posts, if this chunk has any
var _phases: Dictionary = {}  # post id (String) -> phase as last drawn
var _font: Font = ThemeDB.fallback_font
var _trees: Node2D = null  # trees and bollards, if this chunk has any
var _fallen: Dictionary = {}  # MapMath key -> angle, for this chunk's felled trees
var _knocked: Dictionary = {}  # keys of this chunk's bollards lying flat
var drivable_roads: Array = []  # [Rect2, key] per drivable road: the night tint counts them (main.gd)


func setup(message: Dictionary, origin: Vector2) -> void:
	_data = message
	_origin = origin
	var bounds: Array = message.get("bounds", [])
	if bounds.size() == 4:
		var a := MapMath.point(origin, bounds[0], bounds[1])
		var b := MapMath.point(origin, bounds[2], bounds[3])
		_bounds_rect = Rect2(Vector2(minf(a.x, b.x), minf(a.y, b.y)), (b - a).abs())
		_bounds = PackedVector2Array([_bounds_rect.position, Vector2(_bounds_rect.end.x, _bounds_rect.position.y),
			_bounds_rect.end, Vector2(_bounds_rect.position.x, _bounds_rect.end.y)])
	for road in message.get("roads", []):
		if road.get("drivable", false) and road["points"].size() >= 2:
			var box := Rect2(MapMath.point(origin, road["points"][0][0], road["points"][0][1]), Vector2.ZERO)
			for point in road["points"]:
				box = box.expand(MapMath.point(origin, point[0], point[1]))
			drivable_roads.append([box, "%s,%s" % [road["points"][0][0], road["points"][0][1]]])
		var z := clampi(int(road.get("layer", 0)), 0, BRIDGE_Z_MAX) + 1
		if not _roads_by_z.has(z):
			_roads_by_z[z] = []
		_roads_by_z[z].append(road)
	for z in _roads_by_z:
		_roads_by_z[z].sort_custom(func(p, q): return int(p.get("layer", 0)) < int(q.get("layer", 0)))
		var layer_z: int = z
		_add_layer(z, func(node: Node2D): _draw_roads(layer_z, node))
	_add_layer(5, _draw_wet, _wet_darken)
	_add_layer(5, _draw_wet, _wet_sheen)
	_add_layer(5, _draw_puddles, _puddles)
	_add_layer(6, _draw_railways)
	_add_layer(7, _draw_buildings)
	if not message.get("trees", []).is_empty() or not message.get("bollards", []).is_empty():
		_trees = _add_layer(6, _draw_trees)
		_px_layers.append(_trees)
	if not message.get("construction_fences", []).is_empty():
		_px_layers.append(_add_layer(8, _draw_fences))
	if not message.get("fuel_stations", []).is_empty():
		_px_layers.append(_add_layer(6, _draw_fuel_pumps))
		_px_layers.append(_add_layer(11, _draw_fuel_boards))
	if not message.get("roadworks", []).is_empty() or not message.get("taxi_stands", []).is_empty():
		_px_layers.append(_add_layer(8, _draw_points))
	if not message.get("traffic_lights", []).is_empty():
		_lights = _add_layer(8, _draw_traffic_lights)
		_px_layers.append(_lights)
	_puddle_spots = puddle_spots(message.get("roads", []), _bounds_rect, origin)
	set_wetness(_wetness)


## A child canvas item at z; `draw` is called with that node to draw into.
func _add_layer(z: int, draw: Callable, node: Node2D = null) -> Node2D:
	if node == null:
		node = Node2D.new()
	node.z_index = z
	node.draw.connect(draw.bind(node))
	add_child(node)
	return node


## Weather: overlays and puddles follow wetness 0..1 (render/weather.py).
func set_wetness(wetness: float) -> void:
	var previous := _wetness
	_wetness = wetness
	var alphas := RS.wet_alphas(wetness)
	_wet_darken.modulate = Color(RS.WET_DARKEN, alphas[0])
	_wet_sheen.modulate = Color(RS.WET_SHEEN, alphas[1])
	# Alpha only, never `visible`: a canvas item hidden when it entered the
	# tree didn't draw its strokes when shown later (found in a windowed run).
	if not _puddle_spots.is_empty() and (wetness > 0.0 or previous > 0.0):
		_puddles.queue_redraw()


## Screen pixels per metre (the camera zoom): the point layers keep
## Pygame's pixel sizes, so they redraw when it changes.
func set_px_per_m(value: float) -> void:
	if is_equal_approx(value, _px_per_m):
		return
	_px_per_m = value
	for node in _px_layers:
		node.queue_redraw()


## The simulation's phases ({post id: phase}, state "traffic_lights"):
## redraws the posts only when one of this chunk's own lights changed.
## Returns whether it did.
func set_phases(phases: Dictionary) -> bool:
	if _lights == null:
		return false
	var changed := false
	for post in _data["traffic_lights"]:
		var id := str(int(post["id"]))  # JSON numbers arrive as floats: str(0.0) is "0.0"
		var phase: String = phases.get(id, "")
		if _phases.get(id, "") != phase:
			_phases[id] = phase
			changed = true
	if changed:
		_lights.queue_redraw()
	return changed


## The simulation's felled trees ({key: angle}) and knocked posts ({key:
## ...}), keyed by position (obstacle_key): redraws this chunk's trees only
## if one of its own changed. Returns whether it did.
func set_obstacles(fallen: Dictionary, knocked: Dictionary) -> bool:
	if _trees == null:
		return false
	var own_fallen := {}
	for tree in _data.get("trees", []):
		var key := obstacle_key(tree[0], tree[1])
		if fallen.has(key):
			own_fallen[key] = fallen[key]
	var own_knocked := {}
	for post in _data.get("bollards", []):
		var key := obstacle_key(post[0], post[1])
		if knocked.has(key):
			own_knocked[key] = true
	if own_fallen == _fallen and own_knocked == _knocked:
		return false
	_fallen = own_fallen
	_knocked = own_knocked
	_trees.queue_redraw()
	return true


## How the state names a static obstacle: its position at 0.1 m, as both
## the chunks and the state round it.
static func obstacle_key(x: float, y: float) -> String:
	return "%.1f,%.1f" % [x, y]


func _px(pixels: float) -> float:
	return pixels / _px_per_m


func _points(line: Array) -> PackedVector2Array:
	var points := PackedVector2Array()
	for point in line:
		points.append(MapMath.point(_origin, point[0], point[1]))
	return points


func _draw() -> void:
	for water in _data.get("waters", []):
		var polygon := _points(water)
		if polygon.size() >= 3 and not Geometry2D.triangulate_polygon(polygon).is_empty():
			draw_colored_polygon(polygon, Color(0.25, 0.45, 0.65))


func _draw_roads(z: int, node: Node2D) -> void:
	for road in _roads_by_z[z]:
		var width: float = max(0.6, 2.0 * float(road.get("half_width_m", 1.5)))
		var color := Color(0.33, 0.33, 0.35) if road.get("drivable", false) else Color(0.55, 0.52, 0.45)
		if z > 1:
			node.draw_polyline(_points(road["points"]), Color(0.12, 0.12, 0.13), width + 0.6)  # bridge edge
		node.draw_polyline(_points(road["points"]), color, width)


## White strokes over drivable roads, tinted by the node's modulate.
func _draw_wet(node: Node2D) -> void:
	for road in _data.get("roads", []):
		if not road.get("drivable", false):
			continue
		var line := _points(road["points"])
		var parts: Array = [line] if _bounds.is_empty() else Geometry2D.clip_polyline_with_polygon(line, _bounds)
		for part in parts:
			if part.size() >= 2:
				node.draw_polyline(part, Color.WHITE, 2.0 * float(road.get("half_width_m", 1.5)))


func _draw_puddles(node: Node2D) -> void:
	for spot in _puddle_spots:
		var strength := RS.puddle_strength(_wetness, spot["reveal"])
		if strength <= 0.0:
			continue
		var radius: float = spot["radius"] * (0.4 + 0.6 * strength)
		var shape: Array = spot["shape"]
		var polygon := PackedVector2Array()
		for i in shape.size():
			var angle := TAU * i / shape.size()
			polygon.append(spot["at"] + Vector2(cos(angle), sin(angle)) * radius * shape[i])
		node.draw_colored_polygon(polygon, Color(RS.PUDDLE_COLOR, RS.PUDDLE_MAX_ALPHA * strength))


func _draw_railways(node: Node2D) -> void:
	for rail in _data.get("railways", []):
		node.draw_polyline(_points(rail), Color(0.2, 0.17, 0.15), 1.4)


func _draw_buildings(node: Node2D) -> void:
	for building in _data.get("buildings", []):
		var outline := _points(building)
		if outline.size() >= 3 and not Geometry2D.triangulate_polygon(outline).is_empty():
			node.draw_colored_polygon(outline, Color(0.6, 0.58, 0.55))


const TREE_CROWNS := {  # render/scenery.py TREE_CROWN_PALETTES
	"spruce": [Color8(14, 54, 20), Color8(18, 64, 24), Color8(24, 76, 30)],
	"pine": [Color8(88, 108, 42), Color8(102, 122, 50), Color8(118, 136, 60)],
	"birch": [Color8(25, 78, 29), Color8(34, 101, 35), Color8(48, 119, 42), Color8(63, 112, 34)],
}


## A tree's look from its kind and variation (render/scenery.py
## _draw_trees_uncached): crown colour and radius in metres, trunk colour.
static func tree_style(kind: String, variation: float) -> Dictionary:
	var palette: Array = TREE_CROWNS.get(kind, TREE_CROWNS["birch"])
	var size := 0.72 + variation * 0.62
	var trunk := Color8(222, 218, 206)
	if kind == "pine":
		trunk = Color8(112 + int(20 * variation), 70 + int(14 * variation), 36)
	elif kind != "birch":
		trunk = Color8(78 + int(22 * variation), 52 + int(18 * variation), 27)
	return {"crown": palette[mini(palette.size() - 1, int(variation * palette.size()))],
		"radius": (1.9 if kind == "pine" else 2.2) * size, "trunk": trunk, "trunk_width": 0.7 * size}


## render/scenery.py draw_trees: an irregular crown blob seeded by the
## tree's position (same shape every redraw); a felled tree lies 3.2 m
## along the way it was hit, trunk showing. Then the standing bollards.
func _draw_trees(node: Node2D) -> void:
	var rng := RandomNumberGenerator.new()
	for tree in _data.get("trees", []):
		var at := MapMath.point(_origin, tree[0], tree[1])
		var style := tree_style(str(tree[2]), float(tree[3]))
		var radius := maxf(_px(2.0), style["radius"])
		var key := obstacle_key(tree[0], tree[1])
		if _fallen.has(key):
			var tip := at + Vector2(cos(_fallen[key]), -sin(_fallen[key])) * 3.2
			node.draw_line(at, tip, style["trunk"], maxf(_px(2.0), style["trunk_width"]))
			node.draw_circle(tip, radius, style["crown"])
			continue
		rng.seed = hash(key)
		var crown := PackedVector2Array()
		for i in 8:
			var angle := TAU * i / 8.0 + rng.randf_range(-0.2, 0.2)
			crown.append(at + Vector2(cos(angle), sin(angle)) * radius * rng.randf_range(0.78, 1.15))
		node.draw_colored_polygon(crown, style["crown"])
	for post in _data.get("bollards", []):
		if not _knocked.has(obstacle_key(post[0], post[1])):
			node.draw_circle(MapMath.point(_origin, post[0], post[1]), maxf(_px(1.0), 0.25), Color8(48, 48, 46))


## render/scenery.py draw_construction_fences: the site's outline as a
## dashed hazard fence (1.5 m dashes, 1 m gaps, continuous round the ring).
func _draw_fences(node: Node2D) -> void:
	for ring in _data["construction_fences"]:
		var points := _points(ring)
		points.append(points[0])
		for dash in dashes(points, 1.5, 1.0):
			node.draw_line(dash[0], dash[1], Color8(235, 140, 30), maxf(_px(1.0), 0.25))


## [from, to] pieces of a polyline: `dash` long, `gap` apart, the pattern
## carried over the corners.
static func dashes(points: PackedVector2Array, dash: float, gap: float) -> Array:
	var pieces: Array = []
	var phase := 0.0  # distance into the current dash+gap period
	for i in points.size() - 1:
		var a := points[i]
		var b := points[i + 1]
		var length := a.distance_to(b)
		var done := 0.0
		while done < length:
			var step := minf(length - done, (dash - phase) if phase < dash else (dash + gap - phase))
			if phase < dash:
				pieces.append([a.lerp(b, done / length), a.lerp(b, (done + step) / length)])
			done += step
			phase = fmod(phase + step, dash + gap)
	return pieces


## render/scenery.py draw_scenery_objects' "fuel" pumps: red pumps with a
## display, two side by side for an area station, along its angle.
func _draw_fuel_pumps(node: Node2D) -> void:
	for station in _data["fuel_stations"]:
		var at := MapMath.point(_origin, station["x"], station["y"])
		var width := maxf(_px(7.0), 0.8)
		var height := maxf(_px(12.0), 1.3)
		var along := Vector2(cos(station["angle"]), -sin(station["angle"]))
		for offset: float in ([-0.85, 0.85] if station["is_area"] else [0.0]):
			var pump := Rect2(at + along * offset - Vector2(width / 2.0, height), Vector2(width, height))
			node.draw_rect(pump, Color8(205, 62, 48))
			node.draw_rect(pump, Color8(245, 245, 230), false, _px(1.0))
			var inset := maxf(_px(1.0), width / 5.0)
			node.draw_rect(Rect2(pump.position + Vector2(inset, maxf(_px(2.0), height / 6.0)),
				Vector2(maxf(_px(2.0), width - 2.0 * inset), maxf(_px(2.0), height / 4.0))), Color8(20, 30, 32))


## render/scenery.py draw_fuel_station_signs: a pin over the pumps and a
## board with the station's name and the simulation's price, in pixels.
func _draw_fuel_boards(node: Node2D) -> void:
	for station in _data["fuel_stations"]:
		var at := MapMath.point(_origin, station["x"], station["y"])
		node.draw_set_transform(at, 0.0, Vector2.ONE / _px_per_m)  # pixels from here on
		var pump_height := maxf(12.0, 1.3 * _px_per_m)
		var marker := Vector2(0, -pump_height - 18.0)
		node.draw_colored_polygon(PackedVector2Array([marker + Vector2(-6, 7), marker + Vector2(6, 7), Vector2(0, -pump_height - 2.0)]), Color8(255, 205, 35))
		node.draw_circle(marker, 10.0, Color8(255, 205, 35))
		node.draw_arc(marker, 9.0, 0.0, TAU, 24, Color8(25, 28, 30), 2.0)
		var text := fuel_board_text(station)
		var text_size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 16)
		var board := Rect2(Vector2(-text_size.x / 2.0 - 6.0, marker.y - 13.0 - text_size.y - 8.0), text_size + Vector2(12, 8))
		node.draw_rect(board, Color8(15, 22, 25))
		node.draw_rect(board, Color8(255, 205, 35), false, 2.0)
		node.draw_string(_font, board.position + Vector2(6, text_size.y), text, HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color8(255, 235, 120))
	node.draw_set_transform(Vector2.ZERO)


static func fuel_board_text(station: Dictionary) -> String:
	return "%s  %.2f €/L" % [station.get("name", "FUEL"), station["price_cents"] / 100.0]


## render/roads.py draw_roadworks (barriers at both ends, cones between)
## and draw_taxi_stops (a yellow TAXI sign on a pole).
func _draw_points(node: Node2D) -> void:
	for work in _data.get("roadworks", []):
		var start := MapMath.point(_origin, work["start"][0], work["start"][1])
		var end := MapMath.point(_origin, work["end"][0], work["end"][1])
		var length := maxf(start.distance_to(end), 0.001)
		var normal := Vector2(-(end.y - start.y), end.x - start.x) / length
		var barrier := maxf(_px(2.0), float(work["half_width_m"]))
		var closed: bool = work["lane_closed"]
		for point in [start, end]:
			node.draw_line(point if closed else point - normal * barrier, point + normal * barrier, Color8(235, 190, 35), maxf(_px(2.0), 2.0))
		var steps := maxi(2, int(length * _px_per_m / maxf(18.0, 25.0 * _px_per_m)))
		var cone_r := maxf(_px(2.0), 0.35)
		for i in steps + 1:
			var c := start.lerp(end, float(i) / steps) + (normal * barrier * 0.5 if closed else Vector2.ZERO)
			node.draw_colored_polygon(PackedVector2Array([c + Vector2(0, -cone_r * 2.0), c + Vector2(-cone_r, cone_r), c + Vector2(cone_r, cone_r)]), Color8(245, 105, 25))
			node.draw_line(c - Vector2(cone_r / 2.0, 0), c + Vector2(cone_r / 2.0, 0), Color8(255, 220, 120), maxf(_px(1.0), cone_r / 2.0))
	for stand in _data.get("taxi_stands", []):
		node.draw_set_transform(MapMath.point(_origin, stand[0], stand[1]), 0.0, Vector2.ONE / _px_per_m)
		node.draw_line(Vector2(0, -1), Vector2(0, 11), Color8(55, 55, 55), 2.0)
		node.draw_rect(Rect2(-14, -13, 28, 14), Color8(20, 20, 20))
		node.draw_rect(Rect2(-13, -12, 26, 12), Color8(255, 205, 25))
		var label_size := _font.get_string_size("TAXI", HORIZONTAL_ALIGNMENT_LEFT, -1, 10)
		node.draw_string(_font, Vector2(-label_size.x / 2.0, -2), "TAXI", HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color8(20, 20, 20))
	node.draw_set_transform(Vector2.ZERO)


## Which lamps a phase lights: [red, yellow, green]. Unknown (no phase
## sent: the post is far from the player) lights none.
static func lamps(phase: String) -> Array:
	return [phase in ["red", "red+yellow", "all-red"], phase in ["yellow", "red+yellow"], phase == "green"]


## render/roads.py draw_traffic_lights: a 7 x 18 px housing along the
## traffic, red end toward the intersection, lamps by the server's phase.
func _draw_traffic_lights(node: Node2D) -> void:
	var colors := [[Color8(255, 30, 30), Color8(60, 10, 10)], [Color8(255, 210, 0), Color8(60, 50, 0)], [Color8(40, 240, 60), Color8(10, 50, 15)]]
	for post in _data["traffic_lights"]:
		# Pygame rotates the upright housing by degrees(angle) - 90 counter-clockwise on screen.
		node.draw_set_transform(MapMath.point(_origin, post["x"], post["y"]), PI / 2.0 - float(post["angle"]), Vector2.ONE / _px_per_m)
		node.draw_rect(Rect2(-3.5, -9, 7, 18), Color8(15, 15, 15))
		node.draw_rect(Rect2(-3.5, -9, 7, 18), Color8(70, 70, 70), false, 1.0)
		var lit := lamps(_phases.get(str(int(post["id"])), ""))
		for i in 3:
			var c := Vector2(0, -5 + 5 * i)
			if lit[i]:
				node.draw_circle(c, 4.0, Color(colors[i][0], 90.0 / 255.0))
			node.draw_circle(c, 2.0, colors[i][0] if lit[i] else colors[i][1])
	node.draw_set_transform(Vector2.ZERO)


## Where this chunk's puddles are: like render/weather.py _puddle_for_way, a
## 40 % chance per drivable road, one spot on one segment, offset sideways,
## a radius and the wetness that reveals it - seeded from the road's own
## geometry so every chunk and every session agrees (Pygame seeds from OSM
## ids, which chunks don't carry, so the spots differ from Pygame's). Only
## spots inside `bounds` are kept: the road may be in other chunks too.
static func puddle_spots(roads: Array, bounds: Rect2, origin: Vector2) -> Array:
	var spots: Array = []
	var rng := RandomNumberGenerator.new()
	for road in roads:
		var points: Array = road.get("points", [])
		if not road.get("drivable", false) or points.size() < 2:
			continue
		rng.seed = hash(points)
		if rng.randf() > RS.PUDDLE_CHANCE_PER_WAY:
			continue
		var index := rng.randi_range(0, points.size() - 2)
		var a := Vector2(points[index][0], points[index][1])
		var b := Vector2(points[index + 1][0], points[index + 1][1])
		var along := rng.randf_range(0.2, 0.8)
		var segment := b - a
		var perp := Vector2(-segment.y, segment.x).normalized() if segment.length() > 0.0 else Vector2.ZERO
		var half_width := float(road.get("half_width_m", 3.0))
		var world := a + segment * along + perp * rng.randf_range(-0.5, 0.5) * half_width * 0.6
		var at := MapMath.point(origin, world.x, world.y)
		var radius := rng.randf_range(RS.PUDDLE_MIN_RADIUS_M, minf(RS.PUDDLE_MAX_RADIUS_M, half_width * 0.9))
		var reveal := rng.randf_range(RS.PUDDLE_REVEAL_MIN, RS.PUDDLE_REVEAL_MAX)
		var shape: Array = []
		for i in RS.PUDDLE_SHAPE_POINTS:
			shape.append(1.0 + rng.randf_range(-RS.PUDDLE_SHAPE_JITTER, RS.PUDDLE_SHAPE_JITTER))
		if bounds.size == Vector2.ZERO or bounds.has_point(at):
			spots.append({"at": at, "radius": maxf(RS.PUDDLE_MIN_RADIUS_M, radius), "reveal": reveal, "shape": shape})
	return spots
