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
const RS := preload("res://render_style.gd")  # the puddles' colour
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
static var opaque := false  # --outdoor-3d (use_shaded): the view draws its own ground, shaded by real lights
const GROUND := Color(0.27, 0.33, 0.25)  # map_layer._draw_ground's open ground
const SUN_ENERGY := 1.0  # --outdoor-3d light: full clear-sky sun, plus the ambient fill below
const AMBIENT_ENERGY := 0.45


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
	if opaque:
		_view.transparent_bg = false
		var sky := Environment.new()  # off the loaded chunks: the 2D map's open ground
		sky.background_mode = Environment.BG_COLOR
		sky.background_color = GROUND
		sky.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		sky.ambient_light_color = Color.WHITE
		sky.ambient_light_energy = AMBIENT_ENERGY
		sky.sky = Sky.new()  # what wet roads and water reflect (the camera never sees it: the ground fills the view)
		sky.sky.sky_material = ProceduralSkyMaterial.new()
		sky.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
		sky.glow_enabled = true  # step 4: lit lamps and windows (emission above 1) bloom a little
		sky.glow_hdr_threshold = 1.0
		sky.glow_intensity = 0.5
		_view.positional_shadow_atlas_size = 4096  # the nearest lamps' and the taxi's headlights' shadows
		_camera.environment = sky
	_sprite = _make_sprite(_view, 7)
	_sun = make_sun()
	if opaque:
		# The sun lights the drawn meshes and casts with the shadows-only copies
		# straight onto them: no multiplied shadow overlay (it would shade twice).
		_sun.layers = LAYER_BUILDINGS
		_sun.light_cull_mask = LAYER_BUILDINGS
		_sun.shadow_caster_mask = LAYER_BUILDINGS  # step 4: the drawn meshes cast (meshes(), car())
	_view.add_child(_sun)
	_shadow_ground = make_shadow_ground()
	_view.add_child(_shadow_ground)
	_cars_root = Node3D.new()
	_view.add_child(_cars_root)
	if opaque:
		_make_lights()
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
	if opaque:  # the sun lights the scene even without shadows; its shadows land on the meshes themselves
		# Without the sun the ambient light is all there is, at full strength as the unshaded path had it
		_camera.environment.ambient_light_energy = lerpf(1.0, AMBIENT_ENERGY, clampf(strength, 0.0, 1.0))
		_sun.visible = strength > 0.01
		_sun.shadow_enabled = shadows_enabled
		_sun.light_energy = strength * SUN_ENERGY
		_sun.basis = sun_basis(Daylight.sun_direction(altitude_deg, azimuth_deg))
		return
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
	_camera.far = height * 2.0 + 10.0 if opaque else height + 1.0  # opaque: shadows on the ground (see the shadow camera below)
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
	elif opaque:  # shadows straight on the meshes: as far as the camera sees the ground
		_sun.directional_shadow_max_distance = Vector2(height, (Vector2(size) / camera_2d.zoom).length() * 0.5 * SHADOW_GROUND_MARGIN).length()
	_sprite.position = centre
	_sprite.scale = Vector2.ONE / camera_2d.zoom


## Night windows, as the 2D renderer: lit from darkness 0.25, fully by 0.5
## - one material colour, so no geometry is rebuilt.
## godot-lights-01: the buildings take the ambient light in their own
## material (the composite is unshaded, so they're darkened once); the lit
## windows fade from an ordinary window under that light to their own warm
## light as `level` (Daylight.artificial) rises - no geometry is rebuilt.
func set_light(level: float, ambient: Color) -> void:
	if opaque:
		_camera.environment.ambient_light_color = ambient
		_camera.environment.background_color = GROUND * ambient  # off the loaded chunks: the open ground, as dark as the night
		var daylight := clampf(ambient.get_luminance(), 0.0, 1.0)  # the sky reflected in wet roads and water dims with the day
		_camera.environment.sky.sky_material.energy_multiplier = daylight
		_shared["material"].set_shader_parameter("lit_level", clampf(level, 0.0, 1.0))
		return
	_shared["material"].set_shader_parameter("ambient", ambient)
	_shared["material"].set_shader_parameter("lit_level", clampf(level, 0.0, 1.0))  # the walls' own lit windows
	_shared["glass"].albedo_color = Color(ambient.r, ambient.g, ambient.b)
	_shared["ground"].albedo_color = Color(ambient.r, ambient.g, ambient.b)
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


## Step 3: road wetness 0..1 (map_layer.set_wetness), the road shader's.
func set_wetness(value: float) -> void:
	if _shared.has("road"):
		_shared["road"].set_shader_parameter("wetness", value)


func set_snow(cover: float) -> void:
	_shared["material"].set_shader_parameter("snow_cover", clampf(cover, 0.0, 1.0))
	if _shared["ground"] is ShaderMaterial:  # --outdoor-3d's ground (ground.gdshader)
		_shared["ground"].set_shader_parameter("snow_cover", clampf(cover, 0.0, 1.0))


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
	return _view.get_child_count() - 4  # minus the camera, the sun, the shadow ground and the cars


## godot-cars-3d: cars as 3D bodies in this view - the buildings' camera,
## light and sun shadows; the 2D entity layer keeps their lamps and glows on
## top. Each frame: begin_cars(), car() for each one drawn, end_cars().
static var current: Node2D = null  # the live 3D layer, for the entity layer
static var _car_meshes := {}  # [body, shadow caster] meshes by look
var _cars_root: Node3D
var _car_nodes: Array = []  # pooled [body, caster] instances
var _cars_used := 0
const CAR_GLASS := Color8(52, 74, 92)  # render_style.WINDSHIELD
const CAR_SIGN := Color8(240, 220, 20)  # render_style.TAXI_SIGN
enum { PAINT, RUBBER, GLASS_PART, LAMP }  # car.gdshader's parts (UV2.x)
const LAMPS_ON := 1  # car()'s `lamps`: the engine runs (head and tail lights)
const LAMPS_BRAKE := 2
const LAMPS_REVERSE := 4
const LAMPS_LEFT := 8  # an indicator, blinking on now
const LAMPS_RIGHT := 16


func _enter_tree() -> void:
	current = self


func _exit_tree() -> void:
	if current == self:
		current = null


