## Cabins (category 5) keep house windows on plank walls; piers build a deck on posts.
## godot --headless --path godot --script res://tests/wood_and_piers.gd
extends SceneTree

const B3 := preload("res://buildings_3d.gd")

var failed := false

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, message: String) -> void:
	if not ok:
		printerr("FAIL: ", message)
		failed = true

func test_wood_category_keeps_house_windows() -> void:
	var box := PackedVector2Array([Vector2(0, 0), Vector2(20, 0), Vector2(20, 10), Vector2(0, 10)])
	var house := B3.build([box], [[[83, 86, 87], 0, 3.0, [], [139, 60, 50], 1, 1]], Vector2.ZERO)
	var cabin := B3.build([box], [[[83, 86, 87], 0, 3.0, [], [139, 60, 50], 1, B3.CATEGORY_WOOD_HOUSE]], Vector2.ZERO)
	check(cabin["stats"]["windows"] == house["stats"]["windows"] and house["stats"]["windows"] > 0, "a cabin has a house's windows")
	var categories := []
	for i in range(0, cabin["window"].size(), 4):
		if cabin["window"][i + 2] >= 1.0:  # a wall (roofs carry 0)
			categories.append(int(fmod(cabin["window"][i + 2], 10000.0) / 1000.0))
	check(not categories.is_empty() and categories.all(func(c): return c == B3.CATEGORY_WOOD_HOUSE), "its walls tell the shader to draw planks")
	check(load("res://building_snow.gdshader").code.contains("CATEGORY_WOOD_HOUSE"), "the wall shader draws the plank grain")

func test_pier_produces_deck_and_posts() -> void:
	var out := {"deck": PackedVector3Array(), "deck_colors": PackedColorArray()}
	B3._pier(out, PackedVector2Array([Vector2(0, 0), Vector2(30, 0), Vector2(30, -3), Vector2(0, -3)]), Vector2.ZERO)
	var ys: Array = Array(out["deck"]).map(func(v): return v.y)
	check(not ys.is_empty() and is_equal_approx(ys.max(), B3.PIER_DECK_M) and ys.min() < 0.0, "a deck 1 m up on posts into the water")
	check(int(out.get("pier_posts", 0)) >= 20 and int(out.get("pier_posts", 0)) <= 23, "posts every 3 m along a 66 m outline")

func run() -> void:
	test_wood_category_keeps_house_windows()
	test_pier_produces_deck_and_posts()
	print("WOOD_AND_PIERS ", "FAIL" if failed else "OK")
	quit(1 if failed else 0)
