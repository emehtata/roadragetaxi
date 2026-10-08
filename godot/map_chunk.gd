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
##   z8  railings/walls/hedges, construction-site fences, roadworks,
##       taxi-stand signs; traffic-light posts (own node, redrawn
##       only when one of its lights changes phase - the phase is the server's)
##   z11 fuel price boards: above the vehicles, as draw_fuel_station_signs
##   (z20 the night tint: night_layer.gd)
##   z21 street lights, shown only at night: the light pool added onto the
##       tinted scene, then the lamp head (render/roads.py draw_street_lights);
##       a broken lamp (a knocked street lamp) stays dark
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
const Detail := preload("res://chunk_detail.gd")  # godot-16: the rest of the static world's drawing
const B25 := preload("res://buildings_25d.gd")
const B3 := preload("res://buildings_3d.gd")
const Perf := preload("res://perf.gd")
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
var _canopy_layers: Array[Node2D] = []
var _lights: Node2D = null  # traffic-light posts, if this chunk has any
var _phases: Dictionary = {}  # post id (String) -> phase as last drawn
var _font: Font = ThemeDB.fallback_font
var _trees: Node2D = null  # trees and bollards, if this chunk has any
var _fallen: Dictionary = {}  # MapMath key -> angle, for this chunk's felled trees
var _knocked: Dictionary = {}  # keys of this chunk's bollards lying flat
var drivable_roads: Array = []  # [Rect2, key] per drivable road: the night tint counts them (main.gd)
var street_lights := PackedVector2Array()  # positions, for reflectors and long beams
var _pools := Node2D.new()
var _heads := Node2D.new()
var _broken := PackedInt32Array()  # indices of this chunk's street lights that are knocked down
var _season := [0.0, 0.0, 1.0, 0.0]  # [winter, spring, summer, autumn] (state calendar.season)
var _season_layers: Array[Node2D] = []  # landuse and islands: their green kinds follow the season
var _signs: Node2D = null  # signs and speed cameras, if any
var _flash = null  # the flashing speed camera's id (state speed_camera_flash)


