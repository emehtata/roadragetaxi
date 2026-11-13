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
var _surface_pixels_per_m := -1.0
var shadows_enabled := true
var sky_wind := Vector2.ZERO  # m/s, the clouds' drift (main.gd)
var precip_kind := ""  # main.gd: "" underground, clear or with precipitation off
var precip_intensity := 0.7
var _precip: Precipitation3D
var _sky_offset := Vector2.ZERO
var windshield_on := false
var windshield_at := Vector2.ZERO
var windshield_heading := 0.0
var windshield_elevation := 0.0
var eye_height := 1.35  # m above the ground: the driver's eyes, or a walker's (main.gd)
var eye_ahead := 0.55  # m forward of windshield_at
var eye_pitch := 0.0  # rad, up(+)
const EYE_TRANSITION_S := 0.6  # getting out of the taxi or back in: the eye glides between seat and standing height
var _eye_from := Transform3D()
var _eye_blend := 1.0
var test_eye := {}  # visual tests only: "at" (layer point, else the windshield), "height" m above the ground there, "yaw" rad left of the heading
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
	_precip = Precipitation3D.new()
	_view.add_child(_precip)
	if opaque:
		_view.transparent_bg = false
		var sky := Environment.new()  # off the loaded chunks: the 2D map's open ground
		sky.background_mode = Environment.BG_COLOR
		sky.background_color = GROUND
		sky.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		sky.ambient_light_color = Color.WHITE
		sky.ambient_light_energy = AMBIENT_ENERGY
		sky.sky = Sky.new()  # what wet roads and water reflect (the camera never sees it: the ground fills the view)
		sky.sky.sky_material = ShaderMaterial.new()
		sky.sky.sky_material.shader = preload("res://sky_clouds.gdshader")
		sky.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
		sky.glow_enabled = true  # step 4: lit lamps and windows (emission above 1) bloom a little
		sky.glow_hdr_threshold = 1.0
		sky.glow_intensity = 0.5
		_view.positional_shadow_atlas_size = 4096  # the taxi's headlights' shadows
		_camera.environment = sky
		if preload("res://rtx_trial.gd").requested():
			if not preload("res://rtx_trial.gd").configure(_view, sky, "outdoor"):
				get_tree().quit(2)
				return
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
func _process(delta: float) -> void:
	fade_lamps(delta)
	var camera_2d := get_viewport().get_camera_2d()
	if camera_2d == null:
		return
	var size := Vector2i(get_viewport().get_visible_rect().size)
	var centre := camera_2d.get_screen_center_position()
	var height := camera_height(size.y / camera_2d.zoom.y)
	_precip.set_weather(precip_kind, precip_intensity, sky_wind)
	if opaque:
		set_surface_scale(camera_2d.zoom.x * _view.scaling_3d_scale)
		_sky_offset += (sky_wind + Vector2(1.5, 0.5)) * delta * 0.003  # the clouds drift with the wind, slowly even in a calm
		_camera.environment.sky.sky_material.set_shader_parameter("wind_offset", _sky_offset)
	if _view.size != size:
		_view.size = size
	view_centre = centre
	view_height = height
	get_parent().canopies_moved(Rect2(centre - Vector2(size) / camera_2d.zoom / 2.0, Vector2(size) / camera_2d.zoom))
	_camera.position = Vector3(centre.x, height, centre.y)
	_camera.near = maxf(1.0, height * 0.02)
	_camera.far = height * 2.0 + 10.0 if opaque else height + 1.0  # opaque: shadows on the ground (see the shadow camera below)
	if windshield_on:
		if opaque:
			_camera.environment.background_mode = Environment.BG_SKY
		var forward := Vector3(cos(windshield_heading), 0.0, -sin(windshield_heading))
		_camera.position = Vector3(windshield_at.x, eye_height + windshield_elevation, windshield_at.y) + forward * eye_ahead
		forward = Vector3(forward.x * cos(eye_pitch), sin(eye_pitch), forward.z * cos(eye_pitch))
		if not test_eye.is_empty():
			var at: Vector2 = test_eye.get("at", windshield_at)
			forward = forward.rotated(Vector3.UP, float(test_eye.get("yaw", 0.0)))
			_camera.position = to_3d(at, float(test_eye.get("height", 1.35)) + float(test_eye.get("ground", windshield_elevation)))
		_camera.look_at(_camera.position + forward * 100.0, Vector3.UP)
		if _eye_blend < 1.0:
			_eye_blend = minf(1.0, _eye_blend + delta / EYE_TRANSITION_S)
			_camera.transform = _eye_from.interpolate_with(_camera.transform, smoothstep(0.0, 1.0, _eye_blend))
		_camera.near = 0.08
		_camera.far = 1200.0  # far enough to see a forest edge across an open field (the forest's far LOD starts at 400 m)
	else:
		if opaque:
			_camera.environment.background_mode = Environment.BG_COLOR
		_camera.rotation_degrees = Vector3(-90.0, 0.0, 0.0)
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


## Glide the eye from where it is now to its next place (main.gd: out of the taxi, back in).
func begin_eye_transition() -> void:
	_eye_from = _camera.transform
	_eye_blend = 0.0


## Night windows, as the 2D renderer: lit from darkness 0.25, fully by 0.5
## - one material colour, so no geometry is rebuilt.
## godot-lights-01: the buildings take the ambient light in their own
## material (the composite is unshaded, so they're darkened once); the lit
## windows fade from an ordinary window under that light to their own warm
## light as `level` (Daylight.artificial) rises - no geometry is rebuilt.
func set_sky_color(color: Color) -> void:
	if opaque:
		var material: ShaderMaterial = _camera.environment.sky.sky_material
		material.set_shader_parameter("sky_top_color", color.darkened(0.1))
		material.set_shader_parameter("sky_horizon_color", color.lightened(0.2))


func set_cloud_cover(cover: float) -> void:
	if opaque:
		_camera.environment.sky.sky_material.set_shader_parameter("coverage", Daylight.cloud_coverage(cover))


func set_light(level: float, ambient: Color) -> void:
	if opaque:
		_camera.environment.ambient_light_color = ambient
		_camera.environment.background_color = GROUND * ambient  # off the loaded chunks: the open ground, as dark as the night
		var daylight := clampf(ambient.get_luminance(), 0.0, 1.0)  # the sky reflected in wet roads and water dims with the day
		_camera.environment.sky.sky_material.set_shader_parameter("energy", daylight)
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
	for material in road_materials():
		material.set_shader_parameter("wetness", value)


## Step 3: each chunk's road carries its own copy of the road material (its
## snow cells texture); the weather's wetness and wind go to every live one.
static var _road_copies: Array = []  # WeakRef to each chunk's copy


static func road_material_copy() -> ShaderMaterial:
	var copy: ShaderMaterial = _shared["road"].duplicate()
	_road_copies.append(weakref(copy))
	return copy


static func road_materials() -> Array:
	if not _shared.has("road"):
		return []
	_road_copies = _road_copies.filter(func(ref): return ref.get_ref() != null)
	return [_shared["road"]] + _road_copies.map(func(ref): return ref.get_ref())


func set_surface_scale(pixels_per_m: float) -> void:
	if is_equal_approx(pixels_per_m, _surface_pixels_per_m):
		return
	_surface_pixels_per_m = pixels_per_m
	for material in road_materials():
		material.set_shader_parameter("surface_pixels_per_m", pixels_per_m)


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
			if not node is GeometryInstance3D:  # a group (a chunk's trees)
				pass
			elif node.material_override == _shared["lit"]:
				node.visible = _lit_on
			elif node.material_override == _shared["arena"]:
				node.visible = _arena_on
			_view.add_child(node)


func instance_count() -> int:
	return _view.get_child_count() - 5  # minus the camera, the precipitation, the sun, the shadow ground and the cars


## godot-cars-3d: cars as 3D bodies in this view - the buildings' camera,
## light and sun shadows; the 2D entity layer keeps their lamps and glows on
## top. Each frame: begin_cars(), car() for each one drawn, end_cars().
static var current: Node2D = null  # the live 3D layer, for the entity layer
static var _car_meshes := {}  # [body, shadow caster] meshes by look
var _cars_root: Node3D
var _car_nodes: Array = []  # pooled [body, caster] instances
var _cars_used := 0
var _model_nodes := {}  # imported close-range cars, pooled by silhouette
var _model_used := {}
var _animal_rows := {}  # look -> [first model parameters, transforms this frame]
var _animal_batches := {}  # look -> one MultiMeshInstance3D
const CAR_GLASS := Color8(52, 74, 92)  # render_style.WINDSHIELD
const CAR_SIGN := Color8(240, 220, 20)  # render_style.TAXI_SIGN
enum { PAINT, RUBBER, GLASS_PART, LAMP, METAL_PAINT }  # car.gdshader's parts (UV2.x): METAL_PAINT the four-wheelers' bodywork
const LAMPS_ON := 1  # car()'s `lamps`: the engine runs (head and tail lights)
const LAMPS_BRAKE := 2
const LAMPS_REVERSE := 4
const LAMPS_LEFT := 8  # an indicator, blinking on now
const LAMPS_RIGHT := 16
const MODEL_SCENES := {
	"saloon": preload("res://assets/vehicles/saloon.glb"),
	"hatchback": preload("res://assets/vehicles/hatchback.glb"),
	"estate": preload("res://assets/vehicles/estate.glb"),
	"suv": preload("res://assets/vehicles/suv.glb"),
	"pickup": preload("res://assets/vehicles/pickup.glb"),
	"sports": preload("res://assets/vehicles/sports.glb"),
	"city_car": preload("res://assets/vehicles/city_car.glb"),
	"panel_van": preload("res://assets/vehicles/panel_van.glb"),
	"box_truck": preload("res://assets/vehicles/box_truck.glb"),
	"motorcycle": preload("res://assets/vehicles/motorcycle.glb"),
	"city_bus": preload("res://assets/vehicles/city_bus.glb"),
	"camper_van": preload("res://assets/vehicles/camper_van.glb"),
	"tractor": preload("res://assets/vehicles/tractor.glb"),
	"caravan": preload("res://assets/vehicles/caravan.glb"),
	"e_scooter": preload("res://assets/vehicles/e_scooter.glb"),
	"e_scooter_grab3d": preload("res://assets/vehicles/e_scooter_grab3d.glb"),
	"bicycle": preload("res://assets/vehicles/bicycle.glb"),
	"mountain_bike": preload("res://assets/vehicles/mountain_bike.glb"),
	"train_locomotive": preload("res://assets/vehicles/train_locomotive.glb"),
	"train_coach": preload("res://assets/vehicles/train_coach.glb"),
}
const MODEL_SIZE := {  # [width, length] in the source scenes, metres
	"saloon": Vector2(2.0, 4.822), "hatchback": Vector2(1.952, 4.342),
	"estate": Vector2(2.01, 5.041), "suv": Vector2(2.077, 4.782),
	"pickup": Vector2(2.077, 5.392), "sports": Vector2(2.058, 4.882),
	"city_car": Vector2(1.828, 3.592), "panel_van": Vector2(2.154, 5.392),
	"box_truck": Vector2(2.652, 7.542), "motorcycle": Vector2(0.58, 2.106),
	"city_bus": Vector2(3.084, 12.198),
	"camper_van": Vector2(2.154, 5.042),
	"tractor": Vector2(2.33, 3.665), "caravan": Vector2(2.647, 5.365),
	"e_scooter": Vector2(0.482, 0.844), "e_scooter_grab3d": Vector2(0.52, 1.247),
	"bicycle": Vector2(0.617, 1.87), "mountain_bike": Vector2(0.78, 1.885),
	"train_locomotive": Vector2(3.03, 16.25), "train_coach": Vector2(2.89, 26.4),
}
## Height scaled with the length: stretched over 15 % in length alone, their wheels would turn oval.
const UNIFORM_SCALE_MODELS := ["e_scooter", "camper_van"]
## Source and rendered height (m) overriding the length factor: the scooter's bar at a standing rider's hands.
const MODEL_HEIGHT := {"e_scooter": [0.970, 1.2]}
## Rendered width (m) replacing the sim width, only for models whose source width is over 15 % off the
## sim's: the mountain bike's 0.78 m riser bars (the sim's 0.6 m is the body, bars overhang as mirrors).
const MODEL_WIDTH := {"mountain_bike": 0.78}
## The 3D scooter rider's hips (the _rider body's bottom), between the deck and the bar.
const SCOOTER_RIDER_SEAT := 0.85
const SCOOTER_DECK_Y := 0.12
## A kind's close-range models; each vehicle keeps one, picked from its id (docs/specs/vehicle-model-variants.md).
## bmx_bike (1.45 m long: stretched 24 % to the sim's 1.8 m) and tram (22.6 x 3.3 m vs 9.2 m sections, 2.4 m wide) stay out.
const MODEL_VARIANTS := {"bicycle": ["bicycle", "mountain_bike"], "e_scooter": ["e_scooter", "e_scooter_grab3d"]}


static func model_variant(kind: String, id) -> String:
	if not MODEL_VARIANTS.has(kind):
		return kind
	var variants: Array = MODEL_VARIANTS[kind]
	return variants[absi(hash(id)) % variants.size()]


func _enter_tree() -> void:
	current = self


func _exit_tree() -> void:
	if current == self:
		current = null


## rtx-scene-readiness step 4 (--outdoor-3d): the scene's own lights, from
## fixed pools reused every update - the nearest lamps get them, only the
## taxi's headlights cast shadows (lamp shadows read as boxes and jumped lamp to lamp). Street lamps (spots down), open shops'
## spill, floodlit fields, and every shining headlight pair as a spot.
const STREET_POOL := 48
const SHOP_POOL := 16
const FLOOD_POOL := 6
const HEAD_POOL := 32  # two spots a pair
const HEAD_SHADOWED := 2  # the taxi's (headlight_sources: the taxi first)
const LAMP_HEIGHT_M := 7.0
const LAMP_ENERGY := 8.0
const LAMP_COLOR := Color(1.0, 0.86, 0.62)  # high-pressure sodium to warm LED
const SHOP_COLOR := Color(1.0, 0.95, 0.85)
const FLOOD_COLOR := Color(0.95, 0.97, 1.0)
const HEAD_COLOR := Color(1.0, 0.96, 0.88)
var _street_lights: Array = []  # SpotLight3D, pointing down
var _shop_lights: Array = []
var _flood_lights: Array = []
var _head_lights: Array = []  # SpotLight3D


func _make_lights() -> void:
	for i in STREET_POOL:  # a lamp shines down onto the street, never up: a spot, its dark housing lamp_posts_node's
		var lamp := SpotLight3D.new()
		lamp.light_color = LAMP_COLOR
		lamp.layers = LAYER_BUILDINGS
		lamp.light_cull_mask = LAYER_BUILDINGS
		lamp.rotation_degrees.x = -90.0  # -Z, a spot's axis, straight down
		lamp.visible = false
		_view.add_child(lamp)
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
## (Daylight.artificial) fades them all in at dusk. A lamp keeps its light
## while it ranks among the nearest STREET_KEEP; a dropped one fades out
## (fade_lamps) before its light goes to another lamp, which fades in.
const STREET_KEEP := 60  # hysteresis over STREET_POOL: no light swaps back and forth at the cut
const LAMP_FADE_S := 0.5
var _lamp_keys: Array = []  # each light's lamp position, Vector2.INF while free
var _lamp_weights := PackedFloat32Array()
var _lamp_targets := PackedFloat32Array()
var _lamp_level := 0.0


func set_area_lights(level: float, lamps: Array, shops: Array, floods: Array) -> void:
	if _street_lights.is_empty():
		return
	var on := level > 0.01
	_lamp_level = level
	if _lamp_keys.is_empty():
		_lamp_keys.resize(STREET_POOL)
		_lamp_keys.fill(Vector2.INF)
		_lamp_weights.resize(STREET_POOL)
		_lamp_targets.resize(STREET_POOL)
	var before := _lamp_keys.duplicate()
	var reaches := assign_lamps(_lamp_keys, _lamp_weights, _lamp_targets, lamps if on else [], STREET_KEEP)
	var counters: Dictionary = preload("res://perf.gd").counters  # the driving bench's (--bench) light stability
	for i in _street_lights.size():
		if _lamp_keys[i] != before[i]:
			counters["lamp_reassigned"] = counters.get("lamp_reassigned", 0) + 1
			if _lamp_weights[i] > 0.0:
				counters["lamp_moved_lit"] = counters.get("lamp_moved_lit", 0) + 1
		if reaches[i] > 0.0:
			var lamp: SpotLight3D = _street_lights[i]
			var reach: float = reaches[i] * 1.6
			lamp.position = to_3d(_lamp_keys[i], LAMP_HEIGHT_M - 0.2)  # the housing's underside
			lamp.spot_range = Vector2(reach, LAMP_HEIGHT_M).length()
			lamp.spot_angle = rad_to_deg(atan2(reach, LAMP_HEIGHT_M))
	_place_omnis(_shop_lights, shops if on else [], 2.5, 1.2 * level, 1.0)
	_place_omnis(_flood_lights, floods, 18.0, 6.0, 1.3)  # floodlights keep their own schedule (map_layer)
	fade_lamps(0.0)
	counters["lamp_lights_max"] = maxi(counters.get("lamp_lights_max", 0), _lamp_targets.count(1.0))
	counters["lamps_offered_max"] = maxi(counters.get("lamps_offered_max", 0), lamps.size())


## Gives each light (keys: its lamp's position or Vector2.INF, weights: how
## lit it is now) a lamp: kept while the lamp ranks among the first `keep`
## of `lamps` (nearest first, [position, reach]), else targeted to fade out;
## the nearest lamps without one take free (dark) lights. Sets targets; the
## lamps' reaches by light, 0.0 where nothing new is placed.
static func assign_lamps(keys: Array, weights: PackedFloat32Array, targets: PackedFloat32Array, lamps: Array, keep: int) -> PackedFloat32Array:
	var reaches := PackedFloat32Array()
	reaches.resize(keys.size())
	var ranked := {}
	for i in mini(lamps.size(), keep):
		if not ranked.has(lamps[i][0]):  # a lamp twice (chunks overlap) gets one light
			ranked[lamps[i][0]] = i
	var lit := {}
	for i in keys.size():
		targets[i] = 1.0 if ranked.has(keys[i]) else 0.0
		if targets[i] > 0.0:
			lit[keys[i]] = true
			reaches[i] = float(lamps[ranked[keys[i]]][1])
	var free := 0
	for i in mini(lamps.size(), keep):
		var at: Vector2 = lamps[i][0]
		if lit.has(at):
			continue
		while free < keys.size() and not (targets[free] == 0.0 and weights[free] == 0.0):
			free += 1
		if free == keys.size():
			break  # the rest wait for a light to fade out (the next update)
		keys[free] = at
		targets[free] = 1.0
		reaches[free] = float(lamps[i][1])
		lit[at] = true
	return reaches


