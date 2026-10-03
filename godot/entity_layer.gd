## Moving things from "state" messages, redrawn every frame. The simulation
## sends ~30 states/s; between two of them positions are blended
## (interpolation only - no prediction, Python stays authoritative).
extends Node2D

var origin := Vector2.ZERO
var _prev: Dictionary = {}
var _curr: Dictionary = {}
var _curr_at := 0.0
var _interval := 1.0 / 30.0


func push_state(state: Dictionary) -> void:
	var now := Time.get_ticks_msec() / 1000.0
	if not _curr.is_empty():
		_interval = clamp(now - _curr_at, 0.005, 0.5)
	_prev = _curr
	_curr = state
	_curr_at = now


func alpha() -> float:
	return clamp((Time.get_ticks_msec() / 1000.0 - _curr_at) / _interval, 0.0, 1.0)


## The player's interpolated position (the camera follows it).
func player_position() -> Vector2:
	if _curr.is_empty():
		return Vector2.ZERO
	var key := "player_pedestrian" if _curr.get("on_foot", false) else "player"
	var a: Dictionary = _curr[key]
	var b: Dictionary = _prev.get(key, a) if not _prev.is_empty() else a
	return MapMath.point(origin, lerp(b["x"], a["x"], alpha()), lerp(b["y"], a["y"], alpha()))


func _process(_delta: float) -> void:
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


func _draw() -> void:
	if _curr.is_empty():
		return
	var t := alpha()
	for train in _curr.get("trains", []):
		for car in train["cars"]:
			var look: String = car[4]
			_draw_box(car[0], car[1], car[2], car[3] - 0.6, 3.2, Color(0.05, 0.19, 0.09) if look == "locomotive" else Color(0.15, 0.5, 0.25))
	var previous := _by_id(_prev.get("npcs", []))
	for npc in _curr.get("npcs", []):
		var old: Dictionary = previous.get(npc["id"], npc)
		var color := Color(npc["color"][0] / 255.0, npc["color"][1] / 255.0, npc["color"][2] / 255.0)
		_draw_box(lerp(old["x"], npc["x"], t), lerp(old["y"], npc["y"], t), lerp_angle(old["heading"], npc["heading"], t),
			npc["length_m"], npc["width_m"], color)
	var previous_peds := _by_id(_prev.get("pedestrians", []))
	for ped in _curr.get("pedestrians", []):
		var old: Dictionary = previous_peds.get(ped["id"], ped)
		draw_circle(MapMath.point(origin, lerp(old["x"], ped["x"], t), lerp(old["y"], ped["y"], t)), ped["radius_m"],
			Color(ped["color"][0] / 255.0, ped["color"][1] / 255.0, ped["color"][2] / 255.0))
	var p: Dictionary = _curr["player"]
	var q: Dictionary = _prev.get("player", p) if not _prev.is_empty() else p
	_draw_box(lerp(q["x"], p["x"], t), lerp(q["y"], p["y"], t), lerp_angle(q["heading"], p["heading"], t), 4.4, 1.8, Color(1.0, 0.8, 0.1))
	if _curr.get("on_foot", false):
		draw_circle(player_position(), 0.55, Color(1.0, 0.85, 0.25))