func _notification(what: int) -> void:
	if what == NOTIFICATION_PREDELETE:  # light nodes of a chunk without lights never joined the tree
		if _building_task >= 0:
			WorkerThreadPool.wait_for_task_completion(_building_task)
		for node in [_pools, _heads, building_node] + meshes_3d:
			if is_instance_valid(node) and node.get_parent() == null:
				node.free()


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
	# z-1 landuse (under the water, as Pygame's draw_scenery comes before draw_waters)
	if not message.get("landuse", []).is_empty():
		_season_layers.append(_add_layer(-1, func(node: Node2D): Detail.draw_areas(self, node, "landuse")))
	for z in _roads_by_z:
		_roads_by_z[z].sort_custom(func(p, q): return int(p.get("layer", 0)) < int(q.get("layer", 0)))
		var layer_z: int = z
		_px_layers.append(_add_layer(z, func(node: Node2D): _draw_roads(layer_z, node)))  # markings depend on zoom
	_add_layer(5, _draw_wet, _wet_darken)
	_add_layer(5, _draw_wet, _wet_sheen)
	_add_layer(5, _draw_puddles, _puddles)
	if not message.get("parking", []).is_empty():
		_px_layers.append(_add_layer(5, func(node: Node2D): Detail.draw_parking(self, node)))
	if not message.get("guardrails", []).is_empty():
		_px_layers.append(_add_layer(5, func(node: Node2D): Detail.draw_guardrails(self, node)))
	if not message.get("bus_stops", []).is_empty():
		_px_layers.append(_add_layer(5, func(node: Node2D): Detail.draw_bus_stops(self, node)))
	_px_layers.append(_add_layer(6, func(node: Node2D): Detail.draw_tracks(self, node, "railways")))
	if not message.get("traffic_islands", []).is_empty():  # above the roads and rails (render/scenery.py)
		_season_layers.append(_add_layer(6, func(node: Node2D): Detail.draw_areas(self, node, "traffic_islands")))
	var canopy_supports := _add_layer(7, _draw_canopy_supports)
	_px_layers.append(canopy_supports)
	_canopy_layers.append(canopy_supports)
	if not message.get("curbs", []).is_empty() or not message.get("crossings", []).is_empty() or not message.get("speed_bumps", []).is_empty():
		_px_layers.append(_add_layer(8, func(node: Node2D): Detail.draw_road_features(self, node)))
	if not message.get("canopies", []).is_empty():  # z11: above the vehicles; then rail bridges, then (entities) trains
		var canopy_roofs := _add_layer(11, func(node: Node2D): Detail.draw_canopies(self, node))
		_px_layers.append(canopy_roofs)
		_canopy_layers.append(canopy_roofs)
	if not message.get("rail_bridges", []).is_empty() or not message.get("rail_decks", []).is_empty():
		_px_layers.append(_add_layer(11, func(node: Node2D): Detail.draw_rail_bridges(self, node)))
	if not message.get("railings", []).is_empty():
		_px_layers.append(_add_layer(8, _draw_railings))
	if not message.get("street_lights", []).is_empty():
		for light in message["street_lights"]:
			street_lights.append(MapMath.point(origin, light[0], light[1]))
		var add := CanvasItemMaterial.new()
		add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
		add.light_mode = CanvasItemMaterial.LIGHT_MODE_UNSHADED  # light, not lit: the ambient multiply leaves it be
		_pools.material = add
		_pools.draw.connect(_draw_light_pools.bind(_pools))  # MapLayer puts it in its pool group
		_px_layers.append(_pools)
		_px_layers.append(_add_layer(21, _draw_lamp_heads, _heads))
		_heads.material = EMISSIVE
		set_lights_on(false)
	if not message.get("trees", []).is_empty() or not message.get("bollards", []).is_empty() or not message.get("scenery_objects", []).is_empty():
		_trees = _add_layer(6, _draw_trees)
		_px_layers.append(_trees)
	if not message.get("construction_fences", []).is_empty():
		_px_layers.append(_add_layer(8, _draw_fences))
	if not message.get("fuel_stations", []).is_empty():
		_px_layers.append(_add_layer(6, _draw_fuel_pumps))
		var boards := _add_layer(13, _draw_fuel_boards)  # above the trains (z12)
		boards.material = EMISSIVE  # lit price boards
		_px_layers.append(boards)
	if not message.get("roadworks", []).is_empty() or not message.get("taxi_stands", []).is_empty():
		_px_layers.append(_add_layer(8, _draw_points))
	if not message.get("traffic_lights", []).is_empty():
		_lights = _add_layer(8, _draw_traffic_lights)
		_lights.material = EMISSIVE  # the signals glow (godot-lights-01)
		_px_layers.append(_lights)
	if not message.get("signs", []).is_empty() or not message.get("speed_cameras", []).is_empty():
		_signs = _add_layer(8, func(node: Node2D): Detail.draw_signs(self, node, _flash))
		_px_layers.append(_signs)
	_puddle_spots = puddle_spots(message.get("roads", []), _bounds_rect, origin)  # from the raw coordinates
	_compact()
	_build_2_5d()
	set_wetness(_wetness)


## Every polyline and polygon kept as a PackedVector2Array in layer
## coordinates instead of the parsed JSON (an Array of 2-number Arrays per
## point, ~10x the memory): one conversion at load, and the drawing uses
## them directly (godot-16: the chunk data alone had grown by ~20 MiB).
func _compact() -> void:
	for road in _data.get("roads", []):
		road["points"] = _points(road["points"])
	for key in ["waters", "buildings", "parking", "curbs", "construction_fences", "railways", "rail_bridges", "rail_decks", "canopies"]:
		var lines: Array = _data.get(key, [])
		for i in lines.size():
			lines[i] = _points(lines[i])
	for key_index in [["railings", 1], ["landuse", 2], ["traffic_islands", 2], ["level_roads", 1]]:
		for entry in _data.get(key_index[0], []):
			entry[key_index[1]] = _points(entry[key_index[1]])
	if not _bounds.is_empty():
		_clip_to_bounds()


