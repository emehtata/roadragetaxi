## The static map, streamed in chunks ("chunk" / "chunk_unload" messages;
## Python decides which). Each chunk is one child canvas item drawn once
## when it arrives, so loading or dropping one never redraws the others.
## Coordinates are metres relative to `origin` (world y north -> Godot y
## down), so large map coordinates don't lose float precision.
extends Node2D

const MapChunk := preload("res://map_chunk.gd")

var origin := Vector2.ZERO
var wetness := 0.0  # road wetness as last applied (bucketed, see set_wetness)
var px_per_m := 9.0  # the camera zoom, for the chunks' pixel-sized points
var phases: Dictionary = {}  # traffic-light phases as last applied (state "traffic_lights")
var fallen: Dictionary = {}  # felled trees: MapChunk.obstacle_key -> angle (state "fallen_trees")
var knocked: Dictionary = {}  # knocked posts: key -> [x, y, angle, kind] (state "knocked_posts")
var _knocked_posts: Node2D  # drawn here, from the state: a lamp has no static data (made in _ready)
var _last_obstacles := [[], []]
var season := [0.0, 0.0, 1.0, 0.0]  # [winter, spring, summer, autumn] as last applied
var lights_on := false
var _pool_group: Node2D  # every loaded chunk's street-light pools (each chunk's: their union, added once)
var building_view_centre := Vector2.ZERO


func _make_pool_group() -> void:
	# godot-18: a plain container; each chunk draws the union of its pools
	# additively. It was a CanvasGroup (paint, then add the union once):
	# its screen-sized copy cost ~19 ms a frame at night on llvmpipe.
	_pool_group = Node2D.new()
	_pool_group.z_index = 21
	_pool_group.visible = false
	add_child(_pool_group)


func _ready() -> void:
	_ground = Node2D.new()  # under everything, the landuse (z -1) included
	_ground.z_index = -2
	_ground.draw.connect(_draw_ground)
	add_child(_ground)
	_buildings = Node2D.new()
	_buildings.z_index = 7
	add_child(_buildings)
	_underground = Node2D.new()  # level roads (and the dark below ground), over the surface map
	_underground.z_index = 9
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


## Night windows follow the server's darkness (no redraw).
func set_darkness(darkness: float) -> void:
	for chunk in _chunks.values():
		chunk.set_darkness(darkness)


## A chunk and its street-light pools (which live in the pool group), gone now.
func _free_chunk(chunk: Node) -> void:
	if chunk.building_node != null and chunk.building_node.get_parent() == _buildings:
		_buildings.remove_child(chunk.building_node)
		chunk.building_node.free()
	if _pool_group != null and chunk._pools.get_parent() == _pool_group:
		_pool_group.remove_child(chunk._pools)
		chunk._pools.free()  # out of the tree already; the chunk's own cleanup then skips it
	chunk.queue_free()


func chunk_count() -> int:
	return _chunks.size()


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
	chunk.set_wetness(wetness)
	chunk.set_px_per_m(px_per_m)
	chunk.set_phases(phases)
	chunk.set_obstacles(fallen, knocked)
	chunk.set_season(season)
	chunk.set_lights_on(lights_on)
	chunk.set_flash(flash)
	add_child(chunk)
	if not chunk._data.get("level_roads", []).is_empty() and _underground != null:
		_underground.queue_redraw()
	if not chunk.street_lights.is_empty() and _pool_group != null:
		_pool_group.add_child(chunk._pools)
	if chunk.building_node != null and _buildings != null:
		_add_buildings(chunk)
	_chunks[chunk_id] = chunk
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


## The simulation's felled trees and knocked posts this tick (lists that
## only grow, so usually unchanged): chunks redraw only their own.
func set_obstacles(fallen_trees: Array, knocked_posts: Array) -> void:
	if fallen_trees == _last_obstacles[0] and knocked_posts == _last_obstacles[1]:
		return
	_last_obstacles = [fallen_trees, knocked_posts]
	fallen = {}
	for tree in fallen_trees:
		fallen[MapChunk.obstacle_key(tree[0], tree[1])] = float(tree[2])
	knocked = {}
	for post in knocked_posts:
		knocked[MapChunk.obstacle_key(post[0], post[1])] = post
	for chunk in _chunks.values():
		chunk.set_obstacles(fallen, knocked)
	if _knocked_posts != null:
		_knocked_posts.queue_redraw()


