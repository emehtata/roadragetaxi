## The static map, streamed in chunks ("chunk" / "chunk_unload" messages;
## Python decides which). Each chunk is one child canvas item drawn once
## when it arrives, so loading or dropping one never redraws the others.
## Coordinates are metres relative to `origin` (world y north -> Godot y
## down), so large map coordinates don't lose float precision.
extends Node2D

const MapChunk := preload("res://map_chunk.gd")
const Buildings3D := preload("res://buildings_3d.gd")
# shortcut: two whole chunks per frame; split further if one dense chunk exceeds 5 ms.
const SNOW_REDRAW_CHUNKS_PER_FRAME := 2

var origin := Vector2.ZERO
var road_snow := 0.0
var plowed_cells: Array = []
var snowing := false
var _snow_baselines: Dictionary = {}  # preserve a new area's clean start across chunk refreshes
var _snow_redraws: Dictionary = {}
var wetness := 0.0  # road wetness as last applied (bucketed, see set_wetness)
var px_per_m := 9.0  # the camera zoom, for the chunks' pixel-sized points
var phases: Dictionary = {}  # traffic-light phases as last applied (state "traffic_lights")
var knocked: Dictionary = {}  # knocked posts: key -> [x, y, angle, kind] (state "knocked_posts")
var _knocked_posts: Node2D  # drawn here, from the state: a lamp has no static data (made in _ready)
var broken_hedges: Dictionary = {}
var _last_hedge_damage: Array = []
var _last_obstacles := []
var season := [0.0, 0.0, 1.0, 0.0]  # [winter, spring, summer, autumn] as last applied
var lights_on := false
var _pool_group: Node2D  # every loaded chunk's street-light pools (each chunk's: their union, added once)
var _flood_group: Node2D  # every loaded chunk's floodlit sports places
var sports_hours := false  # state calendar.sports_lights: 07-22, when floodlights may burn
var arena_lights_on := false
var building_view_centre := Vector2.ZERO
var shadows_enabled := true


func _make_pool_group() -> void:
	# godot-18: a plain container; each chunk draws the union of its pools
	# additively. It was a CanvasGroup (paint, then add the union once):
	# its screen-sized copy cost ~19 ms a frame at night on llvmpipe.
	_pool_group = Node2D.new()
	_pool_group.z_index = 6  # under the buildings (7): lamps light the street, not the roofs above them
	_pool_group.visible = false
	add_child(_pool_group)
	_flood_group = Node2D.new()
	_flood_group.z_index = 6
	_flood_group.visible = false
	add_child(_flood_group)


## Floodlights: in their hours, when the street lights are on, on the surface.
func _show_floods() -> void:
	_flood_group.visible = sports_hours and lights_on and map_level == 0


func set_sports_hours(on: bool) -> void:
	if on != sports_hours:
		sports_hours = on
		_show_floods()


func set_arena_lights(on: bool) -> void:
	if on == arena_lights_on:
		return
	arena_lights_on = on
	if buildings_3d != null:
		buildings_3d.set_arena_lights(on)
	for chunk in _chunks.values():
		chunk.set_arena_lights(on)


func _ready() -> void:
	_ground = Node2D.new()  # under everything, the landuse (z -1) included
	_ground.z_index = -2
	_ground.draw.connect(_draw_ground)
	add_child(_ground)
	_buildings = Node2D.new()
	_buildings.z_index = 7
	add_child(_buildings)
	_underground = Node2D.new()  # level roads (and the dark below ground), over the surface map
	_underground.z_index = 11  # covers every surface bridge, below the player's entities (12)
	_underground.draw.connect(_draw_underground)
	add_child(_underground)
	_make_pool_group()
	_knocked_posts = Node2D.new()
	_knocked_posts.z_index = 6
	_knocked_posts.draw.connect(_draw_knocked_posts)
	add_child(_knocked_posts)