## godot-18: roads, water and railway tracks are in every chunk they
## touch, whole - a long road made each such chunk's layer kilometres wide,
## so the renderer counted it visible and batched all of it every frame.
## Each chunk keeps only its own share; neighbours meet at the border.
func _clip_to_bounds() -> void:
	var roads: Array = []
	for road in _data.get("roads", []):
		for piece in Geometry2D.intersect_polyline_with_polygon(road["points"], _bounds):
			if piece.size() >= 2:
				var part: Dictionary = road.duplicate()
				part["points"] = piece
				roads.append(part)
	_data["roads"] = roads
	for z in _roads_by_z:  # the layers' lists, refilled in place
		_roads_by_z[z].clear()
	for road in roads:
		var z := clampi(int(road.get("layer", 0)), 0, BRIDGE_Z_MAX) + 1
		if _roads_by_z.has(z):
			_roads_by_z[z].append(road)
	for key in ["railways", "rail_bridges"]:
		var pieces: Array = []
		for line in _data.get(key, []):
			for piece in Geometry2D.intersect_polyline_with_polygon(line, _bounds):
				if piece.size() >= 2:
					pieces.append(piece)
		_data[key] = pieces
	var waters: Array = []
	for water in _data.get("waters", []):
		if water.size() >= 3 and not Geometry2D.triangulate_polygon(water).is_empty():
			for piece in Geometry2D.intersect_polygons(water, _bounds):
				if not Geometry2D.triangulate_polygon(piece).is_empty():
					waters.append(piece)
	_data["waters"] = waters


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
	# godot-18: hidden when dry - at alpha 0 they still blended every road twice
	# each frame. A canvas item hidden when it entered the tree didn't draw
	# its strokes when shown later (found in a windowed run), so becoming
	# visible asks for a redraw.
	for node in [_wet_darken, _wet_sheen]:
		var show: bool = node.modulate.a > 0.0
		if show and not node.visible:
			node.queue_redraw()
		node.visible = show
	_puddles.visible = wetness > 0.0
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
	var broken := PackedInt32Array()  # a knocked street lamp is the light at its spot
	for post in knocked.values():
		if post[3] == "street_lamp" and not street_lights.is_empty():
			var at := MapMath.point(_origin, post[0], post[1])
			for i in street_lights.size():
				if street_lights[i].distance_squared_to(at) < 0.01:
					broken.append(i)
	var lamps_changed: bool = broken != _broken
	if lamps_changed:
		_broken = broken
		_pools.queue_redraw()
		_heads.queue_redraw()
	if _trees == null:
		return lamps_changed
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


var _elevated = null


## Roads above ground level (layer > 0): [layer, bounds, half width,
## points], made on the first headlight check, then kept.
func elevated_roads() -> Array:
	if _elevated == null:
		_elevated = []
		for road in _data.get("roads", []):
			if int(road.get("layer", 0)) > 0 and road["points"].size() >= 2:
				var points := _points(road["points"])
				var box := Rect2(points[0], Vector2.ZERO)
				for point in points:
					box = box.expand(point)
				_elevated.append([int(road["layer"]), box, float(road.get("half_width_m", 3.0)), points])
	return _elevated


var _label_candidates = null


## The chunk's labels in layer coordinates ([x, y, text, category]), made
## once (labels.gd redraws often while driving).
func label_candidates() -> Array:
	if _label_candidates == null:
		_label_candidates = []
		for label in _data.get("labels", []):
			var at := MapMath.point(_origin, label[0], label[1])
			_label_candidates.append([at.x, at.y, label[2], label[3]])
	return _label_candidates


var _volumes: Dictionary = {}  # buildings_25d.build: the chunk's buildings as triangle lists
var building_node: Node2D = null  # drawn in MapLayer's building group (ordered far to near across chunks)
var _lit_windows: Node2D = null  # the lit windows' glow, z 21 (over the night tint), additive
var _darkness := 0.0  # as last set (lit windows built later take it)
var _building_view := Vector2.ZERO
var _built_view := Vector2.INF


## The chunk's radial building volumes, rebuilt only when its camera angle
## crosses a small bucket.
func _build_2_5d() -> void:
	var buildings: Array = _data.get("buildings", [])
	if buildings.is_empty():
		return
	var styles: Array = _data.get("building_styles", [])
	var origin := _origin
	if buildings_3d:  # godot-21: one mesh for the 3D building layer, never rebuilt for the view
		if not build_async:
			_meshes_ready(_build_3d_timed(buildings, styles, origin))
		else:
			_building_task = WorkerThreadPool.add_task(func(): _meshes_ready.call_deferred(_build_3d_timed(buildings, styles, origin)))
		return
	building_node = Node2D.new()
	building_node.draw.connect(_draw_volumes)
	var view := _building_view
	if not build_async:
		_buildings_ready(_build_timed(buildings, styles, origin, view))
		return
	# godot-18: built on a worker thread (up to ~45 ms for a dense chunk, in the
	# frame that added it); the chunk shows at once, its buildings when ready.
	_building_task = WorkerThreadPool.add_task(func(): _buildings_ready.call_deferred(_build_timed(buildings, styles, origin, view)))