## rtx-scene-readiness step 4 (--outdoor-3d): the scene's own lights, from
## fixed pools reused every update - the nearest lamps get them, only the
## nearest few cast shadows. Street lamps (their heads emissive), open shops'
## spill, floodlit fields, and every shining headlight pair as a spot.
const STREET_POOL := 48
const STREET_SHADOWED := 4
const SHOP_POOL := 16
const FLOOD_POOL := 6
const HEAD_POOL := 16
const HEAD_SHADOWED := 1  # the taxi's (headlight_sources: the taxi first)
const LAMP_HEIGHT_M := 7.0
const LAMP_ENERGY := 2.5
const LAMP_COLOR := Color(1.0, 0.86, 0.62)  # high-pressure sodium to warm LED
const SHOP_COLOR := Color(1.0, 0.95, 0.85)
const FLOOD_COLOR := Color(0.95, 0.97, 1.0)
const HEAD_COLOR := Color(1.0, 0.96, 0.88)
var _street_lights: Array = []  # OmniLight3D, each with its head (a MeshInstance3D child)
var _shop_lights: Array = []
var _flood_lights: Array = []
var _head_lights: Array = []  # SpotLight3D


func _make_lights() -> void:
	var head_mesh := BoxMesh.new()
	head_mesh.size = Vector3(0.6, 0.25, 0.6)
	var head_material := StandardMaterial3D.new()
	head_material.emission_enabled = true
	head_material.emission = LAMP_COLOR
	head_material.emission_energy_multiplier = 4.0
	head_material.albedo_color = LAMP_COLOR
	head_mesh.material = head_material
	for i in STREET_POOL:
		var lamp := _omni(LAMP_COLOR, i < STREET_SHADOWED)
		var head := MeshInstance3D.new()
		head.mesh = head_mesh
		head.layers = LAYER_BUILDINGS
		head.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		lamp.add_child(head)
		_street_lights.append(lamp)
	for i in SHOP_POOL:
		_shop_lights.append(_omni(SHOP_COLOR, false))
	for i in FLOOD_POOL:
		_flood_lights.append(_omni(FLOOD_COLOR, false))
	for i in HEAD_POOL:
		var spot := SpotLight3D.new()
		spot.light_color = HEAD_COLOR
		spot.layers = LAYER_BUILDINGS
		spot.light_cull_mask = LAYER_BUILDINGS
		spot.shadow_caster_mask = LAYER_BUILDINGS
		spot.shadow_enabled = i < HEAD_SHADOWED
		spot.shadow_bias = 0.05
		spot.visible = false
		_view.add_child(spot)
		_head_lights.append(spot)


func _omni(color: Color, shadowed: bool) -> OmniLight3D:
	var light := OmniLight3D.new()
	light.light_color = color
	light.layers = LAYER_BUILDINGS
	light.light_cull_mask = LAYER_BUILDINGS
	light.shadow_caster_mask = LAYER_BUILDINGS
	light.shadow_enabled = shadowed
	light.shadow_bias = 0.08
	light.visible = false
	_view.add_child(light)
	return light


## Street lamps, nearest first: [layer position, reach m]; open shops
## [position, reach]; floodlit fields [centre, reach]. `level`
## (Daylight.artificial) fades them all in at dusk.
func set_area_lights(level: float, lamps: Array, shops: Array, floods: Array) -> void:
	if _street_lights.is_empty():
		return
	var on := level > 0.01
	_place_omnis(_street_lights, lamps if on else [], LAMP_HEIGHT_M, LAMP_ENERGY * level, 1.6)
	_place_omnis(_shop_lights, shops if on else [], 2.5, 1.2 * level, 1.0)
	_place_omnis(_flood_lights, floods, 18.0, 6.0, 1.3)  # floodlights keep their own schedule (map_layer)


static func _place_omnis(pool: Array, rows: Array, height: float, energy: float, reach_scale: float) -> void:
	for i in pool.size():
		var light: OmniLight3D = pool[i]
		light.visible = i < rows.size()
		if light.visible:
			light.position = to_3d(rows[i][0], height)
			light.omni_range = float(rows[i][1]) * reach_scale
			light.light_energy = energy


## Headlight pairs (entity_layer.headlight_sources), the taxi first: one spot
## from each front bumper's middle, dipped 15 m wide or high 150 m narrow.
func set_headlights(level: float, sources: Array) -> void:
	for i in _head_lights.size():
		var spot: SpotLight3D = _head_lights[i]
		spot.visible = level > 0.01 and i < sources.size()
		if not spot.visible:
			continue
		var source: Array = sources[i]
		var forward := Vector2(cos(source[1]), -sin(source[1]))  # entity_layer._forward
		var reach := float(source[4])
		var high := reach > 15.0
		spot.position = to_3d(source[0] + forward * float(source[3]), 0.65)
		spot.basis = Basis.looking_at(Vector3(forward.x, -0.6 / maxf(reach, 1.0) - 0.02, forward.y).normalized(), Vector3.UP)
		spot.spot_range = reach * 1.3
		spot.spot_angle = 22.0 if high else 38.0
		spot.light_energy = (4.0 if high else 2.5) * level
		spot.spot_attenuation = 0.8


func begin_cars() -> void:
	_cars_used = 0


## A car at `at` (layer position) facing `heading` (as the 2D layer's):
## `shape` is entity_layer's CAR_SHAPES row; `sign` 0 none, 1 a taxi sign off, 2 lit;
## `lamps` the LAMPS_* lit now.
func car(at: Vector2, heading: float, length: float, width: float, color: Color, shape: Array, sign: int, lamps := 0) -> void:
	var key := "%s|%s|%.2f|%.2f|%d|%d" % [color.to_html(false), shape, length, width, sign, lamps]
	if not _car_meshes.has(key):
		if _car_meshes.size() > 512:  # ponytail: drop the whole cache, an LRU if colours ever vary per frame
			_car_meshes.clear()
		var arrays := car_arrays(length, width, color, shape, sign, lamps)
		_car_meshes[key] = [_mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"]),
			_mesh(arrays["shadow"], PackedColorArray())]
	if _cars_used == _car_nodes.size():
		var body := _instance(_car_meshes[key][0], _shared.get("car", _shared["material"]), LAYER_BUILDINGS)
		var caster := _instance(_car_meshes[key][1], _shared["caster"], LAYER_SHADOW_GROUND)
		caster.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY
		if opaque:  # step 4: the body itself casts; the shadows-only copy is the composite path's
			body.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
		_cars_root.add_child(body)
		_cars_root.add_child(caster)
		_car_nodes.append([body, caster])
	var place := Transform3D(Basis(Vector3.UP, heading), to_3d(at, ROAD_M + 0.016 if opaque else 0.0))  # on the road surface (step 3), not in it  # local +x forward, +z right (entity_layer _forward/_right)
	for i in 2:
		var node: MeshInstance3D = _car_nodes[_cars_used][i]
		node.mesh = _car_meshes[key][i]
		node.transform = place
		node.visible = i == 0 or not opaque
	_cars_used += 1


func end_cars() -> void:
	for i in range(_cars_used, _car_nodes.size()):
		for node in _car_nodes[i]:
			node.visible = false


