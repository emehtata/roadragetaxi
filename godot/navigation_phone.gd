## Compact mounted phone: presentation of the server's next-turn instruction.
extends PanelContainer

const T := preload("res://i18n.gd")
var language := "en"
var _arrow: Control
var _distance: Label
var _street: Label
var _maneuver := "no_target"


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	position = Vector2(16, 125)
	custom_minimum_size = Vector2(210, 240)
	var body := StyleBoxFlat.new()
	body.bg_color = Color8(14, 16, 20)
	body.border_color = Color8(70, 78, 88)
	body.set_border_width_all(3)
	body.set_corner_radius_all(22)
	body.set_content_margin_all(16)
	add_theme_stylebox_override("panel", body)
	var box := VBoxContainer.new()
	box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(box)
	var speaker := Label.new()
	speaker.text = "━━"
	speaker.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	speaker.add_theme_color_override("font_color", Color8(80, 90, 100))
	box.add_child(speaker)
	_arrow = Control.new()
	_arrow.custom_minimum_size = Vector2(170, 90)
	_arrow.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_arrow.draw.connect(_draw_arrow)
	box.add_child(_arrow)
	_distance = Label.new()
	_distance.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_distance.add_theme_font_size_override("font_size", 27)
	box.add_child(_distance)
	_street = Label.new()
	_street.custom_minimum_size.x = 170
	_street.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_street.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(_street)
	hide()


func show_navigation(navigation: Dictionary, enabled: bool, full_phone_open: bool) -> void:
	visible = enabled and not full_phone_open
	if not visible:
		return
	var instruction: Dictionary = navigation.get("instruction", {})
	var maneuver := str(instruction.get("maneuver", "no_target"))
	if maneuver != _maneuver:
		_maneuver = maneuver
		_arrow.queue_redraw()
	var distance := float(instruction.get("distance_m", 0.0))
	_distance.text = ("%d m" % roundi(distance) if distance < 1000 else "%.1f km" % (distance / 1000)) if instruction.has("distance_m") else ""
	var street := str(instruction.get("street", ""))
	_street.text = street if street != "" else T.text("nav_" + maneuver, language)
	tooltip_text = T.text("nav_" + maneuver, language)


## Screen-coordinate arrow geometry; a left turn is an actual bent arrow,
## not a rotated straight compass needle.
static func arrow_points(maneuver: String) -> PackedVector2Array:
	match maneuver:
		"left": return PackedVector2Array([Vector2(0, 35), Vector2(0, -15), Vector2(-45, -15)])
		"right": return PackedVector2Array([Vector2(0, 35), Vector2(0, -15), Vector2(45, -15)])
		"uturn": return PackedVector2Array([Vector2(15, 35), Vector2(15, -25), Vector2(-20, -25), Vector2(-20, 20)])
		"straight": return PackedVector2Array([Vector2(0, 35), Vector2(0, -30)])
	return PackedVector2Array()


func _draw_arrow() -> void:
	var center := _arrow.size * 0.5
	var points := arrow_points(_maneuver)
	var color := Color8(110, 215, 255)
	if _maneuver == "arrive":
		_arrow.draw_line(center + Vector2(-12, 30), center + Vector2(-12, -30), color, 5, true)
		_arrow.draw_rect(Rect2(center + Vector2(-12, -30), Vector2(40, 25)), color)
	elif points.size() >= 2:
		for i in points.size():
			points[i] += center
		_arrow.draw_polyline(points, color, 8, true)
		var tip := points[-1]
		var direction := (tip - points[-2]).normalized()
		var side := Vector2(-direction.y, direction.x)
		_arrow.draw_colored_polygon(PackedVector2Array([tip + direction * 7, tip - direction * 12 + side * 12, tip - direction * 12 - side * 12]), color)