static var build_async := true  # tests build in place
static var buildings_3d := true  # godot-21 prototype; --buildings 2d: the godot-20 radial renderer
var meshes_3d: Array = []  # buildings_3d.meshes, added to MapLayer's 3D building layer


static func _build_3d_timed(buildings: Array, styles: Array, origin: Vector2) -> Dictionary:
	var started := Time.get_ticks_usec()
	var arrays := B3.build(buildings, styles, origin)
	arrays["build_usec"] = Time.get_ticks_usec() - started
	return arrays


func _meshes_ready(arrays: Dictionary) -> void:
	if _building_task >= 0:
		WorkerThreadPool.wait_for_task_completion(_building_task)
		_building_task = -1
	Perf.add("chunk_buildings_build", arrays.get("build_usec", 0))
	meshes_3d = B3.meshes(arrays)
	_volumes = {"stats": arrays["stats"]}  # the vertices live in the meshes
	if is_inside_tree():
		get_parent().add_building_meshes(self)
var _building_task := -1


static func _build_timed(buildings: Array, styles: Array, origin: Vector2, view_centre := Vector2.ZERO) -> Dictionary:
	var started := Time.get_ticks_usec()
	var volumes := B25.build(buildings, styles, origin, view_centre)
	volumes["build_usec"] = Time.get_ticks_usec() - started
	volumes["view_centre"] = view_centre
	return volumes


func _buildings_ready(volumes: Dictionary) -> void:
	if _building_task >= 0:
		WorkerThreadPool.wait_for_task_completion(_building_task)
		_building_task = -1
	_volumes = volumes
	_built_view = volumes.get("view_centre", _building_view)
	Perf.add("chunk_buildings_build", volumes.get("build_usec", 0))
	building_node.queue_redraw()
	if not _volumes["lit_indices"].is_empty() and _lit_windows == null:
		_lit_windows = Node2D.new()
		var add := CanvasItemMaterial.new()
		add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD  # render/buildings.py: BLEND_RGB_ADD
		_lit_windows.material = add
		_lit_windows.visible = false
		_add_layer(21, func(node: Node2D): _triangles(node, _volumes["lit_points"], _volumes["lit_indices"], B25.WINDOW_LIT), _lit_windows)
	if _lit_windows != null:
		_lit_windows.queue_redraw()
		set_darkness(_darkness)


func set_building_view(view_centre: Vector2) -> void:
	var has_buildings: bool = not _data.get("buildings", []).is_empty()
	var has_canopies: bool = not _data.get("canopies", []).is_empty()
	if not has_buildings and not has_canopies:
		return
	var from := _bounds_rect.get_center() - _built_view
	var to := _bounds_rect.get_center() - view_centre
	# ponytail: one angular bucket per chunk avoids rebuilding the whole city
	# every frame; lower this threshold if close-up direction changes look stepped.
	if _built_view != Vector2.INF and not from.is_zero_approx() and not to.is_zero_approx() and absf(from.angle_to(to)) < 0.06:
		return
	_building_view = view_centre
	for node in _canopy_layers:
		node.queue_redraw()
	if not has_buildings or buildings_3d:
		_built_view = view_centre
		return
	if _building_task >= 0:
		return
	var buildings: Array = _data.get("buildings", [])
	var styles: Array = _data.get("building_styles", [])
	var origin := _origin
	var view := _building_view
	if build_async:
		_building_task = WorkerThreadPool.add_task(func(): _buildings_ready.call_deferred(_build_timed(buildings, styles, origin, view)))
	else:
		_buildings_ready(_build_timed(buildings, styles, origin, view))


## The buildings' triangles go to the renderer, which keeps its own copy:
## ours is dropped after the draw (half the memory), rebuilt - identically -
## should the node ever be redrawn. The hulls (headlights) stay.
func _draw_volumes() -> void:
	if _building_task >= 0 or _volumes.is_empty():
		return  # still being built (godot-18)
	var started := Time.get_ticks_usec()
	if _volumes.get("points", PackedVector2Array()).is_empty():
		var hulls: Array = _volumes.get("hulls", [])
		_volumes = B25.build(_data.get("buildings", []), _data.get("building_styles", []), _origin, _building_view)
		_volumes["hulls"] = hulls if not hulls.is_empty() else _volumes["hulls"]
	_triangles_colored(building_node, _volumes["points"], _volumes["indices"], _volumes["colors"])
	for key in ["points", "colors", "indices"]:
		_volumes[key] = _volumes[key].duplicate()
		_volumes[key].clear()
	Perf.add("chunk_buildings_draw", Time.get_ticks_usec() - started)


