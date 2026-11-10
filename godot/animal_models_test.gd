## The CC0 low-poly animal models (docs/specs/animal-models-lowpoly.md), headless:
##   XDG_DATA_HOME=$(mktemp -d) godot --headless --path godot --script res://animal_models_test.gd
## Exits 1 if any check fails.
extends SceneTree

const B3 := preload("res://buildings_3d.gd")
const TARGETS := {"fox": 0.9, "small_bird": 0.3, "roe_deer": 1.2, "horse": 2.0, "hare": 0.5}

var _failures := 0
var _checks := 0


func check(ok: bool, what: String) -> void:
	_checks += 1
	if not ok:
		_failures += 1
		printerr("FAIL: ", what)


static func _box(verts: PackedVector3Array) -> AABB:
	var box := AABB(verts[0], Vector3.ZERO)
	for v in verts:
		box = box.expand(v)
	return box


## Criterion 2: length along +x within 10 %, feet within 1 cm of the ground.
func test_model_aabb_scale() -> void:
	for species: String in TARGETS:
		var arrays := B3.animal_arrays(species, B3.ANIMAL_MODELS[species][3], "stand", 1.0, 1)
		var box := _box(arrays["verts"])
		check(absf(box.size.x / TARGETS[species] - 1.0) <= 0.1, "%s %.3f m long, want %.2f" % [species, box.size.x, TARGETS[species]])
		check(absf(box.position.y) <= 0.01, "%s lowest point at %.3f m" % [species, box.position.y])
		check(box.size.x > box.size.z, "%s longer than wide (%.3f x %.3f)" % [species, box.size.x, box.size.z])


## Criterion 3: the head (the highest quarter of the mesh) is at the +x end.
func test_model_faces_heading() -> void:
	for species: String in TARGETS:
		var verts: PackedVector3Array = B3.animal_arrays(species, Color.WHITE, "stand", 1.0, 1)["verts"]
		var box := _box(verts)
		var sum := 0.0
		var count := 0
		for v in verts:
			if v.y > box.position.y + box.size.y * 0.75:
				sum += v.x
				count += 1
		check(count > 0 and sum / count > 0.0, "%s head at x %.3f, not forward" % [species, sum / maxi(count, 1)])


## Criterion 1: the other species stay procedural; modelled ones use the GLB at detail 0 too (glb-only rule).
func test_unmodelled_species_use_procedural() -> void:
	for species in ["squirrel", "pigeon", "moose", "crow", "duck", "gull", "dog"]:
		check(not B3.ANIMAL_MODELS.has(species), "%s has no model" % species)
		check(B3._model_arrays(species, Color.GRAY, "stand", 1.0).is_empty(), "%s builds no model arrays" % species)
	for species: String in TARGETS:
		var far: Dictionary = B3.animal_arrays(species, Color.GRAY, "stand", 1.0, 0)
		check(B3._model_arrays(species, Color.GRAY, "stand", 1.0)["verts"] == far["verts"], "%s far uses its model" % species)


## Criterion 4 (glb-only rule): a ridden horse is the GLB horse too.
func test_horse_saddle_height() -> void:
	var model: PackedVector3Array = B3.animal_arrays("horse", Color8(139, 91, 57), "stand", 1.0, 1)["verts"]
	var rider: PackedVector3Array = B3.person_arrays(Color.GRAY, "riding", 1.0, "")["verts"]
	check(model == B3._model_arrays("horse", Color8(139, 91, 57), "stand", 1.0)["verts"], "an unmounted horse uses the model")
	check(rider.slice(0, model.size()) == model, "the rider's mount is the GLB horse")


## Criterion 7: a missing GLB: procedural shape, a warning, no error.
func test_missing_glb_falls_back() -> void:
	var real: Array = B3.ANIMAL_MODELS["fox"]
	B3.ANIMAL_MODELS["fox"] = ["res://assets/animals/no_such_fox.glb"] + real.slice(1)
	B3._animal_models.erase("fox")
	check(B3._model_arrays("fox", Color.GRAY, "stand", 1.0).is_empty(), "missing fox GLB builds no model")
	var arrays := B3.animal_arrays("fox", Color.GRAY, "stand", 1.0, 1)
	check(arrays["verts"].size() > 0, "missing fox GLB still draws the procedural fox")
	B3.ANIMAL_MODELS["fox"] = real
	B3._animal_models.erase("fox")


## Criterion 5: N same-key animals are one batch with N instances.
func test_rows_batched_per_key() -> void:
	var layer: Node2D = B3.new()
	layer._cars_root = Node3D.new()
	root.add_child(layer._cars_root)
	for i in 6:
		layer.animal(Vector2(i, 0.0), 0.0, "fox", Color.GRAY, "stand")
	layer.animal(Vector2(0.0, 2.0), 0.0, "horse", Color.GRAY, "stand")
	check(layer._animal_rows.size() == 2, "7 animals of 2 looks: %d row groups" % layer._animal_rows.size())
	if not B3._shared.has("organic"):  # set by the outdoor view's start-up
		B3._shared["organic"] = ShaderMaterial.new()
	layer._flush_animals()
	check(layer._animal_batches.size() == 2 and layer._cars_root.get_child_count() == 2, "2 batches, %d nodes" % layer._cars_root.get_child_count())
	var fox_key: String = layer._animal_rows.keys()[0]
	check(layer._animal_batches[fox_key].multimesh.visible_instance_count == 6, "6 foxes in one batch")
	layer._cars_root.free()
	layer.free()


func _initialize() -> void:
	for test in ["test_model_aabb_scale", "test_model_faces_heading", "test_unmodelled_species_use_procedural",
			"test_horse_saddle_height", "test_missing_glb_falls_back", "test_rows_batched_per_key"]:
		call(test)
	print("animal_models_test: %d checks, %d failed" % [_checks, _failures])
	quit(1 if _failures > 0 else 0)
