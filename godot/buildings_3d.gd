## godot-21 prototype: buildings as real 3D volumes, seen by a top-down
## perspective camera (GTA1/GTA2 did the same) and composited into the 2D
## world as a texture. The ground plane y = 0 maps 1:1 onto the 2D map:
##
##   2D layer (x, y)  ->  3D (x, 0, y)      (y down on screen = +z)
##
## The camera looks straight down from (cx, D, cy) and D is chosen so the
## ground plane fills exactly the 2D camera's view (D = view height / 2 /
## tan(fov / 2)). The ground then lines up exactly; a point at height h is
## pushed out from the view centre by r * h / (D - h). Facades open toward the
## centre and change continuously, with no wall selection anywhere.
##
## One ArrayMesh per chunk (walls, roofs, windows, doors). The lit windows go
## into a second mesh, and the building mesh is instanced again in black.
## A second camera renders those two additively above the night tint, so
## nearer buildings still hide them.
extends Node2D

const B25 := preload("res://buildings_25d.gd")  # colours, window rules, unit()
static var FOV := 30.0  # degrees, vertical; higher = deeper facades. godot-22: 40 let tall buildings swallow streets, 25 flattens low ones
const LIGHT := Vector2(-0.6, -0.8)  # walls facing up-left are lit (2D screen direction)
const WINDOW_OUT := 0.05  # metres in front of the wall, so depth testing keeps windows on top
const LIT_OUT := 0.08
const LAYER_BUILDINGS := 1
const LAYER_LIT := 2
const LAYER_OCCLUDERS := 4

var _view: SubViewport
var _lit_view: SubViewport
var _camera: Camera3D
var _lit_camera: Camera3D
var _sprite: Sprite2D
var _lit_sprite: Sprite2D


static func _make_material(black: bool) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.cull_mode = BaseMaterial3D.CULL_BACK  # godot-22: _tri winds every triangle toward its outward side
	m.vertex_color_use_as_albedo = not black
	m.albedo_color = Color.BLACK if black else Color.WHITE
	return m


func _ready() -> void:
	_view = _make_view(LAYER_BUILDINGS)
	_camera = _view.get_child(0)
	_lit_view = _make_view(LAYER_LIT | LAYER_OCCLUDERS)
	_lit_camera = _lit_view.get_child(0)
	_lit_view.world_3d = _view.world_3d  # same buildings, the other camera
	_sprite = _make_sprite(_view, 7)
	_lit_sprite = _make_sprite(_lit_view, 21)
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD  # render/buildings.py: BLEND_RGB_ADD
	_lit_sprite.material = add
	_lit_view.render_target_update_mode = SubViewport.UPDATE_DISABLED
	_lit_sprite.visible = false


func _make_view(mask: int) -> SubViewport:
	var view := SubViewport.new()
	view.own_world_3d = true
	view.transparent_bg = true
	view.msaa_3d = Viewport.MSAA_DISABLED
	view.positional_shadow_atlas_size = 0
	var camera := Camera3D.new()
	camera.fov = FOV
	camera.keep_aspect = Camera3D.KEEP_HEIGHT
	camera.cull_mask = mask
	camera.rotation_degrees = Vector3(-90.0, 0.0, 0.0)  # looking down -y; screen up = -z = 2D up
	view.add_child(camera)
	add_child(view)
	return view


func _make_sprite(view: SubViewport, z: int) -> Sprite2D:
	var sprite := Sprite2D.new()
	sprite.texture = view.get_texture()
	sprite.z_index = z
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST  # one texel per screen pixel
	add_child(sprite)
	return sprite


## The camera height (metres) at which the ground plane fills a view
## `view_height_m` tall.
static func camera_height(view_height_m: float) -> float:
	return view_height_m / 2.0 / tan(deg_to_rad(FOV) / 2.0)


## Where a 3D point appears on the 2D map (layer coordinates), seen by the
## camera above `centre` at `height`: a pure function, for the alignment tests.
static func project(p: Vector3, centre: Vector2, height: float) -> Vector2:
	return centre + (Vector2(p.x, p.z) - centre) * height / (height - p.y)


static func to_3d(p: Vector2, height := 0.0) -> Vector3:
	return Vector3(p.x, height, p.y)