## Night windows (render/buildings.py draw_illuminated_windows): from
## darkness 0.25, fading in to 165/255 by 0.5 - a modulate, never a redraw.
func set_darkness(darkness: float) -> void:
	_darkness = darkness
	if _lit_windows == null:
		return
	var intensity := clampf((darkness - 0.25) / 0.25, 0.0, 1.0)
	_lit_windows.visible = intensity > 0.0
	_lit_windows.modulate = Color(1, 1, 1, 165.0 / 255.0 * intensity)


static func _triangles_colored(node: Node2D, points: PackedVector2Array, indices: PackedInt32Array, colors: PackedColorArray) -> void:
	if not indices.is_empty():
		RenderingServer.canvas_item_add_triangle_array(node.get_canvas_item(), indices, points, colors)


func _draw_canopy_supports(node: Node2D) -> void:
	Detail.draw_canopy_supports(self, node)


## Which speed camera flashes (state speed_camera_flash, or null): this
## chunk redraws its cameras only if that changes for one of them.
func set_flash(index) -> bool:
	if _signs == null or index == _flash:
		return false
	_flash = index
	_signs.queue_redraw()
	return true


## Street lights shine at night only (darkness > 0.25, render/roads.py):
## shown or hidden, never redrawn for it.
func set_lights_on(on: bool) -> void:
	_heads.visible = on  # the pools: MapLayer shows or hides its group


## The season's weights (state calendar.season): water, trees and their
## colours follow (render/scenery.py seasonal_vegetation_color, render/waters.py
## ice). They change about once a game day, not with the clock.
func set_season(weights: Array) -> bool:
	if weights == _season or weights.size() != 4:
		return false
	_season = weights
	queue_redraw()
	if _trees != null:
		_trees.queue_redraw()
	for node in _season_layers:
		node.queue_redraw()
	return true


## render/scenery.py _season_palette_color and seasonal_vegetation_color:
## a summer colour through the season's palettes, by weight.
static func seasonal_color(summer: Color, weights: Array) -> Color:
	var c := [summer.r8, summer.g8, summer.b8]
	var winter := Color8(mini(245, 218 + c[0] / 10), mini(245, 218 + c[1] / 10), mini(245, 218 + c[2] / 10))
	var spring := Color8(mini(255, int(c[0] * 0.82 + 62)), mini(255, int(c[1] * 0.82 + 62)), mini(255, int(c[2] * 0.82 + 62)))
	var autumn := Color8(mini(210, int(c[0] * 1.35 + 38)), mini(170, int(c[1] * 0.92 + 24)), mini(105, int(c[2] * 0.55 + 18)))
	var palettes := [winter, spring, summer, autumn]
	var out := [0.0, 0.0, 0.0]
	for i in 4:
		out[0] += palettes[i].r8 * weights[i]
		out[1] += palettes[i].g8 * weights[i]
		out[2] += palettes[i].b8 * weights[i]
	return Color8(clampi(roundi(out[0]), 0, 255), clampi(roundi(out[1]), 0, 255), clampi(roundi(out[2]), 0, 255))


## How the state names a static obstacle: its position at 0.1 m, as both
## the chunks and the state round it.
static func obstacle_key(x: float, y: float) -> String:
	return "%.1f,%.1f" % [x, y]


func _px(pixels: float) -> float:
	return pixels / _px_per_m


func _points(line) -> PackedVector2Array:
	if typeof(line) == TYPE_PACKED_VECTOR2_ARRAY:  # already converted (_compact)
		return line
	var points := PackedVector2Array()
	for point in line:
		points.append(MapMath.point(_origin, point[0], point[1]))
	return points


func _draw() -> void:
	# render/waters.py: water freezes with the winter weight.
	var water_color := Color(0.25, 0.45, 0.65).lerp(Color8(232, 240, 244), clampf(_season[0], 0.0, 1.0))
	for water in _data.get("waters", []):
		var polygon := _points(water)
		if polygon.size() >= 3 and not Geometry2D.triangulate_polygon(polygon).is_empty():
			draw_colored_polygon(polygon, water_color)