## One car's mesh arrays, centred at the origin, +x forward: the body,
## wheels, the glasshouse sloping up to the roof, and its extras.
static func car_arrays(length: float, width: float, color: Color, shape: Array, sign: int, lamps := 0) -> Dictionary:
	var out := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array(), "shadow": PackedVector3Array(),
		"part": PackedVector2Array(), "part_now": PAINT}
	var hl := length * 0.5
	var hw := width * 0.5
	var van := str(shape[5]) == "door"
	var sill := 1.0 if van else 0.8
	var roof := 1.95 if van else 1.42
	var tyre := Color8(28, 28, 28)
	out["part_now"] = RUBBER
	for x: float in [hl * 0.64, -hl * 0.64]:
		for y: float in [hw * 0.86, -hw * 0.86]:
			_car_box(out, x - 0.33, x + 0.33, y + signf(y) * 0.05 - 0.14, y + signf(y) * 0.05 + 0.14, 0.0, 0.62, tyre)  # 5 cm out past the body
	out["part_now"] = PAINT
	_car_box(out, -hl, hl, -hw, hw, 0.28, sill, color)
	var top := color.darkened(0.12)
	var glass_front: float = shape[0]
	var roof_front: float = shape[1]
	var roof_rear: float = shape[2]
	var glass_rear: float = minf(shape[3], roof_rear)
	var roof_half: float = shape[4]
	var low := [Vector3(hl * glass_front, sill, -hw * 0.86), Vector3(hl * glass_front, sill, hw * 0.86),
		Vector3(hl * glass_rear, sill, hw * 0.86), Vector3(hl * glass_rear, sill, -hw * 0.86)]
	var high := [Vector3(hl * roof_front, roof, -hw * roof_half), Vector3(hl * roof_front, roof, hw * roof_half),
		Vector3(hl * roof_rear, roof, hw * roof_half), Vector3(hl * roof_rear, roof, -hw * roof_half)]
	var middle := Vector3((glass_front + glass_rear) * hl * 0.5, (sill + roof) * 0.5, 0.0)
	for key in ["verts", "shadow"]:
		for i in 4:  # windshield, right windows, rear window, left windows
			var j := (i + 1) % 4
			var facing: Vector3 = (low[i] + low[j] + high[i] + high[j]) / 4.0 - middle
			out["part_now"] = GLASS_PART
			_quad(out, low[i], low[j], high[j], high[i], CAR_GLASS.lightened(0.1 if i % 2 and not opaque else 0.0), facing, key)
		out["part_now"] = PAINT
		_quad(out, high[0], high[1], high[2], high[3], top, Vector3.UP, key)
	var flat := func(x0: float, x1: float, y0: float, y1: float, h: float, c: Color) -> void:
		_quad(out, Vector3(x0, h, y0), Vector3(x1, h, y0), Vector3(x1, h, y1), Vector3(x0, h, y1), c, Vector3.UP)
	match str(shape[5]):
		"bed":  # a pickup's open load bed behind the cab
			flat.call(-hl * 0.92, hl * (glass_rear - 0.06), -hw * 0.8, hw * 0.8, sill + 0.01, color.darkened(0.35))
		"rails":
			for y: float in [hw * roof_half * 0.82, -hw * roof_half * 0.82]:
				_car_box(out, hl * roof_rear, hl * roof_front, y - 0.03, y + 0.03, roof, roof + 0.08, color.darkened(0.5))
		"stripes":
			for y: float in [hw * 0.18, -hw * 0.18]:
				flat.call(hl * glass_front, hl * 0.98, y - hw * 0.06, y + hw * 0.06, sill + 0.01, color.lightened(0.55))
	if sign > 0:  # a taxi's roof light, lit while free for a fare
		_car_box(out, -hl * 0.24, -hl * 0.04, -hw * 0.48, hw * 0.48, roof, roof + 0.08, Color8(30, 30, 30))
		out["part_now"] = LAMP if sign == 2 else PAINT
		_car_box(out, -hl * 0.22, -hl * 0.06, -hw * 0.42, hw * 0.42, roof + 0.08, roof + 0.24, CAR_SIGN if sign == 2 else CAR_SIGN.darkened(0.45))
	_car_lamps(out, hl, hw, lamps)
	return out


## Step 4: the lamps, emissive while lit (car.gdshader's LAMP part): head
## and tail lights by the engine, brighter brake lights, reversing lights,
## the indicators on their side (left -z, right +z) while they blink on.
static func _car_lamps(out: Dictionary, hl: float, hw: float, lamps: int) -> void:
	var lamp := func(x0: float, x1: float, y_mid: float, half: float, lit: bool, on_color: Color, off_color: Color) -> void:
		out["part_now"] = LAMP if lit else PAINT
		_car_box(out, x0, x1, y_mid - half, y_mid + half, 0.5, 0.68, on_color if lit else off_color)
	var on := lamps & LAMPS_ON != 0
	for side: float in [1.0, -1.0]:
		lamp.call(hl - 0.04, hl + 0.02, side * hw * 0.62, 0.16, on, Color(1.0, 0.97, 0.85), Color8(200, 200, 190))
		var brake := lamps & LAMPS_BRAKE != 0
		lamp.call(-hl - 0.02, -hl + 0.04, side * hw * 0.62, 0.16, on or brake,
			Color(1.0, 0.08, 0.04) if brake else Color(0.55, 0.04, 0.02), Color8(120, 30, 25))
		lamp.call(-hl - 0.02, -hl + 0.04, side * 0.15, 0.08, lamps & LAMPS_REVERSE != 0, Color(1.0, 1.0, 0.95), Color8(170, 170, 165))
		var blinking := lamps & (LAMPS_RIGHT if side > 0.0 else LAMPS_LEFT) != 0
		for x0: float in [hl - 0.04, -hl - 0.02]:
			lamp.call(x0, x0 + 0.06, side * (hw - 0.07), 0.06, blinking, Color(1.0, 0.6, 0.05), Color8(150, 105, 40))
	out["part_now"] = PAINT


