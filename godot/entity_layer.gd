## Moving things from "state" messages, redrawn every frame from the
## interpolation buffer (StateBuffer): positions and headings are blended
## between the two states around the render time; everything discrete (an
## entity appearing, its colour, a train's cars) comes from the earlier one.
extends Node2D

var origin := Vector2.ZERO
var buffer := StateBuffer.new()
var drawn_entities := 0  # last frame (performance readout)
var interp_usec := 0  # time spent sampling and blending last frame

var _frame: Dictionary = {}  # this frame's sample: {"a", "b", "t"}


func now() -> float:
	return Time.get_ticks_usec() / 1000000.0


## The state the picture currently shows (discrete values: HUD, sound).
func shown_state() -> Dictionary:
	return _frame.get("a", {})


## The player's interpolated position (the camera follows it).
func player_position() -> Vector2:
	if _frame.is_empty():
		return Vector2.ZERO
	var key := "player_pedestrian" if _frame["a"].get("on_foot", false) else "player"
	var p := StateBuffer.blend(_frame["a"][key], _frame["b"].get(key, _frame["a"][key]), _frame["t"])
	return MapMath.point(origin, p.x, p.y)


func _process(_delta: float) -> void:
	_frame = buffer.sample(now())
	queue_redraw()


func _by_id(items: Array) -> Dictionary:
	var found := {}
	for item in items:
		found[item["id"]] = item
	return found


func _draw_box(x: float, y: float, heading: float, length: float, width: float, color: Color) -> void:
	draw_set_transform(MapMath.point(origin, x, y), -heading)
	draw_rect(Rect2(-length / 2, -width / 2, length, width), color)
	draw_set_transform(Vector2.ZERO)


func _rgb(values: Array) -> Color:
	return Color(values[0] / 255.0, values[1] / 255.0, values[2] / 255.0)


func _draw() -> void:
	if _frame.is_empty():
		return
	var started := Time.get_ticks_usec()
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var count := 0
	var later_trains := _by_id(b.get("trains", []))
	for train in a.get("trains", []):
		var next: Dictionary = later_trains.get(train["id"], train)
		var same_cars: bool = next["cars"].size() == train["cars"].size()
		for i in train["cars"].size():
			var car: Array = train["cars"][i]
			var to: Array = next["cars"][i] if same_cars else car
			_draw_box(lerpf(car[0], to[0], t), lerpf(car[1], to[1], t), lerp_angle(car[2], to[2], t), car[3] - 0.6, 3.2,
				Color(0.05, 0.19, 0.09) if car[4] == "locomotive" else Color(0.15, 0.5, 0.25))
		count += 1
	var later_npcs := _by_id(b.get("npcs", []))
	for npc in a.get("npcs", []):
		var p := StateBuffer.blend(npc, later_npcs.get(npc["id"], npc), t)
		_draw_box(p.x, p.y, p.z, npc["length_m"], npc["width_m"], _rgb(npc["color"]))
		count += 1
	var later_peds := _by_id(b.get("pedestrians", []))
	for ped in a.get("pedestrians", []):
		var p := StateBuffer.blend(ped, later_peds.get(ped["id"], ped), t)
		draw_circle(MapMath.point(origin, p.x, p.y), ped["radius_m"], _rgb(ped["color"]))
		count += 1
	var taxi := StateBuffer.blend(a["player"], b.get("player", a["player"]), t)
	_draw_box(taxi.x, taxi.y, taxi.z, 4.4, 1.8, Color(1.0, 0.8, 0.1))
	count += 1
	if a.get("on_foot", false):
		draw_circle(player_position(), 0.55, Color(1.0, 0.85, 0.25))
		count += 1
	drawn_entities = count
	interp_usec = Time.get_ticks_usec() - started