func _draw_roads(z: int, node: Node2D) -> void:
	var lines := {}  # centre-line colour -> segments (one call each)
	var chevrons := PackedVector2Array()
	for road in _roads_by_z[z]:
		var width: float = max(0.6, 2.0 * float(road.get("half_width_m", 1.5)))
		var color: Color = Detail._rgb(road["color"]) if road.has("color") else (Color(0.33, 0.33, 0.35) if road.get("drivable", false) else Color(0.55, 0.52, 0.45))
		var points := _points(road["points"])
		if z > 1:
			node.draw_polyline(points, Color(0.12, 0.12, 0.13), width + 0.6)  # bridge edge
		node.draw_polyline(points, color, width)
		Detail.road_markings(self, road, points, lines, chevrons)
	for line_color in lines:  # render/roads.py: after this layer's roads, under the next layer's
		node.draw_multiline(lines[line_color], line_color, -1.0)
	if not chevrons.is_empty():
		node.draw_multiline(chevrons, Color8(200, 200, 200), _px(2.0))


## White strokes over drivable roads, tinted by the node's modulate.
func _draw_wet(node: Node2D) -> void:
	for road in _data.get("roads", []):
		if not road.get("drivable", false):
			continue
		var line := _points(road["points"])
		# godot-18: the part inside the chunk (clip_polyline_with_polygon, used before, returns the part outside)
		var parts: Array = [line] if _bounds.is_empty() else Geometry2D.intersect_polyline_with_polygon(line, _bounds)
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
		if Detail._valid(polygon):  # a jittered outline can cross itself
			node.draw_colored_polygon(polygon, Color(RS.PUDDLE_COLOR, RS.PUDDLE_MAX_ALPHA * strength))


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
		style["crown"] = seasonal_color(style["crown"], _season)
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
	for obj in _data.get("scenery_objects", []):
		_draw_scenery_object(node, MapMath.point(_origin, obj[0], obj[1]), str(obj[2]), float(obj[3]))


## render/scenery.py draw_scenery_objects' decorative kinds, in metres with
## Pygame's minimum pixel sizes.
func _draw_scenery_object(node: Node2D, at: Vector2, kind: String, angle: float) -> void:
	match kind:
		"bench":  # 1.4 x 0.4 m, along the path it's beside
			var along := Vector2(cos(angle), -sin(angle))
			var across := Vector2(-along.y, along.x)
			node.draw_colored_polygon(PackedVector2Array([at - along * 0.7 - across * 0.2, at + along * 0.7 - across * 0.2,
				at + along * 0.7 + across * 0.2, at - along * 0.7 + across * 0.2]), Color8(120, 82, 45))
		"waste_basket":
			var size := maxf(_px(2.0), 0.6)
			node.draw_rect(Rect2(at - Vector2(size, size) / 2.0, Vector2(size, size)), Color8(58, 66, 56))
		"bicycle_parking":
			var size := maxf(_px(2.0), 0.8)
			var color := Color8(75, 95, 115)
			node.draw_rect(Rect2(at - Vector2(size / 2.0, size / 4.0), Vector2(size, maxf(_px(1.0), size / 2.0))), color)
			for dx: float in [-size / 3.0, 0.0, size / 3.0]:
				node.draw_line(at + Vector2(dx, -maxf(_px(2.0), 0.5)), at + Vector2(dx, 0), color, maxf(_px(1.0), 0.08))
		"statue":
			var pedestal := Vector2(maxf(_px(2.0), 0.9), maxf(_px(2.0), 0.6))
			node.draw_rect(Rect2(at - Vector2(pedestal.x / 2.0, 0), pedestal), Color8(110, 110, 105))
			var radius := maxf(_px(2.0), 0.5)
			node.draw_circle(at - Vector2(0, radius / 2.0), radius, Color8(150, 130, 85))
		"picnic_table":
			var size := Vector2(maxf(_px(2.0), 1.6), maxf(_px(2.0), 0.9))
			node.draw_rect(Rect2(at - size / 2.0, size), Color8(135, 95, 55))
		"firepit":
			var radius := maxf(_px(2.0), 0.5)
			node.draw_arc(at, radius, 0.0, TAU, 16, Color8(60, 58, 55), maxf(_px(1.0), radius / 3.0))
			node.draw_circle(at, maxf(_px(1.0), radius / 2.0), Color8(216, 120, 40))
		"fountain":
			var radius := maxf(_px(2.0), 0.7)
			node.draw_circle(at, radius, Color8(90, 165, 185))
			node.draw_circle(at, maxf(_px(1.0), radius / 3.0), Color8(220, 240, 245))
		"gate":
			var half := maxf(_px(2.0), 1.0)
			node.draw_line(at - Vector2(half, 0), at + Vector2(half, 0), Color8(100, 92, 80), maxf(_px(1.0), 0.15))