## An axis-aligned box in the car's own frame: four shaded sides and the
## top, drawn and casting a shadow (the sides' shading turns with the car).
static func _car_box(out: Dictionary, x0: float, x1: float, y0: float, y1: float, bottom: float, top: float, color: Color) -> void:
	var corners := [Vector2(x0, y0), Vector2(x1, y0), Vector2(x1, y1), Vector2(x0, y1)]
	var shades := [baked(0.86), baked(0.80), baked(0.94), baked(0.80)]  # left, front, right, rear
	for key in ["verts", "shadow"]:
		for i in 4:
			var p: Vector2 = corners[i]
			var q: Vector2 = corners[(i + 1) % 4]
			var outward := (p + q) / 2.0 - Vector2(x0 + x1, y0 + y1) / 2.0
			var c := Color(color.r * shades[i], color.g * shades[i], color.b * shades[i])
			_quad(out, to_3d(p, bottom), to_3d(q, bottom), to_3d(q, top), to_3d(p, top), c, to_3d(outward), key)
		_quad(out, to_3d(corners[0], top), to_3d(corners[1], top), to_3d(corners[2], top), to_3d(corners[3], top), color, Vector3.UP, key)
		_quad(out, to_3d(corners[0], bottom), to_3d(corners[1], bottom), to_3d(corners[2], bottom), to_3d(corners[3], bottom),
			color.darkened(0.3), Vector3.DOWN, key)  # the underside: seen in reflections and by secondary rays


## One chunk's mesh arrays (any thread): {"verts", "colors", "lit" (the
## lit windows' verts), "stats"}.
static func build(buildings: Array, styles: Array, origin: Vector2, sites: Array = [], landmarks: Array = [], ground := {}) -> Dictionary:
	var out := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array(), "lit": PackedVector3Array(),
		"wall_uv": PackedVector2Array(), "window": PackedFloat32Array(),  # the shader's windows (building_snow.gdshader)
		"arena": PackedVector3Array(), "shadow": PackedVector3Array(), "glass": PackedVector3Array(), "glass_colors": PackedColorArray(),
		"ground": PackedVector3Array(), "ground_colors": PackedColorArray(),
		"road": PackedVector3Array(), "road_colors": PackedColorArray(), "road_uv": PackedVector2Array(), "road_uv2": PackedVector2Array(),
		"stats": {"buildings": 0, "walls": 0, "windows": 0, "lit": 0, "triangles": 0}}
	if not ground.is_empty():
		_ground(out, ground)
	for i in buildings.size():
		var footprint: PackedVector2Array = buildings[i]
		if footprint.size() >= 3 and not Geometry2D.triangulate_polygon(footprint).is_empty():
			_building(out, footprint, styles[i] if i < styles.size() else [], origin)
	for site in sites:
		_crane(out, site, origin)
	for landmark in landmarks:  # [layer position, angle, spec]
		_landmark(out, landmark[0], landmark[1], landmark[2])
	out["stats"]["triangles"] = (out["verts"].size() + out["lit"].size() + out["glass"].size() + out["ground"].size() + out["road"].size()) / 3
	return out


## The chunk's mesh instances (main thread): the buildings and their lit
## windows, both in the one building view.
static func meshes(arrays: Dictionary) -> Array:
	var instances: Array = []
	if not arrays.get("ground", PackedVector3Array()).is_empty():
		instances.append(_instance(_mesh(arrays["ground"], arrays["ground_colors"]), _shared["ground"], LAYER_BUILDINGS))
	if not arrays.get("road", PackedVector3Array()).is_empty():
		instances.append(_instance(_mesh(arrays["road"], arrays["road_colors"], arrays["road_uv"], PackedVector2Array(), PackedFloat32Array(), arrays["road_uv2"]),
			_shared.get("road", _shared["ground"]), LAYER_BUILDINGS))
	if not arrays.get("glass", PackedVector3Array()).is_empty():
		instances.append(_instance(_mesh(arrays["glass"], arrays["glass_colors"]), _shared["glass"], LAYER_BUILDINGS))
	if arrays["verts"].is_empty():
		return instances
	var mesh := _mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], arrays.get("wall_uv", PackedVector2Array()),
		arrays.get("window", PackedFloat32Array()))
	var drawn := _instance(mesh, _shared["material"], LAYER_BUILDINGS)
	instances.append(drawn)
	if opaque:  # step 4: the buildings themselves cast and receive the sun's shadow; no shadows-only copies
		drawn.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	# rrt-018-shadows: each building as a plain prism (walls and a flat roof,
	# no windows or doors: a fifth of the triangles), not drawn, only casting
	# the sun's shadow in the shadow view (its layer)
	if not arrays["shadow"].is_empty() and not opaque:
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
	"glass": _glass_material(), "ground": _make_material(true)}


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


static func _mesh(verts: PackedVector3Array, colors: PackedColorArray, roof_mask := PackedVector2Array(),
		wall_uv := PackedVector2Array(), window := PackedFloat32Array(), part := PackedVector2Array()) -> ArrayMesh:
	var surface := []
	surface.resize(Mesh.ARRAY_MAX)
	surface[Mesh.ARRAY_VERTEX] = verts
	surface[Mesh.ARRAY_NORMAL] = flat_normals(verts)
	if part.size() == verts.size():
		surface[Mesh.ARRAY_TEX_UV2] = part
	if not colors.is_empty():
		surface[Mesh.ARRAY_COLOR] = colors
	if not roof_mask.is_empty():
		surface[Mesh.ARRAY_TEX_UV] = roof_mask
	var flags := 0
	if wall_uv.size() == verts.size() and window.size() == verts.size() * 4:
		surface[Mesh.ARRAY_TEX_UV2] = wall_uv
		surface[Mesh.ARRAY_CUSTOM0] = window
		flags = Mesh.ARRAY_CUSTOM_RGBA_FLOAT << Mesh.ARRAY_FORMAT_CUSTOM0_SHIFT
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, surface, [], {}, flags)
	return mesh


## Each triangle's outward normal: _tri winds (b - a) x (c - a) inward
## (Godot's clockwise front faces), so the outward side is its negative.
static func flat_normals(verts: PackedVector3Array) -> PackedVector3Array:
	var normals := PackedVector3Array()
	normals.resize(verts.size())
	for i in range(0, verts.size() - 2, 3):
		var n := -(verts[i + 1] - verts[i]).cross(verts[i + 2] - verts[i]).normalized()
		normals[i] = n
		normals[i + 1] = n
		normals[i + 2] = n
	return normals


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
static func _tri(out: Dictionary, a: Vector3, b: Vector3, c: Vector3, color: Color, facing: Vector3, key := "verts",
		uvs := PackedVector2Array(), window := Vector4.ZERO) -> void:
	var normal := (b - a).cross(c - a)
	if uvs.size() != 3:
		uvs = PackedVector2Array([Vector2.ZERO, Vector2.ZERO, Vector2.ZERO])
	if normal.dot(facing) > 0.0:
		var t := b
		b = c
		c = t
		uvs = PackedVector2Array([uvs[0], uvs[2], uvs[1]])
		normal = -normal
	out[key].append_array(PackedVector3Array([a, b, c]))
	if key != "verts":
		return
	if out.has("wall_uv"):  # the building meshes (not glass): every vertex, windows or not
		out["wall_uv"].append_array(uvs)
		for i in 3:
			out["window"].append_array(PackedFloat32Array([window.x, window.y, window.z, window.w]))
	out["colors"].append_array(PackedColorArray([color, color, color]))
	if out.has("part"):  # a car: the part's material (car.gdshader)
		var part := Vector2(out["part_now"], 0.0)
		out["part"].append_array(PackedVector2Array([part, part, part]))
	var shade := baked(0.90 if facing.y > 0.5 and Vector2(-normal.x, -normal.z).dot(LIGHT) < -0.001 else 1.0)
	var mask := Vector2(1.0 if facing.y > 0.5 else 0.0, shade)
	out["roof_mask"].append_array(PackedVector2Array([mask, mask, mask]))