## Follow the 2D camera: same centre, same metres per screen pixel.
func _process(_delta: float) -> void:
	var camera_2d := get_viewport().get_camera_2d()
	if camera_2d == null:
		return
	var size := Vector2i(get_viewport().get_visible_rect().size)
	var centre := camera_2d.get_screen_center_position()
	var height := camera_height(size.y / camera_2d.zoom.y)
	for v in [_view, _lit_view]:
		if v.size != size:
			v.size = size
	for c in [_camera, _lit_camera]:
		c.position = Vector3(centre.x, height, centre.y)
		c.near = maxf(1.0, height * 0.02)
		c.far = height + 1.0
	for s in [_sprite, _lit_sprite]:
		s.position = centre
		s.scale = Vector2.ONE / camera_2d.zoom


## Night windows, as the 2D renderer: from darkness 0.25, up to 165/255 by
## 0.5. The lit pass doesn't render at all by day.
func set_darkness(darkness: float) -> void:
	var intensity := clampf((darkness - 0.25) / 0.25, 0.0, 1.0)
	_lit_sprite.visible = intensity > 0.0
	_lit_sprite.modulate = Color(1, 1, 1, 165.0 / 255.0 * intensity)
	_lit_view.render_target_update_mode = SubViewport.UPDATE_ALWAYS if intensity > 0.0 else SubViewport.UPDATE_DISABLED


## A chunk's mesh instances (meshes()) join the 3D world.
func add(instances: Array) -> void:
	for node in instances:
		if node.get_parent() == null:
			_view.add_child(node)


func instance_count() -> int:
	return _view.get_child_count() - 1  # minus the camera


## One chunk's mesh arrays (any thread): {"verts", "colors", "lit" (the
## lit windows' verts), "hulls", "stats"}.
static func build(buildings: Array, styles: Array, origin: Vector2) -> Dictionary:
	var out := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "lit": PackedVector3Array(), "hulls": [],
		"stats": {"buildings": 0, "walls": 0, "windows": 0, "lit": 0, "triangles": 0}}
	for i in buildings.size():
		var footprint: PackedVector2Array = buildings[i]
		if footprint.size() >= 3 and not Geometry2D.triangulate_polygon(footprint).is_empty():
			_building(out, footprint, styles[i] if i < styles.size() else [], origin)
	out["stats"]["triangles"] = (out["verts"].size() + out["lit"].size()) / 3
	return out


## The chunk's mesh instances (main thread): buildings, their black
## occluders for the lit pass, and the lit windows.
static func meshes(arrays: Dictionary) -> Array:
	var instances: Array = []
	if arrays["verts"].is_empty():
		return instances
	var mesh := _mesh(arrays["verts"], arrays["colors"])
	instances.append(_instance(mesh, _shared["material"], LAYER_BUILDINGS))
	instances.append(_instance(mesh, _shared["black"], LAYER_OCCLUDERS))
	if not arrays["lit"].is_empty():
		var colors := PackedColorArray()
		colors.resize(arrays["lit"].size())
		colors.fill(B25.WINDOW_LIT)
		instances.append(_instance(_mesh(arrays["lit"], colors), _shared["material"], LAYER_LIT))
	return instances


static var _shared := {"material": _make_material(false), "black": _make_material(true)}


static func _mesh(verts: PackedVector3Array, colors: PackedColorArray) -> ArrayMesh:
	var surface := []
	surface.resize(Mesh.ARRAY_MAX)
	surface[Mesh.ARRAY_VERTEX] = verts
	surface[Mesh.ARRAY_COLOR] = colors
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, surface)
	return mesh


static func _instance(mesh: ArrayMesh, material: Material, layer: int) -> MeshInstance3D:
	var node := MeshInstance3D.new()
	node.mesh = mesh
	node.material_override = material
	node.layers = layer
	node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	return node