## Every frame: each lamp's light toward its target, LAMP_FADE_S from dark to full.
func fade_lamps(delta: float) -> void:
	for i in _lamp_keys.size():
		var w := move_toward(_lamp_weights[i], _lamp_targets[i], delta / LAMP_FADE_S)
		_lamp_weights[i] = w
		if w == 0.0 and _lamp_targets[i] == 0.0:
			_lamp_keys[i] = Vector2.INF
		var lamp: SpotLight3D = _street_lights[i]
		lamp.visible = w > 0.0 and _lamp_level > 0.01
		if lamp.visible:
			lamp.light_energy = LAMP_ENERGY * _lamp_level * w


static func _place_omnis(pool: Array, rows: Array, height: float, energy: float, reach_scale: float) -> void:
	for i in pool.size():
		var light: OmniLight3D = pool[i]
		light.visible = i < rows.size()
		if light.visible:
			light.position = to_3d(rows[i][0], height)
			light.omni_range = float(rows[i][1]) * reach_scale
			light.light_energy = energy


## Headlight pairs (entity_layer.headlight_sources), the taxi first: a spot
## from each front corner, dipped 15 m wide or high 150 m narrow.
func set_headlights(level: float, sources: Array) -> void:
	for i in _head_lights.size():
		var spot: SpotLight3D = _head_lights[i]
		spot.visible = level > 0.01 and i / 2 < sources.size()
		if not spot.visible:
			continue
		var source: Array = sources[i / 2]
		var single: bool = source.size() > 7 and source[7]  # a bike: one centred lamp
		spot.visible = not (single and i % 2 == 1)
		var forward := Vector2(cos(source[1]), -sin(source[1]))  # entity_layer._forward
		var side := Vector2(-forward.y, forward.x) * float(source[2]) * (0.0 if single else 0.35 if i % 2 == 0 else -0.35)
		var reach := float(source[4])
		var high := reach > 15.0
		spot.position = to_3d(source[0] + forward * float(source[3]) + side, 0.65 + (float(source[6]) if source.size() > 6 else 0.0))  # on its deck
		spot.basis = Basis.looking_at(Vector3(forward.x, -0.6 / maxf(reach, 1.0) - 0.02, forward.y).normalized(), Vector3.UP)
		spot.spot_range = reach * 1.3
		spot.spot_angle = 12.0 if single else 22.0 if high else 38.0
		spot.light_energy = (24.0 if high else 18.0) * level * (0.3 if single else 1.0)  # one of two; grazing a dark road: far dimmer than the street lamps straight down
		spot.spot_attenuation = 0.8


## Tyre tracks (entity_layer._draw_trail): each trail segment's lines as
## flat strips 4 cm up - over the road markings, under the cars - owned by
## the segment's Node2D (gone with it), faded by its modulate (fresh snow).
const TRACK_M := 0.04
var _tracks := {}  # the owner's instance id -> MeshInstance3D
static var _track_material: StandardMaterial3D = null


func track(owner: Node2D, lines: PackedVector2Array, colors: PackedColorArray, width: float) -> void:
	var id := owner.get_instance_id()
	if not _tracks.has(id):
		if _track_material == null:
			_track_material = StandardMaterial3D.new()
			_track_material.vertex_color_use_as_albedo = true
			_track_material.vertex_color_is_srgb = true
			_track_material.roughness = 0.9
		var node := MeshInstance3D.new()
		node.material_override = _track_material
		node.layers = LAYER_BUILDINGS
		node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		_view.add_child(node)
		_tracks[id] = node
		owner.tree_exiting.connect(func(): _tracks.erase(id); node.queue_free())
	var out := {"ground": PackedVector3Array(), "ground_colors": PackedColorArray()}
	for i in range(0, lines.size() - 1, 2):
		if lines[i].distance_squared_to(lines[i + 1]) > 1e-6:
			var along := (lines[i + 1] - lines[i]).normalized()
			var side := Vector2(-along.y, along.x) * width * 0.5
			_ground_quad(out, lines[i] - side, lines[i + 1] - side, lines[i + 1] + side, lines[i] + side, TRACK_M, colors[i / 2])
	var mesh: MeshInstance3D = _tracks[id]
	mesh.mesh = _mesh(out["ground"], out["ground_colors"]) if not out["ground"].is_empty() else null
	mesh.transparency = 1.0 - owner.modulate.a


## A vehicle kind drawn as a GLB in the opaque view at any distance (docs/specs/glb-only-vehicles.md).
static func has_model(kind: String) -> bool:
	return kind == "train" or MODEL_SCENES.has(vehicle_model_kind(kind, 0))


## The MODEL_SCENES key `vehicle()` draws for `kind` (variants picked by `id`).
static func vehicle_model_kind(kind: String, id) -> String:
	return {"bus": "city_bus", "truck": "box_truck", "trailer": "caravan"}.get(kind, model_variant(kind, id))


func begin_cars() -> void:
	_cars_used = 0
	for kind in _model_used:
		_model_used[kind] = 0
	_puffs_used = 0
	_animal_rows.clear()


## Step 6: smoke puffs (crash smoke, exhaust) - pooled translucent spheres,
## placed each frame like the bodies, gone at end_cars.
var _puffs: Array = []
var _puffs_used := 0
static var _puff_mesh: SphereMesh = null


func puff(at: Vector2, height: float, radius: float, color: Color) -> void:
	if _puffs_used == _puffs.size():
		if _puff_mesh == null:
			_puff_mesh = SphereMesh.new()
			_puff_mesh.radial_segments = 8
			_puff_mesh.rings = 4
			var material := ShaderMaterial.new()
			material.shader = preload("res://smoke.gdshader")
			_puff_mesh.material = material
		var node := MeshInstance3D.new()
		node.mesh = _puff_mesh
		node.layers = LAYER_BUILDINGS
		node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		_cars_root.add_child(node)
		_puffs.append(node)
	var node: MeshInstance3D = _puffs[_puffs_used]
	node.transform = Transform3D(Basis().scaled(Vector3.ONE * radius), to_3d(at, height))
	node.set_instance_shader_parameter("tint", color)
	node.visible = true
	_puffs_used += 1


## A car at `at` (layer position) facing `heading` (as the 2D layer's):
## `shape` is entity_layer's CAR_SHAPES row; `sign` 0 none, 1 a taxi sign off, 2 lit;
## `lamps` the LAMPS_* lit now.
func car(at: Vector2, heading: float, length: float, width: float, color: Color, shape: Array, sign: int, lamps := 0, elevation := 0.0) -> void:
	if opaque:
		var kind := car_model_kind(shape, length)
		place_model_car(kind, at, heading, length, width, color, elevation, lamps)
		var detail_key := "d|%s|%.2f|%.2f|%d|%d" % [kind, length, width, sign, lamps]
		place_body(detail_key, func() -> Dictionary: return model_car_details(length, width, sign, lamps, 0.5, true,
			2.26 if kind == "panel_van" else 1.41), at, heading, elevation)
		return
	var detail := 0 if at.distance_to(windshield_at if windshield_on else view_centre) > 35.0 else 1
	var key := "%s|%s|%.2f|%.2f|%d|%d|%d" % [color.to_html(false), shape, length, width, sign, lamps, detail]
	place_body(key, func() -> Dictionary: return car_arrays(length, width, color, shape, sign, lamps, detail), at, heading, elevation)


static func car_model_kind(shape: Array, length: float) -> String:
	match str(shape[5]):
		"door": return "panel_van"
		"bed": return "pickup"
		"stripes": return "sports"
		"rails": return "estate" if shape[2] < -0.7 else "suv"
	if length < 4.0:
		return "city_car"
	return "hatchback" if shape[3] < -0.7 else "saloon"


func place_model_car(kind: String, at: Vector2, heading: float, length: float, width: float, color: Color, elevation: float, lamps := 0) -> void:
	if not _model_nodes.has(kind):
		_model_nodes[kind] = []
		_model_used[kind] = 0
	var used: int = _model_used[kind]
	var pool: Array = _model_nodes[kind]
	if used == pool.size():
		var model := Node3D.new()
		var merged := MeshInstance3D.new()
		merged.mesh = merged_model(kind)
		model.add_child(merged)
		var paint_materials := []
		var light_materials := []
		for mesh: MeshInstance3D in model.find_children("*", "MeshInstance3D", true, false):
			mesh.layers = LAYER_BUILDINGS
			mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
			for surface in mesh.mesh.get_surface_count():
				var original: Material = mesh.mesh.surface_get_material(surface)
				if original == null:
					continue
				if original.resource_name.begins_with("paint") or (kind == "tractor" and original.resource_name == "orange") or \
					(kind == "caravan" and original.resource_name == "shell") or (kind == "e_scooter" and original.resource_name == "teal") or \
					(kind == "train_locomotive" and original.resource_name == "Original teal enamel paint") or \
					(kind == "train_coach" and original.resource_name == "Original warm white outdoor paint"):
					var paint: StandardMaterial3D = original.duplicate()
					paint.resource_local_to_scene = true
					paint.albedo_texture = null
					mesh.set_surface_override_material(surface, paint)
					paint_materials.append(paint)
				elif original.resource_name == "glass":
					mesh.set_surface_override_material(surface, car_glazing(original))
				elif original.resource_name.begins_with("light"):
					var lens: StandardMaterial3D = original.duplicate()
					lens.emission_enabled = false  # per-side live lamps are the overlay mesh
					mesh.set_surface_override_material(surface, lens)
					light_materials.append([lens, original.resource_name])
		model.set_meta("paint_materials", paint_materials)
		model.set_meta("light_materials", light_materials)
		_cars_root.add_child(model)
		pool.append(model)
	var car_node: Node3D = pool[used]
	if car_node.get_meta("paint", Color.TRANSPARENT) != color:
		for material: StandardMaterial3D in car_node.get_meta("paint_materials"):
			material.albedo_color = color
		car_node.set_meta("paint", color)
	if car_node.get_meta("lamps", -1) != lamps:
		for pair: Array in car_node.get_meta("light_materials"):
			var material: StandardMaterial3D = pair[0]
			var name: String = pair[1]
			if name == "lightWhite":
				material.emission_enabled = lamps & LAMPS_ON != 0
			elif name == "lightRed":
				material.emission_enabled = lamps & (LAMPS_ON | LAMPS_BRAKE) != 0
				material.emission_energy_multiplier = 3.0 if lamps & LAMPS_BRAKE else 1.0
		car_node.set_meta("lamps", lamps)
	var along_x := kind in ["city_bus", "train_locomotive", "train_coach"]
	var turn := heading if along_x else heading + PI / 2.0
	car_node.transform = Transform3D(Basis(Vector3.UP, turn).scaled_local(model_scale(kind, length, width)),
		to_3d(at, ROAD_M + 0.016 + elevation))
	car_node.visible = true
	_model_used[kind] = used + 1


## A GLB as one mesh, one surface per material, its node transforms baked in: a saloon's 23 mesh
## nodes draw (and cast) as 8 draw calls (docs/specs/glb-only-vehicles.md AC 7). Built once per kind.
static var _merged_models := {}


static func merged_model(kind: String) -> ArrayMesh:
	if _merged_models.has(kind):
		return _merged_models[kind]
	var source: Node3D = MODEL_SCENES[kind].instantiate()
	var tools := {}  # Material -> SurfaceTool, in first-seen order
	for mi: MeshInstance3D in source.find_children("*", "MeshInstance3D", true, false):
		var xform := Transform3D()
		var node: Node = mi
		while node != source:
			xform = (node as Node3D).transform * xform
			node = node.get_parent()
		for surface in mi.mesh.get_surface_count():
			var material: Material = mi.mesh.surface_get_material(surface)
			if not tools.has(material):
				tools[material] = SurfaceTool.new()
			tools[material].append_from(mi.mesh, surface, xform)
	var importer := ImporterMesh.new()  # its LODs, as the GLB import made them: far cars draw few triangles
	for material: Material in tools:
		tools[material].index()  # generate_lods needs indices
		importer.add_surface(Mesh.PRIMITIVE_TRIANGLES, tools[material].commit_to_arrays(), [], {}, material)
	importer.generate_lods(25.0, 60.0, [])
	var mesh: ArrayMesh = importer.get_mesh()
	source.free()
	_merged_models[kind] = mesh
	return mesh


## A model's scale to the sim's length x width; UNIFORM_SCALE_MODELS take their height from the length
## factor (round wheels), the rest keep the source height.
static func model_scale(kind: String, length: float, width: float) -> Vector3:
	var source: Vector2 = MODEL_SIZE[kind]
	var up := length / source.y if kind in UNIFORM_SCALE_MODELS else 1.0
	if kind in MODEL_HEIGHT:
		up = MODEL_HEIGHT[kind][1] / MODEL_HEIGHT[kind][0]
	if kind in MODEL_WIDTH:
		width = MODEL_WIDTH[kind]
	if kind in ["city_bus", "train_locomotive", "train_coach"]:
		return Vector3(length / source.y, up, width / source.x)
	return Vector3(width / source.x, up, length / source.y)


## A car's glass from its model: the file's 28% tint reads as a pale sheet
## over the body, so it is a dark, mostly opaque pane.
static func car_glazing(original: Material) -> StandardMaterial3D:
	var glazing: StandardMaterial3D = original.duplicate()
	glazing.albedo_color = Color(0.02, 0.03, 0.04, 0.9)
	glazing.metallic = 0.55  # as car.gdshader glass
	glazing.metallic_specular = 0.6
	glazing.roughness = 0.05
	return glazing


static func model_car_details(length: float, width: float, sign: int, lamps: int, lamp_height := 0.5, native_lights := false,
		roof_height := 1.41, two_wheeler := false) -> Dictionary:
	var out := _empty_arrays()
	var hl := length * 0.5
	var hw := width * 0.5
	if sign > 0:
		_car_box(out, -hl * 0.24, -hl * 0.04, -hw * 0.48, hw * 0.48, roof_height, roof_height + 0.08, Color8(30, 30, 30))
		out["part_now"] = LAMP if sign == 2 else PAINT
		_car_box(out, -hl * 0.22, -hl * 0.06, -hw * 0.42, hw * 0.42, roof_height + 0.08, roof_height + 0.24,
			CAR_SIGN if sign == 2 else CAR_SIGN.darkened(0.45))
	var lens := func(x: float, side: float, across: float, half_width: float, lit: bool, on_color: Color, off_color: Color) -> void:
		out["part_now"] = LAMP if lit else PAINT
		_car_box(out, x - 0.014, x + 0.014, side * across - half_width, side * across + half_width,
			lamp_height, lamp_height + 0.085, on_color if lit else off_color)
	for side: float in [-1.0, 1.0]:
		if not native_lights:
			lens.call(hl, side, hw * 0.68, 0.10, lamps & LAMPS_ON != 0, Color(1.0, 0.95, 0.78), Color8(190, 190, 183))
			lens.call(-hl, side, hw * 0.68, 0.10, lamps & (LAMPS_ON | LAMPS_BRAKE) != 0,
				Color(1.0, 0.07, 0.04) if lamps & LAMPS_BRAKE else Color(0.55, 0.03, 0.02), Color8(120, 30, 25))
		if two_wheeler:
			continue
		lens.call(-hl + 0.08, side, hw * 0.20, 0.035, lamps & LAMPS_REVERSE != 0, Color.WHITE, Color8(170, 170, 165))
		var indicating := lamps & (LAMPS_RIGHT if side > 0.0 else LAMPS_LEFT) != 0
		for x: float in [-hl + 0.08, hl - 0.08]:
			lens.call(x, side, hw * 0.72, 0.025, indicating, Color(1.0, 0.6, 0.05), Color8(150, 105, 40))
	out["part_now"] = PAINT
	return out


## A GLB vehicle's live lamps and rider (vehicle()); bikes and e-scooters get one front and one rear lamp.
static func model_vehicle_details(kind: String, length: float, width: float, color: Color, lamps: int, extra: Dictionary) -> Dictionary:
	var bike := kind in ["bicycle", "e_scooter"]
	var out := model_car_details(length, width, 0, lamps, 0.8,
		bike or kind in ["truck", "motorcycle", "camper_van"], 1.41, bike)
	if bike:
		_bike_lamps(out, length * 0.5, lamps)
	if kind == "motorcycle" and extra.get("riding", false):
		_rider(out, -length * 0.15, length * 0.06, 0.95, Color8(34, 34, 38), color.lightened(0.15))
	elif kind == "bicycle" and extra.get("riding", false):
		_rider(out, -length * 0.15, length * 0.08, 0.8, color, Color8(236, 196, 160))
	elif kind == "e_scooter" and extra.get("riding", false):
		_rider(out, -length * 0.06, length * 0.14, SCOOTER_RIDER_SEAT, color, Color8(236, 196, 160))
		_rider_legs(out, -length * 0.06, length * 0.14, SCOOTER_RIDER_SEAT, SCOOTER_DECK_Y, Color8(48, 58, 74))
	return out


## A bike's lamps (docs/specs/bicycle-rendering.md): white under the bars, red under the saddle, centred.
static func _bike_lamps(out: Dictionary, hl: float, lamps: int) -> void:
	var front := lamps & LAMPS_ON != 0
	_part(out, LAMP if front else PAINT, hl * 0.80 - 0.02, hl * 0.80 + 0.02, -0.03, 0.03, 0.85, 0.91,
		Color(1.0, 0.95, 0.78) if front else Color8(190, 190, 183))
	var rear := lamps & (LAMPS_ON | LAMPS_BRAKE) != 0
	_part(out, LAMP if rear else PAINT, -hl * 0.80 - 0.02, -hl * 0.80 + 0.02, -0.025, 0.025, 0.75, 0.80,
		(Color(1.0, 0.07, 0.04) if lamps & LAMPS_BRAKE else Color(0.55, 0.03, 0.02)) if rear else Color8(120, 30, 25))


