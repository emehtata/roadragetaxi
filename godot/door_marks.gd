## On foot, the front doors of the houses nearby (state home_door.doors, the
## server's choice): a pulsing ring on the door and an arrow pointing in, the
## home's in gold; at the one in reach an E key cap. Screen-pixel sizes,
## unshaded so they show at night. Presentation only.
extends Node2D

const MapMath := preload("res://map_math.gd")
const HOME := Color("ffcd1a")
const HOUSE := Color("dfe9f2")
const REACH_M := 2.5  # home.py DOOR_REACH_M: the nearest door within this gets the E cap

var doors: Array = []  # [map position, outward direction (screen), is home]
var available := false  # E goes in at doors[0]
var px_per_m := 9.0
var _time := 0.0


func _ready() -> void:
	z_index = 25  # over the night layer (20)
	var unshaded := CanvasItemMaterial.new()
	unshaded.light_mode = CanvasItemMaterial.LIGHT_MODE_UNSHADED
	material = unshaded


func show_doors(door_state: Dictionary, origin: Vector2, zoom: float) -> void:
	doors.clear()
	for row in door_state.get("doors", []):
		doors.append([MapMath.point(origin, row[0], row[1]), Vector2(cos(row[2]), -sin(row[2])), bool(row[3])])
	available = bool(door_state.get("available", false)) and not doors.is_empty()
	px_per_m = zoom
	visible = not doors.is_empty()
	queue_redraw()


func _process(delta: float) -> void:
	if visible:
		_time += delta
		queue_redraw()


func _draw() -> void:
	var px := 1.0 / px_per_m  # metres per screen pixel
	var pulse := 0.5 + 0.5 * sin(_time * 4.0)
	for i in doors.size():
		var at: Vector2 = doors[i][0]
		var out: Vector2 = doors[i][1]
		var color: Color = HOME if doors[i][2] else HOUSE
		var near := i == 0 and available
		var ring := (7.0 + pulse * (4.0 if near else 2.0)) * px
		draw_arc(at, ring, 0.0, TAU, 24, Color(color, 0.9 if near else 0.6), 2.5 * px, true)
		draw_circle(at, 2.5 * px, color)
		# An arrow on the doorstep pointing in at the door.
		var tip := at + out * (12.0 + pulse * 3.0) * px
		var tail := tip + out * 12.0 * px
		var side := out.orthogonal() * 5.0 * px
		draw_line(tail, tip, color, 2.5 * px, true)
		draw_colored_polygon(PackedVector2Array([tip - out * 2.0 * px, tip + out * 6.0 * px + side, tip + out * 6.0 * px - side]), color)
		if near:
			_key_cap(at + out * 52.0 * px, px, color)  # past the arrow


## "E" in a key cap, in screen pixels at `at`.
func _key_cap(at: Vector2, px: float, color: Color) -> void:
	draw_set_transform(at, 0.0, Vector2(px, px))
	draw_rect(Rect2(-13, -13, 26, 26), Color(0.08, 0.1, 0.13, 0.9))
	draw_rect(Rect2(-13, -13, 26, 26), color, false, 2.0)
	draw_string(ThemeDB.fallback_font, Vector2(-6, 7), "E", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, color)
	draw_set_transform(Vector2.ZERO)