## render/scenery.py: a post hit hard lies bent over the way the taxi went
## (a street lamp 4 m, a bollard 0.9 m).
func _draw_knocked_posts() -> void:
	for post in knocked.values():
		var at := MapMath.point(origin, post[0], post[1])
		var length := 4.0 if post[3] == "street_lamp" else 0.9
		_knocked_posts.draw_line(at, at + Vector2(cos(post[2]), -sin(post[2])) * length, Color8(88, 90, 92), maxf(2.0 / px_per_m, 0.25))


## How many drivable roads reach into `view` (layer coordinates), each
## counted once though it is in several chunks - Pygame's visible_road_count,
## which darkens empty country at night. Only chunks overlapping the view
## are looked at.
func count_drivable_roads(view: Rect2) -> int:
	var seen := {}
	for chunk in _chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.intersects(view):
			continue
		for road in chunk.drivable_roads:
			if road[0].intersects(view, true):
				seen[road[1]] = true
	return seen.size()


## The server's season weights (state calendar.season): ground, water and
## trees recolour - about once a game day.
func set_season(weights: Array) -> void:
	if weights.size() != 4 or weights == season:
		return
	season = weights
	if _ground != null:
		_ground.queue_redraw()
	for chunk in _chunks.values():
		chunk.set_season(season)


## Street lights on at night (darkness > 0.25), off by day.
func set_lights_on(on: bool) -> void:
	if on == lights_on:
		return
	lights_on = on
	if _pool_group != null:
		_pool_group.visible = on and map_level == 0
	for chunk in _chunks.values():
		chunk.set_lights_on(on)


## Whether a working street light is within `radius` of `at` (layer
## coordinates): reflectors and long beams. Only chunks near `at` are looked at.
func lamp_near(at: Vector2, radius: float) -> bool:
	var around := Rect2(at - Vector2(radius, radius), Vector2(radius, radius) * 2.0)
	for chunk in _chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.intersects(around):
			continue
		for i in chunk.street_lights.size():
			if chunk.street_lights[i].distance_squared_to(at) <= radius * radius and not chunk._broken.has(i):
				return true
	return false


## Building outlines reaching into `area` (layer coordinates), for the beams.
func buildings_in(area: Rect2) -> Array:
	var found: Array = []
	for chunk in _chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.grow(200.0).intersects(area):
			continue  # (a building is in each chunk it touches: 200 m covers one reaching in)
		for building in chunk.building_shapes():
			if building[0].intersects(area) and not found.any(func(f): return f[1] == building[1]):
				found.append(building)
	return found


## The weather's road wetness 0..1 (state "weather.wetness"). Applied in
## steps of 3/255 overlay alpha, as Pygame's wet-road cache does, so a slowly
## drying road doesn't touch every chunk every tick.
func set_wetness(value: float) -> bool:
	var stepped := roundf(clampf(value, 0.0, 1.0) * 30.0) / 30.0
	if is_equal_approx(stepped, wetness):
		return false
	wetness = stepped
	for chunk in _chunks.values():
		chunk.set_wetness(wetness)
	return true


func remove_chunk(chunk_id: String) -> bool:
	if not _chunks.has(chunk_id):
		return false
	_free_chunk(_chunks[chunk_id])
	_chunks.erase(chunk_id)
	return true


func _draw_ground() -> void:
	# Ground, under the chunks: snow cover with the winter weight. (Pygame's
	# other seasonal palettes are tuned to its dark grass; on this lighter
	# ground autumn turns brown, so only the snow is taken.)
	# godot-18: the viewport's clear colour, not a full-screen rectangle - one less layer to fill every frame.
	RenderingServer.set_default_clear_color(Color(0.27, 0.33, 0.25).lerp(Color8(230, 236, 240), clampf(season[0], 0.0, 1.0)))


## render/roads.py draw_level_ways and main()'s underground view: below
## ground, a dark fill over the surface map and the current level's roads;
## on the surface, the covered (level 0) roads Pygame draws there.
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


## The flashing speed camera, to the chunks (only theirs redraw).
func set_flash(index) -> void:
	if index == flash:
		return
	flash = index
	for chunk in _chunks.values():
		chunk.set_flash(flash)


## Whether `at` (layer coordinates) is under a road on a higher layer than
## `layer` (render/common.py _covered_by_higher_road): headlights there
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