## Any pooled body this frame (a car, a bus, a person, an animal): its mesh
## built once per look (`key`) by `build` (car_arrays-style arrays), placed
## on the road at `at` facing `heading`, `elevation` up (a deck), rolled
## `roll` about its length (fallen over).
func place_body(key: String, build: Callable, at: Vector2, heading: float, elevation := 0.0, roll := 0.0, organic := false) -> void:
	if not _car_meshes.has(key):
		if _car_meshes.size() > 1024:  # ponytail: drop the whole cache, an LRU if colours ever vary per frame
			_car_meshes.clear()
		var arrays: Dictionary = build.call()
		_car_meshes[key] = [_mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"], organic),
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
	var place := Transform3D(Basis(Vector3.UP, heading) * Basis(Vector3.RIGHT, roll), to_3d(at, (ROAD_M + 0.016 if opaque else 0.0) + elevation))  # on the road surface (step 3), not in it  # local +x forward, +z right (entity_layer _forward/_right)
	for i in 2:
		var node: MeshInstance3D = _car_nodes[_cars_used][i]
		node.mesh = _car_meshes[key][i]
		if i == 0:
			node.material_override = _shared.get("organic", _shared["car"]) if organic else _shared.get("car", _shared["material"])
		node.transform = place
		node.visible = i == 0 or not opaque
	_cars_used += 1


func end_cars() -> void:
	for kind in _model_nodes:
		var pool: Array = _model_nodes[kind]
		for i in range(_model_used[kind], pool.size()):
			pool[i].visible = false
	for i in range(_cars_used, _car_nodes.size()):
		for node in _car_nodes[i]:
			node.visible = false
	for i in range(_puffs_used, _puffs.size()):
		_puffs[i].visible = false
	_flush_animals()


## This frame's animals: one MultiMeshInstance3D per look, built once.
func _flush_animals() -> void:
	if _animal_batches.size() > 64:
		for old_key in _animal_batches.keys():
			if not _animal_rows.has(old_key):
				_animal_batches[old_key].queue_free()
				_animal_batches.erase(old_key)
	for key in _animal_batches:
		_animal_batches[key].multimesh.visible_instance_count = 0
	for key in _animal_rows:
		var rows: Array = _animal_rows[key]
		if not _animal_batches.has(key):
			var spec: Array = rows[0]
			var arrays := animal_arrays(spec[0], spec[1], spec[2], spec[3], spec[4])
			var multi := MultiMesh.new()
			multi.transform_format = MultiMesh.TRANSFORM_3D
			multi.mesh = _mesh(arrays["verts"], arrays["colors"], arrays["roof_mask"], PackedVector2Array(), PackedFloat32Array(), arrays["part"], true)
			var node := MultiMeshInstance3D.new()
			node.multimesh = multi
			node.material_override = _shared["organic"]
			node.layers = LAYER_BUILDINGS
			node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
			_cars_root.add_child(node)
			_animal_batches[key] = node
		var multi: MultiMesh = _animal_batches[key].multimesh
		if multi.instance_count < rows.size():
			multi.instance_count = rows.size()
		for i in rows.size():
			multi.set_instance_transform(i, rows[i][5])
		multi.visible_instance_count = rows.size()


## Other vehicles: their GLB in the opaque view where one exists (any distance),
## else the procedural mesh. `extra`: "riding", "fallen",
## "plough", "beacon", "profile" (a train car's), "rider" (its colour).
func vehicle(kind: String, at: Vector2, heading: float, length: float, width: float, color: Color, lamps := 0, elevation := 0.0, extra := {}) -> void:
	var id: Variant = extra.get("id", 0)
	if extra.has("id"):  # out of the cache keys below: one shared mesh per look, not per vehicle
		extra = extra.duplicate()
		extra.erase("id")
	if opaque and kind == "train":
		var profile: String = extra.get("profile", "standard")
		var model_kind := "train_locomotive" if profile == "locomotive" else "train_coach"
		place_model_car(model_kind, at, heading, length, width, RS.TRAIN_PROFILES.get(profile, RS.TRAIN_PROFILES["standard"])[0], elevation)
		return
	var model_kind := vehicle_model_kind(kind, id)
	if opaque and has_model(kind) and (kind != "tractor" or not extra.get("plough", false)):
		place_model_car(model_kind, at, heading, length, width, color, elevation, lamps)
		var detail_key := "vd|%s|%.2f|%.2f|%d|%s" % [kind, length, width, lamps, str(extra)]
		place_body(detail_key, model_vehicle_details.bind(kind, length, width, color, lamps, extra), at, heading, elevation)
		return
	var key := "v|%s|%.2f|%.2f|%s|%d|%s" % [kind, length, width, color.to_html(false), lamps, extra]
	var fallen: bool = extra.get("fallen", false)
	place_body(key, func() -> Dictionary: return vehicle_arrays(kind, length, width, color, lamps, extra), at, heading,
		elevation + (width * 0.5 if fallen else 0.0), PI / 2.0 if fallen else 0.0)


static func _empty_arrays() -> Dictionary:
	return {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array(), "shadow": PackedVector3Array(),
		"part": PackedVector2Array(), "part_now": PAINT}


static func _part(out: Dictionary, part: int, x0: float, x1: float, y0: float, y1: float, bottom: float, top: float, color: Color) -> void:
	var before: int = out["part_now"]
	out["part_now"] = part
	_car_box(out, x0, x1, y0, y1, bottom, top, color)
	out["part_now"] = before


## A seated or standing rider from x0 (back) to x1 (front): torso, head.
static func _rider(out: Dictionary, x0: float, x1: float, seat: float, color: Color, head: Color) -> void:
	_part(out, PAINT, x0, x1, -0.22, 0.22, seat, seat + 0.6, color)
	_part(out, PAINT, x1 - 0.22, x1 - 0.02, -0.11, 0.11, seat + 0.62, seat + 0.86, head)


## A standing rider's legs (person_arrays limbs): hips over the deck, back foot at x0,
## front foot at x1, knees bent forward, shoe soles on the deck.
static func _rider_legs(out: Dictionary, x0: float, x1: float, hip: float, deck: float, trousers: Color) -> void:
	for joints: Array in rider_leg_joints(x0, x1, hip, deck):
		var top: Vector3 = joints[0]
		var knee: Vector3 = joints[1]
		var ankle: Vector3 = joints[2]
		_round_limb(out, top, knee, 0.094, 0.075, trousers)
		_round_part(out, knee, Vector3(0.076, 0.074, 0.075), trousers)
		_round_limb(out, knee, ankle, 0.073, 0.046, trousers)
		_round_part(out, ankle + Vector3(0.06, -0.025, 0.0), Vector3(0.12, 0.055, 0.072), Color8(42, 42, 46), 4)


## [hip, knee, ankle] per leg (z -0.1, +0.1): ankle 0.08 m over the deck so the
## shoe sole (0.025 + 0.055 below the ankle) is on it; knee 0.1 m ahead of the
## hip-ankle midpoint.
static func rider_leg_joints(x0: float, x1: float, hip: float, deck: float) -> Array:
	var legs := []
	for side: float in [-1.0, 1.0]:
		var top := Vector3((x0 + x1) * 0.5, hip, side * 0.1)
		var ankle := Vector3(x0 if side < 0.0 else x1, deck + 0.08, side * 0.1)
		legs.append([top, (top + ankle) * 0.5 + Vector3(0.1, 0.0, 0.0), ankle])
	return legs


static func vehicle_arrays(kind: String, length: float, width: float, color: Color, lamps: int, extra: Dictionary) -> Dictionary:
	var out := _empty_arrays()
	var hl := length * 0.5
	var hw := width * 0.5
	var tyre := Color8(28, 28, 28)
	var skin := Color8(236, 196, 160)
	if kind in ["bus", "truck", "tractor", "camper_van", "trailer"]:  # metallic-painted bodywork; riders' and bikes' paint stays plain
		out["part_now"] = METAL_PAINT
	match kind:
		"bus":
			for x: float in [hl * 0.62, -hl * 0.55]:
				for y: float in [hw * 0.8, -hw * 0.8]:
					_wheel(out, x, y, 0.5, 0.3, tyre)
			_car_box(out, -hl, hl, -hw, hw, 0.35, 1.15, color)
			_part(out, GLASS_PART, -hl + 0.05, hl - 0.02, -hw + 0.02, hw - 0.02, 1.15, 2.6, CAR_GLASS)
			_car_box(out, -hl, hl, -hw, hw, 2.6, 3.0, color)
			for hatch: float in [hl * 0.55, -hl * 0.62]:
				_car_box(out, hatch - hl * 0.07, hatch + hl * 0.07, -hw * 0.3, hw * 0.3, 3.0, 3.12, color.darkened(0.11))
			_car_lamps(out, hl, hw, lamps)
		"truck":
			for x: float in [hl * 0.65, -hl * 0.45, -hl * 0.75]:
				for y: float in [hw * 0.8, -hw * 0.8]:
					_wheel(out, x, y, 0.5, 0.36, tyre)
			_car_box(out, hl * 0.24, hl, -hw * 0.92, hw * 0.92, 0.5, 2.8, color)
			_part(out, GLASS_PART, hl - 0.05, hl + 0.01, -hw * 0.8, hw * 0.8, 1.6, 2.5, CAR_GLASS)
			_car_box(out, -hl, hl * 0.18, -hw, hw, 1.0, 3.4, color.lightened(0.11))
			_car_lamps(out, hl, hw, lamps)
		"tractor":
			for y: float in [hw * 0.8, -hw * 0.8]:
				_wheel(out, -hl * 0.55, y, 0.8, hw * 0.4, tyre)
				_wheel(out, hl * 0.7, y * 0.78, 0.45, hw * 0.26, tyre)
			_car_box(out, -hl * 0.1, hl, -hw * 0.36, hw * 0.36, 0.7, 1.5, color)
			_car_box(out, -hl * 0.95, -hl * 0.05, -hw * 0.58, hw * 0.58, 0.9, 1.5, color)
			_part(out, GLASS_PART, -hl * 0.9, -hl * 0.1, -hw * 0.54, hw * 0.54, 1.5, 2.6, CAR_GLASS)
			_car_box(out, -hl * 0.95, -hl * 0.05, -hw * 0.6, hw * 0.6, 2.6, 2.75, color)
			if extra.get("plough", false):  # an angled blade ahead, wider than the tractor
				for i in 6:
					var y0 := -hw * 1.2 + hw * 2.4 * i / 6.0
					var x0 := hl * 1.02 + 0.28 * (1.0 - float(i) / 6.0)
					_car_box(out, x0, x0 + 0.12, y0, y0 + hw * 0.4, 0.05, 0.9, Color8(240, 150, 20))
				_part(out, LAMP if extra.get("beacon", false) else PAINT, -hl * 0.58, -hl * 0.42, -0.12, 0.12, 2.75, 2.95,
					Color(1.0, 0.6, 0.05) if extra.get("beacon", false) else Color8(150, 105, 40))
			_car_lamps(out, hl, hw * 0.6, lamps)
		"camper_van":
			var box := Color8(238, 234, 220)
			for x: float in [hl * 0.6, -hl * 0.6]:
				for y: float in [hw * 0.85, -hw * 0.85]:
					_wheel(out, x, y, 0.35, 0.3, tyre)
			_car_box(out, hl * 0.62, hl, -hw * 0.92, hw * 0.92, 0.3, 1.1, color)
			_part(out, GLASS_PART, hl * 0.46, hl * 0.62, -hw * 0.86, hw * 0.86, 1.1, 1.9, CAR_GLASS)
			_car_box(out, -hl, hl * 0.48, -hw, hw, 0.3, 2.9, box)
			_car_box(out, -hl * 0.6, -hl * 0.45, -hw * 0.3, hw * 0.3, 2.9, 3.05, Color8(186, 185, 170))
			_car_lamps(out, hl, hw, lamps)
		"trailer":  # a caravan: its box, the drawbar to the hitch ahead, its wheels and tail lights
			for y: float in [-hw, hw]:
				_wheel(out, 0.0, y, 0.3, 0.2, tyre)
			_car_box(out, -hl, hl, -hw, hw, 0.35, 2.5, Color8(238, 234, 220))
			_car_box(out, hl, hl + 0.9, -0.05, 0.05, 0.4, 0.5, Color8(165, 168, 162))
			_part(out, GLASS_PART, hl * 0.2, hl * 0.55, -hw * 0.34, hw * 0.34, 2.5, 2.56, Color8(120, 150, 160))
			_car_lamps(out, hl, hw, lamps)
		"motorcycle":
			_wheel(out, -hl * 0.7, 0.0, 0.31, hw * 0.5, tyre)
			_wheel(out, hl * 0.75, 0.0, 0.3, hw * 0.4, tyre)
			_car_box(out, -hl * 0.55, hl * 0.52, -hw * 0.45, hw * 0.45, 0.45, 0.9, color)
			_car_box(out, -hl * 0.5, -hl * 0.08, -hw * 0.3, hw * 0.3, 0.9, 0.98, Color8(40, 40, 42))
			_part(out, LAMP if lamps & LAMPS_ON else PAINT, hl * 0.86, hl * 0.99, -0.08, 0.08, 0.8, 0.95,
				Color(1.0, 0.97, 0.85) if lamps & LAMPS_ON else Color8(170, 170, 160))
			if extra.get("riding", false):
				_rider(out, -hl * 0.3, hl * 0.12, 0.95, Color8(34, 34, 38), color.lightened(0.15))
		"bicycle":
			var rear := Vector3(-hl * 0.62, 0.33, 0.0)
			var front := Vector3(hl * 0.62, 0.33, 0.0)
			var crank := Vector3(-hl * 0.04, 0.38, 0.0)
			var saddle := Vector3(-hl * 0.20, 0.86, 0.0)
			var fork := Vector3(hl * 0.39, 0.88, 0.0)
			_bike_wheel(out, rear, 0.33)
			_bike_wheel(out, front, 0.33)
			for tube in [[rear, saddle], [rear, crank], [saddle, crank], [saddle, fork], [fork, crank], [fork, front]]:
				_round_limb(out, tube[0], tube[1], 0.019, 0.019, color, PAINT, 0)
			_round_limb(out, saddle, saddle + Vector3(-0.03, 0.13, 0.0), 0.016, 0.014, Color8(95, 100, 104), PAINT, 0)
			_car_box(out, saddle.x - 0.13, saddle.x + 0.08, -0.06, 0.06, 0.99, 1.04, Color8(35, 36, 39))
			_round_limb(out, fork, fork + Vector3(0.04, 0.17, 0.0), 0.016, 0.016, Color8(95, 100, 104), PAINT, 0)
			_car_box(out, fork.x - 0.02, fork.x + 0.10, -hw * 0.9, hw * 0.9, 1.04, 1.07, tyre)
			_round_part(out, crank, Vector3(0.055, 0.055, 0.016), Color8(75, 79, 82), PAINT, 0)
			for side: float in [-1.0, 1.0]:
				_round_limb(out, crank + Vector3(0.0, 0.0, side * 0.03), crank + Vector3(0.08 * side, 0.0, side * 0.08),
					0.01, 0.01, Color8(82, 86, 88), PAINT, 0)
			_bike_lamps(out, hl, lamps)
			if extra.get("riding", false):
				_rider(out, -hl * 0.37, hl * 0.18, 0.8, color, skin)
		"e_scooter":
			for x: float in [hl * 0.78, -hl * 0.78]:
				_part(out, RUBBER, x - hl * 0.18, x + hl * 0.18, -0.03, 0.03, 0.0, 0.2, tyre)
			_car_box(out, -hl * 0.72, hl * 0.62, -hw * 0.32, hw * 0.32, 0.1, 0.18, Color8(40, 160, 110))
			_car_box(out, hl * 0.72, hl * 0.82, -0.03, 0.03, 0.18, 1.1, Color8(40, 40, 42))
			_car_box(out, hl * 0.72, hl * 0.82, -hw, hw, 1.05, 1.1, tyre)
			if extra.get("riding", false):
				_rider(out, -hl * 0.12, hl * 0.28, SCOOTER_RIDER_SEAT, color, skin)
				_rider_legs(out, -hl * 0.12, hl * 0.28, SCOOTER_RIDER_SEAT, SCOOTER_DECK_Y, Color8(48, 58, 74))
		"ferry":  # open vehicle deck and side wheelhouse, like Finnish yellow road ferries
			var hull: Color = RS.TRAIN_PROFILES["ferry"][0]
			_car_box(out, -hl, hl, -hw, hw, -0.9, -0.05, hull.darkened(0.15))
			_car_box(out, -hl, hl, -hw, hw, -0.9, -0.68, Color8(35, 38, 40))
			_car_box(out, -hl, hl, -hw + 0.5, hw - 0.5, -0.05, 0.02, RS.TRAIN_PROFILES["ferry"][1])
			for x: float in [-hl * 0.55, 0.0, hl * 0.55]:
				_car_box(out, x - 1.4, x + 1.4, -0.06, 0.06, 0.021, 0.025, Color8(228, 226, 196))
			for y: float in [hw - 0.5, -hw]:
				_car_box(out, -hl * 0.9, hl * 0.9, y, y + 0.5, -0.05, 1.05, hull)
			for x: float in [-hl + 1.5, hl - 2.8]:
				_car_box(out, x, x + 1.3, -hw, -hw + 1.1, 0.02, 1.6, hull)
				_car_box(out, x, x + 1.3, hw - 1.1, hw, 0.02, 1.6, hull)
			_car_box(out, -3.3, 3.3, hw - 2.0, hw - 0.5, 1.05, 3.1, hull)
			_car_box(out, -3.3, 3.3, hw - 2.0, hw - 0.5, 3.1, 4.0, hull)
			for x: float in [-2.6, -1.3, 0.0, 1.3, 2.6]:
				_part(out, GLASS_PART, x - 0.52, x + 0.52, hw - 2.025, hw - 1.995, 3.2, 3.86, CAR_GLASS)
				_part(out, GLASS_PART, x - 0.52, x + 0.52, hw - 0.505, hw - 0.475, 3.2, 3.86, CAR_GLASS)
			for side: float in [hw - 1.8, hw - 0.7]:
				_part(out, GLASS_PART, -3.325, -3.295, side - 0.42, side + 0.42, 3.2, 3.86, CAR_GLASS)
				_part(out, GLASS_PART, 3.295, 3.325, side - 0.42, side + 0.42, 3.2, 3.86, CAR_GLASS)
			_car_box(out, -3.5, 3.5, hw - 2.2, hw - 0.3, 4.0, 4.2, hull)
		"train", "tram":
			var tram := kind == "tram"
			var style: Array = RS.TRAIN_PROFILES.get(extra.get("profile", "standard"), RS.TRAIN_PROFILES["standard"])
			var top := 3.4 if tram else 3.9
			for x: float in [hl * 0.7, -hl * 0.7]:
				_part(out, RUBBER, x - 1.2, x + 1.2, -hw * 0.75, hw * 0.75, 0.0, 0.6, Color8(40, 40, 40))
			_car_box(out, -hl, hl, -hw, hw, 0.6, 1.45, style[0])
			_car_box(out, -hl, hl, -hw, hw, 1.45, 2.55, style[0].darkened(0.16))
			_car_box(out, -hl, hl, -hw, hw, 2.55, top, style[0])
			var bay_count := maxi(2, int(length / 2.2))
			for bay in bay_count:
				var x0 := -hl + 0.45 + bay * (length - 0.9) / bay_count
				var x1 := -hl + 0.3 + (bay + 1) * (length - 0.9) / bay_count
				for side: float in [-1.0, 1.0]:
					var y := side * (hw + 0.012)
					_part(out, GLASS_PART, x0, x1, y - 0.013, y + 0.013, 1.63, 2.44, CAR_GLASS)
			for side: float in [-0.55, 0.55]:
				_part(out, GLASS_PART, hl - 0.018, hl + 0.018, side * hw - hw * 0.4, side * hw + hw * 0.4,
					1.65, 2.48, CAR_GLASS)
				_part(out, LAMP, hl + 0.02, hl + 0.05, side * hw - 0.11, side * hw + 0.11,
					0.95, 1.13, Color8(242, 236, 205))
				_part(out, LAMP, -hl - 0.05, -hl - 0.02, side * hw - 0.11, side * hw + 0.11,
					0.95, 1.13, Color8(203, 36, 28))
			if tram or extra.get("profile", "") != "locomotive":  # a coach's doors near its ends
				for door_x: float in ([-hl * 0.55, hl * 0.38] if tram else [-hl + 0.9, hl - 0.965]):
					for side: float in ([-1.0, 1.0] if tram else [1.0]):  # a tram's on both sides, a coach's on the right (+y)
						var leaf := 0.0 if tram else 0.6  # a coach door: a 1.3 m leaf, seen at lineup zoom
						_part(out, PAINT, door_x - leaf, door_x + 0.065 + leaf, side * hw - 0.015, side * hw + 0.015, 0.68, 2.53, Color8(42, 48, 51))
			if tram:  # the locomotive model is a diesel: no pantograph
				var pan := Color8(52, 54, 56)
				_car_box(out, -0.5, 0.5, -0.4, 0.4, top, top + 0.15, pan)  # base frame
				_car_box(out, -0.05, 0.05, -0.03, 0.03, top + 0.15, top + 0.75, pan)  # arm
				_car_box(out, -0.08, 0.08, -0.7, 0.7, top + 0.75, top + 0.8, pan)  # collector head
			if style[1] != null and extra.get("profile", "") == "locomotive":
				_car_box(out, hl - 3.0, hl, -hw, hw, top, top + 0.05, style[1])
			elif style[1] != null:
				_car_box(out, -hl + 1.0, hl - 1.0, -0.5, 0.5, top, top + 0.05, style[1])
	return out


## Step 6: a person, a dog, a larger wild animal as pooled boxes, posed by
## their animation state; +x the way they face. Lying poses are rolled by
## place_body (fallen, sunbathing).
func person(at: Vector2, heading: float, clothing: Color, pose: String, scale := 1.0, costume := "", elevation := 0.0,
		variant := 0, winter := false) -> void:
	var detail := 0 if at.distance_to(windshield_at if windshield_on else view_centre) > 40.0 else 1
	var key := "p|%s|%s|%.2f|%s|%d|%d|%d" % [clothing.to_html(false), pose, scale, costume, variant, int(winter), detail]
	var lying := pose == "lying"
	place_body(key, func() -> Dictionary: return person_arrays(clothing, pose, scale, costume, variant, winter, detail), at, heading,
		elevation + (0.2 * scale if lying else 0.0), PI / 2.0 if lying else 0.0, true)


func animal(at: Vector2, heading: float, species: String, color: Color, pose: String, size := 1.0, elevation := 0.0) -> void:
	var detail := 0 if at.distance_to(windshield_at if windshield_on else view_centre) > 40.0 else 1
	var key := "a|%s|%s|%s|%.2f|%d" % [species, color.to_html(false), pose, size, detail]
	if not _animal_rows.has(key):
		_animal_rows[key] = []
	_animal_rows[key].append([species, color, pose, size, detail,
		Transform3D(Basis(Vector3.UP, heading), to_3d(at, ROAD_M + 0.016 + elevation))])


const SKIN_TONES := [Color8(232, 184, 150), Color8(191, 137, 103), Color8(145, 93, 66), Color8(222, 162, 119)]
const HAIR_TONES := [Color8(49, 35, 29), Color8(108, 67, 39), Color8(178, 147, 95), Color8(35, 32, 34)]


static func person_arrays(clothing: Color, pose: String, scale: float, costume: String, variant := 0, winter := false, detail := 1) -> Dictionary:
	var out := _empty_arrays()
	var k := scale * (0.96 + 0.015 * (variant % 5))
	var skin: Color = SKIN_TONES[variant % SKIN_TONES.size()]
	var hair: Color = Color8(150, 150, 145) if variant == 7 else HAIR_TONES[(variant / 2) % HAIR_TONES.size()]
	var style := 3 if winter else variant % 8
	var jacket := style in [1, 3, 4, 7]
	var skirt := style == 5
	var shorts := style == 6
	var fabric := Color8(224, 170, 54) if style == 4 else clothing.lerp(Color8(88, 91, 92), 0.22)
	var trousers := Color8(48, 58, 74) if style % 3 == 0 else Color8(38, 43, 53) if style % 3 == 1 else Color8(79, 72, 66)
	var offset := -0.35 if pose == "sitting" else 0.68 if pose == "riding" else -1.34 if pose == "swimming" else 0.0
	var moving := pose.begins_with("walk_") or pose.begins_with("run_")
	var running := pose.begins_with("run_")
	var phase := int(pose.split("_")[1]) if moving else 0
	var swing := sin(float(phase) * TAU / 6.0) * (0.31 if running else 0.21) if moving else 0.0
	if pose == "riding":
		var mount := animal_arrays("horse", Color8(139, 91, 57), "stand", scale, detail)
		for key in ["verts", "colors", "roof_mask", "shadow", "part"]:
			out[key].append_array(mount[key])
	if pose != "swimming":
		for side: float in [-1.0, 1.0]:
			var z := side * 0.11
			var lift := maxf(0.0, cos(float(phase) * TAU / 6.0) * side) * (0.15 if running else 0.1) if moving else 0.0
			var hip := Vector3(0.0, 0.87 + offset, z) * k
			var knee := Vector3((0.44 if pose == "sitting" else swing * side * 0.5), (0.85 if pose == "sitting" else 0.45 + lift * 0.3) + offset, z * 1.1) * k  # sitting: thighs level on the seat
			var ankle := Vector3((0.47 if pose == "sitting" else swing * side), (0.09 if pose != "riding" else 0.82) + (0.0 if pose == "sitting" else lift), z * 1.1) * k
			_round_limb(out, hip, knee, 0.094 * k, 0.075 * k, trousers, 0, detail)
			_round_part(out, knee, Vector3(0.076, 0.074, 0.075) * k, trousers, 0, detail)
			_round_limb(out, knee, ankle, 0.073 * k, 0.046 * k, skin if shorts else trousers, 1 if shorts else 0, detail)
			_round_part(out, ankle + Vector3(0.06, -0.025, 0.0) * k, Vector3(0.12, 0.055, 0.072) * k, Color8(42, 42, 46), 4, detail)
	var torso_y := 1.14 + offset
	_garment_torso(out, torso_y * k, k, fabric, jacket, 0.94 + 0.04 * (variant % 4), detail)
	if skirt:
		_garment_skirt(out, offset * k, k, fabric.darkened(0.08), detail)
	if jacket:
		_round_limb(out, Vector3(0.168, 0.93 + offset, 0.0) * k, Vector3(0.17, 1.4 + offset, 0.0) * k,
			0.008 * k, 0.008 * k, fabric.darkened(0.22), 0, detail)
	if style == 4:
		for h in [1.05, 1.32]:
			_round_limb(out, Vector3(0.17, h + offset, -0.17) * k, Vector3(0.17, h + offset, 0.17) * k,
				0.015 * k, 0.015 * k, Color8(225, 230, 218), 0, detail)
	for side: float in [-1.0, 1.0]:
		var shoulder := Vector3(0.0, 1.37 + offset, side * 0.215) * k
		var elbow := Vector3(0.06 if pose == "sitting" else -side * 0.045, 1.13 + offset, side * 0.245) * k
		var wrist := Vector3(0.3, 1.0 + offset, side * 0.16) * k if pose == "sitting" \
			else Vector3(-swing * side * 0.75, 0.91 + offset, side * 0.24) * k  # sitting: hands on the thighs
		_round_limb(out, shoulder, elbow, 0.072 * k, 0.057 * k, fabric, 0, detail)
		_round_part(out, elbow, Vector3(0.058, 0.06, 0.058) * k, fabric, 0, detail)
		_round_limb(out, elbow, wrist, 0.055 * k, 0.042 * k, fabric if jacket else skin, 0 if jacket else 1, detail)
		_round_part(out, wrist, Vector3(0.045, 0.055, 0.045) * k, skin, 1, detail)
	_round_limb(out, Vector3(0.0, 1.42 + offset, 0.0) * k, Vector3(0.0, 1.54 + offset, 0.0) * k,
		0.055 * k, 0.05 * k, skin, 1, detail)
	var head := Vector3(0.025, 1.61 + offset, 0.0) * k
	_round_part(out, head, Vector3(0.118, 0.145, 0.112) * k, skin, 1, detail)
	_round_part(out, head + Vector3(-0.015, 0.085, 0.0) * k, Vector3(0.122, 0.07, 0.115) * k, hair, 2, detail)
	if style == 1:
		_round_part(out, head + Vector3(-0.07, -0.025, 0.0) * k, Vector3(0.09, 0.14, 0.14) * k, fabric.darkened(0.12), 0, detail)
	if variant % 3 == 1:
		for side: float in [-1.0, 1.0]:
			_round_part(out, head + Vector3(-0.04, -0.01, side * 0.1) * k, Vector3(0.05, 0.085, 0.028) * k, hair, 2, detail)
	if detail > 0:
		for side: float in [-1.0, 1.0]:
			_round_part(out, head + Vector3(0.0, -0.01, side * 0.11) * k, Vector3(0.032, 0.045, 0.026) * k, skin, 1, detail)
			_round_part(out, head + Vector3(0.105, 0.016, side * 0.047) * k, Vector3(0.014, 0.016, 0.015) * k, Color8(49, 42, 38), 3, detail)
			_round_part(out, head + Vector3(0.112, 0.05, side * 0.048) * k, Vector3(0.013, 0.009, 0.026) * k, hair, 2, detail)
		_round_part(out, head + Vector3(0.12, -0.022, 0.0) * k, Vector3(0.032, 0.038, 0.029) * k, skin, 1, detail)
		_round_part(out, head + Vector3(0.113, -0.078, 0.0) * k, Vector3(0.012, 0.008, 0.031) * k, skin.darkened(0.3), 1, detail)
	if costume in ["santa", "elf"]:
		_round_part(out, head + Vector3(-0.025, 0.145, 0.0) * k, Vector3(0.14, 0.08, 0.13) * k, Color8(190, 30, 35), 0, detail)
		_round_limb(out, head + Vector3(0.0, 0.18, 0.0) * k, head + Vector3(-0.04, 0.36, 0.0) * k,
			0.10 * k, 0.015 * k, Color8(190, 30, 35), 0, detail)
	return out


static var ANIMAL_MODELS := {  # species -> [CC0 GLB preloaded so exports pack it (assets/animals/SOURCES.md), yaw turning its nose to +x, body length m, its coat (no tint)]
	"fox": [preload("res://assets/animals/fox.glb"), 0.0, 0.9, Color8(194, 91, 38)],
	"small_bird": [preload("res://assets/animals/small_bird.glb"), PI / 2.0, 0.3, Color.WHITE],  # untinted; the old 0.3 m bird size (a real robin is 0.14 m), to read on screen
	"roe_deer": [preload("res://assets/animals/roe_deer.glb"), PI / 2.0, 1.2, Color8(151, 104, 62)],
	"horse": [preload("res://assets/animals/horse.glb"), PI / 2.0, 2.0, Color8(139, 91, 57)],
	"hare": [preload("res://assets/animals/hare.glb"), PI / 2.0, 0.5, Color8(142, 126, 101)],
}
static var _animal_models := {}  # species -> [verts at body length 1, feet at y=0, nose +x; face colours; face normals], [] if unusable


## A species' GLB flattened once into triangles; [] (with one warning) when missing.
static func _animal_model(species: String) -> Array:
	if _animal_models.has(species):
		return _animal_models[species]
	var spec: Array = ANIMAL_MODELS[species]
	var scene: PackedScene = spec[0]
	_animal_models[species] = []
	if scene == null:
		push_warning("animal model missing: %s stays procedural" % species)
		return []
	var root := scene.instantiate()
	var verts := PackedVector3Array()
	var colors := PackedColorArray()
	var normals := PackedVector3Array()
	for mesh_node: MeshInstance3D in root.find_children("*", "MeshInstance3D", true, false):
		var xf := Transform3D(Basis(Vector3.UP, spec[1]))
		var chain := Transform3D.IDENTITY
		var up: Node = mesh_node
		while up != root:
			chain = (up as Node3D).transform * chain
			up = up.get_parent()
		xf = xf * chain
		for surface in mesh_node.mesh.get_surface_count():
			var arrays := mesh_node.mesh.surface_get_arrays(surface)
			var material := mesh_node.mesh.surface_get_material(surface) as BaseMaterial3D
			var tint := material.albedo_color if material else Color.WHITE
			var image: Image = material.albedo_texture.get_image() if material and material.albedo_texture else null
			if image and image.is_compressed():
				image.decompress()
			var points: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			var uvs = arrays[Mesh.ARRAY_TEX_UV]
			var index = arrays[Mesh.ARRAY_INDEX]
			var order: PackedInt32Array = index if index != null else PackedInt32Array(range(points.size()))
			for t in range(0, order.size() - 2, 3):
				var tri := [xf * points[order[t]], xf * points[order[t + 1]], xf * points[order[t + 2]]]
				verts.append_array(PackedVector3Array(tri))
				normals.append((tri[1] - tri[0]).cross(tri[2] - tri[0]))
				var color := tint
				if image and uvs != null:
					var uv: Vector2 = (uvs[order[t]] + uvs[order[t + 1]] + uvs[order[t + 2]]) / 3.0
					color *= image.get_pixel(clampi(int(uv.x * image.get_width()), 0, image.get_width() - 1),
						clampi(int(uv.y * image.get_height()), 0, image.get_height() - 1))
				colors.append(color)
	root.free()
	if verts.is_empty():
		push_warning("animal model %s has no mesh: %s stays procedural" % [spec[0], species])
		return []
	var box := AABB(verts[0], Vector3.ZERO)
	for v in verts:
		box = box.expand(v)
	var shift := Vector3(box.get_center().x, box.position.y, box.get_center().z)
	for i in verts.size():
		verts[i] = (verts[i] - shift) / box.size.x
	# The palette's sRGB colours, as the procedural shapes' vertex colours are.
	_animal_models[species] = [verts, colors, normals]
	return _animal_models[species]


## A modelled species' arrays (as animal_arrays builds them), {} without a model. No rig: pose is ignored.
static func _model_arrays(species: String, color: Color, _pose: String, size: float) -> Dictionary:
	if not ANIMAL_MODELS.has(species):
		return {}
	var model := _animal_model(species)
	if model.is_empty():
		return {}
	var spec: Array = ANIMAL_MODELS[species]
	var coat: Color = spec[3]
	var tint := Color(color.r / maxf(coat.r, 0.01), color.g / maxf(coat.g, 0.01), color.b / maxf(coat.b, 0.01)) if coat != Color.WHITE else Color.WHITE
	var k: float = spec[2] * size
	var out := _empty_arrays()
	out["part_now"] = 5
	var verts: PackedVector3Array = model[0]
	for key in ["verts", "shadow"]:
		for f in model[1].size():
			var c: Color = model[1][f] * tint
			_tri(out, verts[f * 3] * k, verts[f * 3 + 1] * k, verts[f * 3 + 2] * k, Color(minf(c.r, 1.0), minf(c.g, 1.0), minf(c.b, 1.0)),
				-model[2][f], key)
	return out


## One mesh per species, coat, pose and detail level; all animals share the
## same smooth organic material and the existing pooled body instances.
## A species with a GLB draws it at every detail, ridden horses too; the procedural shape only without one (or its file missing).
static func animal_arrays(species: String, color: Color, pose: String, size: float, detail := 1) -> Dictionary:
	if ANIMAL_MODELS.has(species):
		var model := _model_arrays(species, color, pose, size)
		if not model.is_empty():
			return model
	var out := _empty_arrays()
	if species in ["small_bird", "pigeon", "crow", "duck", "gull"]:
		var bird_size: float = {"small_bird": 0.3, "pigeon": 0.48, "crow": 0.52, "duck": 0.58, "gull": 0.65}.get(species, 0.4) * size
		var flying := pose.begins_with("fly")
		var body_y := 0.28 if flying else 0.22
		_round_part(out, Vector3(0.0, body_y, 0.0), Vector3(bird_size * 0.48, bird_size * 0.28, bird_size * 0.27), color, 5, detail)
		_round_part(out, Vector3(bird_size * 0.38, body_y + bird_size * 0.18, 0.0), Vector3(bird_size * 0.2, bird_size * 0.2, bird_size * 0.18),
			color.lightened(0.08), 5, detail)
		_round_limb(out, Vector3(bird_size * 0.48, body_y + bird_size * 0.12, 0.0),
			Vector3(bird_size * 0.78, body_y + bird_size * 0.08, 0.0), bird_size * 0.09, 0.005,
			Color8(229, 190, 64) if species in ["duck", "gull"] else Color8(55, 48, 43), 4, detail)
		for side: float in [-1.0, 1.0]:
			var wing_y: float = body_y + (bird_size * 0.38 if pose == "fly_1" else -bird_size * 0.12 if flying else 0.06)
			_round_limb(out, Vector3(0.0, body_y + 0.02, side * bird_size * 0.18),
				Vector3(-bird_size * 0.12, wing_y, side * bird_size * (1.35 if flying else 0.48)),
				bird_size * 0.17, bird_size * 0.025, color.darkened(0.08), 5, detail)
			_round_part(out, Vector3(bird_size * 0.52, body_y + bird_size * 0.2, side * bird_size * 0.105),
				Vector3(0.012, 0.012, 0.012), Color8(32, 30, 28), 3, detail)
			if not flying:
				_round_limb(out, Vector3(-bird_size * 0.1, body_y - bird_size * 0.12, side * bird_size * 0.13),
					Vector3(-bird_size * 0.04, 0.02, side * bird_size * 0.13), 0.017, 0.012, Color8(96, 73, 53), 4, detail)
		_round_part(out, Vector3(-bird_size * 0.5, body_y, 0.0), Vector3(bird_size * 0.22, 0.035, bird_size * 0.18),
			color.darkened(0.12), 5, detail)
		return out
	var dims: Array = {"moose": [3.0, 0.7, 1.9], "roe_deer": [1.25, 0.3, 0.9], "fox": [0.8, 0.18, 0.42],
		"dog": [0.9, 0.23, 0.53], "horse": [2.0, 0.32, 1.45], "hare": [0.5, 0.18, 0.34], "squirrel": [0.32, 0.11, 0.23]}.get(species, [0.9, 0.2, 0.5])
	var hl: float = dims[0] * 0.5 * size
	var hw: float = dims[1] * size
	var shoulder: float = dims[2] * size
	var body_y := shoulder * (0.79 if species in ["moose", "roe_deer", "horse"] else 0.72)
	var leg_top := shoulder * 0.72
	var stride := hl * (0.13 if pose == "walk_a" else -0.13 if pose == "walk_b" else 0.0)
	_round_part(out, Vector3(-hl * 0.12, body_y, 0.0), Vector3(hl * 0.84, shoulder * 0.22, hw), color, 5, detail)
	_round_part(out, Vector3(hl * 0.46, body_y + shoulder * 0.05, 0.0), Vector3(hl * 0.36, shoulder * 0.27, hw * 0.85),
		color.lightened(0.04), 5, detail)
	for x: float in [-hl * 0.64, hl * 0.58]:
		for side: float in [-1.0, 1.0]:
			var z := side * hw * 0.66
			var swing := stride * signf(x) * side
			var hip := Vector3(x, leg_top, z)
			var knee := Vector3(x + swing * 0.45, shoulder * 0.36, z)
			var foot := Vector3(x + swing, 0.06 * size, z)
			var radius := minf(hw * 0.36, shoulder * 0.085)
			_round_limb(out, hip, knee, radius, radius * 0.72, color.darkened(0.08), 5, detail)
			_round_part(out, knee, Vector3(radius * 0.8, radius * 0.8, radius * 0.8), color.darkened(0.08), 5, detail)
			_round_limb(out, knee, foot, radius * 0.7, radius * 0.46, color.darkened(0.12), 5, detail)
			_round_part(out, foot + Vector3(0.035 * size, 0.0, 0.0), Vector3(radius * 1.3, 0.045 * size, radius * 0.7),
				Color8(61, 54, 46) if species in ["moose", "roe_deer", "horse"] else color.darkened(0.23), 4, detail)
	var feeding := pose == "feed"
	var head := Vector3(hl * 0.9, shoulder * (0.5 if feeding else 1.03), 0.0)
	var neck_base := Vector3(hl * 0.55, body_y + shoulder * 0.12, 0.0)
	_round_limb(out, neck_base, head, hw * 0.72, hw * 0.43, color, 5, detail)
	_round_part(out, head, Vector3(hl * 0.25, shoulder * 0.18, hw * 0.55), color.lightened(0.05), 5, detail)
	var muzzle := head + Vector3(hl * (0.22 if species in ["moose", "fox", "dog", "horse"] else 0.14), -shoulder * 0.07, 0.0)
	_round_part(out, muzzle, Vector3(hl * 0.24, shoulder * 0.095, hw * 0.36),
		Color8(225, 215, 197) if species == "fox" else color.lightened(0.08), 5, detail)
	for side: float in [-1.0, 1.0]:
		var ear := head + Vector3(-hl * 0.08, shoulder * 0.17, side * hw * 0.37)
		_round_limb(out, ear, ear + Vector3(-hl * 0.04, shoulder * (0.22 if species in ["hare", "fox", "roe_deer"] else 0.12),
			side * hw * 0.35), hw * 0.15, hw * 0.025, color.darkened(0.1), 5, detail)
		if detail > 0:
			_round_part(out, head + Vector3(hl * 0.1, shoulder * 0.04, side * hw * 0.51),
				Vector3(0.016 * size, 0.018 * size, 0.012 * size), Color8(33, 30, 27), 3, detail)
	if species == "fox":
		_round_limb(out, Vector3(-hl * 0.84, body_y, 0.0), Vector3(-hl * 1.65, body_y - shoulder * 0.08, 0.0),
			hw * 0.38, hw * 0.18, color, 5, detail)
		_round_part(out, Vector3(-hl * 1.66, body_y - shoulder * 0.08, 0.0), Vector3(hl * 0.2, hw * 0.22, hw * 0.19),
			Color8(235, 231, 219), 5, detail)
	elif species in ["dog", "horse", "squirrel"]:
		_round_limb(out, Vector3(-hl * 0.88, body_y, 0.0), Vector3(-hl * 1.4, body_y + shoulder * 0.12, 0.0),
			hw * 0.24, hw * 0.08, color, 5, detail)
	elif species in ["hare", "roe_deer"]:
		_round_part(out, Vector3(-hl * 0.9, body_y, 0.0), Vector3(hl * 0.16, shoulder * 0.13, hw * 0.35),
			Color8(235, 231, 219), 5, detail)
	if species == "moose" and not feeding:
		for side: float in [-1.0, 1.0]:
			var antler := head + Vector3(-hl * 0.05, shoulder * 0.18, side * hw * 0.38)
			var palm := antler + Vector3(-hl * 0.11, shoulder * 0.3, side * hw * 0.7)
			_round_limb(out, antler, palm, 0.05 * size, 0.04 * size, Color8(189, 164, 128), 5, detail)
			for tine in 3:
				_round_limb(out, palm + Vector3(-hl * 0.055 * tine, 0.0, side * hw * 0.1 * tine),
					palm + Vector3(-hl * 0.06 * tine, shoulder * (0.22 + 0.04 * tine), side * hw * (0.14 + 0.18 * tine)),
					0.035 * size, 0.008 * size, Color8(189, 164, 128), 5, detail)
	return out


## One car's mesh arrays, centred at the origin, +x forward: the body,
## wheels, the glasshouse sloping up to the roof, and its extras.
static func car_arrays(length: float, width: float, color: Color, shape: Array, sign: int, lamps := 0, detail := 1) -> Dictionary:
	var out := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array(), "shadow": PackedVector3Array(),
		"part": PackedVector2Array(), "part_now": PAINT}
	var hl := length * 0.5
	var hw := width * 0.5
	var van := str(shape[5]) == "door"
	var sill := 1.0 if van else 0.8
	var roof := 1.95 if van else 1.42
	if not van and str(shape[5]) == "rails" and shape[2] > -0.7:
		roof = 1.68  # SUV; estates keep the lower roofline
	elif not van and str(shape[5]) == "stripes":
		roof = 1.29
	elif not van and length < 4.0:
		roof = 1.5
	var tyre := Color8(28, 28, 28)
	out["part_now"] = RUBBER
	for x: float in [hl * 0.64, -hl * 0.64]:
		for y: float in [hw * 0.86, -hw * 0.86]:
			_wheel(out, x, y + signf(y) * 0.05, 0.31, 0.28, tyre, detail)  # 5 cm out past the body
	out["part_now"] = METAL_PAINT
	_car_shell(out, hl, hw, sill, color)
	var top := color.darkened(0.12)
	var glass_front: float = shape[0]
	var roof_front: float = shape[1]
	var roof_rear: float = shape[2]
	var glass_rear: float = minf(shape[3], roof_rear)
	var roof_half: float = shape[4]
	var low := [Vector3(hl * glass_front, sill, -hw * 0.86), Vector3(hl * glass_front, sill, hw * 0.86),
		Vector3(hl * glass_rear, sill, hw * 0.86), Vector3(hl * glass_rear, sill, -hw * 0.86)]
	var high := [Vector3(hl * roof_front, roof - 0.1, -hw * roof_half), Vector3(hl * roof_front, roof - 0.1, hw * roof_half),
		Vector3(hl * roof_rear, roof - 0.1, hw * roof_half), Vector3(hl * roof_rear, roof - 0.1, -hw * roof_half)]
	var roof_edge := [Vector3(high[0].x - 0.1, roof, high[0].z + 0.1), Vector3(high[1].x - 0.1, roof, high[1].z - 0.1),
		Vector3(high[2].x + 0.1, roof, high[2].z - 0.1), Vector3(high[3].x + 0.1, roof, high[3].z + 0.1)]
	var middle := Vector3((glass_front + glass_rear) * hl * 0.5, (sill + roof) * 0.5, 0.0)
	for key in ["verts", "shadow"]:
		for i in 4:  # windshield, right windows, rear window, left windows
			var j := (i + 1) % 4
			var facing: Vector3 = (low[i] + low[j] + high[i] + high[j]) / 4.0 - middle
			out["part_now"] = GLASS_PART
			_quad(out, low[i], low[j], high[j], high[i], CAR_GLASS.lightened(0.1 if i % 2 and not opaque else 0.0), facing, key)
		out["part_now"] = METAL_PAINT
		for i in 4:
			var j := (i + 1) % 4
			_quad(out, high[i], high[j], roof_edge[j], roof_edge[i], color, (high[i] + high[j]) * 0.5 - middle, key)
		_quad(out, roof_edge[0], roof_edge[1], roof_edge[2], roof_edge[3], top, Vector3.UP, key)
	# The pillars and window belt are separate narrow metal strips, following
	# each actual glass edge rather than floating rectangular window decals.
	if detail > 0:
		for i in 4:
			var j := (i + 1) % 4
			_round_limb(out, low[i], high[i], 0.023, 0.023, color.darkened(0.3), METAL_PAINT, 0)
			_round_limb(out, low[i], low[j], 0.016, 0.016, color.darkened(0.25), METAL_PAINT, 0)
	# Door seams, handles, mirrors and a fuel cap give a readable scale.
	for side: float in [-1.0, 1.0] if detail > 0 else []:
		var edge := side * hw * 0.97
		for door_x: float in [hl * (glass_front + glass_rear) * 0.5, hl * glass_rear - 0.03]:
			_round_limb(out, Vector3(door_x, 0.35, edge), Vector3(door_x, sill - 0.06, edge), 0.007, 0.007, color.darkened(0.42), PAINT, 0)
		for handle_x: float in [hl * 0.03, hl * glass_rear + 0.13]:
			_car_box(out, handle_x - 0.055, handle_x + 0.055, edge - 0.012, edge + 0.012, sill - 0.16, sill - 0.13, Color8(80, 84, 86))
		_round_part(out, Vector3(hl * glass_front + 0.06, sill + 0.03, side * hw * 0.99), Vector3(0.11, 0.045, 0.10), color.darkened(0.2), METAL_PAINT, 0)
		_round_part(out, Vector3(-hl * 0.72, sill - 0.18, edge), Vector3(0.055, 0.055, 0.008), color.darkened(0.22), PAINT, 0)
		_car_box(out, -hl * 0.88, hl * 0.88, edge - 0.016, edge + 0.016, 0.29, 0.33, Color8(37, 39, 40))
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
	# Bumpers and grille sit below the lamp assemblies; their depth helps the
	# silhouette read correctly from the front and in the rear-view mirror.
	out["part_now"] = RUBBER
	_car_box(out, hl - 0.04, hl + 0.035, -hw * 0.83, hw * 0.83, 0.28, 0.36, Color8(37, 39, 41))
	_car_box(out, -hl - 0.035, -hl + 0.04, -hw * 0.83, hw * 0.83, 0.28, 0.36, Color8(37, 39, 41))
	if detail > 0:
		_car_box(out, hl + 0.022, hl + 0.032, -hw * 0.42, hw * 0.42, 0.43, 0.54, Color8(27, 30, 32))
		for height: float in [0.46, 0.51]:
			_car_box(out, hl + 0.033, hl + 0.038, -hw * 0.39, hw * 0.39, height, height + 0.008, Color8(115, 123, 125))
	out["part_now"] = PAINT
	return out


