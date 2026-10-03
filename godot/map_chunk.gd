## One map chunk, drawn once into a few canvas items (one draw list each,
## never a node per road), stacked by z like Pygame's draw order
## (render/roads.py draw_ways by layer, then wet roads and puddles, then
## railways, then buildings):
##
##   z0  water (this node): another chunk's lake can't cover a bridge
##   z1  roads at ground level and below, lowest layer first
##   z2+ bridges: layer 1, 2, 3 (higher clamps to 3)
##   z5  wet-road darkening and sheen, puddles (weather; alpha follows wetness)
##   z6  railways
##   z7  buildings
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
