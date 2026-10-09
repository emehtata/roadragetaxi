## The player's HUD: money, speed, game time, weather, the fare and the
## simulation's notice, all read from the state being shown. Only formats
## what Python decided (`values` is a pure state -> text mapping); no game
## rules here. F3 toggles the developer readout (main.gd fills it).
extends Control

const T := preload("res://i18n.gd")

@onready var _money: Label = %Money
@onready var _speed: Label = %Speed
@onready var _clock: Label = %Clock
@onready var _weather: Label = %Weather
@onready var _fare: Label = %Fare
@onready var _notice: Label = %Notice
@onready var _hint: Label = %Hint

var _meet := Label.new()  # render/menus.py draw_meet_panel
var _subtitle := Label.new()  # render/hud.py comment_text: "Speaker: line" (godot-final-07)
var _subtitle_until := 0  # real-time ms
var _board := Label.new()  # render/hud.py draw_next_train (J)
var _timetable_hint_shown := false  # main(): once a session, when the map first has timetabled stations
var _timetable_hint_until := 0
var _summary := Label.new()  # render/menus.py draw_city_summary: covers everything once the career city is done
var _notice_style := StyleBoxFlat.new()
var _fare_style := StyleBoxFlat.new()
var layout = preload("res://hud_layout.gd").new(false)  # main.gd gives the shared, saved one
var _notice_mode := ""  # "camera", "start" or "" (the banner)
var language := "en"


func _ready() -> void:
	var meet_style := _box(Color8(16, 35, 55), Color8(90, 200, 255))
	meet_style.set_corner_radius_all(5)
	_meet.add_theme_stylebox_override("normal", meet_style)
	_meet.add_theme_font_size_override("font_size", 20)
	_meet.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_meet.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP, Control.PRESET_MODE_MINSIZE)
	_meet.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_meet.position.y = 100.0  # under the notice line
	_meet.visible = false
	add_child(_meet)
	var summary_style := StyleBoxFlat.new()
	summary_style.bg_color = Color8(18, 24, 32)  # Pygame fills the screen with this
	_summary.add_theme_stylebox_override("normal", summary_style)
	_summary.add_theme_font_size_override("font_size", 24)
	_summary.add_theme_color_override("font_color", Color8(205, 215, 225))
	_summary.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_summary.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_summary.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_summary.visible = false
	var subtitle_style := StyleBoxFlat.new()
	subtitle_style.bg_color = Color(0, 0, 0, 205.0 / 255.0)
	subtitle_style.set_content_margin_all(8)
	subtitle_style.content_margin_left = 17
	subtitle_style.content_margin_right = 17
	_subtitle.add_theme_stylebox_override("normal", subtitle_style)
	_subtitle.add_theme_font_size_override("font_size", 20)
	_subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_subtitle.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	_subtitle.visible = false
	add_child(_subtitle)
	var board_style := _box(Color8(20, 25, 35, 210), Color8(120, 160, 220))
	board_style.border_width_left = 1
	board_style.border_width_right = 1
	board_style.border_width_top = 1
	board_style.border_width_bottom = 1
	board_style.set_content_margin_all(6)
	board_style.set_corner_radius_all(3)
	_board.add_theme_stylebox_override("normal", board_style)
	_board.add_theme_color_override("font_color", Color8(200, 225, 255))
	_board.add_theme_font_size_override("font_size", 15)
	_board.visible = false
	add_child(_board)
	add_child(_summary)  # last child: above the HUD rows
	_notice_style = _box(Color8(20, 30, 40, 235), Color8(255, 200, 50))
	_notice.add_theme_stylebox_override("normal", _notice_style)
	# render/hud.py's layout, no shared bar: the clock top right, the score
	# box left of it, the weather under them, the fare banner top left
	# under the trip meter (instruments.gd), notices low in the middle.
	var bar: Control = _clock.get_parent().get_parent()
	for label: Label in [_clock, _money, _speed, _weather, _fare]:
		label.get_parent().remove_child(label)
		add_child(label)
		label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
		label.add_theme_font_size_override("font_size", 17)
		label.add_theme_constant_override("outline_size", 4)
		label.add_theme_color_override("font_outline_color", Color8(20, 24, 28, 230))
	bar.visible = false
	_speed.visible = false  # the speedometer shows it (hud.py has no speed text)
	_clock.add_theme_color_override("font_color", Color8(255, 230, 120))
	_money.add_theme_color_override("font_color", Color8(255, 230, 110))
	var money_style := _box(Color8(20, 20, 20, 200), Color8(220, 180, 50))
	money_style.set_border_width_all(1)
	money_style.set_content_margin_all(4)
	money_style.content_margin_left = 6
	money_style.content_margin_right = 6
	money_style.set_corner_radius_all(3)
	_money.add_theme_stylebox_override("normal", money_style)
	_weather.add_theme_font_size_override("font_size", 15)
	_weather.add_theme_color_override("font_color", Color8(200, 220, 240))
	_fare_style = _box(Color8(25, 30, 35, 220), Color8(190, 200, 205))
	_fare_style.set_border_width_all(1)
	_fare_style.set_content_margin_all(4)
	_fare_style.content_margin_left = 6
	_fare_style.content_margin_right = 6
	_fare_style.set_corner_radius_all(3)
	_fare.add_theme_stylebox_override("normal", _fare_style)
	_fare.clip_text = true
	_fare.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS


