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
## One ArrayMesh per chunk (walls, roofs, windows, doors), and one for its lit
## windows, both seen by the one camera (godot-final-09: no second pass).
extends Node2D

const B25 := preload("res://buildings_25d.gd")  # colours, window rules, unit()
static var FOV := 30.0  # degrees, vertical; higher = deeper facades. godot-22: 40 let tall buildings swallow streets, 25 flattens low ones
const LIGHT := Vector2(-0.6, -0.8)  # walls facing up-left are lit (2D screen direction)
const WINDOW_OUT := 0.05  # metres in front of the wall, so depth testing keeps windows on top
const LIT_OUT := 0.08
const LAYER_BUILDINGS := 1
# godot-final-09: the lit windows are their own mesh in the one building view,
# just in front of the windows; one shared material fades them from the
# ordinary window colour (day) to lit (night) - no second camera, viewport,
# occluders or composite. Bright, so they read through the night tint.
const WINDOW_LIT_NIGHT := Color8(255, 222, 142)
# rrt-018-shadows: the sun lights only a ground plane (the buildings are
# unshaded, their light is baked into their colours); the buildings cast
# its shadows. A second view of the SAME 3D world sees nothing but that
# plane - white in the sun, darker in shadow - and is multiplied over the map
# under the buildings (z 6). The Compatibility renderer has no working
# shadow_to_opacity, so the shadows can't be alpha in the building view.
const LAYER_SHADOW_GROUND := 2
const SHADOW_DARKNESS := 0.45  # how much a shadow darkens the ground in full, clear-sky sunlight
const SHADOW_VIEW_SCALE := 2  # the shadow view renders at 1/2 resolution, smoothed up (shadows need no more)
const SHADOW_GROUND_MARGIN := 1.3  # the plane covers this times the view (the camera moves between frames)

var _view: SubViewport
var _camera: Camera3D
var _sprite: Sprite2D
var _sun: DirectionalLight3D
var _shadow_ground: MeshInstance3D
var _shadow_view: SubViewport
var _shadow_camera: Camera3D
var _shadow_sprite: Sprite2D
var _sun_key := Vector3(INF, INF, INF)  # the (altitude, azimuth, cloud) applied last
var shadows_enabled := true


static func _make_material(flat := false) -> Material:
	if not flat:
		var roof := ShaderMaterial.new()
		roof.shader = preload("res://building_snow.gdshader")
		return roof
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.cull_mode = BaseMaterial3D.CULL_BACK  # godot-22: _tri winds every triangle toward its outward side
	m.vertex_color_use_as_albedo = true
	m.albedo_color = lit_color(0.0) if flat else Color.WHITE  # times the vertex colours: the ambient light (set_light)
	return m


func _ready() -> void:
	_view = _make_view(LAYER_BUILDINGS)
	_camera = _view.get_child(0)
	_sprite = _make_sprite(_view, 7)
	_sun = make_sun()
	_view.add_child(_sun)
	_shadow_ground = make_shadow_ground()
	_view.add_child(_shadow_ground)
	_shadow_view = SubViewport.new()  # the same world: no building geometry twice
	_shadow_view.world_3d = _view.find_world_3d()  # its own_world_3d (world_3d itself is unset)
	_shadow_view.transparent_bg = false
	_shadow_view.msaa_3d = Viewport.MSAA_DISABLED
	_shadow_view.positional_shadow_atlas_size = 0
	_shadow_view.render_target_update_mode = SubViewport.UPDATE_DISABLED
	_shadow_camera = Camera3D.new()
	_shadow_camera.fov = FOV
	_shadow_camera.keep_aspect = Camera3D.KEEP_HEIGHT
	_shadow_camera.cull_mask = LAYER_SHADOW_GROUND
	_shadow_camera.rotation_degrees = Vector3(-90.0, 0.0, 0.0)
	var white := Environment.new()  # nothing there (off the plane): multiplied by 1, unchanged
	white.background_mode = Environment.BG_COLOR
	white.background_color = Color.WHITE
	_shadow_camera.environment = white
	_shadow_view.add_child(_shadow_camera)
	add_child(_shadow_view)
	_shadow_sprite = _make_sprite(_shadow_view, 6)  # under the buildings (7), over the ground and roads
	var multiply := CanvasItemMaterial.new()
	multiply.blend_mode = CanvasItemMaterial.BLEND_MODE_MUL
	_shadow_sprite.material = multiply
	_shadow_sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	_shadow_sprite.visible = false