## Step 4: the lamps, emissive while lit (car.gdshader's LAMP part): head
## and tail lights by the engine, brighter brake lights, reversing lights,
## the indicators on their side (left -z, right +z) while they blink on.
static func _car_lamps(out: Dictionary, hl: float, hw: float, lamps: int, height := 0.5) -> void:
	var lamp := func(x0: float, x1: float, y_mid: float, half: float, lit: bool, on_color: Color, off_color: Color) -> void:
		out["part_now"] = LAMP if lit else PAINT
		_car_box(out, x0, x1, y_mid - half, y_mid + half, height, height + 0.18, on_color if lit else off_color)
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


static func _car_shell(out: Dictionary, hl: float, hw: float, sill: float, color: Color) -> void:
	var rings := []
	for profile in [[0.24, 0.88, 0.72], [0.29, 0.95, 0.87], [0.42, 0.99, 0.96],
		[sill - 0.16, 1.0, 1.0], [sill - 0.035, 0.96, 0.97], [sill, 0.90, 0.88]]:
		var x: float = hl * profile[1]
		var z: float = hw * profile[2]
		var c := minf(0.24, z * 0.35)
		rings.append([Vector3(x - c, profile[0], -z), Vector3(x, profile[0], -z + c),
			Vector3(x, profile[0], z - c), Vector3(x - c, profile[0], z),
			Vector3(-x + c, profile[0], z), Vector3(-x, profile[0], z - c),
			Vector3(-x, profile[0], -z + c), Vector3(-x + c, profile[0], -z)])
	for key in ["verts", "shadow"]:
		for r in rings.size() - 1:
			for i in 8:
				var j := (i + 1) % 8
				var facing: Vector3 = (rings[r][i] + rings[r][j]) * 0.5
				_quad(out, rings[r][i], rings[r][j], rings[r + 1][j], rings[r + 1][i], color, Vector3(facing.x, 0.0, facing.z), key)
		for i in 8:
			var j := (i + 1) % 8
			_tri(out, Vector3(0.0, sill, 0.0), rings[-1][i], rings[-1][j], color, Vector3.UP, key)
			_tri(out, Vector3(0.0, 0.28, 0.0), rings[0][j], rings[0][i], color.darkened(0.3), Vector3.DOWN, key)


