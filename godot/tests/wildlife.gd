extends SceneTree


func _initialize() -> void:
	var WildlifeLayer := preload("res://wildlife.gd")
	assert(WildlifeLayer.SPECIES == [&"squirrel", &"small_bird", &"pigeon", &"hare", &"fox", &"moose", &"roe_deer", &"crow"])
	assert(WildlifeLayer._speed("crow", "FLY") == 7.0)
	var layer: Node = WildlifeLayer.new()
	root.add_child(layer)
	assert(layer.config_valid(layer.species_weights))
	assert(not layer.habitat_weights("urban").has("moose") and not layer.habitat_weights("urban").has("roe_deer"))
	assert(layer.habitat_weights("rural").has("moose") and layer.habitat_weights("suburban").has("hare"))
	assert(layer.activity("small_bird", 12 * 3600) > layer.activity("small_bird", 0))
	assert(layer.activity("fox", 0) > layer.activity("fox", 12 * 3600))
	assert(layer.activity("moose", 6 * 3600) > layer.activity("moose", 12 * 3600))
	var chunk := {"chunk_id": "1_2", "bounds": [0.0, 0.0, 500.0, 500.0], "buildings": [], "trees": [[250.0, 250.0, "birch", 0.5]]}
	layer.density = 2.0
	layer.max_active = 3
	preload("res://map_chunk.gd").prepare(chunk, Vector2.ZERO)  # the same worker preparation used for streamed chunks
	layer.replace_chunk(chunk, Vector2.ZERO)
	assert(layer.animals.size() == 2 and layer._chunks.size() == 1)
	assert(layer.animals.filter(func(animal): return animal.species != "pigeon").all(func(animal): return animal.position.distance_to(Vector2(250, -250)) <= 14.1), "woodland wildlife spawns by streamed trees")
	var ids: Array = layer.animals.map(func(animal): return animal.id)
	layer.replace_chunk(chunk, Vector2.ZERO)
	assert(layer.animals.size() == 2 and layer.animals.map(func(animal): return animal.id) == ids, "a chunk refresh cannot duplicate or teleport animals")
	layer.replace_chunk(chunk.merged({"chunk_id": "2_2"}, true), Vector2.ZERO)
	assert(layer.animals.size() == 3, "the wildlife-only population cap is enforced")
	for animal in layer.animals:
		assert(animal.state in WildlifeLayer.VALID_STATES)
	var before: Vector2 = layer.animals[0].position
	layer.animals[0].state = "WANDER"
	layer.animals[0].timer = 10.0
	layer.update(0.5, 12 * 3600, before)
	var coarse: Vector2 = layer.animals[0].position
	layer.animals[0].position = before
	layer._accumulator = 0.0
	for unused in 5:
		layer.update(0.1, 12 * 3600, before)
	assert(layer.animals[0].position.is_equal_approx(coarse), "fixed-step movement is frame-rate independent")
	layer.remove_chunk("1_2")
	assert(layer.animals.size() == 1 and not layer._chunks.has("1_2"))
	layer.clear()
	assert(layer.animals.is_empty() and layer._chunks.is_empty())
	var rng := RandomNumberGenerator.new()
	rng.seed = 19
	for id in 48:
		layer.animals.append(layer._animal(id, WildlifeLayer.SPECIES[id % WildlifeLayer.SPECIES.size()], Rect2(-100, -100, 200, 200), rng))
	var started := Time.get_ticks_usec()
	for unused in 1000:
		layer.update(0.1, 12 * 3600, Vector2.ZERO)
	print("Wildlife benchmark: 48 animals x 1000 fixed updates = %.2f ms" % ((Time.get_ticks_usec() - started) / 1000.0))
	print("Wildlife tests passed")
	quit()