## The sun's light: one orthogonal shadow map (the top-down view needs no
## splits), off until set_sun() turns it on.
static func make_sun() -> DirectionalLight3D:
	var sun := DirectionalLight3D.new()
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	sun.directional_shadow_blend_splits = false
	sun.shadow_bias = 0.05
	sun.shadow_normal_bias = 0.5
	# All on the shadow view's layer: a camera culls the light itself and every
	# caster outside its mask. The casters are shadows-only copies of the
	# building meshes (meshes()), so the shadow view draws only the ground.
	sun.layers = LAYER_SHADOW_GROUND
	sun.light_cull_mask = LAYER_SHADOW_GROUND
	sun.shadow_caster_mask = LAYER_SHADOW_GROUND
	sun.visible = false
	return sun


static func make_shadow_ground() -> MeshInstance3D:
	var plane := PlaneMesh.new()
	plane.size = Vector2.ONE
	var material := ShaderMaterial.new()
	material.shader = preload("res://shadow_ground.gdshader")
	var ground := MeshInstance3D.new()
	ground.mesh = plane
	ground.material_override = material
	ground.layers = LAYER_SHADOW_GROUND
	ground.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	ground.visible = false
	return ground


func set_shadows_enabled(on: bool) -> void:
	if on == shadows_enabled:
		return
	shadows_enabled = on
	_sun.shadow_enabled = on
	var previous := _sun_key
	_sun_key = Vector3(INF, INF, INF)
	if is_finite(previous.x):
		set_celestial_light(previous.x, previous.y, previous.z)


## Sun direction/strength from the server, cached until the weather or option changes.
func set_sun(altitude_deg: float, azimuth_deg: float, cloud_cover: float) -> void:
	set_celestial_light(altitude_deg, azimuth_deg, Daylight.sunlight(altitude_deg, cloud_cover))


func set_celestial_light(altitude_deg: float, azimuth_deg: float, strength: float) -> void:
	var key := Vector3(altitude_deg, azimuth_deg, strength)
	if key.is_equal_approx(_sun_key):
		return
	_sun_key = key
	var on := shadows_enabled and strength > 0.01
	_sun.visible = on
	_shadow_ground.visible = on
	_shadow_sprite.visible = on
	_shadow_view.render_target_update_mode = SubViewport.UPDATE_ALWAYS if on else SubViewport.UPDATE_DISABLED  # no cost at night or overcast
	if not on:
		return
	_sun.basis = sun_basis(Daylight.sun_direction(altitude_deg, azimuth_deg))
	_shadow_ground.material_override.set_shader_parameter("darkness", SHADOW_DARKNESS * strength)


## A light whose -z (where Godot's directional light shines) points away
## from `towards_sun`.
static func sun_basis(towards_sun: Vector3) -> Basis:
	var up := Vector3.UP if absf(towards_sun.y) < 0.999 else Vector3.FORWARD
	return Basis.looking_at(-towards_sun, up)


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
	# Unshaded: the 3D view is lit already (set_light), not again. Premultiplied:
	# see-through glass was blended over the view's clear background once
	# already; a plain alpha blend did it twice and darkened the ground under it.
	var material := CanvasItemMaterial.new()
	material.light_mode = CanvasItemMaterial.LIGHT_MODE_UNSHADED
	material.blend_mode = CanvasItemMaterial.BLEND_MODE_PREMULT_ALPHA
	sprite.material = material
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST  # one texel per screen pixel
	add_child(sprite)
	return sprite


## The camera height (metres) at which the ground plane fills a view
## `view_height_m` tall.
static func camera_height(view_height_m: float) -> float:
	return view_height_m / 2.0 / tan(deg_to_rad(FOV) / 2.0)


## The 3D camera this frame: what draws at a height in 2D (the canopies)
## projects the same way.
static var view_centre := Vector2.ZERO
static var view_height := 0.0