static func _bike_wheel(out: Dictionary, hub: Vector3, radius: float) -> void:
	for i in 16:
		var angle := TAU * i / 16.0
		var next := TAU * (i + 1) / 16.0
		var rim := hub + Vector3(cos(angle) * radius, sin(angle) * radius, 0.0)
		var rim_next := hub + Vector3(cos(next) * radius, sin(next) * radius, 0.0)
		_round_limb(out, rim, rim_next, 0.027, 0.027, Color8(27, 28, 30), RUBBER, 0)
		if i % 2 == 0:
			_round_limb(out, hub, rim, 0.005, 0.005, Color8(150, 155, 158), PAINT, 0)
	_round_part(out, hub, Vector3(0.045, 0.045, 0.045), Color8(107, 111, 114), PAINT, 0)


static func _wheel(out: Dictionary, x: float, y: float, radius: float, width: float, color: Color, detail := 1) -> void:
	var previous: int = out["part_now"]
	out["part_now"] = RUBBER
	var sides := 16 if detail > 0 else 8
	for i in sides:
		var a := float(i) * TAU / sides
		var b := float(i + 1) * TAU / sides
		var p := Vector2(x + cos(a) * radius, sin(a) * radius + radius)
		var q := Vector2(x + cos(b) * radius, sin(b) * radius + radius)
		for key in ["verts", "shadow"]:
			_quad(out, Vector3(p.x, p.y, y - width * 0.5), Vector3(q.x, q.y, y - width * 0.5),
				Vector3(q.x, q.y, y + width * 0.5), Vector3(p.x, p.y, y + width * 0.5), color, Vector3(cos((a + b) * 0.5), sin((a + b) * 0.5), 0.0), key)
			for side: float in [-1.0, 1.0]:
				var face := y + side * width * 0.5
				var rim := radius * 0.57
				var inner_p := Vector3(x + cos(a) * rim, radius + sin(a) * rim, face + side * 0.004)
				var inner_q := Vector3(x + cos(b) * rim, radius + sin(b) * rim, face + side * 0.004)
				_quad(out, Vector3(p.x, p.y, face), Vector3(q.x, q.y, face), inner_q, inner_p,
					color.darkened(0.12), Vector3(0.0, 0.0, side), key)
				if key == "verts" and detail > 0:
					out["part_now"] = PAINT
					_tri(out, Vector3(x, radius, face + side * 0.006), inner_p, inner_q,
						Color8(127, 137, 143) if i % 4 != 0 else Color8(52, 56, 58), Vector3(0.0, 0.0, side), key)
					out["part_now"] = RUBBER
	if detail > 0:
		for side: float in [-1.0, 1.0]:
			_round_part(out, Vector3(x, radius, y + side * (width * 0.5 + 0.009)), Vector3(radius * 0.13, radius * 0.13, 0.009), Color8(58, 62, 64), PAINT, 0)
	out["part_now"] = previous


static func _round_part(out: Dictionary, centre: Vector3, radii: Vector3, color: Color, part := 0, detail := 1) -> void:
	var previous: int = out["part_now"]
	out["part_now"] = part
	var sides := 12 if detail > 0 else 6
	var bands := 6 if detail > 0 else 3
	for key in ["verts", "shadow"]:
		for band in bands:
			var low := -PI * 0.5 + PI * float(band) / bands
			var high := -PI * 0.5 + PI * float(band + 1) / bands
			for i in sides:
				var a := TAU * float(i) / sides
				var b := TAU * float(i + 1) / sides
				var p := centre + Vector3(cos(low) * cos(a) * radii.x, sin(low) * radii.y, cos(low) * sin(a) * radii.z)
				var q := centre + Vector3(cos(low) * cos(b) * radii.x, sin(low) * radii.y, cos(low) * sin(b) * radii.z)
				var r := centre + Vector3(cos(high) * cos(b) * radii.x, sin(high) * radii.y, cos(high) * sin(b) * radii.z)
				var s := centre + Vector3(cos(high) * cos(a) * radii.x, sin(high) * radii.y, cos(high) * sin(a) * radii.z)
				var outward := (p + q + r + s) * 0.25 - centre
				if band == 0:
					_tri(out, centre - Vector3.UP * radii.y, r, s, color, outward, key)
				elif band == bands - 1:
					_tri(out, p, q, centre + Vector3.UP * radii.y, color, outward, key)
				else:
					_quad(out, p, q, r, s, color, outward, key)
	out["part_now"] = previous


static func _round_limb(out: Dictionary, start: Vector3, finish: Vector3, start_radius: float, end_radius: float,
		color: Color, part := 0, detail := 1) -> void:
	var direction := (finish - start).normalized()
	if direction.length_squared() < 0.5:
		return
	var tangent := direction.cross(Vector3.FORWARD if absf(direction.z) < 0.9 else Vector3.RIGHT).normalized()
	var other := direction.cross(tangent)
	var previous: int = out["part_now"]
	out["part_now"] = part
	var sides := 12 if detail > 0 else 6
	for key in ["verts", "shadow"]:
		for i in sides:
			var a := (tangent * cos(TAU * float(i) / sides) + other * sin(TAU * float(i) / sides))
			var b := (tangent * cos(TAU * float(i + 1) / sides) + other * sin(TAU * float(i + 1) / sides))
			_quad(out, start + a * start_radius, start + b * start_radius, finish + b * end_radius, finish + a * end_radius,
				color, (a + b).normalized(), key)
			_tri(out, start, start + b * start_radius, start + a * start_radius, color, -direction, key)
			_tri(out, finish, finish + a * end_radius, finish + b * end_radius, color, direction, key)
	out["part_now"] = previous


