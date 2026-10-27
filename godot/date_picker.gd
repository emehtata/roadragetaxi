## A bounded, Monday-first calendar. The grid is one Tab stop; arrows select dates.
extends VBoxContainer

signal date_changed(value: Dictionary)

const T := preload("res://i18n.gd")
var value := {}
var minimum := {}
var maximum := {}
var language := "en"
var previous: Button
var next: Button
var _heading: Label
var _days: Array[Button] = []

func configure(selected: Dictionary, earliest: Dictionary, latest: Dictionary, locale: String) -> void:
	minimum = earliest.duplicate()
	maximum = latest.duplicate()
	language = locale
	focus_mode = Control.FOCUS_ALL
	add_theme_constant_override("separation", 6)
	var header := HBoxContainer.new()
	previous = Button.new()
	previous.text = "‹"
	previous.custom_minimum_size = Vector2(44, 36)
	previous.tooltip_text = T.text("previous_month", language)
	previous.pressed.connect(func(): _move_month(-1))
	header.add_child(previous)
	_heading = Label.new()
	_heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_heading.add_theme_font_size_override("font_size", 22)
	header.add_child(_heading)
	next = Button.new()
	next.text = "›"
	next.custom_minimum_size = Vector2(44, 36)
	next.tooltip_text = T.text("next_month", language)
	next.pressed.connect(func(): _move_month(1))
	header.add_child(next)
	add_child(header)
	var grid := GridContainer.new()
	grid.columns = 7
	for weekday in T.text("calendar_weekdays", language).split("|"):
		var label := Label.new()
		label.text = weekday
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		grid.add_child(label)
	for i in 42:
		var day := Button.new()
		day.focus_mode = Control.FOCUS_NONE
		day.custom_minimum_size = Vector2(44, 32)
		day.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		day.pressed.connect(func():
			var selected_day := value.duplicate()
			selected_day.day = int(day.text)
			_select(selected_day)
			grab_focus())
		_days.append(day)
		grid.add_child(day)
	add_child(grid)
	var hint := Label.new()
	hint.text = T.text("calendar_keys", language)
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.custom_minimum_size.x = 420
	hint.add_theme_font_size_override("font_size", 14)
	add_child(hint)
	focus_entered.connect(_refresh)
	focus_exited.connect(_refresh)
	set_value(selected)

static func _stamp(date: Dictionary) -> int:
	return int(Time.get_unix_time_from_datetime_dict({"year": date.year, "month": date.month, "day": date.day}))

func set_value(selected: Dictionary) -> void:
	value = Time.get_date_dict_from_unix_time(clampi(_stamp(selected), _stamp(minimum), _stamp(maximum)))
	_refresh()

func _select(selected: Dictionary) -> void:
	set_value(selected)
	date_changed.emit(value.duplicate())

func _move_month(offset: int) -> void:
	var previous_had_focus := previous.has_focus()
	var next_had_focus := next.has_focus()
	var month_index := int(value.year) * 12 + int(value.month) - 1 + offset
	var target := {"year": month_index / 12, "month": month_index % 12 + 1, "day": 1}
	var following := {"year": (month_index + 1) / 12, "month": (month_index + 1) % 12 + 1, "day": 1}
	target.day = mini(int(value.day), int((_stamp(following) - _stamp(target)) / 86400))
	_select(target)
	if (previous_had_focus and previous.disabled) or (next_had_focus and next.disabled):
		grab_focus()

func _refresh() -> void:
	if _heading == null:
		return
	_heading.text = "%s %d" % [T.text("calendar_months", language).split("|")[int(value.month) - 1], value.year]
	previous.disabled = int(value.year) * 12 + int(value.month) <= int(minimum.year) * 12 + int(minimum.month)
	next.disabled = int(value.year) * 12 + int(value.month) >= int(maximum.year) * 12 + int(maximum.month)
	var first := {"year": value.year, "month": value.month, "day": 1}
	var start := _stamp(first)
	var weekday := int(Time.get_date_dict_from_unix_time(start).weekday)
	var offset := (weekday + 6) % 7
	for i in _days.size():
		var stamp := start + (i - offset) * 86400
		var date := Time.get_date_dict_from_unix_time(stamp)
		var day := _days[i]
		day.text = str(date.day) if date.month == value.month else ""
		day.disabled = day.text == "" or stamp < _stamp(minimum) or stamp > _stamp(maximum)
		day.remove_theme_stylebox_override("normal")
		day.remove_theme_color_override("font_color")
		if stamp == _stamp(value):
			var style := StyleBoxFlat.new()
			style.bg_color = Color8(255, 199, 0)
			style.border_color = Color.WHITE
			style.set_border_width_all(2 if has_focus() else 0)
			style.set_corner_radius_all(4)
			day.add_theme_stylebox_override("normal", style)
			day.add_theme_color_override("font_color", Color.BLACK)

func _gui_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed:
		return
	var delta: int = {KEY_LEFT: -1, KEY_RIGHT: 1, KEY_UP: -7, KEY_DOWN: 7}.get(event.keycode, 0)
	if delta != 0:
		_select(Time.get_date_dict_from_unix_time(_stamp(value) + delta * 86400))
	elif event.keycode == KEY_PAGEUP or event.keycode == KEY_PAGEDOWN:
		_move_month(-1 if event.keycode == KEY_PAGEUP else 1)
	elif not event.is_action_pressed("ui_accept"):
		return
	accept_event()