var _chunks: Dictionary = {}  # chunk_id -> MapChunk
var map_level := 0  # the taxi's map level (state player.map_level): 0 surface, < 0 underground
var flash = null  # the flashing speed camera (state speed_camera_flash)
var _ground: Node2D
var _buildings: Node2D  # every chunk's 2.5D buildings, z 7, ordered far to near (godot-17)
var _underground: Node2D
var buildings_3d: Node2D = null  # godot-21: the 3D building layer (MapChunk.buildings_3d)


## Made on first use: main.gd reads --buildings after this node's _ready.
func _layer_3d() -> Node2D:
	if buildings_3d == null:
		buildings_3d = Buildings3D.new()  # its sprites carry their own z (7, lit windows 21)
		add_child(buildings_3d)
		buildings_3d.set_shadows_enabled(shadows_enabled)
		buildings_3d.set_arena_lights(arena_lights_on)
		buildings_3d.set_snow(float(season[0]))
	return buildings_3d


func add_building_meshes(chunk: Node) -> void:
	if not chunk.meshes_3d.is_empty():
		_layer_3d().add(chunk.meshes_3d)


func set_origin(world_origin: Vector2) -> void:
	origin = world_origin
	clear()
	queue_redraw()
	if _knocked_posts != null:
		_knocked_posts.queue_redraw()


func clear() -> void:
	for chunk in _chunks.values():
		_free_chunk(chunk)
	_chunks.clear()
	_snow_redraws.clear()


## A chunk's buildings into the shared group, farthest from the current view
## centre first. Nearer radial volumes then cover farther ones.
func _add_buildings(chunk: Node) -> void:
	var centre: Vector2 = chunk._bounds_rect.get_center()
	chunk.building_node.set_meta("depth", centre.distance_squared_to(building_view_centre))
	chunk.building_node.set_meta("centre", centre)
	var at := 0
	for other in _buildings.get_children():
		if other.get_meta("depth") > chunk.building_node.get_meta("depth"):
			at += 1
	_buildings.add_child(chunk.building_node)
	_buildings.move_child(chunk.building_node, at)


func set_building_view(view_centre: Vector2) -> void:
	if view_centre.is_equal_approx(building_view_centre):
		return
	building_view_centre = view_centre
	for chunk in _chunks.values():
		chunk.set_building_view(view_centre)
	var ordered := _buildings.get_children()
	for node in ordered:
		node.set_meta("depth", Vector2(node.get_meta("centre")).distance_squared_to(view_centre))
	ordered.sort_custom(func(a, b):
		return Vector2(a.get_meta("centre")).distance_squared_to(view_centre) > Vector2(b.get_meta("centre")).distance_squared_to(view_centre))
	for i in ordered.size():
		_buildings.move_child(ordered[i], i)


## godot-lights-01: how much artificial light shows (Daylight.artificial,
## 0 by day .. 1 at night) and the ambient multiply - continuous, no redraw:
## the pools fade in by their group's alpha, the buildings darken in their
## own material (their composite is unshaded), the windows light up.
var light_level := 0.0


var _ambient := Color.WHITE  # the world's ambient multiply (set_light): the ground's clear colour takes it too


## rrt-018-shadows: the sun for the 3D buildings' shadows (Buildings3D.set_sun).
func set_shadows_enabled(on: bool) -> void:
	shadows_enabled = on
	if buildings_3d != null:
		buildings_3d.set_shadows_enabled(on)


func set_sun(altitude_deg: float, azimuth_deg: float, cloud_cover: float) -> void:
	if MapChunk.buildings_3d:
		_layer_3d().set_sun(altitude_deg, azimuth_deg, cloud_cover)


func set_celestial_light(altitude_deg: float, azimuth_deg: float, strength: float) -> void:
	if MapChunk.buildings_3d:
		_layer_3d().set_celestial_light(altitude_deg, azimuth_deg, strength)


