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
const POOL_SHADER := """shader_type canvas_item;
render_mode blend_add;
uniform sampler2D screen_texture : hint_screen_texture, repeat_disable, filter_nearest;
void fragment() {
	COLOR = vec4(textureLod(screen_texture, SCREEN_UV, 0.0).rgb, 1.0);
}"""
var _pool_group: CanvasGroup  # every loaded chunk's street-light pools: painted, then added once


func _make_pool_group() -> void:
	_pool_group = CanvasGroup.new()
	_pool_group.z_index = 21
	# A CanvasGroup's custom material must read the group's own buffer
	# (a CanvasItemMaterial ADD on the group renders it white): the
	# union of the pools, added once.
	var shader := Shader.new()
	shader.code = POOL_SHADER
	var add := ShaderMaterial.new()
	add.shader = shader
	_pool_group.material = add
	_pool_group.visible = false
	add_child(_pool_group)


func _ready() -> void:
	_make_pool_group()
	_knocked_posts = Node2D.new()
	_knocked_posts.z_index = 6
	_knocked_posts.draw.connect(_draw_knocked_posts)
	add_child(_knocked_posts)
var _chunks: Dictionary = {}  # chunk_id -> MapChunk


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


## A chunk and its street-light pools (which live in the pool group), gone now.
func _free_chunk(chunk: Node) -> void:
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
	chunk.setup(message, origin)
	chunk.set_wetness(wetness)
	chunk.set_px_per_m(px_per_m)
	chunk.set_phases(phases)
	chunk.set_obstacles(fallen, knocked)
	chunk.set_season(season)
	chunk.set_lights_on(lights_on)
	add_child(chunk)
	if not chunk.street_lights.is_empty() and _pool_group != null:
		_pool_group.add_child(chunk._pools)
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
	queue_redraw()
	for chunk in _chunks.values():
		chunk.set_season(season)


## Street lights on at night (darkness > 0.25), off by day.
func set_lights_on(on: bool) -> void:
	if on == lights_on:
		return
	lights_on = on
	if _pool_group != null:
		_pool_group.visible = on
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


func _draw() -> void:
	# Ground, under the chunks: snow cover with the winter weight. (Pygame's
	# other seasonal palettes are tuned to its dark grass; on this lighter
	# ground autumn turns brown, so only the snow is taken.)
	draw_rect(Rect2(-100000, -100000, 200000, 200000), Color(0.27, 0.33, 0.25).lerp(Color8(230, 236, 240), clampf(season[0], 0.0, 1.0)))