## A point at height h, where the 3D camera shows it (the 2D map position
## of its image); unchanged before the first frame.
static func lift_point(p: Vector2, h: float) -> Vector2:
	return project(to_3d(p, h), view_centre, view_height) if view_height > h else p


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
	if _view.size != size:
		_view.size = size
	view_centre = centre
	view_height = height
	get_parent().canopies_moved(Rect2(centre - Vector2(size) / camera_2d.zoom / 2.0, Vector2(size) / camera_2d.zoom))
	_camera.position = Vector3(centre.x, height, centre.y)
	_camera.near = maxf(1.0, height * 0.02)
	_camera.far = height + 1.0
	if _shadow_ground.visible:  # under the whole view; shadows only as far as the camera sees
		if _shadow_view.size != size / SHADOW_VIEW_SCALE:
			_shadow_view.size = size / SHADOW_VIEW_SCALE
		_shadow_camera.position = _camera.position
		_shadow_camera.near = _camera.near
		# Far beyond the ground: with the ground at the far plane (as the
		# building camera has it) the orthogonal shadow fit loses every shadow.
		_shadow_camera.far = height * 2.0 + 10.0
		_shadow_sprite.position = centre
		_shadow_sprite.scale = _sprite.scale * SHADOW_VIEW_SCALE
		var view_m := Vector2(size) / camera_2d.zoom
		_shadow_ground.position = Vector3(centre.x, 0.0, centre.y)
		_shadow_ground.scale = Vector3(view_m.x * SHADOW_GROUND_MARGIN, 1.0, view_m.y * SHADOW_GROUND_MARGIN)
		_sun.directional_shadow_max_distance = Vector2(height, view_m.length() * 0.5 * SHADOW_GROUND_MARGIN).length()
	_sprite.position = centre
	_sprite.scale = Vector2.ONE / camera_2d.zoom


## Night windows, as the 2D renderer: lit from darkness 0.25, fully by 0.5
## - one material colour, so no geometry is rebuilt.
## godot-lights-01: the buildings take the ambient light in their own
## material (the composite is unshaded, so they're darkened once); the lit
## windows fade from an ordinary window under that light to their own warm
## light as `level` (Daylight.artificial) rises - no geometry is rebuilt.
func set_light(level: float, ambient: Color) -> void:
	_shared["material"].set_shader_parameter("ambient", ambient)
	_shared["glass"].albedo_color = Color(ambient.r, ambient.g, ambient.b)
	_shared["lit"].albedo_color = lit_color(level, ambient)
	if (level > 0.01) != _lit_on:  # the lit meshes in or out (by day they'd only cost)
		_lit_on = level > 0.01
		for node in _view.get_children():
			if node is MeshInstance3D and node.material_override == _shared["lit"]:
				node.visible = _lit_on


func set_arena_lights(on: bool) -> void:
	_arena_on = on
	_shared["arena"].albedo_color = Color.WHITE
	for node in _view.get_children():
		if node is MeshInstance3D and node.material_override == _shared["arena"]:
			node.visible = on


var _lit_on := false
var _arena_on := false


func set_snow(cover: float) -> void:
	_shared["material"].set_shader_parameter("snow_cover", clampf(cover, 0.0, 1.0))


## The lit windows' multiplier over their (warm, varied) vertex colours: at
## level 0 an ordinary window under the ambient light, at 1 their own light.
static func lit_color(level: float, ambient := Color.WHITE) -> Color:
	var dim := Color(B25.WINDOW.r / WINDOW_LIT_NIGHT.r * ambient.r, B25.WINDOW.g / WINDOW_LIT_NIGHT.g * ambient.g, B25.WINDOW.b / WINDOW_LIT_NIGHT.b * ambient.b)
	return dim.lerp(Color.WHITE, clampf(level, 0.0, 1.0))


## A chunk's mesh instances (meshes()) join the 3D world.
func add(instances: Array) -> void:
	for node in instances:
		if node.get_parent() == null:
			if node.material_override == _shared["lit"]:
				node.visible = _lit_on
			elif node.material_override == _shared["arena"]:
				node.visible = _arena_on
			_view.add_child(node)


func instance_count() -> int:
	return _view.get_child_count() - 3  # minus the camera, the sun and the shadow ground


## One chunk's mesh arrays (any thread): {"verts", "colors", "lit" (the
## lit windows' verts), "stats"}.
static func build(buildings: Array, styles: Array, origin: Vector2, sites: Array = []) -> Dictionary:
	var out := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array(), "lit": PackedVector3Array(),
		"arena": PackedVector3Array(), "shadow": PackedVector3Array(), "glass": PackedVector3Array(), "glass_colors": PackedColorArray(),
		"stats": {"buildings": 0, "walls": 0, "windows": 0, "lit": 0, "triangles": 0}}
	for i in buildings.size():
		var footprint: PackedVector2Array = buildings[i]
		if footprint.size() >= 3 and not Geometry2D.triangulate_polygon(footprint).is_empty():
			_building(out, footprint, styles[i] if i < styles.size() else [], origin)
	for site in sites:
		_crane(out, site, origin)
	out["stats"]["triangles"] = (out["verts"].size() + out["lit"].size() + out["glass"].size()) / 3
	return out