static func _quad(out: Dictionary, a: Vector3, b: Vector3, c: Vector3, d: Vector3, color: Color, facing: Vector3, key := "verts",
		uvs := PackedVector2Array(), window := Vector4.ZERO) -> void:
	if uvs.size() == 4:
		_tri(out, a, b, c, color, facing, key, PackedVector2Array([uvs[0], uvs[1], uvs[2]]), window)
		_tri(out, a, c, d, color, facing, key, PackedVector2Array([uvs[0], uvs[2], uvs[3]]), window)
		return
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
	var shop_state: int = int(style[8]) if style.size() > 8 else -1
	var arena := style.size() > 7 and int(style[7]) == 1
	var gabled := style.size() > 1 and int(style[1]) >= 1
	var steep := style.size() > 1 and int(style[1]) == 2  # a church
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
		var shade := baked(0.72 + 0.28 * clampf(normal.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0))
		var wall_shade := Color(wall_color.r * shade, wall_color.g * shade, wall_color.b * shade)
		out["stats"]["walls"] += 1
		if arena:  # their windows light up with a match (set_arena_lights): geometry, as before
			_quad(out, to_3d(a), to_3d(b), to_3d(b, height), to_3d(a, height), wall_shade, to_3d(normal))
			_windows(out, a, b, normal, height, floors, category, seed_base + i * 7.13, arena)
			continue
		# The windows are the wall shader's (building_snow.gdshader): metres on the wall, and its window grid.
		var length := a.distance_to(b)
		var count := window_count(length, category)
		out["stats"]["windows"] += count * (1 if category == CATEGORY_RETAIL_HALL else ceili(floors / 2.0) if category == 1 else floors)
		_quad(out, to_3d(a), to_3d(b), to_3d(b, height), to_3d(a, height), wall_shade, to_3d(normal), "verts",
			PackedVector2Array([Vector2(0.0, 0.0), Vector2(length, 0.0), Vector2(length, height), Vector2(0.0, height)]),
			Vector4(length, minf(3.2, height / floors) if category == CATEGORY_RETAIL_HALL else height / floors,
				count + 1000 * category + 10000 * (shop_state + 1), seed_base + i * 7.13))
	_doors(out, footprint, style[3] if style.size() > 3 else [], outward_sign, height, floors, origin)
	_shadow_prism(out["shadow"], footprint, height)
	if gabled:
		_gabled(out, footprint, height, roof_color, wall_color, steep)
	else:
		var heights := PackedFloat32Array()
		heights.resize(footprint.size())
		heights.fill(height)
		_polygon(out, footprint, heights, roof_color)
		if category != CATEGORY_WALL:
			_roof_details(out, footprint, height, floors, roof_color, wall_color, seed_base)


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
		var shade := baked(0.85 + 0.15 * clampf(normal.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0))
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


## A named landmark's 3D shapes (assets/landmarks.json): boxes and cylinders
## (cones, frustums) in metres from its point, times its scale, drawn and
## casting the sun's shadow like a building. Its 2D shapes are map_chunk's.
const LANDMARK_SEGMENTS := 12

static func _landmark(out: Dictionary, at: Vector2, angle: float, spec: Dictionary) -> void:
	var scale := float(spec.get("scale", 1.0))
	var turn := Transform2D(deg_to_rad(float(spec.get("heading_deg", 0.0))) - angle, at) * Transform2D.IDENTITY.scaled(Vector2(scale, scale))
	for shape: Array in spec.get("shapes", []):
		var colour := Color.html(str(shape[-1]))
		match str(shape[0]):
			"box":  # [x, y, width, depth, bottom, top]
				var along := turn.basis_xform(Vector2(float(shape[3]) / 2.0, 0.0))
				var centre := turn * Vector2(shape[1], shape[2])
				_box(out, centre - along, centre + along, float(shape[4]) * scale / 2.0, float(shape[5]) * scale, float(shape[6]) * scale, colour)
			"cylinder":  # [x, y, bottom radius, top radius, bottom, top]
				_frustum(out, turn * Vector2(shape[1], shape[2]), float(shape[3]) * scale, float(shape[4]) * scale,
					float(shape[5]) * scale, float(shape[6]) * scale, colour)


static func _frustum(out: Dictionary, centre: Vector2, r_bottom: float, r_top: float, bottom: float, top: float, color: Color) -> void:
	for key in ["verts", "shadow"]:
		for i in LANDMARK_SEGMENTS:
			var u := Vector2.from_angle(TAU * i / LANDMARK_SEGMENTS)
			var v := Vector2.from_angle(TAU * (i + 1) / LANDMARK_SEGMENTS)
			var outward := (u + v).normalized()
			var shade := baked(0.72 + 0.28 * clampf(outward.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0))
			var lit := Color(color.r * shade, color.g * shade, color.b * shade)
			_tri(out, to_3d(centre + u * r_bottom, bottom), to_3d(centre + v * r_bottom, bottom), to_3d(centre + v * r_top, top), lit, to_3d(outward), key)
			if r_top > 0.0:
				_tri(out, to_3d(centre + u * r_bottom, bottom), to_3d(centre + v * r_top, top), to_3d(centre + u * r_top, top), lit, to_3d(outward), key)
				_tri(out, to_3d(centre, top), to_3d(centre + u * r_top, top), to_3d(centre + v * r_top, top), color, Vector3.UP, key)


## rtx-scene-readiness step 2: --outdoor-3d's materials respond to light.
## Before any mesh is built: shaded copies of the building shader (lit windows
## as emission) and of the ground, the car shader, and no baked shading.
static func use_shaded() -> void:
	opaque = true
	var shader := Shader.new()
	# Vertex colours are sRGB: Forward+ lights in linear space (Compatibility's unshaded view never converted them)
	shader.code = preload("res://building_snow.gdshader").code.replace("render_mode unshaded, cull_back;", "render_mode cull_back;") \
		.replace("mix(COLOR.rgb,", "mix(pow(COLOR.rgb, vec3(2.2)),")
	_shared["material"].shader = shader
	_shared["material"].set_shader_parameter("ambient", Color.WHITE)  # the Environment's ambient light instead
	_shared["ground"] = ShaderMaterial.new()
	_shared["ground"].shader = preload("res://ground.gdshader")
	_shared["road"] = ShaderMaterial.new()
	_shared["road"].shader = preload("res://road.gdshader")
	_shared["car"] = ShaderMaterial.new()
	_shared["car"].shader = preload("res://car.gdshader")