## One triangle, wound so its front faces `facing` (the outward normal):
## Godot's front faces are clockwise, i.e. (b - a) x (c - a) points away.
## Footprints come either way round, so the winding is decided here, once.
static func _tri(out: Dictionary, a: Vector3, b: Vector3, c: Vector3, color: Color, facing: Vector3, key := "verts") -> void:
	if (b - a).cross(c - a).dot(facing) > 0.0:
		var t := b
		b = c
		c = t
	out[key].append_array(PackedVector3Array([a, b, c]))
	if key == "lit":
		return
	out["colors"].append_array(PackedColorArray([color, color, color]))


static func _quad(out: Dictionary, a: Vector3, b: Vector3, c: Vector3, d: Vector3, color: Color, facing: Vector3, lit := false) -> void:
	_tri(out, a, b, c, color, facing, "lit" if lit else "verts")
	_tri(out, a, c, d, color, facing, "lit" if lit else "verts")


static func _polygon(out: Dictionary, polygon: PackedVector2Array, heights: PackedFloat32Array, color: Color) -> void:
	var triangles := Geometry2D.triangulate_polygon(polygon)
	for t in range(0, triangles.size(), 3):
		_tri(out, to_3d(polygon[triangles[t]], heights[triangles[t]]), to_3d(polygon[triangles[t + 1]], heights[triangles[t + 1]]),
			to_3d(polygon[triangles[t + 2]], heights[triangles[t + 2]]), color, Vector3.UP)


static func _building(out: Dictionary, footprint: PackedVector2Array, style: Array, origin: Vector2) -> void:
	var roof_color := Color8(int(style[0][0]), int(style[0][1]), int(style[0][2])) if style.size() > 0 else Color8(83, 86, 87)
	var height: float = style[2] if style.size() > 2 else 8.0
	var wall_color := Color8(int(style[4][0]), int(style[4][1]), int(style[4][2])) if style.size() > 4 else Color8(139, 139, 137)
	var floors: int = maxi(1, int(style[5]) if style.size() > 5 else roundi(height / 3.0))
	var category: int = int(style[6]) if style.size() > 6 else 0
	var gabled := style.size() > 1 and int(style[1]) == 1
	var outward_sign := -1.0 if B25.signed_area(footprint) > 0.0 else 1.0
	var centre := Vector2.ZERO
	for p in footprint:
		centre += p
	centre /= footprint.size()
	var seed_base := roundf(centre.x + origin.x) * 0.0001 + roundf(-centre.y + origin.y) * 0.00013
	out["stats"]["buildings"] += 1
	# Every wall: the camera decides which ones show.
	for i in footprint.size():
		var a := footprint[i]
		var b := footprint[(i + 1) % footprint.size()]
		var edge := b - a
		if edge.length_squared() < 1e-6:
			continue
		var normal := Vector2(-edge.y, edge.x).normalized() * outward_sign
		var shade := 0.72 + 0.28 * clampf(normal.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0)
		_quad(out, to_3d(a), to_3d(b), to_3d(b, height), to_3d(a, height), Color(wall_color.r * shade, wall_color.g * shade, wall_color.b * shade), to_3d(normal))
		out["stats"]["walls"] += 1
		_windows(out, a, b, normal, height, floors, category, seed_base + i * 7.13)
	_doors(out, footprint, style[3] if style.size() > 3 else [], outward_sign, height, floors, origin)
	if gabled:
		_gabled(out, footprint, height, roof_color)
	else:
		var heights := PackedFloat32Array()
		heights.resize(footprint.size())
		heights.fill(height)
		_polygon(out, footprint, heights, roof_color)
	out["hulls"].append(Geometry2D.convex_hull(footprint))  # headlight clipping: the footprint (the roof moves with the camera)