## The chunk's mesh instances (main thread): the buildings and their lit
## windows, both in the one building view.
static func meshes(arrays: Dictionary) -> Array:
	var instances: Array = []
	if not arrays.get("glass", PackedVector3Array()).is_empty():
		instances.append(_instance(_mesh(arrays["glass"], arrays["glass_colors"]), _shared["glass"], LAYER_BUILDINGS))
	if arrays["verts"].is_empty():
		return instances
	var mesh := _mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"])
	instances.append(_instance(mesh, _shared["material"], LAYER_BUILDINGS))
	# rrt-018-shadows: each building as a plain prism (walls and a flat roof,
	# no windows or doors: a fifth of the triangles), not drawn, only casting
	# the sun's shadow in the shadow view (its layer)
	if not arrays["shadow"].is_empty():
		var caster := _instance(_mesh(arrays["shadow"], PackedColorArray()), _shared["caster"], LAYER_SHADOW_GROUND)
		caster.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY
		instances.append(caster)
	if not arrays["lit"].is_empty():
		var colors := PackedColorArray()  # warm, each window a little brighter or dimmer (deterministic)
		colors.resize(arrays["lit"].size())
		for i in colors.size():
			var shade := 0.82 + 0.18 * B25.unit(float(i / 6) * 0.61803 + arrays["lit"][i - i % 6].x * 0.013)
			colors[i] = Color(WINDOW_LIT_NIGHT.r * shade, WINDOW_LIT_NIGHT.g * shade, WINDOW_LIT_NIGHT.b * shade)
		instances.append(_instance(_mesh(arrays["lit"], colors), _shared["lit"], LAYER_BUILDINGS))
	if not arrays["arena"].is_empty():
		var colors := PackedColorArray()
		colors.resize(arrays["arena"].size())
		colors.fill(WINDOW_LIT_NIGHT)
		instances.append(_instance(_mesh(arrays["arena"], colors), _shared["arena"], LAYER_BUILDINGS))
	return instances


static var _shared := {"material": _make_material(), "lit": _make_material(true), "arena": _make_material(true),
	"caster": _caster_material(),  # the shadows-only prisms: any opaque material casts (the unshaded shader didn't)
	"glass": _glass_material()}


## Greenhouse glass: alpha-blended vertex colours, both faces (the far
## panes show through the near ones), times the ambient light (set_light).
static func _glass_material() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.vertex_color_use_as_albedo = true
	return m


static func _caster_material() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.cull_mode = BaseMaterial3D.CULL_DISABLED  # the prisms' winding doesn't matter
	return m


static func _mesh(verts: PackedVector3Array, colors: PackedColorArray, roof_mask := PackedVector2Array()) -> ArrayMesh:
	var surface := []
	surface.resize(Mesh.ARRAY_MAX)
	surface[Mesh.ARRAY_VERTEX] = verts
	if not colors.is_empty():
		surface[Mesh.ARRAY_COLOR] = colors
	if not roof_mask.is_empty():
		surface[Mesh.ARRAY_TEX_UV] = roof_mask
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
	var normal := (b - a).cross(c - a)
	if normal.dot(facing) > 0.0:
		var t := b
		b = c
		c = t
		normal = -normal
	out[key].append_array(PackedVector3Array([a, b, c]))
	if key != "verts":
		return
	out["colors"].append_array(PackedColorArray([color, color, color]))
	var shade := 0.90 if facing.y > 0.5 and Vector2(-normal.x, -normal.z).dot(LIGHT) < -0.001 else 1.0
	var mask := Vector2(1.0 if facing.y > 0.5 else 0.0, shade)
	out["roof_mask"].append_array(PackedVector2Array([mask, mask, mask]))


static func _quad(out: Dictionary, a: Vector3, b: Vector3, c: Vector3, d: Vector3, color: Color, facing: Vector3, key := "verts") -> void:
	_tri(out, a, b, c, color, facing, key)
	_tri(out, a, c, d, color, facing, key)


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
	var arena := style.size() > 7 and int(style[7]) == 1
	var gabled := style.size() > 1 and int(style[1]) == 1
	var outward_sign := -1.0 if B25.signed_area(footprint) > 0.0 else 1.0
	if style.size() > 7 and int(style[7]) == 2:
		_glasshouse(out, footprint, height, gabled, outward_sign)
		return
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
		_windows(out, a, b, normal, height, floors, category, seed_base + i * 7.13, arena)
	_doors(out, footprint, style[3] if style.size() > 3 else [], outward_sign, height, floors, origin)
	_shadow_prism(out["shadow"], footprint, height)
	if gabled:
		_gabled(out, footprint, height, roof_color, wall_color)
	else:
		var heights := PackedFloat32Array()
		heights.resize(footprint.size())
		heights.fill(height)
		_polygon(out, footprint, heights, roof_color)