## A face's baked directional shading: none where real lights shade it.
static func baked(shade: float) -> float:
	return 1.0 if opaque else shade


## rtx-scene-readiness step 1: a chunk's ground plane and its roads as flat
## ribbons just above it (square caps close the bends), the more important
## roads a little higher so crossings don't flicker. Flat colours for now:
## materials, markings and wetness are step 3.
## Step 3: landuse, parking and water under the roads, in the 2D layers'
## order (a little higher each: no flicker where they overlap); roads, their
## centre lines, crossings, bumps, puddles and open water in the road mesh
## (road.gdshader: patterns, wetness, puddles, snow); raised islands and
## curbs. Everything flat stays within 4 cm of the ground, under the tyres.
const DASH_M := 3.0  # a dashed centre line: 3 m paint, 3 m gap
const MARKING_HALF_M := 0.1  # a 0.2 m line: thinner vanishes under a pixel at the default zoom
const AREAS_TOP_M := 0.010  # the landuse, parking and water layers between 0.002 m and this
const ROAD_M := 0.012  # a road's surface (+ 0.002 m per rank, the more important on top)
const PUDDLE_M := 0.032
const MARKING_M := 0.036
const CURB_M := 0.12  # kerbs and traffic islands stand this high
const CURB_HALF_M := 0.08
const BUMP_M := 0.07
enum { ROAD_SURFACE, ROAD_WATER, ROAD_PUDDLE }  # road.gdshader's UV.x


static func _ground(out: Dictionary, ground: Dictionary) -> void:
	var rect: Rect2 = ground["rect"]
	_ground_quad(out, rect.position, Vector2(rect.end.x, rect.position.y), rect.end, Vector2(rect.position.x, rect.end.y), 0.0, GROUND)
	var areas: Array = ground.get("areas", [])
	for i in areas.size():
		var h := 0.002 + (AREAS_TOP_M - 0.002) * i / maxf(1.0, areas.size())
		_flat_polygon(out, areas[i][0], h, areas[i][1], "road" if areas[i][2] else "ground", Vector2(ROAD_WATER, 0))
	for road: Array in ground.get("roads", []):
		var points: PackedVector2Array = road[0]
		var half: float = road[1]
		var h := ROAD_M + 0.002 * clampi(road[3], 0, 8)
		var surface := Vector2(ROAD_SURFACE, float(road[6]) if road.size() > 6 else 0.0)
		var drivable := Vector2(0.0, 1.0 if road.size() > 7 and road[7] else 0.0)
		var carry := 0.0  # metres along the road, for the dashes
		for i in points.size() - 1:
			var length := points[i].distance_to(points[i + 1])
			if length < 1e-3:
				continue
			_ribbon(out, points[i], points[i + 1], half, half, h, road[2], surface, drivable)
			if road[4] != null and half >= 2.0:  # a centre line on a two-lane road
				var u := (points[i + 1] - points[i]) / length
				var s := 0.0
				while s < length:
					var phase := 0.0 if road[5] else fmod(carry + s, DASH_M * 2.0)
					if phase < DASH_M:  # painted (a solid line: all the way)
						var paint := length - s if road[5] else minf(DASH_M - phase, length - s)
						_ribbon(out, points[i] + u * s, points[i] + u * (s + paint), MARKING_HALF_M, 0.0, MARKING_M, road[4])
						s += paint
					else:
						s += DASH_M * 2.0 - phase
				carry += length
	for stripe: Array in ground.get("stripes", []):  # zebra stripes, 0.5 m wide
		_ribbon(out, stripe[0], stripe[1], 0.25, 0.0, MARKING_M, Color8(245, 245, 245))
	for bump: Array in ground.get("bumps", []):
		_raised_strip(out, bump[0], bump[1], bump[2], ROAD_M, BUMP_M, Color8(45, 42, 40), "road")
	for puddle: Array in ground.get("puddles", []):
		_puddle(out, puddle[0], puddle[1], puddle[2], puddle[3])
	for island: Array in ground.get("islands", []):
		_raised_polygon(out, island[0], CURB_M, island[1])
	for curb: PackedVector2Array in ground.get("curbs", []):
		for i in curb.size() - 1:
			if curb[i].distance_to(curb[i + 1]) > 1e-3:
				_raised_strip(out, curb[i], curb[i + 1], CURB_HALF_M, 0.0, CURB_M, Color8(145, 145, 140), "ground")


static func _flat_polygon(out: Dictionary, polygon: PackedVector2Array, h: float, color: Color, key: String, uv := Vector2.ZERO) -> void:
	var triangles := Geometry2D.triangulate_polygon(polygon) if polygon.size() >= 3 else PackedInt32Array()
	for t in range(0, triangles.size(), 3):
		_ground_tri(out, polygon[triangles[t]], polygon[triangles[t + 1]], polygon[triangles[t + 2]], h, color, key, uv)


## A traffic island: its top at `top` and its kerb walls down to the ground.
static func _raised_polygon(out: Dictionary, polygon: PackedVector2Array, top: float, color: Color) -> void:
	if polygon.size() < 3:
		return
	_flat_polygon(out, polygon, top, color, "ground")
	var winding := signf(_signed_area(polygon))
	for i in polygon.size():
		var p := polygon[i]
		var q := polygon[(i + 1) % polygon.size()]
		var edge := q - p
		if edge.length_squared() > 1e-6:
			_ground_wall(out, p, q, 0.0, top, Color8(150, 150, 145), Vector2(edge.y, -edge.x) * winding, "ground")


static func _signed_area(polygon: PackedVector2Array) -> float:
	var area := 0.0
	for i in polygon.size():
		area += polygon[i].cross(polygon[(i + 1) % polygon.size()])
	return area * 0.5


## A low box from `a` to `b`, `half` either side: a kerb or a speed bump.
static func _raised_strip(out: Dictionary, a: Vector2, b: Vector2, half: float, bottom: float, top: float, color: Color, key: String) -> void:
	var along := (b - a).normalized()
	var side := Vector2(-along.y, along.x) * half
	var corners := [a - side, b - side, b + side, a + side]
	_ground_quad(out, corners[0], corners[1], corners[2], corners[3], top, color, key)
	for i in 4:
		var p: Vector2 = corners[i]
		var q: Vector2 = corners[(i + 1) % 4]
		_ground_wall(out, p, q, bottom, top, color.darkened(0.15), (p + q) / 2.0 - (a + b) / 2.0, key)


