## Presentation only: all metre-scale geometry comes from the simulation server.
extends PanelContainer

signal closed
const T := preload("res://i18n.gd")
var language := "en"
var plan: Dictionary = {}
var _title: Label
var _description: Label
var _legend: Label
var _canvas: PlanCanvas
var _close: Button


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var style := StyleBoxFlat.new()
	style.bg_color = Color8(21, 27, 35)
	style.content_margin_left = 24
	style.content_margin_right = 24
	style.content_margin_top = 20
	style.content_margin_bottom = 20
	add_theme_stylebox_override("panel", style)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	add_child(column)
	var header := HBoxContainer.new()
	column.add_child(header)
	_title = Label.new()
	_title.text = T.text("home_floor_plan", language)
	_title.add_theme_font_size_override("font_size", 28)
	_title.add_theme_color_override("font_color", Color8(255, 205, 26))
	_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(_title)
	_close = Button.new()
	_close.text = T.text("back", language) + " · Esc"
	_close.custom_minimum_size = Vector2(120, 44)
	_close.pressed.connect(func(): closed.emit())
	header.add_child(_close)
	_description = Label.new()
	_description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_description)
	_canvas = PlanCanvas.new()
	_canvas.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_canvas.custom_minimum_size = Vector2(0, 160)
	column.add_child(_canvas)
	_legend = Label.new()
	_legend.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_legend)
	show_plan(plan)
	_close.grab_focus()


func show_plan(value: Dictionary) -> void:
	plan = value
	if not is_node_ready():
		return
	_canvas.plan = value
	_canvas.queue_redraw()
	var error := str(value.get("error", ""))
	if value.is_empty():
		_description.text = T.text("home_plan_loading", language)
	elif error != "":
		_description.text = T.text("home_plan_" + error, language)
	else:
		_description.text = "%s · %.1f m² · %s" % [value.get("name", value.get("building_id", "")), value.get("area_m2", 0), T.text("home_plan_generated", language)]
		if value.get("simple", false):
			_description.text += "\n" + T.text("home_plan_simple", language)
	var entries := PackedStringArray()
	for i in value.get("rooms", []).size():
		entries.append("%d  %s" % [i + 1, T.text("room_" + value["rooms"][i]["kind"], language)])
	_legend.text = "     ·     ".join(entries)


class PlanCanvas extends Control:
	const COLORS := {"hall": Color("d6c9ac"), "living": Color("e4d3b5"), "living_kitchen": Color("e4d3b5"),
		"kitchen": Color("c7d9cb"), "bedroom": Color("c7d3e0"), "bathroom": Color("aed2d8"), "studio": Color("e4d3b5")}
	var plan: Dictionary = {}
	var _scale := 1.0
	var _offset := Vector2.ZERO

	func _ready() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE
		resized.connect(queue_redraw)

	func point(p: Array) -> Vector2:
		return Vector2(float(p[0]), -float(p[1])) * _scale + _offset

	func points(values: Array) -> PackedVector2Array:
		var result := PackedVector2Array()
		for p in values:
			result.append(point(p))
		return result

	func _draw() -> void:
		draw_rect(Rect2(Vector2.ZERO, size), Color("1b2430"))
		if not plan.has("footprint") or size.x < 80 or size.y < 80:
			return
		var bounds := Rect2(Vector2(plan["footprint"][0][0], -plan["footprint"][0][1]), Vector2.ZERO)
		for p in plan["footprint"]:
			bounds = bounds.expand(Vector2(p[0], -p[1]))
		_scale = minf((size.x - 72) / maxf(bounds.size.x, 0.1), (size.y - 72) / maxf(bounds.size.y, 0.1))
		_offset = (size - bounds.size * _scale) / 2 - bounds.position * _scale
		for room in plan.get("rooms", []):
			draw_colored_polygon(points(room["points"]), COLORS.get(room["kind"], Color.BEIGE))
		for item in plan.get("furniture", []):
			_furniture(item)
		for wall in plan.get("walls", []):
			draw_polyline(points(wall), Color("30343b"), clampf(_scale * 0.16, 2, 9), true)
		for door in plan.get("doors", []):
			var a := point(door["points"][0])
			var b := point(door["points"][1])
			var leaf := point(door["leaf"])
			draw_line(a, leaf, Color("8b5b32"), 2, true)
			var start := (b - a).angle()
			draw_arc(a, a.distance_to(b), start, start + angle_difference(start, (leaf - a).angle()), 16, Color("8b5b32"), 1, true)
		var font := ThemeDB.fallback_font
		for i in plan.get("rooms", []).size():
			var at := point(plan["rooms"][i]["label_at"])
			draw_circle(at, 12, Color("273645"))
			draw_string(font, at + Vector2(-5, 5), str(i + 1), HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color.WHITE)
		var bar := minf(5, maxf(1, floorf(bounds.size.x / 3)))
		var base := Vector2(18, size.y - 16)
		draw_line(base, base + Vector2(bar * _scale, 0), Color.WHITE, 2)
		draw_string(font, base + Vector2(0, -8), "%d m" % bar, HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color.WHITE)
		draw_string(font, Vector2(size.x - 34, 24), "N ↑", HORIZONTAL_ALIGNMENT_RIGHT, -1, 14, Color.WHITE)

	func _furniture(item: Dictionary) -> void:
		var shape := points(item["points"])
		var kind: String = item["kind"]
		var wet: bool = kind in ["shower", "toilet", "sink"]
		var fill := Color("edf6f5") if wet else Color("a27d59")
		if kind == "bed":
			fill = Color("748eae")
		elif kind == "sofa":
			fill = Color("65877c")
		draw_colored_polygon(shape, fill)
		var outline := shape.duplicate()
		outline.append(shape[0])
		draw_polyline(outline, Color("4b4b48"), 1.3, true)
		var a := shape[0]
		var u := shape[1] - a
		var v := shape[3] - a
		if kind == "bed":
			draw_line(a + u * 0.25, a + u * 0.25 + v, Color("dbe5ee"), 3, true)
		elif kind in ["sofa", "counter", "wardrobe"]:
			draw_line(a + u * 0.5, a + u * 0.5 + v, Color("4b4b48"), 1, true)
		elif wet:
			draw_circle(a + (u + v) * 0.5, minf(u.length(), v.length()) * 0.28, Color("89afb9"))
