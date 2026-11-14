## The navigation route in the 3D world (docs/specs/third-person-camera.md):
## the 2D route's dark edge and gold centre as a ribbon on the road, at the
## deck height of each point's layer (navigation.points [x, y, layer]).
## Rebuilt only for a new route or new map chunks; the top-down 2D route is
## entity_layer.gd's, unchanged.
extends MeshInstance3D

const RS := preload("res://render_style.gd")
const STEP_M := 2.0
const LIFT_M := 0.08  # over the road: no z-fighting
const EDGE_M := 1.2
const CENTRE_M := 0.5

var _key := []


func _init() -> void:
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.vertex_color_use_as_albedo = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	material_override = material
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF


## source: the state's navigation.points as received (rebuild only when it or
## `chunks` changes); tint: EntityLayer.route_tint.
func show_route(source, points: PackedVector2Array, layers: PackedInt32Array, height: Callable, chunks: int, tint: Color) -> void:
	visible = points.size() >= 2
	if not visible:
		return
	(material_override as StandardMaterial3D).albedo_color = tint
	var key := [source, chunks]
	if key != _key:  # ponytail: any new chunk rebuilds (a few ms); only chunks under the route if it shows
		_key = key
		mesh = build(points, layers, height)


## Resampled every STEP_M; a segment between two layers (a bridge end) takes
## the higher one: deck_height's ramp brings it down to the ground there.
static func build(points: PackedVector2Array, layers: PackedInt32Array, height: Callable) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	if points.size() < 2:
		return mesh
	var vertices := PackedVector3Array()
	var colors := PackedColorArray()
	for strip in [[EDGE_M, RS.ROUTE_EDGE, 0.0], [CENTRE_M, RS.ROUTE, 0.01]]:
		for i in points.size() - 1:
			var a := points[i]
			var b := points[i + 1]
			var layer := maxi(layers[i] if i < layers.size() else 0, layers[i + 1] if i + 1 < layers.size() else 0)
			var side := (b - a).normalized().orthogonal() * float(strip[0]) * 0.5
			var steps := maxi(1, ceili(a.distance_to(b) / STEP_M))
			for k in steps:
				var quad := []
				for p: Vector2 in [a.lerp(b, float(k) / steps), a.lerp(b, float(k + 1) / steps)]:
					var y: float = float(height.call(p, layer)) + LIFT_M + float(strip[2])
					quad.append([Vector3(p.x - side.x, y, p.y - side.y), Vector3(p.x + side.x, y, p.y + side.y)])
				for v: Vector3 in [quad[0][0], quad[0][1], quad[1][1], quad[0][0], quad[1][1], quad[1][0]]:
					vertices.append(v)
					colors.append(strip[1])
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_COLOR] = colors
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