func set_light(level: float, ambient: Color) -> void:
	if not ambient.is_equal_approx(_ambient):
		_ambient = Color(ambient, 1.0)
		if _ground != null:
			_ground.queue_redraw()
	if MapChunk.buildings_3d:
		_layer_3d().set_light(level, ambient)
	if is_equal_approx(level, light_level) and (level > 0.01) == lights_on:
		return
	light_level = level
	if _pool_group != null:
		_pool_group.modulate = Color(1, 1, 1, level)
		_flood_group.modulate = Color(1, 1, 1, level)
	var on := level > 0.01
	if on != lights_on:
		lights_on = on
		if _pool_group != null:
			_pool_group.visible = on and map_level == 0
			_show_floods()
		for chunk in _chunks.values():
			chunk.set_lights_on(on)
	for chunk in _chunks.values():
		chunk.set_darkness(0.25 + 0.25 * level)  # the legacy 2D renderer's windows (--buildings 2d)


## A chunk and its street-light pools (which live in the pool group), gone now.
func _free_chunk(chunk: Node) -> void:
	if chunk.building_node != null and chunk.building_node.get_parent() == _buildings:
		_buildings.remove_child(chunk.building_node)
		chunk.building_node.free()
	for node in chunk.meshes_3d:
		node.free()
	chunk.meshes_3d = []
	chunk.drop_stale_buildings()
	if _pool_group != null and chunk._pools.get_parent() == _pool_group:
		_pool_group.remove_child(chunk._pools)
		chunk._pools.free()  # out of the tree already; the chunk's own cleanup then skips it
	if _flood_group != null and chunk._floods.get_parent() == _flood_group:
		_flood_group.remove_child(chunk._floods)
		chunk._floods.free()
	chunk.queue_free()


func chunk_count() -> int:
	return _chunks.size()


func holiday_yards(view: Rect2, limit := 64) -> PackedVector2Array:
	var result := PackedVector2Array()
	var scanned := 0
	for chunk in _chunks.values():
		if not view.intersects(chunk._bounds_rect):
			continue
		for row in chunk._data.get("holiday_yards", []):
			scanned += 1
			if scanned > 2048:  # shortcut: cap dense-yard queries; index them if this hides visible yards.
				return result
			var at := MapMath.point(origin, row[0], row[1])
			if view.has_point(at):
				result.append(at)
				if result.size() >= limit:
					return result
	return result


func holiday_hiding_spots(view: Rect2, limit := 48) -> PackedVector2Array:
	var result := PackedVector2Array()
	var scanned := 0
	for chunk in _chunks.values():
		if not view.intersects(chunk._bounds_rect):
			continue
		for tree in chunk._data.get("trees", []):
			scanned += 1
			if scanned > 2048:  # shortcut: cap scenery search; index it if dense maps miss visible elves.
				return result
			var at := MapMath.point(origin, tree[0], tree[1])
			if posmod(hash(Vector2i(roundi(tree[0]), roundi(tree[1]))), 5) == 0:
				at += Vector2(2.0, -1.0)
				if view.has_point(at):
					result.append(at)
					if result.size() >= limit:
						return result
		for building in chunk._data.get("buildings", []):
			scanned += 1
			if scanned > 2048:
				return result
			if building.is_empty():
				continue
			var centre := Vector2.ZERO
			for point in building:
				centre += point
			centre /= building.size()
			var key := Vector2i(roundi(centre.x), roundi(centre.y))
			var h := hash(key)
			if posmod(h, 8) != 0:
				continue
			var edge: Vector2 = building[posmod(h / 8, building.size())]
			var at := edge + (edge - centre).normalized() * 2.0
			if view.has_point(at):
				result.append(at)
				if result.size() >= limit:
					return result
	return result


func has_chunk(chunk_id: String) -> bool:
	return _chunks.has(chunk_id)


