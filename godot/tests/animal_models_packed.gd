## Animal GLBs are preloaded PackedScenes, so an export always packs them (no load(path) by string).
extends SceneTree

const Buildings3D := preload("res://buildings_3d.gd")


func _initialize() -> void:
	var failures := 0
	for species in Buildings3D.ANIMAL_MODELS:
		if not Buildings3D.ANIMAL_MODELS[species][0] is PackedScene:
			failures += 1
			printerr("FAIL: %s model is not a preloaded PackedScene" % species)
		elif Buildings3D._animal_model(species).is_empty():
			failures += 1
			printerr("FAIL: %s model is empty" % species)
	quit(1 if failures else 0)