static func _garment_torso(out: Dictionary, centre_y: float, scale: float, color: Color, jacket: bool, build: float, detail: int) -> void:
	var sides := 12 if detail > 0 else 6
	var rings := []
	for profile in [[-0.29, 0.12, 0.17], [-0.2, 0.14, 0.19], [0.0, 0.17, 0.22], [0.18, 0.16, 0.24], [0.29, 0.10, 0.13]]:
		var ring := []
		for i in sides:
			var angle := TAU * float(i) / sides
			ring.append(Vector3(cos(angle) * float(profile[1]) * scale * build * (1.12 if jacket else 1.0),
				centre_y + float(profile[0]) * scale, sin(angle) * float(profile[2]) * scale * build * (1.09 if jacket else 1.0)))
		rings.append(ring)
	for key in ["verts", "shadow"]:
		for r in rings.size() - 1:
			for i in sides:
				var j := (i + 1) % sides
				var facing: Vector3 = (rings[r][i] + rings[r][j]) * 0.5
				_quad(out, rings[r][i], rings[r][j], rings[r + 1][j], rings[r + 1][i], color,
					Vector3(facing.x, 0.0, facing.z), key)
		for i in sides:
			var j := (i + 1) % sides
			_tri(out, Vector3(0.0, centre_y + 0.29 * scale, 0.0), rings[-1][i], rings[-1][j], color, Vector3.UP, key)
			_tri(out, Vector3(0.0, centre_y - 0.29 * scale, 0.0), rings[0][j], rings[0][i], color, Vector3.DOWN, key)


static func _garment_skirt(out: Dictionary, offset: float, scale: float, color: Color, detail: int) -> void:
	var sides := 12 if detail > 0 else 6
	for key in ["verts", "shadow"]:
		for i in sides:
			var a := TAU * float(i) / sides
			var b := TAU * float(i + 1) / sides
			var top_a := Vector3(cos(a) * 0.15, 0.96, sin(a) * 0.17) * scale + Vector3.UP * offset
			var top_b := Vector3(cos(b) * 0.15, 0.96, sin(b) * 0.17) * scale + Vector3.UP * offset
			var hem_a := Vector3(cos(a) * 0.25, 0.61, sin(a) * 0.28) * scale + Vector3.UP * offset
			var hem_b := Vector3(cos(b) * 0.25, 0.61, sin(b) * 0.28) * scale + Vector3.UP * offset
			_quad(out, hem_a, hem_b, top_b, top_a, color, (hem_a + hem_b) * 0.5, key)
			_tri(out, Vector3(0.0, 0.61 * scale + offset, 0.0), hem_b, hem_a, color.darkened(0.1), Vector3.DOWN, key)


## One chunk's mesh arrays (any thread): {"verts", "colors", "lit" (the
## lit windows' verts), "stats"}.
static func build(buildings: Array, styles: Array, origin: Vector2, sites: Array = [], landmarks: Array = [], ground := {}) -> Dictionary:
	var out := {"verts": PackedVector3Array(), "colors": PackedColorArray(), "roof_mask": PackedVector2Array(), "lit": PackedVector3Array(),
		"wall_uv": PackedVector2Array(), "window": PackedFloat32Array(),  # the shader's windows (building_snow.gdshader)
		"arena": PackedVector3Array(), "shadow": PackedVector3Array(), "glass": PackedVector3Array(), "glass_colors": PackedColorArray(),
		"ground": PackedVector3Array(), "ground_colors": PackedColorArray(),
		"deck": PackedVector3Array(), "deck_colors": PackedColorArray(),  # step 5: solid structures that cast (bridges, fences, shelters)
		"canopy": PackedVector3Array(), "canopy_colors": PackedColorArray(),  # step 5: see-through open roofs
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
	var grid: Dictionary = ground.get("ground_heights", {})
	if not grid.is_empty():  # DEM terrain: every vertex onto the ground under it (decks keep their DECK_M above it)
		# ponytail: per vertex - a tall building's roof follows the slope and big flat areas stay planar between
		# their corners; per-building base height and a gridded ground mesh if hills show it
		for key in ["verts", "shadow", "lit", "glass", "arena", "ground", "deck", "canopy", "road"]:
			var verts: PackedVector3Array = out[key]
			for i in verts.size():
				verts[i].y += ground_height(grid, Vector2(verts[i].x, verts[i].z))
			out[key] = verts
	# The per-vertex loops run here, on the worker, not in meshes() on the main thread.
	var normals := {}
	for key in ["verts", "shadow", "lit", "glass", "arena", "ground", "deck", "canopy", "road"]:
		normals[key] = flat_normals(out[key])
	out["normals"] = normals
	out["lit_colors"] = lit_colors(out["lit"])
	out["stats"]["triangles"] = (out["verts"].size() + out["lit"].size() + out["glass"].size() + out["ground"].size() + out["road"].size()) / 3
	return out


## The chunk's mesh instances (main thread): the buildings and their lit
## windows, both in the one building view.
static func meshes(arrays: Dictionary) -> Array:
	var instances: Array = []
	for step: Callable in mesh_steps(arrays):
		instances.append_array(step.call())
	return instances


## meshes() one surface at a time: each Callable makes one ArrayMesh and
## returns its instances, so the main thread can spread a chunk over frames.
static func mesh_steps(arrays: Dictionary) -> Array:
	var steps: Array = []
	for r in _pieces(arrays.get("ground", PackedVector3Array()).size()):
		steps.append(func(): return [_instance(_mesh(_cut(arrays["ground"], r), _cut(arrays["ground_colors"], r), PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _cut(_n(arrays, "ground"), r)), _shared["ground"], LAYER_BUILDINGS)])
	if not arrays.get("deck", PackedVector3Array()).is_empty():
		steps.append(func():
			var deck := _instance(_mesh(arrays["deck"], arrays["deck_colors"], PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _n(arrays, "deck")), _shared["ground"], LAYER_BUILDINGS)
			deck.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
			return [deck])
	if not arrays.get("canopy", PackedVector3Array()).is_empty():
		steps.append(func():
			var roof_mesh := _mesh(arrays["canopy"], arrays["canopy_colors"], PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _n(arrays, "canopy"))
			var roof_shadow := _instance(roof_mesh, _shared["caster"], LAYER_BUILDINGS)  # its shade is solid
			roof_shadow.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY
			return [_instance(roof_mesh, _shared["glass"], LAYER_BUILDINGS), roof_shadow])  # see-through: the taxi and the pumps show under it
	for r in _pieces(arrays.get("road", PackedVector3Array()).size()):
		steps.append(func(): return [_instance(_mesh(_cut(arrays["road"], r), _cut(arrays["road_colors"], r), _cut(arrays["road_uv"], r), PackedVector2Array(), PackedFloat32Array(),
			_cut(arrays["road_uv2"], r), false, _cut(_n(arrays, "road"), r)), _shared.get("road", _shared["ground"]), LAYER_BUILDINGS)])
	if not arrays.get("glass", PackedVector3Array()).is_empty():
		steps.append(func(): return [_instance(_mesh(arrays["glass"], arrays["glass_colors"], PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _n(arrays, "glass")), _shared["glass"], LAYER_BUILDINGS)])
	if arrays["verts"].is_empty():
		return steps
	for r in _pieces(arrays["verts"].size()):
		steps.append(func():
			var drawn := _instance(_mesh(_cut(arrays["verts"], r), _cut(arrays["colors"], r), _cut(arrays["roof_mask"], r), _cut(arrays.get("wall_uv", PackedVector2Array()), r),
				_cut(arrays.get("window", PackedFloat32Array()), r, 4), PackedVector2Array(), false, _cut(_n(arrays, "verts"), r)), _shared["material"], LAYER_BUILDINGS)
			if opaque:  # step 4: the buildings themselves cast and receive the sun's shadow; no shadows-only copies
				drawn.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
			return [drawn])
	# rrt-018-shadows: each building as a plain prism (walls and a flat roof,
	# no windows or doors: a fifth of the triangles), not drawn, only casting
	# the sun's shadow in the shadow view (its layer)
	if not opaque:
		for r in _pieces(arrays["shadow"].size()):
			steps.append(func():
				var caster := _instance(_mesh(_cut(arrays["shadow"], r), PackedColorArray(), PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _cut(_n(arrays, "shadow"), r)), _shared["caster"], LAYER_SHADOW_GROUND)
				caster.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY
				return [caster])
	for r in _pieces(arrays["lit"].size()):
		steps.append(func():
			var colors: PackedColorArray = arrays["lit_colors"] if arrays.has("lit_colors") else lit_colors(arrays["lit"])
			return [_instance(_mesh(_cut(arrays["lit"], r), _cut(colors, r), PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _cut(_n(arrays, "lit"), r)), _shared["lit"], LAYER_BUILDINGS)])
	if not arrays["arena"].is_empty():
		steps.append(func():
			var colors := PackedColorArray()
			colors.resize(arrays["arena"].size())
			colors.fill(WINDOW_LIT_NIGHT)
			return [_instance(_mesh(arrays["arena"], colors, PackedVector2Array(), PackedVector2Array(), PackedFloat32Array(), PackedVector2Array(), false, _n(arrays, "arena")), _shared["arena"], LAYER_BUILDINGS)])
	return steps


## A surface's vertex ranges for mesh_steps: one ArrayMesh per range, so no
## single main-thread step uploads a whole dense chunk (5-6 ms measured).
## ponytail: fixed size; more pieces = more draw calls on dense chunks.
const MESH_STEP_VERTS := 24000  # a multiple of 3: whole triangles


static func _pieces(count: int) -> Array:
	var ranges: Array = []
	for start in range(0, count, MESH_STEP_VERTS):
		ranges.append(Vector2i(start, mini(count, start + MESH_STEP_VERTS)))
	return ranges


## One vertex range of a per-vertex array (`per` values a vertex); an array
## that isn't per-vertex (empty, or absent) is passed through as it is.
static func _cut(values, r: Vector2i, per := 1):
	var count: int = values.size()
	if count == 0 or count % per != 0 or count / per < r.y:
		return values
	if r.x == 0 and r.y * per == count:
		return values
	return values.slice(r.x * per, r.y * per)


static func _n(arrays: Dictionary, key: String) -> PackedVector3Array:
	return arrays.get("normals", {}).get(key, PackedVector3Array())


## Lit windows: warm, each a little brighter or dimmer (deterministic).
static func lit_colors(lit: PackedVector3Array) -> PackedColorArray:
	var colors := PackedColorArray()
	colors.resize(lit.size())
	for i in colors.size():
		var shade := 0.82 + 0.18 * B25.unit(float(i / 6) * 0.61803 + lit[i - i % 6].x * 0.013)
		colors[i] = Color(WINDOW_LIT_NIGHT.r * shade, WINDOW_LIT_NIGHT.g * shade, WINDOW_LIT_NIGHT.b * shade)
	return colors


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
		wall_uv := PackedVector2Array(), window := PackedFloat32Array(), part := PackedVector2Array(), smooth := false,
		normals := PackedVector3Array()) -> ArrayMesh:
	var surface := []
	surface.resize(Mesh.ARRAY_MAX)
	surface[Mesh.ARRAY_VERTEX] = verts
	surface[Mesh.ARRAY_NORMAL] = normals if normals.size() == verts.size() and not verts.is_empty() \
		else smooth_normals(verts, colors) if smooth else flat_normals(verts)
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


static func smooth_normals(verts: PackedVector3Array, colors: PackedColorArray) -> PackedVector3Array:
	var normals := flat_normals(verts)
	var sums := {}
	for i in verts.size():
		var p := verts[i]
		var key := Vector4i(roundi(p.x * 10000.0), roundi(p.y * 10000.0), roundi(p.z * 10000.0), colors[i].to_rgba32())
		sums[key] = sums.get(key, Vector3.ZERO) + normals[i]
	for i in verts.size():
		var p := verts[i]
		var key := Vector4i(roundi(p.x * 10000.0), roundi(p.y * 10000.0), roundi(p.z * 10000.0), colors[i].to_rgba32())
		normals[i] = sums[key].normalized()
	return normals


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
	_shared["organic"] = ShaderMaterial.new()
	_shared["organic"].shader = preload("res://character.gdshader")


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
const RAIL_M := 0.03  # ground railways' ballast, over the roads they cross (a level crossing)
const RAIL_BALLAST_HALF_M := 1.65
enum { ROAD_SURFACE, ROAD_WATER, ROAD_PUDDLE, ROAD_FOAM }  # road.gdshader's UV.x


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
	for line: PackedVector2Array in ground.get("rail_lines", []):  # ground railways: ballast, ties every 0.6 m, the rails (chunk_detail.draw_tracks' sizes)
		var carry := 0.0
		for i in line.size() - 1:
			var length := line[i].distance_to(line[i + 1])
			if length < 1e-3:
				continue
			_ribbon(out, line[i], line[i + 1], RAIL_BALLAST_HALF_M, 0.0, RAIL_M, Color8(108, 100, 92))
			var u := (line[i + 1] - line[i]) / length
			var s := fmod(0.6 - fmod(carry, 0.6), 0.6)
			while s < length:
				var at := line[i] + u * s
				_ribbon(out, at - u * 0.09, at + u * 0.09, 1.3, 0.0, RAIL_M + 0.002, Color8(90, 65, 45))
				s += 0.6
			for offset: float in [-0.72, 0.72]:
				var side := u.orthogonal() * offset
				_ribbon(out, line[i] + side, line[i + 1] + side, 0.04, 0.0, RAIL_M + 0.004, Color8(150, 145, 135))
			carry += length
	for bay: Array in ground.get("bus_bays", []):  # [polygon, colour]: its paved bay and its kerb
		var polygon: PackedVector2Array = bay[0]
		_flat_polygon(out, polygon, ROAD_M + 0.003, bay[1], "road", Vector2(ROAD_SURFACE, 0))
		if polygon.size() >= 4:
			for k in [[1, 2], [2, 3], [3, 0]]:
				_raised_strip(out, polygon[k[0]], polygon[k[1]], CURB_HALF_M, 0.0, CURB_M, Color8(175, 175, 168), "ground")
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
	_structures(out, ground)


## rtx-scene-readiness step 5: bridge decks at their height (DECK_M per OSM
## layer: a game policy, the layer is not metres), ramping down to where they
## meet a lower road; their slab and piers cast shadows; guardrails on them.
## Rail decks, open canopies on their posts, construction fences, bus
## shelters and benches, fuel pumps.
const DECK_M := 6.0  # a bridge's deck above the road it crosses, per layer (4.6 m clearance + structure)
const RAMP_M := 45.0  # a deck climbs to its height over this from where it meets a lower road
const SLAB_M := 0.8
const PIER_EVERY_M := 24.0
const DECK_STEP_M := 5.0  # the deck follows its ramp in pieces this long
const GUARDRAIL_M := 0.9
const DECK_COLOR := Color8(150, 150, 146)
const BALLAST := Color8(120, 112, 100)


## A deck's height at `at` on a layer-`layer` bridge: full height, eased down
## to the ground over RAMP_M toward the nearest end (`ends`: where bridge ways
## meet a lower road, map_chunk.prepare). Negative layers: tunnels, below ground.
## `grid`: the chunk's ground_heights (map_chunk.prepare) - the deck rides on the DEM ground.
static func deck_height(at: Vector2, layer: int, ends: PackedVector2Array, grid := {}) -> float:
	var ground := ground_height(grid, at)
	if layer <= 0:
		return float(layer) * DECK_M + ground
	var nearest := INF
	for end in ends:
		nearest = minf(nearest, at.distance_to(end))
	return float(layer) * DECK_M * smoothstep(0.0, RAMP_M, nearest) + ground


## The DEM ground's height at layer point `at`: bilinear on the chunk's grid
## (origin: its first sample, map metres from the layer origin, rows along map
## +y = layer -y), clamped at its edges. Empty grid: flat ground, 0.
static func ground_height(grid: Dictionary, at: Vector2) -> float:
	if grid.is_empty():
		return 0.0
	var heights: PackedFloat32Array = grid["heights"]
	var cols: int = grid["cols"]
	var rows := heights.size() / cols
	var o: Vector2 = grid["origin"]
	var fx := clampf((at.x - o.x) / float(grid["step"]), 0.0, cols - 1)
	var fy := clampf((-at.y - o.y) / float(grid["step"]), 0.0, rows - 1)
	var ix := mini(int(fx), maxi(cols - 2, 0))
	var iy := mini(int(fy), maxi(rows - 2, 0))
	var ix1 := mini(ix + 1, cols - 1)
	var iy1 := mini(iy + 1, rows - 1)
	var tx := fx - ix
	var ty := fy - iy
	var low := lerpf(heights[iy * cols + ix], heights[iy * cols + ix1], tx)
	var high := lerpf(heights[iy1 * cols + ix], heights[iy1 * cols + ix1], tx)
	return lerpf(low, high, ty)