static func _box(fill: Color, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(2)
	style.set_content_margin_all(8)
	return style


func show_state(state: Dictionary, toggles := {}) -> void:
	var text := values(state, toggles, language)
	_money.text = "%s: %s  |  %s: %d  |  %s" % [T.text("score", language, "Score"), text["score"],
		T.text("fares", language, "Fares"), int(state.get("taxi", {}).get("completed_fares", 0)), text["money"]]
	_speed.text = text["speed"]
	_clock.text = text["clock"]
	_weather.text = text["weather"]
	_fare.text = text["fare"]
	_fare_style.border_color = text["fare_color"]
	_fare.add_theme_color_override("font_color", text["fare_color"])
	var start_hint: bool = text["notice"] == "" and text["start_hint"] != ""  # main(): draw_game_start_hint, blue
	_notice.text = text["start_hint"] if start_hint else text["notice"]
	_notice.visible = _notice.text != ""
	# hud.py: a speed-camera hit is centred on screen with a red border, other notices at the top in amber.
	_notice_style.border_color = Color8(255, 70, 45) if text["notice_camera"] else (Color8(100, 190, 240) if start_hint else Color8(255, 200, 50))
	_notice_style.bg_color = Color8(16, 35, 55, 235) if start_hint else Color8(20, 30, 40, 235)
	_notice_mode = "camera" if text["notice_camera"] else ("start" if start_hint else "")
	_meet.text = text["meet"]
	_meet.visible = text["meet"] != ""
	_hint.text = text["hint"]
	var board := next_train_text(state.get("railway"), language) if toggles.get("next_train", false) else ""
	_board.text = board
	_board.visible = board != ""
	if _board.visible:
		_board.reset_size()
		_board.position = Vector2(size.x - 10.0 - _board.size.x, 116.0)  # draw_next_train: top right under the limit sign
	_layout_subtitle()
	_subtitle.visible = Time.get_ticks_msec() < _subtitle_until
	_layout()
	var railway = state.get("railway")
	if not _timetable_hint_shown and railway is Dictionary and railway.get("stations") is Array and not railway["stations"].is_empty():
		_timetable_hint_shown = true  # the client's own hint: it never overwrites the server's notices
		_timetable_hint_until = Time.get_ticks_msec() + 6000
	if Time.get_ticks_msec() < _timetable_hint_until and _hint.text != "":
		_hint.text = T.text("train_hint", language, "Train timetables available. Press J.   ") + _hint.text


## Where everything goes (render/hud.py draw_hud), after the texts changed:
## nothing shares a row, so nothing can run into anything else.
func _layout() -> void:
	for label: Label in [_clock, _money, _weather, _notice, _hint]:
		label.size = Vector2.ZERO
		label.reset_size()
	_clock.position = Vector2(size.x - 12.0 - _clock.size.x, 8.0)
	_money.position = Vector2(_clock.position.x - 12.0 - _money.size.x, 6.0)
	_weather.position = Vector2(size.x - 92.0 - _weather.size.x, 40.0)  # left of the limit sign
	# The clock, the score box and the weather move as one panel.
	var status := Rect2(_money.position, Vector2.ZERO).merge(Rect2(_clock.position, _clock.size)).merge(Rect2(_money.position, _money.size))
	if _weather.text != "":
		status = status.merge(Rect2(_weather.position, _weather.size))
	var moved: Vector2 = layout.place("status", status, size).position - status.position
	for label: Label in [_clock, _money, _weather]:
		label.position += moved
	_fare.position = Vector2(10.0, 44.0)  # under the trip meter
	# A clipping Label reports no minimum width: measure the text instead.
	var font := _fare.get_theme_font("font")
	var font_size := _fare.get_theme_font_size("font_size")
	var text_size := font.get_multiline_string_size(_fare.text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var room := maxf(120.0, minf(_weather.position.x, size.x - 100.0) - 20.0)  # left of the weather and the sign
	_fare.size = Vector2(minf(text_size.x + 14.0, room), text_size.y + 10.0)
	_fare.visible = _fare.text != ""
	if _fare.visible:
		_fare.position = layout.place("fare", Rect2(_fare.position, _fare.size), size).position
	else:
		layout.rects.erase("fare")  # nothing there to grab
	_hint.visible = _hint.text != "" and not _notice.visible
	_hint.position = Vector2((size.x - _hint.size.x) / 2.0, size.y - 30.0)
	match _notice_mode:
		"camera":  # hud.py: a speed-camera hit centred on screen, red
			_notice.position = (size - _notice.size) / 2.0
		"start":  # menus.py draw_game_start_hint: top middle, blue
			_notice.position = Vector2((size.x - _notice.size.x) / 2.0, 100.0)
		_:  # the notification banner: low in the middle
			_notice.position = Vector2((size.x - _notice.size.x) / 2.0, size.y - 45.0 - _notice.size.y / 2.0)


## Display text for one state. Every field is optional: a missing one shows
## a placeholder instead of failing.
static func values(state: Dictionary, toggles := {}, language := "en") -> Dictionary:
	var player: Dictionary = state.get("player", {})
	var taxi: Dictionary = state.get("taxi", {})
	var weather: Dictionary = state.get("weather", {})
	var on_foot: bool = state.get("on_foot", true)
	var text := {}
	text["money"] = "%.2f €" % (taxi["balance_cents"] / 100.0) if taxi.has("balance_cents") else "– €"
	text["score"] = str(int(taxi["total_score"])) if typeof(taxi.get("total_score")) in [TYPE_INT, TYPE_FLOAT] else "–"
	text["speed"] = T.text("on_foot", language, "on foot") if on_foot else ("%d km/h" % roundi(absf(player.get("speed", 0.0)) * 3.6))
	if state.has("game_time_seconds"):
		var minutes := int(state["game_time_seconds"] / 60.0)
		text["clock"] = "%02d:%02d" % [minutes / 60 % 24, minutes % 60]
		var calendar = state.get("calendar")
		if typeof(calendar) == TYPE_DICTIONARY:  # hud.py: the date first, " *" while time runs 1:1 (a fare)
			var temperature = state.get("weather", {}).get("temperature_c")  # hud.py: "  +4.0 °C" after the time
			text["clock"] = "%s %s%s%s" % [calendar.get("date", ""), text["clock"],
				"  %+.1f °C" % temperature if typeof(temperature) in [TYPE_INT, TYPE_FLOAT] else "", " *" if calendar.get("time_scale", 60.0) == 1.0 else ""]
	else:
		text["clock"] = "--:--"
	if weather.has("weather_type"):
		text["weather"] = T.text("road_wet", language, "%s, road %d%% wet") % [T.weather(str(weather["weather_type"]), language), roundi(weather.get("wetness", 0.0) * 100)]
	else:
		text["weather"] = ""
	var passenger = taxi.get("current_passenger")
	# hud.py's banner colours: grey idle, yellow picking up, green with the passenger.
	text["fare_color"] = Color8(190, 200, 205)
	if typeof(passenger) == TYPE_DICTIONARY:
		text["fare_color"] = Color8(100, 240, 140) if taxi.get("state", "") == "DROPOFF" else Color8(255, 215, 60)
	if passenger == null or typeof(passenger) != TYPE_DICTIONARY:
		text["fare"] = T.text("no_fare", language, "No fare - %d done") % taxi.get("completed_fares", 0)
	else:
		var who: String = passenger.get("name", T.text("passenger", language, "Passenger"))
		match taxi.get("state", ""):
			"PICKUP":
				text["fare"] = T.text("pick_up", language, "Pick up %s at %s") % [who, passenger.get("pickup", {}).get("address", "?")]
			"WALKING":
				text["fare"] = T.text("walking_taxi", language, "%s is walking to the taxi") % who
			"DROPOFF":
				text["fare"] = T.text("drive_to", language, "Drive %s to %s") % [who, passenger.get("dropoff", {}).get("address", "?")] + fare_details(taxi)
			_:
				text["fare"] = who
	text["notice"] = str(taxi.get("notification_msg", "")) if taxi.get("notification_timer", 0.0) > 0.0 else ""
	text["notice_camera"] = text["notice"] != "" and taxi.get("speed_camera_notice", false)
	# main()'s start hints: get in (until the driver first does), then start the engine.
	text["start_hint"] = ""
	if on_foot and not toggles.get("entered_taxi", true):
		text["start_hint"] = T.text("hint_enter_taxi", language, "Press F to get into your taxi")
	elif not on_foot and not player.get("engine_on", true) and player.get("fuel_l", 0.0) > 0.0:
		text["start_hint"] = T.text("hint_start_engine", language, "Press E to start the engine")
	var meet = state.get("meet")
	text["meet"] = "\n".join(meet.get("lines", [])) if typeof(meet) == TYPE_DICTIONARY else ""
	# hud.py's road line (Pygame shows it in the debug HUD; here the F3 readout).
	var road = state.get("road")
	if typeof(road) != TYPE_DICTIONARY:
		text["road"] = ""
	else:
		text["road"] = "%s: %s" % [T.text("road", language, "Road"), road["name"] if road.get("name") else T.text("off_road", language, "Off-road")]
		if road.get("speed_limit_kmh") != null:
			text["road"] += " [%s: %d km/h]" % [T.text("limit", language, "Limit"), int(road["speed_limit_kmh"])]
	if on_foot:
		text["hint"] = T.text("hint_foot", language, "F get in the taxi · WASD walk · P phone")
	elif not player.get("engine_on", true):
		text["hint"] = T.text("hint_engine", language, "E start the engine · F get out · P phone")
	else:  # hud.py's long controls line is debug-only; F1 lists them all
		text["hint"] = ""
	return text


## A server speech line: "<name or Driver/Passenger>: <text>" for its
## duration in real seconds; a later one replaces it. No text: no subtitle.
func show_subtitle(event: Dictionary) -> void:
	var line := subtitle_text(event)
	if line == "":
		return
	_subtitle.text = line
	var duration = event.get("duration_s", 4.0)
	_subtitle_until = Time.get_ticks_msec() + int(1000.0 * clampf(float(duration) if typeof(duration) in [TYPE_INT, TYPE_FLOAT] else 4.0, 0.0, 15.0))
	_layout_subtitle()
	_subtitle.visible = true


static func subtitle_text(event: Dictionary) -> String:
	var text = event.get("text")
	if typeof(text) != TYPE_STRING or text == "":
		return ""
	var name = event.get("speaker_name")
	var speaker: String = name if typeof(name) == TYPE_STRING and name != "" else ("Passenger" if event.get("speaker") == "passenger" else "Driver")
	return "%s: %s" % [speaker, text]


func _layout_subtitle() -> void:
	if not _subtitle.visible and Time.get_ticks_msec() >= _subtitle_until:
		return
	# An autowrapping Label reports ~0 minimum width (one letter per line):
	# wrap only a line wider than the screen.
	var font := _subtitle.get_theme_font("font")
	var text_width := font.get_string_size(_subtitle.text, HORIZONTAL_ALIGNMENT_LEFT, -1, _subtitle.get_theme_font_size("font_size")).x
	var too_wide := text_width + 34.0 > size.x - 40.0
	_subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART if too_wide else TextServer.AUTOWRAP_OFF
	_subtitle.custom_minimum_size = Vector2(size.x - 40.0 if too_wide else 0.0, 0.0)
	_subtitle.size = Vector2.ZERO
	_subtitle.reset_size()
	_subtitle.position = Vector2((size.x - _subtitle.size.x) / 2.0, size.y - 82.0 - _subtitle.size.y / 2.0)  # hud.py: centred at height - 82


## render/hud.py draw_next_train's board: the station, "Next trains:" and
## "Departing trains:" (time, track, train, where from / to), "" when there's nothing.
static func next_train_text(railway, language := "en") -> String:
	if not railway is Dictionary:
		return ""
	var lines := []
	for section in [["arrivals", T.text("next_trains", language, "Next trains"), "origin"], ["departures", T.text("departing_trains", language, "Departing trains"), "destination"]]:
		var rows = railway.get(section[0])
		if not rows is Array or rows.is_empty():
			continue
		lines.append(section[1] + ":")
		for row in rows.slice(0, 5):
			if not row is Dictionary:
				continue
			var track := str(row.get("track", ""))
			lines.append("%s%s  %s %s %s" % [str(row.get("time", "--:--")), (" " + T.text("track", language, "track") + " " + track) if track != "" else "",
				str(row.get("train_type", "")), str(row.get("number", "")), str(row.get(section[2], ""))])
	if lines.is_empty():
		return ""
	return "\n".join([str(railway.get("nearest_station", ""))] + lines)


func show_summary(text: String) -> void:
	_summary.text = text
	_summary.visible = true


## render/menus.py draw_city_summary's lines from state city_summary
## [city, score, fares, next_city, career_total_score]; a missing or
## malformed summary shows only that the city is done, never made-up values.
static func summary_text(state: Dictionary, language := "en") -> String:
	var summary = state.get("city_summary")
	if typeof(summary) != TYPE_ARRAY or summary.size() < 5 or typeof(summary[0]) != TYPE_STRING \
			or not typeof(summary[1]) in [TYPE_INT, TYPE_FLOAT] or not typeof(summary[2]) in [TYPE_INT, TYPE_FLOAT]:
		return "%s\n\n%s" % [T.text("city_summary", language, "City summary"), T.text("city_complete", language, "This city is complete.")]
	var lines := [T.text("city_summary", language, "City summary"), "", summary[0], "%s: %d" % [T.text("score", language, "Score"), int(summary[1])], T.text("fares_completed", language, "Fares completed: %d") % int(summary[2])]
	if typeof(summary[3]) == TYPE_STRING and summary[3] != "":
		lines.append(T.text("next_city", language, "Next city: %s") % summary[3])
	else:
		lines.append(T.text("career_complete", language, "Career complete! Helsinki conquered."))
		if typeof(summary[4]) in [TYPE_INT, TYPE_FLOAT]:
			lines.append(T.text("career_score", language, "Total career score: %d") % int(summary[4]))
	return "\n".join(lines)


## render/hud.py's mission bar while driving a fare: elapsed time, then the
## meter, its distance and the passenger's happiness once the meter runs
## (the server sends those null before). Missing or malformed values are left out.
static func fare_details(taxi: Dictionary) -> String:
	var parts := []
	var numeric := func(key): return typeof(taxi.get(key)) in [TYPE_INT, TYPE_FLOAT]
	if numeric.call("elapsed_time"):
		parts.append("%.0f s" % taxi["elapsed_time"])
	if numeric.call("live_fare_cents"):
		parts.append("meter %.2f €" % (int(taxi["live_fare_cents"]) / 100.0))
	if numeric.call("fare_distance_m"):
		parts.append("%.2f km" % (taxi["fare_distance_m"] / 1000.0))
	if numeric.call("passenger_happiness"):
		parts.append("happiness %d%%" % roundi(taxi["passenger_happiness"]))
	return "" if parts.is_empty() else " · " + " · ".join(parts)