## A greenhouse (static_world.is_glasshouse): walls and roof of see-through
## glass in their own mesh (_shared["glass"]), the ground and cars showing
## through. No windows or doors, and no shadow prism: glass casts none.
const GLASS := Color(0.86, 0.95, 0.90, 0.3)

static func _glasshouse(out: Dictionary, footprint: PackedVector2Array, height: float, gabled: bool, outward_sign: float) -> void:
	var glass := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array()}
	for i in footprint.size():
		var a := footprint[i]
		var b := footprint[(i + 1) % footprint.size()]
		var edge := b - a
		if edge.length_squared() < 1e-6:
			continue
		var normal := Vector2(-edge.y, edge.x).normalized() * outward_sign
		var shade := 0.85 + 0.15 * clampf(normal.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0)
		_quad(glass, to_3d(a), to_3d(b), to_3d(b, height), to_3d(a, height), Color(GLASS.r * shade, GLASS.g * shade, GLASS.b * shade), to_3d(normal))
	if gabled:
		_gabled(glass, footprint, height, GLASS, GLASS)
	else:
		var heights := PackedFloat32Array()
		heights.resize(footprint.size())
		heights.fill(height)
		_polygon(glass, footprint, heights, GLASS)
	for i in glass["colors"].size():  # the shading above drops alpha: every pane the same glass
		var color: Color = glass["colors"][i]
		color.a = GLASS.a
		glass["colors"][i] = color
	out["glass"].append_array(glass["verts"])
	out["glass_colors"].append_array(glass["colors"])
	out["stats"]["buildings"] += 1


## A tower crane on a construction site (its fence ring) big enough for
## one: a yellow mast, the jib swung to a position-seeded angle and sized
## to the site, the counter-jib with its concrete weights and the cab.
## Casts its shadow like a building.
const CRANE_YELLOW := Color8(235, 185, 30)
const MIN_CRANE_SITE_M2 := 600.0

static func _crane(out: Dictionary, site: PackedVector2Array, origin: Vector2) -> void:
	if site.size() < 3 or absf(B25.signed_area(site)) < MIN_CRANE_SITE_M2:
		return
	var centre := Vector2.ZERO
	for p in site:
		centre += p
	centre /= site.size()
	var reach := 0.0
	for p in site:
		reach = maxf(reach, centre.distance_to(p))
	var seed := B25.unit(roundf(centre.x + origin.x) * 0.0007 + roundf(origin.y - centre.y) * 0.0011)
	var height := 28.0 + 16.0 * seed
	var jib := clampf(reach * 0.9, 18.0, 50.0)
	var d := Vector2.from_angle(TAU * B25.unit(seed * 7.31 + 0.17))
	_box(out, centre - d * 1.0, centre + d * 1.0, 1.0, 0.0, height + 3.0, CRANE_YELLOW)  # the mast
	_box(out, centre, centre + d * jib, 0.7, height, height + 1.4, CRANE_YELLOW)  # the jib
	_box(out, centre, centre - d * jib * 0.3, 0.8, height, height + 1.0, CRANE_YELLOW)  # the counter-jib
	_box(out, centre - d * jib * 0.3, centre - d * (jib * 0.3 - 3.0), 1.3, height - 1.5, height + 1.2, Color8(150, 150, 145))  # its weights
	_box(out, centre + d * 1.0, centre + d * 3.0, 1.0, height - 2.5, height, Color8(60, 70, 80))  # the cab
	out["stats"]["cranes"] = out["stats"].get("cranes", 0) + 1


## A box from `a` to `b` on the ground plan, `half_width` either side,
## between heights `bottom` and `top`: four sides and the top (never seen
## from below), drawn and casting a shadow.
static func _box(out: Dictionary, a: Vector2, b: Vector2, half_width: float, bottom: float, top: float, color: Color) -> void:
	var along := (b - a).normalized()
	var side := Vector2(-along.y, along.x) * half_width
	var corners := [a - side, b - side, b + side, a + side]
	for key in ["verts", "shadow"]:
		for i in 4:
			var p: Vector2 = corners[i]
			var q: Vector2 = corners[(i + 1) % 4]
			var outward := ((p + q) / 2.0 - (a + b) / 2.0).normalized()
			var shade := 0.72 + 0.28 * clampf(outward.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0)
			_quad(out, to_3d(p, bottom), to_3d(q, bottom), to_3d(q, top), to_3d(p, top), Color(color.r * shade, color.g * shade, color.b * shade),
				to_3d(outward), key)
		_quad(out, to_3d(corners[0], top), to_3d(corners[1], top), to_3d(corners[2], top), to_3d(corners[3], top), color, Vector3.UP, key)