static func _structures(out: Dictionary, ground: Dictionary) -> void:
	var ends: PackedVector2Array = ground.get("bridge_ends", PackedVector2Array())
	for bridge: Array in ground.get("bridges", []):  # [points, half width, colour, layer, rank, centre colour, solid]
		var points: PackedVector2Array = bridge[0]
		var half: float = bridge[1]
		var since_pier := PIER_EVERY_M * 0.5
		for i in points.size() - 1:
			var length := points[i].distance_to(points[i + 1])
			var pieces := maxi(1, ceili(length / DECK_STEP_M))
			for k in pieces:
				var a := points[i].lerp(points[i + 1], float(k) / pieces)
				var b := points[i].lerp(points[i + 1], float(k + 1) / pieces)
				var ha := deck_height(a, bridge[3], ends)
				var hb := deck_height(b, bridge[3], ends)
				_deck_piece(out, a, b, half, ha, hb, bridge[2], 0.002 * clampi(bridge[4], 0, 8))
				if bridge[5] != null and half >= 2.0 and (k % 2 == 0 or bridge[6]):  # its centre line, dashed by pieces
					_sloped_strip(out, "road", a, b, MARKING_HALF_M, ha + 0.05, hb + 0.05, bridge[5], Vector2.ZERO, Vector2.ZERO)
				since_pier += a.distance_to(b)
				if since_pier >= PIER_EVERY_M and minf(ha, hb) > SLAB_M + 1.0:
					since_pier = 0.0
					_box3d(out, "deck", b, 0.5, 0.0, minf(ha, hb) - SLAB_M, DECK_COLOR.darkened(0.15))
	for rail: Array in ground.get("guardrails", []):  # [from, to, layer]
		var ha := deck_height(rail[0], rail[2], ends)
		var hb := deck_height(rail[1], rail[2], ends)
		_sloped_wall(out, rail[0], rail[1], 0.06, ha, hb, GUARDRAIL_M, Color8(170, 172, 168))
	for deck: PackedVector2Array in ground.get("rail_decks", []):  # a railway bridge: a slab at deck height, ballast on top
		_raised_polygon_at(out, "deck", deck, DECK_M - SLAB_M, DECK_M, BALLAST)
	for line: PackedVector2Array in ground.get("rail_tracks", []):  # its rails, on the ballast
		for i in line.size() - 1:
			_sloped_strip(out, "deck", line[i], line[i + 1], 0.9, DECK_M + 0.03, DECK_M + 0.03, Color8(70, 66, 60), Vector2.ZERO, Vector2.ZERO)
	for canopy: Array in ground.get("canopies", []):  # [polygon, height]: a thin see-through roof on posts at its corners
		var polygon: PackedVector2Array = canopy[0]
		var height: float = canopy[1]
		_flat_polygon(out, polygon, height, Color(0.78, 0.80, 0.82, 0.55), "canopy")
		for p in polygon:
			_box3d(out, "deck", p, 0.12, 0.0, height, Color8(150, 150, 150))
	for ring: PackedVector2Array in ground.get("site_fences", []):  # construction sites: an orange 2 m mesh fence
		for i in ring.size():
			_sloped_wall(out, ring[i], ring[(i + 1) % ring.size()], 0.05, 0.0, 0.0, 2.0, Color8(235, 140, 30))
	for box: Array in ground.get("shelters", []):  # [footprint, kind]: a bus shelter's glass box roof, a bench
		var footprint: PackedVector2Array = box[0]
		if box[1] == "shelter":
			_raised_polygon_at(out, "deck", footprint, 2.3, 2.45, Color8(70, 80, 90))
			for p in footprint:
				_box3d(out, "deck", p, 0.05, 0.0, 2.3, Color8(70, 80, 90))
		else:
			_raised_polygon_at(out, "deck", footprint, 0.0, 0.45, Color8(120, 82, 50))
	props(out, ground.get("props", []))
	power_lines(out, ground.get("power_lines", []))
	attractions(out, ground.get("attractions", []))
	site_details(out, ground.get("site_details", []), float(ground.get("snow", 0.0)))
	for band: Array in ground.get("shore_foam", []):  # [line, its distance from the shore 0..1]: foam on the water (road.gdshader)
		var line: PackedVector2Array = band[0]
		for i in line.size() - 1:
			if line[i].distance_to(line[i + 1]) > 1e-3:
				_ribbon(out, line[i], line[i + 1], 0.33, 0.0, AREAS_TOP_M + 0.0005, Color(0.20, 0.26, 0.29), Vector2(ROAD_FOAM, 0), Vector2(band[1], 0))
	for net: Array in ground.get("nets", []):  # a volleyball net: its posts, the 1 m net below the 2.43 m top
		for end: Vector2 in net:
			_box3d(out, "deck", end, 0.07, 0.0, 2.43, Color8(65, 85, 115))
		_sloped_wall(out, net[0], net[1], 0.03, 1.43, 1.43, 1.0, Color8(55, 60, 65))
	for sign: Vector2 in ground.get("sign_posts", []):  # the post; its readable face stays a 2D overlay
		_box3d(out, "deck", sign, 0.04, 0.0, 2.2, Color8(110, 112, 115))
	for pump: Array in ground.get("pumps", []):  # [position, along]
		var along: Vector2 = pump[1]
		_raised_polygon_at(out, "deck", PackedVector2Array([pump[0] - along * 0.4 - along.orthogonal() * 0.25, pump[0] + along * 0.4 - along.orthogonal() * 0.25,
			pump[0] + along * 0.4 + along.orthogonal() * 0.25, pump[0] - along * 0.4 + along.orthogonal() * 0.25]), 0.0, 1.6, Color8(205, 62, 48))


## Step 5: a chunk's trees and bollards as instances of shared meshes (one
## MultiMesh each: trunks, round crowns, conifer cones, bollards), rebuilt
## when the chunk redraws them (one felled, the season); rows
## [position, kind, crown radius, crown colour, trunk colour, felled angle or NAN].
static var _tree_meshes := {}
const FOREST_NEAR_M := 400.0  # forest_node: detailed crowns nearer (the chunk's centre), simple ones beyond


## A crown built from primitives into one mesh: [mesh, transform] parts,
## base at y 0, top at y 1, radius about 1.
static func _merged(parts: Array, material: Material) -> Mesh:
	var tool := SurfaceTool.new()
	for part: Array in parts:
		tool.append_from(part[0], 0, part[1])
	var mesh := tool.commit()
	mesh.surface_set_material(0, material)
	return mesh


static func _tree_mesh(name: String) -> Mesh:
	if _tree_meshes.is_empty():
		var material := StandardMaterial3D.new()
		material.vertex_color_use_as_albedo = true
		material.vertex_color_is_srgb = true
		material.roughness = 0.9
		var trunk := CylinderMesh.new()
		trunk.top_radius = 0.5
		trunk.bottom_radius = 0.5
		trunk.height = 1.0
		trunk.radial_segments = 6
		trunk.rings = 1
		var crown := SphereMesh.new()
		crown.radius = 1.0
		crown.height = 1.6
		crown.radial_segments = 8
		crown.rings = 4
		var cone := CylinderMesh.new()
		cone.top_radius = 0.0
		cone.bottom_radius = 1.0
		cone.height = 1.0
		cone.radial_segments = 8
		cone.rings = 1
		for mesh in [trunk, crown, cone]:
			mesh.material = material
		var tiers := []  # spruce: four drooping branch whorls narrowing to the top
		for i in 4:
			tiers.append([cone, Transform3D(Basis().scaled(Vector3(1.0 - 0.2 * i, 0.34, 1.0 - 0.2 * i)), Vector3(0, 0.22 * i + 0.17, 0))])
		var pine := [  # pine: a flat, lumpy umbrella of clumps
			[crown, Transform3D(Basis().scaled(Vector3(0.7, 0.45, 0.7)), Vector3(0, 0.6, 0))],
			[crown, Transform3D(Basis().scaled(Vector3(0.45, 0.35, 0.45)), Vector3(0.45, 0.45, 0.15))],
			[crown, Transform3D(Basis().scaled(Vector3(0.45, 0.3, 0.45)), Vector3(-0.35, 0.5, -0.3))],
			[crown, Transform3D(Basis().scaled(Vector3(0.35, 0.3, 0.35)), Vector3(0.05, 0.4, 0.5))]]
		var birch := [  # birch: a tall, loose oval with offset lobes
			[crown, Transform3D(Basis().scaled(Vector3(0.75, 0.5, 0.75)), Vector3(0, 0.42, 0))],
			[crown, Transform3D(Basis().scaled(Vector3(0.5, 0.4, 0.5)), Vector3(0.2, 0.68, 0.1))],
			[crown, Transform3D(Basis().scaled(Vector3(0.45, 0.35, 0.45)), Vector3(-0.25, 0.3, -0.2))]]
		_tree_meshes = {"trunk": trunk, "crown": crown, "cone": cone,
			"spruce": _merged(tiers, material), "pine": _merged(pine, material), "birch": _merged(birch, material)}
	return _tree_meshes[name]


## `grid`: the chunk's DEM ground (trunks stand on it); `far`: the simple
## shapes (one cone or blob per crown) instead of the species' crowns.
static func trees_node(rows: Array, bollards: PackedVector2Array, grid := {}, far := false) -> Node3D:
	var parts := tree_parts(rows, bollards, grid, far)
	var node := Node3D.new()
	for name in parts:
		if parts[name].is_empty():
			continue
		var multi := MultiMesh.new()
		multi.transform_format = MultiMesh.TRANSFORM_3D
		multi.use_colors = true
		multi.mesh = _tree_mesh(name)
		multi.instance_count = parts[name].size()
		for i in parts[name].size():
			multi.set_instance_transform(i, parts[name][i][0])
			multi.set_instance_color(i, parts[name][i][1])
		var instance := MultiMeshInstance3D.new()
		instance.multimesh = multi
		instance.layers = LAYER_BUILDINGS
		instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
		node.add_child(instance)
	return node


## trees_node's instances: mesh name -> [[Transform3D, Color]].
static func tree_parts(rows: Array, bollards: PackedVector2Array, grid := {}, far := false) -> Dictionary:
	var parts := {"trunk": [], "crown": [], "cone": [], "spruce": [], "pine": [], "birch": []}  # [Transform3D, Color]
	for row: Array in rows:
		var at: Vector2 = row[0]
		var radius: float = row[2]
		var conifer: bool = row[1] == "pine" or row[1] == "spruce"
		var felled: float = row[5]
		var ground := ground_height(grid, at)
		if row[1] == "shrub":  # a low round bush, no trunk
			parts["crown"].append([Transform3D(Basis().scaled(Vector3(radius, radius * 0.8, radius)), to_3d(at, ground + radius * 0.6)), row[3]])
			continue
		var trunk_top := radius * (2.6 if row[1] == "pine" else 1.0 if row[1] == "spruce" else 1.6)
		var crown_top := trunk_top + radius * (3.2 if conifer else 1.6)
		if not is_nan(felled):  # lying along where it fell: trunk and crown on the ground
			var along := Vector2(cos(felled), -sin(felled))
			var lying := Basis.looking_at(to_3d(along), Vector3.UP) * Basis(Vector3.RIGHT, -PI / 2.0)
			parts["trunk"].append([Transform3D(lying.scaled(Vector3(radius * 0.18, trunk_top, radius * 0.18)), to_3d(at + along * trunk_top * 0.5, ground + 0.25)), row[4]])
			parts["crown"].append([Transform3D(Basis().scaled(Vector3(radius, radius * 0.5, radius)), to_3d(at + along * (trunk_top + radius), ground + radius * 0.4)), row[3]])
			continue
		parts["trunk"].append([Transform3D(Basis().scaled(Vector3(radius * 0.16, trunk_top + radius, radius * 0.16)), to_3d(at, ground + (trunk_top + radius) * 0.5)), row[4]])
		if far:
			if conifer:
				parts["cone"].append([Transform3D(Basis().scaled(Vector3(radius, crown_top - trunk_top, radius)), to_3d(at, ground + (trunk_top + crown_top) * 0.5)), row[3]])
			else:
				parts["crown"].append([Transform3D(Basis().scaled(Vector3(radius, radius, radius)), to_3d(at, ground + trunk_top + radius * 0.8)), row[3]])
			continue
		var turn := Basis(Vector3.UP, fposmod(at.x * 12.9898 + at.y * 78.233, TAU))  # each crown its own way round
		var top := ground + trunk_top - (radius * 0.4 if row[1] == "birch" else 0.0)
		var tall := crown_top - trunk_top + (radius * 0.4 if row[1] == "birch" else 0.0)
		parts[row[1]].append([Transform3D(turn.scaled(Vector3(radius, tall, radius)), to_3d(at, top)), row[3]])
	for post in bollards:
		parts["trunk"].append([Transform3D(Basis().scaled(Vector3(0.24, 0.9, 0.24)), to_3d(post, ground_height(grid, post) + 0.45)), Color8(48, 48, 46)])
	return parts


## A chunk's procedural forest (map_chunk.forest_trees): the species'
## crowns within FOREST_NEAR_M of the camera, simple cones and blobs beyond
## (Godot's visibility ranges, per chunk instance batch).
static func forest_node(rows: Array, grid: Dictionary) -> Node3D:
	var node := trees_node(rows, PackedVector2Array(), grid)
	for child: GeometryInstance3D in node.get_children():
		child.visibility_range_end = FOREST_NEAR_M
	var far := trees_node(rows, PackedVector2Array(), grid, true)
	for child: GeometryInstance3D in far.get_children():
		child.visibility_range_begin = FOREST_NEAR_M
		child.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		far.remove_child(child)
		node.add_child(child)
	far.free()
	return node


## Step 5: hedges, walls, fences and rink boards standing along their lines,
## casting shadows; rows [kind, PackedVector2Array]. Rebuilt with the chunk's
## railings (a hedge or wooden fence broken through).
const RAILINGS := {"hedge": [0.8, 1.3, Color8(34, 62, 34)], "wall": [0.3, 1.5, Color8(175, 164, 144)],
	"fence": [0.08, 1.2, Color8(205, 193, 157)], "boards": [0.12, 1.1, Color8(240, 242, 244)]}


static func railings_node(rows: Array) -> MeshInstance3D:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	for row: Array in rows:
		var style: Array = RAILINGS.get(row[0], RAILINGS["fence"])
		var line: PackedVector2Array = row[1]
		for i in line.size() - 1:
			_sloped_wall(out, line[i], line[i + 1], style[0], 0.0, 0.0, style[1], style[2])
	if out["deck"].is_empty():
		return null
	var node := _instance(_mesh(out["deck"], out["deck_colors"]), _shared["ground"], LAYER_BUILDINGS)
	node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	return node


## Step 6: roadside fixtures as one node per chunk part, built in layer
## coordinates (an identity transform: _car_box's x and y are the map's):
## street lamp posts reaching to their lamp; traffic signals, their housing's
## three lamps on top lit by the phase (readable from above, as the 2D ones).
static func _world_node(out: Dictionary) -> MeshInstance3D:
	if out["verts"].is_empty():
		return null
	var node := _instance(_mesh(out["verts"], out["colors"], out["roof_mask"], PackedVector2Array(), PackedFloat32Array(), out["part"],
		false, out.get("normals", PackedVector3Array())),
		_shared.get("car", _shared["material"]), LAYER_BUILDINGS)
	node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	return node


## rows [lamp position, toward the road (unit)]: the pole 1.2 m behind the lamp, its arm and head.
static func lamp_posts_node(rows: Array) -> MeshInstance3D:
	return _world_node(lamp_posts_arrays(rows))


## lamp_posts_node's arrays (pure data, worker-safe), normals included.
static func lamp_posts_arrays(rows: Array) -> Dictionary:
	var out := _empty_arrays()
	var steel := Color8(110, 112, 115)
	for row: Array in rows:
		var lamp: Vector2 = row[0]
		var pole: Vector2 = lamp - row[1] * 1.2
		_car_box(out, pole.x - 0.08, pole.x + 0.08, pole.y - 0.08, pole.y + 0.08, 0.0, LAMP_HEIGHT_M + 0.1, steel)
		for k in 3:
			var p := pole.lerp(lamp, (k + 0.5) / 3.0)
			_car_box(out, p.x - 0.22, p.x + 0.22, p.y - 0.05, p.y + 0.05, LAMP_HEIGHT_M - 0.02, LAMP_HEIGHT_M + 0.08, steel)
		_car_box(out, lamp.x - 0.28, lamp.x + 0.28, lamp.y - 0.28, lamp.y + 0.28, LAMP_HEIGHT_M - 0.2, LAMP_HEIGHT_M, Color8(60, 62, 64))
	out["normals"] = flat_normals(out["verts"])
	return out


const SIGNAL_COLORS := [[Color(1.0, 0.12, 0.12), Color8(60, 10, 10)], [Color(1.0, 0.82, 0.0), Color8(60, 50, 0)], [Color(0.16, 0.94, 0.24), Color8(10, 50, 15)]]


## rows [post position, direction toward approaching traffic, lit [red, yellow, green]].
static func signals_node(rows: Array) -> MeshInstance3D:
	var out := _empty_arrays()
	for row: Array in rows:
		var at: Vector2 = row[0]
		var facing: Vector2 = row[1]
		var side := Vector2(-facing.y, facing.x) * 0.16
		_car_box(out, at.x - 0.06, at.x + 0.06, at.y - 0.06, at.y + 0.06, 0.0, 2.6, Color8(70, 70, 70))
		_car_box(out, at.x - 0.19, at.x + 0.19, at.y - 0.19, at.y + 0.19, 2.18, 3.02, Color8(15, 15, 15))
		for k in 3:
			var p: Vector2 = at + facing * 0.2
			var h := 2.84 - k * 0.26
			var lit: bool = row[2][k]
			out["part_now"] = LAMP if lit else PAINT
			_quad(out, to_3d(p - side * 0.65, h - 0.095), to_3d(p + side * 0.65, h - 0.095),
				to_3d(p + side * 0.65, h + 0.095), to_3d(p - side * 0.65, h + 0.095),
				SIGNAL_COLORS[k][0] if lit else SIGNAL_COLORS[k][1], to_3d(facing))
	return _world_node(out)


## Live roadworks (entity_layer): a cone, a barrier board `length` long across the road.
func roadwork_cone(at: Vector2) -> void:
	place_body("cone", func() -> Dictionary:
		var out := _empty_arrays()
		_car_box(out, -0.2, 0.2, -0.2, 0.2, 0.0, 0.05, Color8(30, 30, 30))
		_car_box(out, -0.12, 0.12, -0.12, 0.12, 0.05, 0.45, Color8(245, 105, 25))
		_car_box(out, -0.09, 0.09, -0.09, 0.09, 0.45, 0.55, Color8(255, 240, 220))
		_car_box(out, -0.06, 0.06, -0.06, 0.06, 0.55, 0.72, Color8(245, 105, 25))
		return out, at, 0.0)


func roadwork_barrier(at: Vector2, heading: float, length: float) -> void:
	place_body("barrier|%.1f" % length, func() -> Dictionary:
		var out := _empty_arrays()
		for x: float in [-length * 0.45, length * 0.45]:
			_car_box(out, x - 0.05, x + 0.05, -0.05, 0.05, 0.0, 1.0, Color8(200, 200, 200))
		for k in 4:  # yellow and white panels along the board
			var x0 := -length * 0.5 + length * k / 4.0
			_car_box(out, x0, x0 + length / 4.0, -0.04, 0.04, 0.7, 1.0, Color8(235, 190, 35) if k % 2 == 0 else Color8(245, 245, 240))
		return out, at, heading)


## Step 6: scenery objects as simple shapes at their size and height:
## [length along its angle, width, height, colour]; the rest (shrubs, landmarks) elsewhere.
const PROPS := {"caravan": [6.0, 2.3, 2.5, Color8(238, 234, 220)], "caravan_with_car": [10.5, 2.3, 2.5, Color8(238, 234, 220)],
	"tent": [2.4, 2.0, 1.3, Color8(70, 120, 90)], "camper_van": [0.0, 2.3, 2.9, Color8(238, 234, 220)],  # camper_van: no default length, the row carries vehicles/base.py's (props errors without)
	"bench": [1.4, 0.45, 0.85, Color8(120, 82, 50)], "waste_basket": [0.4, 0.4, 0.9, Color8(60, 90, 60)],
	"bicycle_parking": [3.0, 0.6, 0.8, Color8(150, 150, 150)], "charging_station": [0.5, 0.3, 1.5, Color8(40, 120, 70)],
	"statue": [1.2, 1.2, 2.6, Color8(120, 110, 95)], "picnic_table": [1.8, 1.5, 0.75, Color8(130, 92, 58)],
	"firepit": [1.2, 1.2, 0.3, Color8(90, 85, 80)], "fountain": [4.0, 4.0, 0.6, Color8(170, 175, 180)],
	"gate": [3.0, 0.1, 1.2, Color8(90, 90, 92)], "sandpit": [2.6, 2.6, 0.3, Color8(200, 180, 130)],
	"swing": [3.4, 1.8, 2.2, Color8(170, 60, 50)], "slide": [3.2, 0.9, 1.8, Color8(220, 170, 40)],
	"spring_rider": [0.7, 0.3, 0.8, Color8(60, 150, 210)], "climbing_frame": [2.4, 2.4, 1.6, Color8(200, 80, 60)],
	"seesaw": [3.0, 0.3, 0.6, Color8(70, 140, 70)],
	# osm-render-gaps.md (gap_prop): row[3] is a skyline structure's height or a boulder's size from the server
	"power_pole": [0.0, 0.0, POLE_TOP_M, Color8(92, 72, 52)], "power_tower": [0.0, 0.0, 22.0, Color8(140, 145, 150)],
	"chimney": [0.0, 0.0, 25.0, Color8(150, 72, 58)], "mast": [0.0, 0.0, 30.0, Color8(200, 200, 205)],
	"tower": [0.0, 0.0, 30.0, Color8(170, 168, 160)], "communications_tower": [0.0, 0.0, 30.0, Color8(190, 190, 195)],
	"water_tower": [0.0, 0.0, 20.0, Color8(180, 182, 178)], "boulder": [0.0, 0.0, 1.0, Color8(118, 116, 110)],
	"level_crossing": [0.0, 0.0, 2.6, Color8(235, 235, 235)], "level_crossing_barrier": [0.0, 0.0, 1.0, Color8(235, 235, 235)]}