## A vertical face from p to q, facing `outward` (on the ground plan).
static func _ground_wall(out: Dictionary, p: Vector2, q: Vector2, bottom: float, top: float, color: Color, outward: Vector2, key: String) -> void:
	for tri in [[to_3d(p, bottom), to_3d(q, bottom), to_3d(q, top)], [to_3d(p, bottom), to_3d(q, top), to_3d(p, top)]]:
		var a: Vector3 = tri[0]
		var b: Vector3 = tri[1]
		var c: Vector3 = tri[2]
		if (b - a).cross(c - a).dot(to_3d(outward)) > 0.0:  # Godot's clockwise front faces: the cross points inward
			var t := b
			b = c
			c = t
		_ground_push(out, key, a, b, c, color, Vector2.ZERO, Vector2.ZERO)


## A puddle as a fan from its centre: UV2.x its distance out (1 at the rim),
## COLOR.a the wetness it shows from - the road shader grows it.
static func _puddle(out: Dictionary, at: Vector2, radius: float, shape: Array, reveal: float) -> void:
	var color := Color(RS.PUDDLE_COLOR, reveal)
	var rim := PackedVector2Array()
	for i in shape.size():
		var angle := TAU * i / shape.size()
		rim.append(at + Vector2(cos(angle), sin(angle)) * radius * float(shape[i]))
	for i in rim.size():
		var b := rim[i]
		var c := rim[(i + 1) % rim.size()]
		var verts := [to_3d(at, PUDDLE_M), to_3d(b, PUDDLE_M), to_3d(c, PUDDLE_M)]
		var reach := [0.0, 1.0, 1.0]
		if (verts[1] - verts[0]).cross(verts[2] - verts[0]).y > 0.0:
			verts = [verts[0], verts[2], verts[1]]
		out["road"].append_array(PackedVector3Array(verts))
		out["road_colors"].append_array(PackedColorArray([color, color, color]))
		out["road_uv"].append_array(PackedVector2Array([Vector2(ROAD_PUDDLE, 0), Vector2(ROAD_PUDDLE, 0), Vector2(ROAD_PUDDLE, 0)]))
		out["road_uv2"].append_array(PackedVector2Array([Vector2(reach[0], 0), Vector2(reach[1], 0), Vector2(reach[2], 0)]))


## A strip from `a` to `b`, `half` either side, `cap` beyond each end (closing the bends).
static func _ribbon(out: Dictionary, a: Vector2, b: Vector2, half: float, cap: float, h: float, color: Color,
		uv := Vector2.ZERO, uv2 := Vector2.ZERO) -> void:
	var along := (b - a).normalized()
	var side := Vector2(-along.y, along.x) * half
	a -= along * cap
	b += along * cap
	_ground_quad(out, a - side, b - side, b + side, a + side, h, color, "road", uv, uv2)


static func _ground_quad(out: Dictionary, a: Vector2, b: Vector2, c: Vector2, d: Vector2, h: float, color: Color, key := "ground",
		uv := Vector2.ZERO, uv2 := Vector2.ZERO) -> void:
	_ground_tri(out, a, b, c, h, color, key, uv, uv2)
	_ground_tri(out, a, c, d, h, color, key, uv, uv2)


## One flat triangle seen from above: wound clockwise as seen from +y (Godot's front faces).
static func _ground_tri(out: Dictionary, a: Vector2, b: Vector2, c: Vector2, h: float, color: Color, key := "ground",
		uv := Vector2.ZERO, uv2 := Vector2.ZERO) -> void:
	if (to_3d(b) - to_3d(a)).cross(to_3d(c) - to_3d(a)).y > 0.0:
		var t := b
		b = c
		c = t
	_ground_push(out, key, to_3d(a, h), to_3d(b, h), to_3d(c, h), color, uv, uv2)


## The road mesh carries the road shader's UV (kind, pattern) and UV2 (puddle reach, drivable).
static func _ground_push(out: Dictionary, key: String, a: Vector3, b: Vector3, c: Vector3, color: Color, uv: Vector2, uv2: Vector2) -> void:
	out[key].append_array(PackedVector3Array([a, b, c]))
	out[key + "_colors"].append_array(PackedColorArray([color, color, color]))
	if key == "road":
		out["road_uv"].append_array(PackedVector2Array([uv, uv, uv]))
		out["road_uv2"].append_array(PackedVector2Array([uv2, uv2, uv2]))


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
			var shade := baked(0.72 + 0.28 * clampf(outward.dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0))
			_quad(out, to_3d(p, bottom), to_3d(q, bottom), to_3d(q, top), to_3d(p, top), Color(color.r * shade, color.g * shade, color.b * shade),
				to_3d(outward), key)
		_quad(out, to_3d(corners[0], top), to_3d(corners[1], top), to_3d(corners[2], top), to_3d(corners[3], top), color, Vector3.UP, key)


## The building's shadow caster: its walls and a flat roof at the eaves
## (a gable's ridge is left out: a little shorter shadow, far fewer cases).
## A flat roof as seen from above in a Finnish town (Oulu's Valkea talo):
## a parapet round the edge, the lift and stair machine rooms on a block of
## three floors or more, a few vent units - placed by the building's own seed,
## so the same every time, and casting the sun's shadow.
const PARAPET_M := 0.7
const PARAPET_INSET_M := 0.35
const MACHINE_ROOM_MIN_AREA := 250.0


