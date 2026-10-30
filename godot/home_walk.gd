## Inside a house (rrt-019-in-house-02): the server's floor plan, walked on
## by the client. The simulation only knows the player is indoors (state
## home_door.indoors) - its map player waits at the front door; the walk here
## is presentation and never reaches the map, roads or traffic. E at the front
## door asks the server to go out (main.gd sends home_door); H makes it home.
extends CanvasLayer

const HomeInterior := preload("res://home_interior.gd")
const T := preload("res://i18n.gd")
const RADIUS_M := 0.25  # the walker; a door (0.95 m) leaves 0.15 m either side past the jambs
const WALL_HALF_M := 0.08  # half the drawn wall
const SPEED_M_S := 2.5  # indoor walk; Shift twice that (the street's walk is 4 m/s)
const TURN_RAD_S := 2.6  # physics.py STEER_RATE: the same tank steering as outside
const EXIT_REACH_M := 0.9  # this close to the front door's middle: E goes out
const FIGURE_M := 0.32  # the drawn person (the street's 0.45 m figure, a little slimmer than its shadow reach)
const SPAWN_IN_M := 0.45  # entering, the walker stands this far inside the front door (interior.py STEP_IN_M: clear floor)

var language := "en"
var notice := ""
var is_home := false  # state home_door.is_home: no "H: make this home" hint
var walk_time := 0.0  # seconds walked: the figure's gait
var moving := false
var _figure := preload("res://entity_layer.gd").new()  # draws the player as on the street, never in the tree
var plan: Dictionary = {}
var at := Vector2.ZERO  # plan metres, y up
var heading := 0.0  # radians, as on the map: 0 east, counter-clockwise
var _segments := PackedVector2Array()  # wall segments, pairs
var _furniture: Array[PackedVector2Array] = []
var _outline := PackedVector2Array()
var _canvas: WalkCanvas


func _ready() -> void:
	layer = 5  # over the map, under menus
	visible = false
	_canvas = WalkCanvas.new()
	_canvas.walk = self
	_canvas.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_canvas)


## A new plan (or the same one again after leaving): cached geometry, the walker at the front door.
func enter(value: Dictionary) -> bool:
	if not value.has("footprint") or front_door(value).is_empty():
		return false
	if value != plan:
		plan = value
		_outline = _points(plan["footprint"])
		_segments.clear()
		for wall in plan.get("walls", []):
			var line := _points(wall)
			for i in line.size() - 1:
				_segments.append_array([line[i], line[i + 1]])
		_furniture.clear()
		for item in plan.get("furniture", []):
			_furniture.append(_points(item["points"]))
	var door := front_door(plan)
	at = door["middle"] + door["inward"] * SPAWN_IN_M
	heading = door["inward"].angle()
	visible = true
	if _canvas != null:
		_canvas.queue_redraw()
	return true


func leave() -> void:
	visible = false


func _notification(what: int) -> void:
	if what == NOTIFICATION_PREDELETE and is_instance_valid(_figure):
		_figure.free()


## The plan's front door: {"middle", "inward"} in plan metres, or {} without one.
static func front_door(value: Dictionary) -> Dictionary:
	for door in value.get("doors", []):
		if int(door["rooms"][0]) == -1:
			var a := Vector2(door["points"][0][0], door["points"][0][1])
			var b := Vector2(door["points"][1][0], door["points"][1][1])
			var leaf := Vector2(door["leaf"][0], door["leaf"][1])
			return {"middle": (a + b) / 2.0, "inward": (leaf - a).normalized()}
	return {}


func at_exit() -> bool:
	var door := front_door(plan)
	return not door.is_empty() and at.distance_to(door["middle"]) <= EXIT_REACH_M


## Whether the walker fits at `p`: inside the footprint, clear of walls and furniture.
func fits(p: Vector2) -> bool:
	if not Geometry2D.is_point_in_polygon(p, _outline):
		return false
	var reach := RADIUS_M + WALL_HALF_M
	for i in range(0, _segments.size(), 2):
		if Geometry2D.get_closest_point_to_segment(p, _segments[i], _segments[i + 1]).distance_squared_to(p) < reach * reach:
			return false
	for item in _furniture:
		if Geometry2D.is_point_in_polygon(p, item):
			return false
		for i in item.size():
			var a := item[i]
			if Geometry2D.get_closest_point_to_segment(p, a, item[(i + 1) % item.size()]).distance_squared_to(p) < RADIUS_M * RADIUS_M:
				return false
	return true


## Moves by `motion`, sliding along whatever blocks it; never into a wall.
func move(motion: Vector2) -> void:
	for step in [motion, Vector2(motion.x, 0), Vector2(0, motion.y)]:
		if step != Vector2.ZERO and fits(at + step):
			at += step
			return


func _process(delta: float) -> void:
	if not visible:
		return
	var forward := float(Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP)) - float(Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN))
	var turn := float(Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT)) - float(Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT))
	heading += turn * TURN_RAD_S * delta
	var speed := SPEED_M_S * (2.0 if Input.is_key_pressed(KEY_SHIFT) else 1.0)
	# Short steps: a fast frame can't jump a wall.
	var motion := Vector2(cos(heading), sin(heading)) * forward * speed * minf(delta, 0.1)
	var steps := maxi(1, ceili(motion.length() / 0.05))
	var start := at
	for i in steps:
		move(motion / steps)
	moving = at != start
	if moving:
		walk_time += delta
	_canvas.queue_redraw()


static func _points(values: Array) -> PackedVector2Array:
	var result := PackedVector2Array()
	for p in values:
		result.append(Vector2(float(p[0]), float(p[1])))
	return result


## The floor-plan viewer's drawing, with the walker and the door prompt on top.
class WalkCanvas extends HomeInterior.PlanCanvas:
	var walk

	func _draw() -> void:
		plan = walk.plan
		super._draw()
		if not plan.has("footprint"):
			return
		# The street's player figure, in screen pixels (px_per_m 1), the player's yellow.
		var figure = walk._figure
		figure.px_per_m = 1.0
		figure._canvas = self
		figure._pedestrian(point([walk.at.x, walk.at.y]), walk.heading, {"color": [255, 217, 64], "radius_m": walk.FIGURE_M * _scale,
			"animation_state": "walking" if walk.moving else "standing"}, walk.walk_time)
		figure._canvas = figure
		var font := ThemeDB.fallback_font
		var name := str(plan.get("name", ""))
		draw_string(font, Vector2(24, 40), name, HORIZONTAL_ALIGNMENT_LEFT, -1, 24, Color("ffcd1a"))
		if walk.notice != "":
			draw_string(font, Vector2(24, 66), walk.notice, HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color("ffcd1a"))
		var hint: String = walk.T.text("house_leave_prompt" if walk.at_exit() else "home_walk_hint", walk.language)
		if not walk.is_home:
			hint += " · " + walk.T.text("home_choose_hint", walk.language)
		var width := font.get_string_size(hint, HORIZONTAL_ALIGNMENT_LEFT, -1, 20).x
		draw_rect(Rect2((size.x - width) / 2.0 - 14, size.y - 54, width + 28, 36), Color(0.08, 0.1, 0.13, 0.85))
		draw_string(font, Vector2((size.x - width) / 2.0, size.y - 28), hint, HORIZONTAL_ALIGNMENT_LEFT, -1, 20, Color.WHITE)
