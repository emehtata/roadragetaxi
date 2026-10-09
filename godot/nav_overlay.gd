## Screen-space navigation aids from render/navigation.py: the arrow at
## the screen edge pointing to an off-screen pickup / drop-off with its
## distance (draw_taxi_target), and the compass (draw_compass, C toggles,
## off by default as in Pygame). The target itself comes from the
## simulation's state (EntityLayer.current_target); nothing is routed here.
extends Control

const EDGE_MARGIN := 130.0
const RS := preload("res://render_style.gd")
const T := preload("res://i18n.gd")

var show_compass := false
var show_route := false  # N (render/navigation.py draw_navigation_route), off by default: drawn by EntityLayer
var _font: Font
var _target: Dictionary = {}
var _target_screen := Vector2.ZERO  # target position on screen
var _camera_world := Vector2.ZERO  # world metres at the screen centre
var _heading := 0.0
var language := "en"


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_font = ThemeDB.fallback_font


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_C:
		show_compass = not show_compass
		queue_redraw()
	elif event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_N:
		show_route = not show_route  # presentation only: the server plans the route either way


## Called each frame by main.gd: the target, where it is on screen, where
## the camera is in the world, and the taxi's heading.
func update_view(target: Dictionary, target_screen: Vector2, camera_world: Vector2, heading: float) -> void:
	_target = target
	_target_screen = target_screen
	_camera_world = camera_world
	_heading = heading
	if not target.is_empty() or show_compass:
		queue_redraw()


## Where the edge arrow goes for a target in direction `angle` (world
## radians, counter-clockwise from east) on a screen of `screen_size`.
static func edge_point(angle: float, screen_size: Vector2, margin := EDGE_MARGIN) -> Vector2:
	var direction := Vector2(cos(angle), -sin(angle))
	var half := screen_size / 2.0 - Vector2(margin, margin)
	var scale_x := absf(half.x / direction.x) if direction.x != 0.0 else INF
	var scale_y := absf(half.y / direction.y) if direction.y != 0.0 else INF
	return screen_size / 2.0 + direction * minf(scale_x, scale_y)


static func distance_text(metres: float) -> String:
	return "%dm" % roundi(metres) if metres < 1000.0 else "%.1fkm" % (metres / 1000.0)


## True when the target is far enough inside the screen to be drawn in the world.
static func on_screen(point: Vector2, screen_size: Vector2) -> bool:
	return point.x >= 30.0 and point.x <= screen_size.x - 30.0 and point.y >= 30.0 and point.y <= screen_size.y - 30.0


func _draw() -> void:
	if not _target.is_empty() and not on_screen(_target_screen, size):
		var color := RS.PICKUP if _target["is_pickup"] else RS.DROPOFF
		var delta := Vector2(_target["x"], _target["y"]) - _camera_world
		var angle := atan2(delta.y, delta.x)
		var at := edge_point(angle, size)
		var tip := at + Vector2(cos(angle), -sin(angle)) * 16.0
		var left := at + Vector2(cos(angle + 2.5), -sin(angle + 2.5)) * 11.2
		var right := at + Vector2(cos(angle - 2.5), -sin(angle - 2.5)) * 11.2
		var arrow := PackedVector2Array([tip, left, right])
		draw_colored_polygon(arrow, color)
		draw_polyline(PackedVector2Array([tip, left, right, tip]), RS.OUTLINE, 1.0)
		var text := "%s %s" % [T.text("pickup", language, "PICKUP") if _target["is_pickup"] else T.text("dropoff", language, "DROPOFF"), distance_text(delta.length())]
		var text_size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14)
		var label_y := at.y + 18.0 if at.y < size.y - 40.0 else at.y - 18.0
		var box := Rect2(Vector2(at.x - text_size.x / 2.0 - 3.0, label_y - text_size.y / 2.0 - 2.0), text_size + Vector2(6, 4))
		draw_rect(box, Color8(15, 15, 15, 210))
		draw_string(_font, box.position + Vector2(3, text_size.y - 2), text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color.WHITE)
	if show_compass:
		_draw_compass(Vector2(size.x - 64.0, 145.0), 28.0)


func _draw_compass(c: Vector2, r: float) -> void:
	draw_circle(c, r, Color8(40, 40, 40))
	draw_arc(c, r, 0.0, TAU, 32, Color8(200, 200, 200), 2.0)
	draw_string(_font, c + Vector2(-5, -r + 16), "N", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color8(240, 240, 240))
	if not _target.is_empty():
		var delta := Vector2(_target["x"], _target["y"]) - _camera_world
		var t_ang := atan2(delta.y, delta.x)
		var tip := c + Vector2(cos(t_ang), -sin(t_ang)) * (r - 4.0)
		draw_colored_polygon(PackedVector2Array([tip, tip + Vector2(cos(t_ang + 2.5), -sin(t_ang + 2.5)) * 8.0,
			tip + Vector2(cos(t_ang - 2.5), -sin(t_ang - 2.5)) * 8.0]), Color8(255, 215, 0))
	var needle := c + Vector2(cos(_heading), -sin(_heading)) * (r - 8.0)
	draw_line(c, needle, Color8(220, 40, 40), 3.0)
	draw_colored_polygon(PackedVector2Array([needle, needle + Vector2(cos(_heading + 2.4), -sin(_heading + 2.4)) * 6.0,
		needle + Vector2(cos(_heading - 2.4), -sin(_heading - 2.4)) * 6.0]), Color8(220, 40, 40))
	var bearing := fposmod(90.0 - rad_to_deg(_heading), 360.0)
	draw_string(_font, c + Vector2(-14, r - 6), "%03d°" % int(bearing), HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color8(240, 240, 240))