## Returns false for a chunk already loaded (it isn't rebuilt).
func add_chunk(message: Dictionary) -> bool:
	var chunk_id: String = message["chunk_id"]
	if _chunks.has(chunk_id):
		return false
	var chunk := MapChunk.new()
	chunk.name = "Chunk_" + chunk_id
	chunk._building_view = building_view_centre
	chunk.setup(message, origin)
	if not _snow_baselines.has(chunk_id):
		_snow_baselines[chunk_id] = 0.0 if snowing else road_snow
	chunk.snow_baseline = float(_snow_baselines[chunk_id])
	chunk.set_wetness(wetness)
	chunk.set_road_snow(road_snow, plowed_cells)
	chunk.set_px_per_m(px_per_m)
	chunk.set_phases(phases)
	chunk.set_obstacles(knocked)
	chunk.set_broken_hedges(broken_hedges)
	chunk.set_season(season)
	chunk.set_lights_on(lights_on)
	chunk.set_arena_lights(arena_lights_on)
	chunk.set_flash(flash)
	add_child(chunk)
	if not chunk._data.get("level_roads", []).is_empty() and _underground != null:
		_underground.queue_redraw()
	if not chunk.street_lights.is_empty() and _pool_group != null:
		_pool_group.add_child(chunk._pools)
	if not chunk._data.get("floodlit", []).is_empty() and _flood_group != null:
		_flood_group.add_child(chunk._floods)
	if chunk.building_node != null and _buildings != null:
		_add_buildings(chunk)
	add_building_meshes(chunk)
	_chunks[chunk_id] = chunk
	_snow_redraws.erase(chunk_id)  # its initial draw already uses the latest snow
	return true


func set_px_per_m(value: float) -> void:
	if is_equal_approx(value, px_per_m):
		return
	px_per_m = value
	for chunk in _chunks.values():
		chunk.set_px_per_m(px_per_m)
	if _knocked_posts != null:
		_knocked_posts.queue_redraw()


## The simulation's traffic-light phases this tick; chunks redraw only
## posts whose phase changed. Nothing here computes a phase.
func set_traffic_lights(value: Dictionary) -> void:
	if value == phases:
		return
	phases = value
	for chunk in _chunks.values():
		chunk.set_phases(phases)


func set_broken_hedges(rows: Array) -> void:
	if rows == _last_hedge_damage:
		return
	_last_hedge_damage = rows.duplicate(true)
	broken_hedges = {}
	for row in rows:
		broken_hedges[MapChunk.hedge_key(["hedge", row[1], row[0]])] = row[2]
	for chunk in _chunks.values():
		chunk.set_broken_hedges(broken_hedges)


## The simulation's knocked posts this tick (a list that only grows, so
## usually unchanged): chunks redraw only their own.
func set_obstacles(knocked_posts: Array) -> void:
	if knocked_posts == _last_obstacles:
		return
	_last_obstacles = knocked_posts
	knocked = {}
	for post in knocked_posts:
		knocked[MapChunk.obstacle_key(post[0], post[1])] = post
	for chunk in _chunks.values():
		chunk.set_obstacles(knocked)
	if _knocked_posts != null:
		_knocked_posts.queue_redraw()


## The taxi knocks over the trees it touches (MapChunk.knock_trees, which
## skips chunks far from it): the client's alone. Returns how many fell.
func knock_trees(body: Dictionary) -> int:
	var felled := 0
	for chunk in _chunks.values():
		felled += chunk.knock_trees(body["position"], body["heading"], body["length"], body["width"])
	return felled


## A post hit hard lies bent over the way the taxi went
## (a street lamp 4 m, a bollard 0.9 m).
func _draw_knocked_posts() -> void:
	for post in knocked.values():
		var at := MapMath.point(origin, post[0], post[1])
		var length := 4.0 if post[3] == "street_lamp" else 0.9
		_knocked_posts.draw_line(at, at + Vector2(cos(post[2]), -sin(post[2])) * length, Color8(88, 90, 92), maxf(2.0 / px_per_m, 0.25))


## The server's season weights (state calendar.season): ground, water and
## trees recolour - about once a game day.
func set_season(weights: Array) -> void:
	if weights.size() != 4 or weights == season:
		return
	season = weights
	if buildings_3d != null:
		buildings_3d.set_snow(float(season[0]))
	if _ground != null:
		_ground.queue_redraw()
	for chunk in _chunks.values():
		chunk.set_season(season)


