## Compact mounted phone: presentation of the server's next-turn instruction.
extends PanelContainer

const T := preload("res://i18n.gd")
var language := "en"
var _arrow: Control
var _distance: Label
var _street: Label
var _maneuver := "no_target"
var _clock: Label
var _battery_label: Label
var _battery_icon: Control
var _battery := 100.0
var _charging := false


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	position = Vector2(16, 125)
	custom_minimum_size = Vector2(270, 280)
	add_theme_stylebox_override("panel", Phone.device_style())
	var screen := PanelContainer.new()
	screen.mouse_filter = Control.MOUSE_FILTER_IGNORE
	screen.add_theme_stylebox_override("panel", Phone.screen_style())
	add_child(screen)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	screen.add_child(box)
	var status := Phone.make_status_bar()
	box.add_child(status)
	_clock = status.get_node("Bar/Clock")
	_battery_label = status.get_node("Bar/BatteryLabel")
	_battery_icon = status.get_node("Bar/BatteryIcon")
	_battery_icon.draw.connect(func(): Phone.draw_battery(_battery_icon, _battery, _charging))
	var title := Phone._label(20, Color8(20, 20, 20), "RageCab")
	var header := PanelContainer.new()
	var header_style := StyleBoxFlat.new()
	header_style.bg_color = Color8(255, 199, 0)
	header_style.set_content_margin_all(8)
	header_style.content_margin_left = 18
	header.add_theme_stylebox_override("panel", header_style)
	header.add_child(title)
	box.add_child(header)
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
	box.add_child(Phone.home_indicator())
	hide()


func show_status(phone: Phone) -> void:
	_clock.text = phone.clock_text
	_battery = phone.battery
	_charging = phone.charging
	_battery_label.text = "  %d%%" % roundi(_battery)
	_battery_icon.queue_redraw()


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