## The building's shadow caster: its walls and a flat roof at the eaves
## (a gable's ridge is left out: a little shorter shadow, far fewer cases).
static func _shadow_prism(verts: PackedVector3Array, footprint: PackedVector2Array, height: float) -> void:
	for i in footprint.size():
		var a := footprint[i]
		var b := footprint[(i + 1) % footprint.size()]
		verts.append_array(PackedVector3Array([to_3d(a), to_3d(b), to_3d(b, height), to_3d(a), to_3d(b, height), to_3d(a, height)]))
	var triangles := Geometry2D.triangulate_polygon(footprint)
	for t in triangles:
		verts.append(to_3d(footprint[t], height))


## Window slots on a real wall: up to 3 a floor (2 on a
## house, every other floor), a storefront row on a commercial ground floor,
## lit deterministically (LIT_PROBABILITY).
const CATEGORY_WALL := 3  # a plain wall (a stadium's stands, map_chunks.stadium_stands): no window rows


static func _windows(out: Dictionary, a: Vector2, b: Vector2, normal: Vector2, height: float, floors: int, category: int, seed: float, arena: bool) -> void:
	var length := a.distance_to(b)
	if length < 12.0 / 9.0 or category == CATEGORY_WALL:
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
			var color: Color = B25.STOREFRONT if storefront else B25.WINDOW
			var o := normal * WINDOW_OUT
			_quad(out, to_3d(p0 + o, bottom), to_3d(p1 + o, bottom), to_3d(p1 + o, bottom + tall), to_3d(p0 + o, bottom + tall), color, to_3d(normal))
			out["stats"]["windows"] += 1
			if unit_lit(seed + f * 3.71 + w * 1.37, storefront, category):
				o = normal * LIT_OUT
				_quad(out, to_3d(p0 + o, bottom), to_3d(p1 + o, bottom), to_3d(p1 + o, bottom + tall), to_3d(p0 + o, bottom + tall), color, to_3d(normal), "lit")
				out["stats"]["lit"] += 1
			if arena:
				o = normal * (LIT_OUT + 0.01)
				_quad(out, to_3d(p0 + o, bottom), to_3d(p1 + o, bottom), to_3d(p1 + o, bottom + tall), to_3d(p0 + o, bottom + tall), color, to_3d(normal), "arena")


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
## Every wall under a sloping edge gets its gable: the wall continued up to
## the roof (godot-23). Returns the ridge's rise.
static func _gabled(out: Dictionary, footprint: PackedVector2Array, height: float, color: Color, wall_color: Color) -> float:
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
	var outward_sign := -1.0 if B25.signed_area(footprint) > 0.0 else 1.0
	var roof_at := func(p: Vector2) -> float: return height + rise * (1.0 - absf((p - centre).dot(normal)) / reach) if reach > 0.0 else height
	for i in footprint.size():
		var a := footprint[i]
		var b := footprint[(i + 1) % footprint.size()]
		var top := [to_3d(b, roof_at.call(b)), to_3d(a, roof_at.call(a))]
		var da := (a - centre).dot(normal)
		var db := (b - centre).dot(normal)
		if signf(da) != signf(db) and da != db:  # the ridge crosses this wall: the gable's peak
			top.insert(1, to_3d(a.lerp(b, da / (da - db)), height + rise))
		if top.all(func(v): return v.y - height < 1e-3) or a.distance_squared_to(b) < 1e-6:
			continue  # an eave: the roof meets this wall at its top
		var edge := b - a
		var facing := to_3d(Vector2(-edge.y, edge.x).normalized() * outward_sign)
		var shade := 0.72 + 0.28 * clampf(Vector2(facing.x, facing.z).dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0)
		var wall := Color(wall_color.r * shade, wall_color.g * shade, wall_color.b * shade)
		var fan := [to_3d(b, height)] + top
		for t in fan.size() - 1:
			_tri(out, to_3d(a, height), fan[t], fan[t + 1], wall, facing)
	return rise