## Whether a working street light is within `radius` of `at` (layer
## coordinates): reflectors and long beams. Only chunks near `at` are looked at.
func lamp_near(at: Vector2, radius: float) -> bool:
	var around := Rect2(at - Vector2(radius, radius), Vector2(radius, radius) * 2.0)
	for chunk in _chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.intersects(around):
			continue
		# Every light sits in its own cell's list (light_cells), so the cells under the circle's box cover it.
		var low := Vector2i((around.position / chunk.LIGHT_CELL_M).floor())
		var high := Vector2i((around.end / chunk.LIGHT_CELL_M).floor())
		for x in range(low.x, high.x + 1):
			for y in range(low.y, high.y + 1):
				for i in chunk.light_cells.get(Vector2i(x, y), []):
					if chunk.street_lights[i].distance_squared_to(at) <= radius * radius and not chunk._broken.has(i):
						return true
	return false


## How much street light falls on a point, 0 (none) .. ~1.5 (several
## lamps): each working lamp within its pool's reach adds (1 - d/reach)²,
## the shape of its pool. For lighting what stands on the street (vehicles).
func light_at(at: Vector2) -> float:
	var total := 0.0
	var around := Rect2(at - Vector2(20, 20), Vector2(40, 40))
	for chunk in _chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.intersects(around):
			continue
		var lights: Array = chunk._data.get("street_lights", [])
		for i in chunk.light_cells.get(Vector2i((at / chunk.LIGHT_CELL_M).floor()), []):
			if chunk._broken.has(i):
				continue
			var reach := float(lights[i][3]) if i < lights.size() and lights[i].size() > 3 else 10.0
			var d: float = chunk.street_lights[i].distance_to(at)
			if d < reach:
				total += (1.0 - d / reach) * (1.0 - d / reach)
		if _flood_group != null and _flood_group.visible:  # under the floodlights: near daylight
			for ring in chunk._data.get("floodlit", []):
				if Geometry2D.is_point_in_polygon(at, ring):
					return FLOODLIGHT_ON_PEOPLE
	return minf(total, 1.5)


const FLOODLIGHT_ON_PEOPLE := 3.0  # light_at in a floodlit field: saturates vehicle_light to near white


## 3D buildings: canopies in view project with the camera, so they redraw each frame.
func canopies_moved(view: Rect2) -> void:
	for chunk in _chunks.values():
		if not chunk._canopy_layers.is_empty() and not chunk._data.get("canopies", []).is_empty() and chunk._bounds_rect.grow(50.0).intersects(view):
			for node in chunk._canopy_layers:
				node.queue_redraw()


## The weather's road wetness 0..1 (state "weather.wetness"). Applied in
## steps of 3/255 overlay alpha, so a slowly
## drying road doesn't touch every chunk every tick.
func set_wetness(value: float) -> bool:
	var stepped := roundf(clampf(value, 0.0, 1.0) * 30.0) / 30.0
	if is_equal_approx(stepped, wetness):
		return false
	wetness = stepped
	for chunk in _chunks.values():
		chunk.set_wetness(wetness)
	return true


func set_road_snow(depth: float, cells: Array, falling := true) -> void:
	snowing = falling
	if depth == road_snow and cells == plowed_cells:
		return
	road_snow = depth
	plowed_cells = cells
	for chunk in _chunks.values():
		var id: String = chunk._data["chunk_id"]
		_snow_baselines[id] = minf(float(_snow_baselines[id]), depth)
		chunk.snow_baseline = float(_snow_baselines[id])
		if chunk.set_road_snow(depth, cells, false) and not chunk._road_layers.is_empty():
			_snow_redraws[id] = true
	set_process(not _snow_redraws.is_empty())