## render/roads.py draw_railings: hedges and walls solid, fences and
## railings dashed (0.8 m on, 0.4 m off).
## One draw call per style (a city has thousands of fences: a call per
## dash cost megabytes of draw commands).
func _draw_railings(node: Node2D) -> void:
	var lines := {"hedge": PackedVector2Array(), "wall": PackedVector2Array(), "fence": PackedVector2Array()}
	for railing in _data["railings"]:
		var points := _points(railing[1])
		var kind := str(railing[0]) if railing[0] in ["hedge", "wall"] else "fence"
		if kind == "fence":
			for dash in dashes(points, 0.8, 0.4):
				lines["fence"].append_array(PackedVector2Array([dash[0], dash[1]]))
		else:
			for i in points.size() - 1:
				lines[kind].append_array(PackedVector2Array([points[i], points[i + 1]]))
	if not lines["hedge"].is_empty():
		node.draw_multiline(lines["hedge"], Color8(58, 92, 48), maxf(_px(2.0), 0.25))
	if not lines["wall"].is_empty():
		node.draw_multiline(lines["wall"], Color8(128, 122, 112), maxf(_px(2.0), 0.25))
	if not lines["fence"].is_empty():
		# 0.12 m is a pixel or so at normal zoom: a hairline then (no triangles per dash).
		node.draw_multiline(lines["fence"], Color8(150, 145, 130), -1.0 if 0.12 * _px_per_m < 1.5 else 0.12)


## render/roads.py draw_street_lights: each light's pool, a 270-degree fan
## toward its road, added onto the tinted scene. godot-final-09: the fans
## go straight into one triangle array - one draw for the chunk - and simply
## add where they overlap, at a low alpha so a dense junction stays a warm
## pool rather than white. (They used to be boolean-cut into disjoint pieces
## on a worker at dusk - up to 260 ms - and drawn as ~2,500 separate
## polygons: ~7 ms a night frame on llvmpipe.) Broken lamps are left out.
const POOL_CORE := Color(0.34, 0.23, 0.08)  # added at the lamp: warm amber (godot-lights-01)
const POOL_MID := Color(0.11, 0.075, 0.025)  # the inner ring: a soft shoulder
const POOL_EDGE := Color(0, 0, 0)  # ... fading to nothing at the reach
const POOL_STEPS := 16
const POOL_INNER := 0.32  # the inner ring's share of the pool
const EMISSIVE := preload("res://emissive.tres")  # unshaded: lamps, signals and boards glow through the night


func _draw_light_pools(node: Node2D) -> void:
	var fans := pool_fans(street_lights, _data.get("street_lights", []), _broken)
	var colors := PackedColorArray()
	colors.resize(fans[0].size())
	for centre in fans[2]:  # per lamp: centre, POOL_STEPS inner ring points, POOL_STEPS outer
		colors[centre] = POOL_CORE
		for k in POOL_STEPS:
			colors[centre + 1 + k] = POOL_MID
			colors[centre + 1 + POOL_STEPS + k] = POOL_EDGE
	if not fans[1].is_empty():
		RenderingServer.canvas_item_add_triangle_array(node.get_canvas_item(), fans[1], fans[0], colors)