static func _roof_details(out: Dictionary, footprint: PackedVector2Array, height: float, floors: int,
		roof_color: Color, wall_color: Color, seed: float) -> void:
	var area := absf(B25.signed_area(footprint))
	if area < 40.0:
		return
	var rim := roof_color.lerp(Color.WHITE, 0.18)
	var inner_rings := Geometry2D.offset_polygon(footprint, -PARAPET_INSET_M)
	if inner_rings.size() == 1 and inner_rings[0].size() == footprint.size():
		var inner: PackedVector2Array = inner_rings[0]
		var outward := -1.0 if B25.signed_area(footprint) > 0.0 else 1.0
		var top := height + PARAPET_M
		for i in footprint.size():
			var a := footprint[i]
			var b := footprint[(i + 1) % footprint.size()]
			var ia := inner[i]
			var ib := inner[(i + 1) % inner.size()]
			if (b - a).length_squared() < 1e-4 or ia.distance_to(a) > 1.2 or ib.distance_to(b) > 1.2:
				continue  # the inset ring's corners in another order (a concave footprint): no parapet there
			var normal := Vector2(-(b - a).y, (b - a).x).normalized() * outward
			_quad(out, to_3d(a, height), to_3d(b, height), to_3d(b, top), to_3d(a, top), wall_color, to_3d(normal))  # outside
			_quad(out, to_3d(ia, height), to_3d(ib, height), to_3d(ib, top), to_3d(ia, top), wall_color.darkened(0.25), to_3d(-normal))  # inside
			_quad(out, to_3d(a, top), to_3d(b, top), to_3d(ib, top), to_3d(ia, top), rim, Vector3.UP)  # its top
		_shadow_ring(out["shadow"], footprint, height, top)
	# Machine rooms (lift, stairs) along the roof's longest edge, a few vents.
	var longest := 0
	for i in footprint.size():
		if footprint[i].distance_squared_to(footprint[(i + 1) % footprint.size()]) > footprint[longest].distance_squared_to(footprint[(longest + 1) % footprint.size()]):
			longest = i
	var along := (footprint[(longest + 1) % footprint.size()] - footprint[longest]).normalized()
	var across := Vector2(-along.y, along.x)
	var centre := Vector2.ZERO
	for p in footprint:
		centre += p
	centre /= footprint.size()
	var extent := 0.0
	for p in footprint:
		extent = maxf(extent, absf((p - centre).dot(along)))
	var box_color := roof_color.lerp(Color.WHITE, 0.1)
	if floors >= 3 and area >= MACHINE_ROOM_MIN_AREA:
		var rooms := clampi(1 + int(area / 1500.0), 1, 3)
		for k in rooms:
			var offset := (float(k) - (rooms - 1) / 2.0) * extent * 0.9 / rooms + (B25.unit(seed + k * 2.3) - 0.5) * 3.0
			var size := Vector2(4.0 + 2.0 * B25.unit(seed + k * 5.1), 3.0 + 1.5 * B25.unit(seed + k * 7.7))
			_roof_box(out, footprint, centre + along * offset, along, across, size, height, height + 2.8, box_color, wall_color)
	var vents := clampi(int(area / 200.0), 0, 6)
	for k in vents:
		var at := centre + along * (B25.unit(seed + k * 3.3) - 0.5) * extent * 1.6 \
			+ across * (B25.unit(seed + k * 4.9) - 0.5) * 6.0
		_roof_box(out, footprint, at, along, across, Vector2(1.1, 1.1), height, height + 1.0, box_color, wall_color)


## A box standing on the roof (a machine room, a vent), if it fits inside the footprint.
static func _roof_box(out: Dictionary, footprint: PackedVector2Array, at: Vector2, along: Vector2, across: Vector2,
		size: Vector2, base: float, top: float, top_color: Color, side_color: Color) -> void:
	var corners := PackedVector2Array([
		at - along * size.x / 2 - across * size.y / 2, at + along * size.x / 2 - across * size.y / 2,
		at + along * size.x / 2 + across * size.y / 2, at - along * size.x / 2 + across * size.y / 2])
	for c in corners:
		if not Geometry2D.is_point_in_polygon(c, footprint):
			return
	var centre := at
	for i in 4:
		var a := corners[i]
		var b := corners[(i + 1) % 4]
		var mid := (a + b) / 2.0
		var shade := baked(0.72 + 0.28 * clampf((mid - centre).normalized().dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0))
		_quad(out, to_3d(a, base), to_3d(b, base), to_3d(b, top), to_3d(a, top),
			Color(side_color.r * shade, side_color.g * shade, side_color.b * shade), to_3d(mid - centre))
	_quad(out, to_3d(corners[0], top), to_3d(corners[1], top), to_3d(corners[2], top), to_3d(corners[3], top), top_color, Vector3.UP)
	_shadow_prism(out["shadow"], corners, top)


## The parapet's own shadow: its walls, from the roof up.
static func _shadow_ring(verts: PackedVector3Array, footprint: PackedVector2Array, base: float, top: float) -> void:
	for i in footprint.size():
		var a := footprint[i]
		var b := footprint[(i + 1) % footprint.size()]
		verts.append_array(PackedVector3Array([to_3d(a, base), to_3d(b, base), to_3d(b, top), to_3d(a, base), to_3d(b, top), to_3d(a, top)]))


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
const CATEGORY_RETAIL_HALL := 4  # ground-level shop glazing, plain walls above


static func _windows(out: Dictionary, a: Vector2, b: Vector2, normal: Vector2, height: float, floors: int, category: int, seed: float, arena: bool) -> void:
	var length := a.distance_to(b)
	if length < 12.0 / 9.0 or category == CATEGORY_WALL:
		return
	var house := category == 1
	var along := (b - a) / length
	var count := clampi(int(length / ((44.0 if house else 32.0) / 9.0)), 1, 2 if house else 3)
	var storey := minf(3.2, height / floors) if category == CATEGORY_RETAIL_HALL else height / floors
	for f in (1 if category == CATEGORY_RETAIL_HALL else floors):
		if house and floors > 1 and f % 2 == 1:
			continue
		var storefront := (category == 2 or category == CATEGORY_RETAIL_HALL) and f == 0
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


## Windows per floor on a wall `length` long (the shader's bays): a ~3 m bay in
## town (Oulu's Valkea talo), 4.5 m on a house; none on a short or plain wall.
const WINDOW_BAY_M := 3.0
const HOUSE_WINDOW_BAY_M := 4.5


static func window_count(length: float, category: int) -> int:
	if length < 1.5 or category == CATEGORY_WALL:
		return 0
	return maxi(1, roundi(length / (HOUSE_WINDOW_BAY_M if category == 1 else WINDOW_BAY_M)))


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
static func _gabled(out: Dictionary, footprint: PackedVector2Array, height: float, color: Color, wall_color: Color, steep := false) -> float:
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
	var rise := minf(12.0, reach) if steep else minf(4.0, reach * 0.3)  # steep: about 45 degrees (a church)
	var far := 10000.0
	for side: float in [1.0, -1.0]:
		var half := PackedVector2Array([centre - axis * far, centre + axis * far, centre + axis * far + normal * side * far, centre - axis * far + normal * side * far])
		var shade := color if opaque else color.lightened(14.0 / 255.0) if side > 0.0 else color.darkened(12.0 / 255.0)
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
		var shade := baked(0.72 + 0.28 * clampf(Vector2(facing.x, facing.z).dot(LIGHT.normalized()) * 0.5 + 0.5, 0.0, 1.0))
		var wall := Color(wall_color.r * shade, wall_color.g * shade, wall_color.b * shade)
		var fan := [to_3d(b, height)] + top
		for t in fan.size() - 1:
			_tri(out, to_3d(a, height), fan[t], fan[t + 1], wall, facing)
	return rise
