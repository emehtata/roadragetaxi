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
var _knocked_posts := Node2D.new()  # drawn here, from the state: a lamp has no static data
var _last_obstacles := [[], []]


func _ready() -> void:
	_knocked_posts.z_index = 6
	_knocked_posts.draw.connect(_draw_knocked_posts)
	add_child(_knocked_posts)
var _chunks: Dictionary = {}  # chunk_id -> MapChunk


func set_origin(world_origin: Vector2) -> void:
	origin = world_origin
	clear()
	queue_redraw()
	_knocked_posts.queue_redraw()


func clear() -> void:
	for chunk in _chunks.values():
		chunk.queue_free()
	_chunks.clear()


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
	add_child(chunk)
	_chunks[chunk_id] = chunk
	return true


func set_px_per_m(value: float) -> void:
	if is_equal_approx(value, px_per_m):
		return
	px_per_m = value
	for chunk in _chunks.values():
		chunk.set_px_per_m(px_per_m)
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
	_chunks[chunk_id].queue_free()
	_chunks.erase(chunk_id)
	return true


func _draw() -> void:
	draw_rect(Rect2(-100000, -100000, 200000, 200000), Color(0.27, 0.33, 0.25))  # ground, under the chunks