## The working lamps' pools as one triangle list: [points, indices, each
## pool's centre index]. A pool is a soft ellipse leaning toward its road
## (the lamp's direction): a centre, an inner ring and an outer ring that
## fades to nothing - no straight fan edges (render/roads.py: a 270-degree
## fan; this reads as light, not a wedge).
static func pool_fans(positions: PackedVector2Array, lights: Array, broken: PackedInt32Array) -> Array:
	var points := PackedVector2Array()
	var triangles := PackedInt32Array()
	var centres := PackedInt32Array()
	for i in positions.size():
		if broken.has(i) or i >= lights.size():
			continue
		var light: Array = lights[i]
		var reach := float(light[3])
		var along := Vector2(cos(light[2]), -sin(light[2]))  # toward the road
		var across := Vector2(-along.y, along.x)
		var middle: Vector2 = positions[i] + along * reach * 0.22
		var centre := points.size()
		centres.append(centre)
		points.append(positions[i])
		for ring in [POOL_INNER, 1.0]:
			for k in POOL_STEPS:
				var angle := TAU * k / POOL_STEPS
				points.append(middle + (along * cos(angle) * 0.78 + across * sin(angle) * 0.62) * reach * ring)
		for k in POOL_STEPS:
			var next := (k + 1) % POOL_STEPS
			var inner := centre + 1
			var outer := centre + 1 + POOL_STEPS
			triangles.append_array(PackedInt32Array([centre, inner + k, inner + next]))
			triangles.append_array(PackedInt32Array([inner + k, outer + k, outer + next, inner + k, outer + next, inner + next]))
	return [points, triangles, centres]


static func _box(polygon: PackedVector2Array) -> Rect2:
	var box := Rect2(polygon[0], Vector2.ZERO)
	for point in polygon:
		box = box.expand(point)
	return box


## A triangle list drawn in one colour, as one command.
static func _triangles(node: Node2D, points: PackedVector2Array, triangles: PackedInt32Array, color: Color) -> void:
	if triangles.is_empty():
		return
	var colors := PackedColorArray()
	colors.resize(points.size())
	colors.fill(color)
	RenderingServer.canvas_item_add_triangle_array(node.get_canvas_item(), triangles, points, colors)


func _draw_lamp_heads(node: Node2D) -> void:
	var radius := maxf(_px(1.0), 0.28)
	var points := PackedVector2Array()
	var triangles := PackedInt32Array()
	for i in street_lights.size():
		if _broken.has(i):
			continue
		var centre := points.size()
		points.append(street_lights[i])
		for step in 8:
			points.append(street_lights[i] + Vector2(cos(TAU * step / 8.0), sin(TAU * step / 8.0)) * radius)
			triangles.append_array(PackedInt32Array([centre, centre + 1 + step, centre + 1 + (step + 1) % 8]))
	_triangles(node, points, triangles, Color8(215, 215, 200))


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
		# One chance per PUDDLE_STRETCH_M of road, not Pygame's one per way: a
		# way can be a whole street, which left about one puddle a screen.
		var lengths := PackedFloat32Array()
		var total := 0.0
		for i in points.size() - 1:
			total += Vector2(points[i][0], points[i][1]).distance_to(Vector2(points[i + 1][0], points[i + 1][1]))
			lengths.append(total)
		for chance in maxi(1, int(total / RS.PUDDLE_STRETCH_M)):
			if rng.randf() > RS.PUDDLE_CHANCE_PER_WAY:
				continue
			var s := rng.randf_range(0.0, total)  # where along the road
			var index := 0
			while index < lengths.size() - 1 and lengths[index] < s:
				index += 1
			var a := Vector2(points[index][0], points[index][1])
			var b := Vector2(points[index + 1][0], points[index + 1][1])
			var segment := b - a
			var start := lengths[index] - segment.length()
			var along := clampf((s - start) / segment.length(), 0.0, 1.0) if segment.length() > 0.0 else 0.0
			var perp := Vector2(-segment.y, segment.x).normalized() if segment.length() > 0.0 else Vector2.ZERO
			var half_width := float(road.get("half_width_m", 3.0))
			var world := a + segment * along + perp * rng.randf_range(-0.5, 0.5) * half_width * 0.6
			var at := MapMath.point(origin, world.x, world.y)
			var radius := rng.randf_range(RS.PUDDLE_MIN_RADIUS_M, minf(RS.PUDDLE_MAX_RADIUS_M, half_width * 0.9))
			var reveal := rng.randf_range(RS.PUDDLE_REVEAL_MIN, RS.PUDDLE_REVEAL_MAX)
			var shape: Array = []
			for i in RS.PUDDLE_SHAPE_POINTS:
				shape.append(1.0 + rng.randf_range(-RS.PUDDLE_SHAPE_JITTER, RS.PUDDLE_SHAPE_JITTER))
			var phase := rng.randf()  # the ripple's place in its 2.4 s cycle (render/weather.py ripple_phase)
			if bounds.size == Vector2.ZERO or bounds.has_point(at):
				spots.append({"at": at, "radius": maxf(RS.PUDDLE_MIN_RADIUS_M, radius), "reveal": reveal, "shape": shape, "phase": phase})
	return spots