## render/buildings.py's window slots on a real wall: up to 3 a floor (2 on a
## house, every other floor), a storefront row on a commercial ground floor,
## lit deterministically by Pygame's probabilities.
static func _windows(out: Dictionary, a: Vector2, b: Vector2, normal: Vector2, height: float, floors: int, category: int, seed: float) -> void:
	var length := a.distance_to(b)
	if length < 12.0 / 9.0:
		return
	var house := category == 1
	var along := (b - a) / length
	var count := clampi(int(length / ((44.0 if house else 32.0) / 9.0)), 1, 2 if house else 3)
	var storey := height / floors
	for f in floors:
		if house and floors > 1 and f % 2 == 1:
			continue
		var storefront := category == 2 and f == 0
		var tall := storey * 0.55 * (1.45 if storefront else 0.75 if house else 1.0)
		var half := length / (count + 2) * 0.45 / 2.0 * (1.35 if storefront else 0.75 if house else 1.0)
		var bottom := storey * (f + 0.5) - tall / 2.0
		for w in count:
			var at := a + (b - a) * ((w + 1.0) / (count + 1.0))
			var p0 := at - along * half
			var p1 := at + along * half
			for lit in [false, true]:
				if lit and not unit_lit(seed + f * 3.71 + w * 1.37, storefront, category):
					continue
				var o := normal * (LIT_OUT if lit else WINDOW_OUT)
				_quad(out, to_3d(p0 + o, bottom), to_3d(p1 + o, bottom), to_3d(p1 + o, bottom + tall), to_3d(p0 + o, bottom + tall),
					B25.STOREFRONT if storefront else B25.WINDOW, to_3d(normal), lit)
				out["stats"]["lit" if lit else "windows"] += 1


static func unit_lit(seed: float, storefront: bool, category: int) -> bool:
	return B25.unit(seed) < B25.LIT_PROBABILITY[2 if storefront else category if category == 1 else 0]


## A door at each OSM entrance, on its nearest wall, one storey high.
static func _doors(out: Dictionary, footprint: PackedVector2Array, entrances: Array, outward_sign: float, height: float, floors: int, origin: Vector2) -> void:
	for entrance in entrances:
		var at := MapMath.point(origin, entrance[0], entrance[1])
		var best := -1
		var best_distance := INF
		for i in footprint.size():
			var d := Geometry2D.get_closest_point_to_segment(at, footprint[i], footprint[(i + 1) % footprint.size()]).distance_to(at)
			if d < best_distance:
				best_distance = d
				best = i
		var a := footprint[best]
		var b := footprint[(best + 1) % footprint.size()]
		var along := (b - a).normalized()
		var o := Vector2(-along.y, along.x) * outward_sign * WINDOW_OUT
		var foot := Geometry2D.get_closest_point_to_segment(at, a, b) + o
		var half := clampf(a.distance_to(b) * 0.22, 0.33, 1.22) / 2.0
		var top := minf(2.2, height / floors * 0.8)
		_quad(out, to_3d(foot - along * half), to_3d(foot + along * half), to_3d(foot + along * half, top), to_3d(foot - along * half, top), B25.DOOR, to_3d(o))


## A simple pitched roof: the ridge along the longest edge's direction,
## through the centre, rising 0.3 x the half width (at most 4 m). Each side
## is one plane (height grows linearly toward the ridge), so the footprint is
## cut at the ridge line and each half triangulated with its vertex heights.
## ponytail: the gable-end triangles stay open; add them if they show.
static func _gabled(out: Dictionary, footprint: PackedVector2Array, height: float, color: Color) -> void:
	var longest := 0
	for i in footprint.size():
		if footprint[i].distance_squared_to(footprint[(i + 1) % footprint.size()]) > footprint[longest].distance_squared_to(footprint[(longest + 1) % footprint.size()]):
			longest = i
	var axis := (footprint[(longest + 1) % footprint.size()] - footprint[longest]).normalized()
	var normal := Vector2(-axis.y, axis.x)
	var centre := Vector2.ZERO
	for p in footprint:
		centre += p
	centre /= footprint.size()
	var reach := 0.0
	for p in footprint:
		reach = maxf(reach, absf((p - centre).dot(normal)))
	var rise := minf(4.0, reach * 0.3)
	var far := 10000.0
	for side: float in [1.0, -1.0]:
		var half := PackedVector2Array([centre - axis * far, centre + axis * far, centre + axis * far + normal * side * far, centre - axis * far + normal * side * far])
		var shade := color.lightened(14.0 / 255.0) if side > 0.0 else color.darkened(12.0 / 255.0)
		for facet in Geometry2D.intersect_polygons(footprint, half):
			var heights := PackedFloat32Array()
			for p in facet:
				heights.append(height + rise * (1.0 - absf((p - centre).dot(normal)) / reach) if reach > 0.0 else height)
			_polygon(out, facet, heights, shade)