func _process(_delta: float) -> void:
	var remaining := SNOW_REDRAW_CHUNKS_PER_FRAME
	for id in _snow_redraws.keys():
		_snow_redraws.erase(id)
		var chunk = _chunks.get(id)
		if chunk != null:
			chunk.redraw_road_snow()
			remaining -= 1
			if remaining == 0:
				break
	set_process(not _snow_redraws.is_empty())


## A chunk the server resent (changed) swapped in for the drawn one in the
## same frame, so there is no hole; its old buildings stay until the new
## chunk's are built (MapChunk.keep_until_built). A new chunk is just added.
func replace_chunk(message: Dictionary) -> void:
	var old = _chunks.get(message["chunk_id"])
	var keep: Array = []
	if old != null:
		keep = old.stale_buildings + old.meshes_3d
		old.stale_buildings = []
		old.meshes_3d = []
		if old.building_node != null and old.building_node.get_parent() == _buildings:
			keep.append(old.building_node)
			old.building_node = null
		remove_chunk(message["chunk_id"])
	add_chunk(message)
	_chunks[message["chunk_id"]].keep_until_built(keep)


## rrt-019: the loaded chunks' nightclubs ([x, y, weekly open intervals]):
## a chunk's go with it, so nothing to keep in step.
func nightclubs() -> Array:
	var clubs: Array = []
	for chunk in _chunks.values():
		clubs.append_array(chunk._data.get("nightclubs", []))
	return clubs


func remove_chunk(chunk_id: String) -> bool:
	if not _chunks.has(chunk_id):
		return false
	_free_chunk(_chunks[chunk_id])
	_chunks.erase(chunk_id)
	return true


func _draw_ground() -> void:
	# Ground, under the chunks: snow cover with the winter weight (on this
	# light ground other seasonal palettes turned it brown, so only snow).
	# godot-18: the viewport's clear colour, not a full-screen rectangle - one less layer to fill every frame.
	# The world's ambient multiply (CanvasModulate) never reaches the clear
	# colour, so the night is applied here: snow-white open ground glowed in the dark.
	var ground := Color(0.27, 0.33, 0.25).lerp(Color8(230, 236, 240), clampf(season[0], 0.0, 1.0))
	RenderingServer.set_default_clear_color(ground * _ambient)


## The underground view: below
## ground, a dark fill over the surface map and the current level's roads;
## on the surface, the covered (level 0) roads.
func _draw_underground() -> void:
	if map_level != 0:
		_underground.draw_rect(Rect2(-100000, -100000, 200000, 200000), Color8(34, 34, 38))
	for chunk in _chunks.values():
		for road in chunk._data.get("level_roads", []):
			if road[0].any(func(level): return int(level) == map_level):  # JSON numbers are floats
				_underground.draw_polyline(chunk._points(road[1]), MapChunk.Detail._rgb(road[3]), maxf(1.0 / px_per_m, 2.0 * float(road[2])))


## The taxi's map level (state player.map_level): the underground view.
func set_map_level(level: int) -> void:
	if level == map_level:
		return
	map_level = level
	_underground.queue_redraw()
	if _pool_group != null:  # no street lights below ground
		_pool_group.visible = lights_on and map_level == 0
		_show_floods()


## The flashing speed camera, to the chunks (only theirs redraw).
func set_flash(index) -> void:
	if index == flash:
		return
	flash = index
	for chunk in _chunks.values():
		chunk.set_flash(flash)


## Whether `at` (layer coordinates) is under a road on a higher layer than
## `layer`: headlights there
## are hidden by the bridge above.
func covered(at: Vector2, layer: int) -> bool:
	for chunk in _chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.grow(50.0).has_point(at):
			continue
		for road in chunk.elevated_roads():
			if road[0] > layer and road[1].grow(road[2]).has_point(at):
				var points: PackedVector2Array = road[3]
				for i in points.size() - 1:
					if Geometry2D.get_closest_point_to_segment(at, points[i], points[i + 1]).distance_to(at) <= road[2]:
						return true
	return false
