## The static map, streamed in chunks ("chunk" / "chunk_unload" messages;
## Python decides which). Each chunk is one child canvas item drawn once
## when it arrives, so loading or dropping one never redraws the others.
## Coordinates are metres relative to `origin` (world y north -> Godot y
## down), so large map coordinates don't lose float precision.
extends Node2D

const MapChunk := preload("res://map_chunk.gd")

var origin := Vector2.ZERO
var wetness := 0.0  # road wetness as last applied (bucketed, see set_wetness)
var _chunks: Dictionary = {}  # chunk_id -> MapChunk


func set_origin(world_origin: Vector2) -> void:
	origin = world_origin
	clear()
	queue_redraw()


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
	add_child(chunk)
	_chunks[chunk_id] = chunk
	return true


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
