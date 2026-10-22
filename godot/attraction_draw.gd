class_name AttractionDraw
extends RefCounted

## Footprints and ride loops come from the simulation map; visitors move on the server.
static func draw_ride(node: Node2D, kind: String, points: PackedVector2Array) -> void:
	if points.size() < 4:
		return
	var centre := Vector2.ZERO
	for i in points.size() - 1:
		centre += points[i]
	centre /= points.size() - 1
	var colours := [Color8(232, 76, 65), Color8(248, 194, 62), Color8(65, 160, 198), Color8(160, 94, 185)]
	node.draw_polyline(points, Color8(62, 65, 68), 1.0, true)
	if kind == "roller_coaster":
		for i in range(0, points.size() - 1, 2):
			var normal := (points[i+1] - points[i]).normalized().orthogonal() * 1.2
			node.draw_line(points[i] - normal, points[i] + normal, Color8(104, 79, 65), 0.45, true)
		for offset in [-0.5, 0.5]:
			var rail := PackedVector2Array()
			for i in points.size():
				var outward := (points[i] - centre).normalized()
				rail.append(points[i] + outward * offset)
			node.draw_polyline(rail, Color8(211, 70, 55), 0.25, true)
		return
	if kind == "drop_tower":
		node.draw_line(centre + Vector2(2, 2), centre + Vector2(4, 8), Color8(40, 40, 40, 90), 3.0)
		node.draw_rect(Rect2(centre - Vector2(1.2, 1.2), Vector2(2.4, 2.4)), Color8(91, 108, 126))
	else:
		var rim := PackedVector2Array()
		var canopy_scale := 0.45 if kind == "swing_carousel" else 0.72
		for p in points:
			rim.append(centre + (p - centre) * canopy_scale)
		if kind in ["carousel", "swing_carousel"]:
			for i in range(0, points.size() - 1, 6):
				var wedge := PackedVector2Array([centre])
				for j in range(i, mini(i + 7, points.size())):
					wedge.append(rim[j])
				node.draw_colored_polygon(wedge, colours[(i / 6) % 4])
		else:  # Ferris wheel spokes and supporting frame, seen from above.
			node.draw_polyline(rim, Color8(233, 229, 208), 0.55, true)
			node.draw_line(centre + Vector2(-3, 4), centre, Color8(77, 99, 124), 0.8)
			node.draw_line(centre + Vector2(3, 4), centre, Color8(77, 99, 124), 0.8)
		for i in range(0, points.size() - 1, 6):
			node.draw_line(centre, points[i], Color8(220, 215, 184), 0.18, true)
			node.draw_rect(Rect2(points[i] - Vector2(0.8, 0.6), Vector2(1.6, 1.2)), colours[(i / 6) % 4])
	node.draw_circle(centre, 0.65, Color8(248, 213, 93))
