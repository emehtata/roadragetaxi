## The static map from the "world" message, drawn once into this canvas
## item (one draw list, not a node per road - the map has thousands).
## Coordinates are metres relative to `origin` (world y north -> Godot y down),
## so large map coordinates don't lose float precision.
extends Node2D

var origin := Vector2.ZERO
var _roads: Array = []
var _railways: Array = []
var _waters: Array = []
var _buildings: Array = []


func set_world(world: Dictionary, world_origin: Vector2) -> void:
	origin = world_origin
	_roads = world.get("roads", [])
	_railways = world.get("railways", [])
	_waters = world.get("waters", [])
	_buildings = world.get("buildings", [])
	queue_redraw()


func _points(line: Array) -> PackedVector2Array:
	var points := PackedVector2Array()
	for point in line:
		points.append(MapMath.point(origin, point[0], point[1]))
	return points


func _draw() -> void:
	draw_rect(Rect2(-100000, -100000, 200000, 200000), Color(0.27, 0.33, 0.25))  # ground
	for water in _waters:
		var polygon := _points(water)
		if polygon.size() >= 3 and not Geometry2D.triangulate_polygon(polygon).is_empty():
			draw_colored_polygon(polygon, Color(0.25, 0.45, 0.65))
	for road in _roads:
		var width: float = max(0.6, 2.0 * float(road.get("half_width_m", 1.5)))
		var color := Color(0.33, 0.33, 0.35) if road.get("drivable", false) else Color(0.55, 0.52, 0.45)
		draw_polyline(_points(road["points"]), color, width)
	for rail in _railways:
		draw_polyline(_points(rail), Color(0.2, 0.17, 0.15), 1.4)
	for building in _buildings:
		var outline := _points(building)
		if outline.size() >= 3 and not Geometry2D.triangulate_polygon(outline).is_empty():
			draw_colored_polygon(outline, Color(0.6, 0.58, 0.55))
