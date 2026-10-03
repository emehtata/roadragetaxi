## One map chunk, drawn once into two canvas items (one draw list each, not
## a node per road): water here, and roads, railways and buildings in a
## child one z level up - so another chunk's lake, drawn later, can't cover
## this chunk's bridge.
extends Node2D

var _data: Dictionary = {}
var _origin := Vector2.ZERO
var _top := Node2D.new()


func setup(message: Dictionary, origin: Vector2) -> void:
	_data = message
	_origin = origin
	_top.z_index = 1
	_top.draw.connect(_draw_top)
	add_child(_top)


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


func _draw_top() -> void:
	for road in _data.get("roads", []):
		var width: float = max(0.6, 2.0 * float(road.get("half_width_m", 1.5)))
		var color := Color(0.33, 0.33, 0.35) if road.get("drivable", false) else Color(0.55, 0.52, 0.45)
		_top.draw_polyline(_points(road["points"]), color, width)
	for rail in _data.get("railways", []):
		_top.draw_polyline(_points(rail), Color(0.2, 0.17, 0.15), 1.4)
	for building in _data.get("buildings", []):
		var outline := _points(building)
		if outline.size() >= 3 and not Geometry2D.triangulate_polygon(outline).is_empty():
			_top.draw_colored_polygon(outline, Color(0.6, 0.58, 0.55))