const GAP_KINDS := ["power_pole", "power_tower", "chimney", "mast", "tower", "communications_tower", "water_tower", "boulder",
	"level_crossing", "level_crossing_barrier"]
const POLE_TOP_M := 9.0
const WIRE_M := 8.6  # the crossarm's height: where the wires hang
const WIRE_SPAN_MAX_M := 150.0


static func props(out: Dictionary, rows: Array) -> void:  # rows [position, angle, kind, length (camper_van: the server's), bench: backrest 0/1]
	for row: Array in rows:
		var look: Array = PROPS.get(row[2], [])
		if look.is_empty():
			continue
		if GAP_KINDS.has(row[2]):
			_gap_prop(out, row[0], float(row[1]), str(row[2]), float(row[3] if row.size() > 3 else look[2]), look[3])
			continue
		var length := float(row[3] if row.size() > 3 else look[0])
		if length <= 0.0:  # a camper van without the server's length (map_chunks): an error, not a flat deck
			push_error("prop %s without its length" % row[2])
			continue
		var along: Vector2 = Vector2(cos(row[1]), -sin(row[1])) * length * 0.5
		var across: Vector2 = along.orthogonal().normalized() * float(look[1]) * 0.5
		var at: Vector2 = row[0]
		if row[2] == "bench":
			_bench(out, at, along, across, look[3], row.size() < 5 or bool(row[4]))
			continue
		_raised_polygon_at(out, "deck", PackedVector2Array([at - along - across, at + along - across, at + along + across, at - along + across]),
			0.0, look[2], look[3])


## A park bench (PROPS "bench"): three seat slats at 0.46 m, two backrest
## slats on the +across side up to 0.85 m (without them for OSM backrest=no),
## and a metal side frame at each end.
## The sitter faces -across (bench_sitting.py), hips on the seat's middle.
static func _bench(out: Dictionary, at: Vector2, along: Vector2, across: Vector2, wood: Color, backrest := true) -> void:
	var u := along.normalized()
	var v := across.normalized()
	var half := along.length()
	var depth := across.length()  # half the seat's depth
	var piece := func(u0: float, u1: float, v0: float, v1: float, z0: float, z1: float, color: Color) -> void:
		_raised_polygon_at(out, "deck", PackedVector2Array([at + u * u0 + v * v0, at + u * u1 + v * v0, at + u * u1 + v * v1, at + u * u0 + v * v1]), z0, z1, color)
	for slat in 3:  # the seat
		var v0 := -depth + slat * depth * 2.0 / 3.0
		piece.call(-half, half, v0 + 0.01, v0 + depth * 2.0 / 3.0 - 0.01, 0.42, 0.46, wood)
	for z in ([0.56, 0.72] if backrest else []):  # the backrest
		piece.call(-half, half, depth - 0.04, depth, z, z + 0.11, wood)
	var metal := Color8(55, 58, 62)
	for end in [-1.0, 1.0]:
		var u0: float = end * (half - 0.12)
		piece.call(u0 - 0.03, u0 + 0.03, -depth + 0.03, -depth + 0.08, 0.0, 0.42, metal)  # front leg
		piece.call(u0 - 0.03, u0 + 0.03, depth - 0.08, depth - 0.03, 0.0, 0.85 if backrest else 0.42, metal)  # back leg and backrest upright
		piece.call(u0 - 0.03, u0 + 0.03, -depth + 0.03, depth - 0.03, 0.36, 0.42, metal)  # the seat's bearer


## osm-render-gaps.md: visual only, nothing collides with these. `size`: the
## height (skyline structures, poles) or a boulder's size; `angle` the road's
## direction at a level crossing.
static func _gap_prop(out: Dictionary, at: Vector2, angle: float, kind: String, size: float, color: Color) -> void:
	var ring := func(radius: float, sides: int, wobble: float) -> PackedVector2Array:
		var points := PackedVector2Array()
		for i in sides:
			var a := TAU * i / sides
			points.append(at + Vector2(cos(a), sin(a)) * radius * (1.0 + wobble * sin(a * 3.0 + at.x)))
		return points
	var along := Vector2(cos(angle), -sin(angle))
	var across := along.orthogonal()
	match kind:
		"power_pole":  # a wooden pole and its crossarm
			_box3d(out, "deck", at, 0.13, 0.0, size, color)
			_sloped_wall(out, at - across * 0.9, at + across * 0.9, 0.12, WIRE_M, WIRE_M, 0.12, color)
		"power_tower":  # a lattice-style tower: four legs narrowing upwards, two crossarms
			for corner in [Vector2(-1, -1), Vector2(1, -1), Vector2(1, 1), Vector2(-1, 1)]:
				for s in 3:
					_box3d(out, "deck", at + corner * (2.0 - s * 0.6), 0.12, size * s / 3.0, size * (s + 1) / 3.0, color)
			for z in [size * 0.75, size - 0.3]:
				_sloped_wall(out, at - across * 5.0, at + across * 5.0, 0.3, z, z, 0.3, color)
		"chimney":
			_raised_polygon_at(out, "deck", ring.call(1.2, 10, 0.0), 0.0, size, color)
		"mast":
			_box3d(out, "deck", at, 0.35, 0.0, size, color)
		"tower", "communications_tower":
			_raised_polygon_at(out, "deck", ring.call(2.0, 8, 0.0), 0.0, size - 3.0, color)
			_raised_polygon_at(out, "deck", ring.call(3.2, 8, 0.0), size - 3.0, size, color)
		"water_tower":  # a shaft and its tank
			_raised_polygon_at(out, "deck", ring.call(1.6, 10, 0.0), 0.0, size * 0.7, color)
			_raised_polygon_at(out, "deck", ring.call(5.0, 12, 0.0), size * 0.7, size, color)
		"boulder":  # a lumpy rock, wider than tall
			_raised_polygon_at(out, "deck", ring.call(size * 0.7, 7, 0.15), 0.0, size * 0.6, color)
			_raised_polygon_at(out, "deck", ring.call(size * 0.45, 7, 0.2), size * 0.6, size, color)
		"level_crossing":  # a crossbuck (St Andrew's cross) on a post either side of the road
			for side in [-1.0, 1.0]:
				var post: Vector2 = at + across * side * 4.0
				_box3d(out, "deck", post, 0.05, 0.0, 2.6, Color8(70, 70, 70))
				_sloped_wall(out, post - along * 0.6, post + along * 0.6, 0.03, 1.8, 2.5, 0.15, color)
				_sloped_wall(out, post - along * 0.6, post + along * 0.6, 0.03, 2.5, 1.8, 0.15, color)
		_:  # level_crossing_barrier: a lowered boom across each half of the road
			for side in [-1.0, 1.0]:
				var post: Vector2 = at + across * side * 4.0
				_box3d(out, "deck", post, 0.15, 0.0, 1.0, Color8(70, 70, 70))
				_sloped_wall(out, post, post - across * side * 3.8, 0.08, 0.85, 0.85, 0.1, Color8(215, 40, 40))


## osm-render-gaps.md: a sagging wire between consecutive poles of a power
## line (lines [pole positions]); spans over WIRE_SPAN_MAX_M stay unwired.
static func power_lines(out: Dictionary, lines: Array) -> void:
	for line: PackedVector2Array in lines:
		for i in line.size() - 1:
			var a := line[i]
			var b := line[i + 1]
			var span := a.distance_to(b)
			if span < 1.0 or span > WIRE_SPAN_MAX_M:
				continue
			var sag := span * 0.02
			for k in 4:  # a parabola in four pieces
				var t0 := k / 4.0
				var t1 := (k + 1) / 4.0
				_sloped_wall(out, a.lerp(b, t0), a.lerp(b, t1), 0.0, WIRE_M - 4.0 * sag * t0 * (1.0 - t0),
					WIRE_M - 4.0 * sag * t1 * (1.0 - t1), 0.04, Color8(40, 40, 42))


## Step 6: amusement rides from their footprint loop (attraction_draw's
## kinds): a roller coaster's track rising and falling on supports, a drop
## tower, a carousel's or swing carousel's canopy on its pole, a Ferris
## wheel's cabins standing in a ring over its A-frame. rows [kind, loop].
const RIDE_COLORS := [Color8(232, 76, 65), Color8(248, 194, 62), Color8(65, 160, 198), Color8(160, 94, 185)]


static func attractions(out: Dictionary, rows: Array) -> void:
	for row: Array in rows:
		var loop: PackedVector2Array = row[1]
		if loop.size() < 4:
			continue
		var centre := Vector2.ZERO
		for i in loop.size() - 1:
			centre += loop[i] / (loop.size() - 1)
		match str(row[0]):
			"roller_coaster":
				var height := func(i: int) -> float: return 3.0 + 3.0 * (0.5 + 0.5 * sin(i * 0.4))
				for i in loop.size() - 1:
					_sloped_strip(out, "deck", loop[i], loop[i + 1], 0.6, height.call(i), height.call(i + 1), Color8(211, 70, 55))
					if i % 3 == 0:
						_box3d(out, "deck", loop[i], 0.12, 0.0, height.call(i), Color8(104, 79, 65))
			"drop_tower":
				_box3d(out, "deck", centre, 1.2, 0.0, 30.0, Color8(91, 108, 126))
				_box3d(out, "deck", centre, 2.0, 8.0, 9.0, RIDE_COLORS[0])
			"carousel", "swing_carousel":
				var swing := str(row[0]) == "swing_carousel"
				var top := 7.0 if swing else 4.5
				_box3d(out, "deck", centre, 0.3, 0.0, top + 0.6, Color8(248, 213, 93))
				var rim := PackedVector2Array()
				for i in loop.size() - 1:
					rim.append(centre + (loop[i] - centre) * (0.45 if swing else 0.72))
				for i in rim.size():  # coloured wedges of the canopy
					var wedge := PackedVector2Array([centre, rim[i], rim[(i + 1) % rim.size()]])
					_raised_polygon_at(out, "deck", wedge, top, top + 0.4, RIDE_COLORS[(i / 6) % 4])
				for i in range(0, loop.size() - 1, 6):  # the seats out at the rim
					_box3d(out, "deck", loop[i], 0.6, 0.9 if not swing else 3.0, 1.6 if not swing else 3.6, RIDE_COLORS[(i / 6) % 4])
			_:  # a Ferris wheel: across its loop's longest axis, cabins in a vertical ring
				var far := loop[0]
				for p in loop:
					if p.distance_to(centre) > far.distance_to(centre):
						far = p
				var radius := maxf(far.distance_to(centre), 3.0)
				var axis := (far - centre).normalized()
				var hub := radius + 2.0
				for side: float in [-1.0, 1.0]:
					var foot := centre + axis.orthogonal() * 2.0 * side
					_sloped_wall(out, foot - axis * 3.0, centre + axis.orthogonal() * 0.5 * side, 0.4, 0.0, hub, 0.4, Color8(77, 99, 124))
					_sloped_wall(out, foot + axis * 3.0, centre + axis.orthogonal() * 0.5 * side, 0.4, 0.0, hub, 0.4, Color8(77, 99, 124))
				for k in 16:
					var t := TAU * k / 16.0
					var at := centre + axis * radius * cos(t)
					var h := hub + radius * sin(t)
					_box3d(out, "deck", at, 0.6, h - 0.7, h + 0.7, RIDE_COLORS[k % 4])
					var next := TAU * (k + 1) / 16.0
					_sloped_wall(out, at, centre + axis * radius * cos(next), 0.2, h, hub + radius * sin(next), 0.2, Color8(233, 229, 208))


## Step 6: a biergarten's tables (benches either side, now and then an
## umbrella) and a cemetery's graves (a plot, its headstone), snowed over as the 2D ones.
static func site_details(out: Dictionary, rows: Array, snow: float) -> void:
	var snowy := Color8(215, 224, 232)
	for row: Array in rows:
		var at: Vector2 = row[0]
		if row[1] == "biergarten":
			var wood := Color8(140, 94, 52).lerp(snowy, snow * 0.7)
			_raised_polygon_at(out, "deck", _rect_at(at, 1.1, 0.45), 0.0, 0.75, wood)
			for side: float in [-1.0, 1.0]:
				_raised_polygon_at(out, "deck", _rect_at(at + Vector2(0, side * 0.95), 1.1, 0.16), 0.0, 0.45, wood)
			if fposmod(sin(at.dot(Vector2(0.73, 0.37))) * 43758.0, 1.0) < 0.4:
				_box3d(out, "deck", at, 0.04, 0.75, 2.2, Color8(236, 209, 161))
				_raised_polygon_at(out, "deck", _rect_at(at, 1.25, 1.25), 2.2, 2.3, Color8(185, 67, 45).lerp(snowy, snow * 0.8))
		else:
			_raised_polygon_at(out, "deck", _rect_at(at, 0.65, 0.9), 0.0, 0.08, Color8(68, 80, 57).lerp(snowy, snow * 0.85))
			_raised_polygon_at(out, "deck", _rect_at(at - Vector2(0, 0.8), 0.6, 0.1), 0.0, 0.85, Color8(155, 157, 150).lerp(snowy, snow * 0.5))


static func _rect_at(at: Vector2, half_x: float, half_y: float) -> PackedVector2Array:
	return PackedVector2Array([at + Vector2(-half_x, -half_y), at + Vector2(half_x, -half_y), at + Vector2(half_x, half_y), at + Vector2(-half_x, half_y)])


## One piece of a deck from a to b: its road surface (the road mesh: wet,
## snowy, patterned), the slab under it with a casting top just below the
## surface, its sides and underside.
static func _deck_piece(out: Dictionary, a: Vector2, b: Vector2, half: float, ha: float, hb: float, color: Color, lift: float) -> void:
	_sloped_strip(out, "road", a, b, half, ha + lift, hb + lift, color, Vector2(ROAD_SURFACE, 0), Vector2(0, 1))
	_sloped_strip(out, "deck", a, b, half, ha - 0.02, hb - 0.02, DECK_COLOR)
	_sloped_strip(out, "deck", a, b, half, ha - SLAB_M, hb - SLAB_M, DECK_COLOR, Vector2.ZERO, Vector2.ZERO, true)
	var side := (b - a).normalized().orthogonal() * half
	for s: float in [1.0, -1.0]:
		_sloped_wall(out, a + side * s, b + side * s, 0.0, ha - SLAB_M, hb - SLAB_M, SLAB_M, DECK_COLOR, side * s)


## A strip from a to b, `half` either side, at heights ha..hb; `down`: facing down (an underside).
static func _sloped_strip(out: Dictionary, key: String, a: Vector2, b: Vector2, half: float, ha: float, hb: float, color: Color,
		uv := Vector2.ZERO, uv2 := Vector2.ZERO, down := false) -> void:
	var side := (b - a).normalized().orthogonal() * half
	var corners := [to_3d(a - side, ha), to_3d(b - side, hb), to_3d(b + side, hb), to_3d(a + side, ha)]
	for tri in [[0, 1, 2], [0, 2, 3]]:
		var p: Vector3 = corners[tri[0]]
		var q: Vector3 = corners[tri[1]]
		var r: Vector3 = corners[tri[2]]
		if ((q - p).cross(r - p).y > 0.0) != down:  # Godot's clockwise front faces: the cross points away from the viewer
			var t := q
			q = r
			r = t
		_ground_push(out, key, p, q, r, color, uv, uv2)


## A wall `thick` thick along a..b, standing `tall` on heights ha..hb (both sides and its top), facing `outward` if given.
static func _sloped_wall(out: Dictionary, a: Vector2, b: Vector2, thick: float, ha: float, hb: float, tall: float, color: Color,
		outward := Vector2.ZERO) -> void:
	if a.distance_squared_to(b) < 1e-6:
		return
	var side := (b - a).normalized().orthogonal()
	var faces := [outward] if outward != Vector2.ZERO else [side, -side]
	for facing: Vector2 in faces:
		var off := facing.normalized() * thick * 0.5
		var quad := [to_3d(a + off, ha), to_3d(b + off, hb), to_3d(b + off, hb + tall), to_3d(a + off, ha + tall)]
		for tri in [[0, 1, 2], [0, 2, 3]]:
			var p: Vector3 = quad[tri[0]]
			var q: Vector3 = quad[tri[1]]
			var r: Vector3 = quad[tri[2]]
			if (q - p).cross(r - p).dot(to_3d(facing)) > 0.0:
				var t := q
				q = r
				r = t
			_ground_push(out, "deck", p, q, r, color, Vector2.ZERO, Vector2.ZERO)
	if thick > 0.0:
		_sloped_strip(out, "deck", a, b, thick * 0.5, ha + tall, hb + tall, color)


## A square post (half width `half`) from `bottom` to `top`.
static func _box3d(out: Dictionary, key: String, at: Vector2, half: float, bottom: float, top: float, color: Color) -> void:
	var square := PackedVector2Array([at + Vector2(-half, -half), at + Vector2(half, -half), at + Vector2(half, half), at + Vector2(-half, half)])
	_raised_polygon_at(out, key, square, bottom, top, color)


## A prism over `polygon` from `bottom` to `top`: its top and walls.
static func _raised_polygon_at(out: Dictionary, key: String, polygon: PackedVector2Array, bottom: float, top: float, color: Color) -> void:
	if polygon.size() < 3:
		return
	_flat_polygon(out, polygon, top, color, key)
	var winding := signf(_signed_area(polygon))
	for i in polygon.size():
		var p := polygon[i]
		var q := polygon[(i + 1) % polygon.size()]
		var edge := q - p
		if edge.length_squared() > 1e-6:
			_ground_wall(out, p, q, bottom, top, color, Vector2(edge.y, -edge.x) * winding, key)


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
		_ground_wall(out, p, q, bottom, top, color, (p + q) / 2.0 - (a + b) / 2.0, key)


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
			_quad(out, to_3d(ia, height), to_3d(ib, height), to_3d(ib, top), to_3d(ia, top), wall_color if opaque else wall_color.darkened(0.25), to_3d(-normal))  # inside
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
