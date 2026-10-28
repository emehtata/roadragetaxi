## The player's HUD: money, speed, game time, weather, the taximeter and the
## simulation's notice, all read from the state being shown. Only formats
## what Python decided (`values` is a pure state -> text mapping); no game
## rules here. F3 toggles the developer readout (main.gd fills it).
extends Control

const T := preload("res://i18n.gd")

@onready var _money: Label = %Money
@onready var _speed: Label = %Speed
@onready var _clock: Label = %Clock
@onready var _weather: Label = %Weather
@onready var _notice: Label = %Notice
@onready var _hint: Label = %Hint

var _meet := Label.new()  # the meet & greet panel
var _subtitle := Label.new()  # "Speaker: line" (godot-final-07)
var _subtitle_until := 0  # real-time ms
var _board := Label.new()  # the next trains board (J)
var _electronic := preload("res://electronic_signs.gd").new()
var _timetable_hint_shown := false  # once a session, when the map first has timetabled stations
var _timetable_hint_until := 0
var _meter := preload("res://taxi_meter.gd").new()  # the seven-segment taximeter
var _summary := Label.new()  # the city summary: covers everything once the career city is done
var _notice_style := StyleBoxFlat.new()
var layout = preload("res://hud_layout.gd").new(false)  # main.gd gives the shared, saved one
var _notice_mode := ""
var _map_sign := Label.new()  # the map growing at its edge: wait for it (state.map_loading)  # "camera", "start" or "" (the banner)
var language := "en"


var osm_credit := Label.new()  # the map data's attribution, always on in the game view


func _ready() -> void:
	# ODbL: credit where the map is shown (the start map credits its tiles itself).
	osm_credit.text = "© OpenStreetMap contributors"
	osm_credit.add_theme_font_size_override("font_size", 12)
	osm_credit.add_theme_color_override("font_color", Color(1, 1, 1, 0.75))
	osm_credit.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	osm_credit.add_theme_constant_override("outline_size", 3)
	osm_credit.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_RIGHT, Control.PRESET_MODE_MINSIZE, 6)
	osm_credit.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	osm_credit.grow_vertical = Control.GROW_DIRECTION_BEGIN
	osm_credit.mouse_filter = Control.MOUSE_FILTER_IGNORE
	osm_credit.offset_right -= 160.0  # left of the rage-face panel in the bottom-right corner
	osm_credit.offset_left -= 160.0
	add_child(osm_credit)
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
	summary_style.bg_color = Color8(18, 24, 32)
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
	# Just a small line, no box: the map is still drivable while it grows.
	_map_sign.add_theme_font_size_override("font_size", 13)
	_map_sign.add_theme_color_override("font_color", Color8(190, 215, 235))
	_map_sign.add_theme_constant_override("outline_size", 4)
	_map_sign.add_theme_color_override("font_outline_color", Color8(20, 24, 28, 220))
	_map_sign.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_map_sign.visible = false
	add_child(_map_sign)
	add_child(_meter)
	add_child(_electronic)
	add_child(_summary)  # last child: above the HUD rows
	_notice_style = _box(Color8(20, 30, 40, 235), Color8(255, 200, 50))
	_notice.add_theme_stylebox_override("normal", _notice_style)
	# No shared bar: the clock top right, the score
	# box left of it, the weather under them, the taximeter top middle,
	# notices low in the middle (the fare's task is in the phone).
	var bar: Control = _clock.get_parent().get_parent()
	for label: Label in [_clock, _money, _speed, _weather]:
		label.get_parent().remove_child(label)
		add_child(label)
		label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
		label.add_theme_font_size_override("font_size", 17)
		label.add_theme_constant_override("outline_size", 4)
		label.add_theme_color_override("font_outline_color", Color8(20, 24, 28, 230))
	bar.visible = false
	_speed.visible = false  # the speedometer shows it (no speed text)
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


static func _box(fill: Color, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(2)
	style.set_content_margin_all(8)
	return style


func show_state(state: Dictionary, toggles := {}) -> void:
	_electronic.show_state(state.get("electronic_signs", []), language)
	var text := values(state, toggles, language)
	_money.text = "%s: %s  |  %s: %d  |  %s" % [T.text("score", language), text["score"],
		T.text("fares", language), int(state.get("taxi", {}).get("completed_fares", 0)), text["money"]]
	_speed.text = text["speed"]
	_clock.text = text["clock"]
	_weather.text = text["weather"]
	var taxi: Dictionary = state.get("taxi", {})
	var live = taxi.get("live_fare_cents")
	_meter.visible = typeof(live) in [TYPE_INT, TYPE_FLOAT]
	if _meter.visible:
		_meter.cents = int(live)
		_meter.info = meter_info(taxi)
	var start_hint: bool = text["notice"] == "" and text["start_hint"] != ""  # the start hint, blue
	_notice.text = text["start_hint"] if start_hint else text["notice"]
	_notice.visible = _notice.text != ""
	# A speed-camera hit is centred on screen with a red border, other notices at the top in amber.
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
		_board.position = Vector2(size.x - 10.0 - _board.size.x, 180.0 if _electronic.visible else 116.0)
	_layout_subtitle()
	_subtitle.visible = Time.get_ticks_msec() < _subtitle_until
	_map_sign.text = map_loading_text(str(state.get("map_loading", "")), Time.get_ticks_msec(), language, str(state.get("map_loading_detail", "")))
	_map_sign.visible = _map_sign.text != ""
	_layout()
	var railway = state.get("railway")
	if not _timetable_hint_shown and railway is Dictionary and railway.get("stations") is Array and not railway["stations"].is_empty():
		_timetable_hint_shown = true  # the client's own hint: it never overwrites the server's notices
		_timetable_hint_until = Time.get_ticks_msec() + 6000
	if Time.get_ticks_msec() < _timetable_hint_until and _hint.text != "":
		_hint.text = T.text("train_hint", language) + _hint.text


## Where everything goes, after the texts changed:
## nothing shares a row, so nothing can run into anything else.
func _layout() -> void:
	for label: Label in [_clock, _money, _weather, _notice, _hint]:
		label.size = Vector2.ZERO
		label.reset_size()
	_clock.position = Vector2(size.x - 12.0 - _clock.size.x, 8.0)
	_money.position = Vector2(_clock.position.x - 12.0 - _money.size.x, 6.0)
	_weather.position = Vector2(size.x - 92.0 - _weather.size.x, 40.0)  # left of the limit sign
	_electronic.size = Vector2(minf(330.0, maxf(160.0, size.x - 110.0)), 0)
	_electronic.position = Vector2(size.x - 90.0 - _electronic.size.x, 68.0)
	# The clock, the score box and the weather move as one panel.
	var status := Rect2(_money.position, Vector2.ZERO).merge(Rect2(_clock.position, _clock.size)).merge(Rect2(_money.position, _money.size))
	if _weather.text != "":
		status = status.merge(Rect2(_weather.position, _weather.size))
	var placed: Rect2 = layout.place("status", status, size)
	var factor: float = layout.scale_of("status")
	for label: Label in [_clock, _money, _weather]:
		label.position = placed.position + (label.position - status.position) * factor
		label.scale = Vector2(factor, factor)
	if _meter.visible:  # top middle by default
		var meter_factor: float = layout.scale_of("meter")
		_meter.scale = Vector2(meter_factor, meter_factor)
		_meter.position = layout.place("meter", Rect2(Vector2((size.x - _meter.size.x * meter_factor) / 2.0, 8.0), _meter.size), size).position
	else:
		layout.rects.erase("meter")
	_hint.visible = _hint.text != "" and not _notice.visible
	_hint.position = Vector2((size.x - _hint.size.x) / 2.0, size.y - 30.0)
	if _map_sign.visible:  # small, right under the weather line
		_map_sign.size = Vector2.ZERO
		_map_sign.reset_size()
		_map_sign.position = Vector2(_weather.position.x + _weather.size.x - _map_sign.size.x, _weather.position.y + _weather.size.y)
	match _notice_mode:
		"camera":  # a speed-camera hit centred on screen, red
			_notice.position = (size - _notice.size) / 2.0
		"start":  # the start hint: top middle, blue
			_notice.position = Vector2((size.x - _notice.size.x) / 2.0, 100.0)
		_:  # the notification banner: low in the middle
			_notice.position = Vector2((size.x - _notice.size.x) / 2.0, size.y - 45.0 - _notice.size.y / 2.0)


## The loading sign: "" when the map is settled, else a turning spinner,
## "Loading map…" and what it is at (the server's map_loading stage).
static func map_loading_text(stage: String, now_ms: int, language := "en", detail := "") -> String:
	if stage == "":
		return ""
	var spinner: String = ["◐", "◓", "◑", "◒"][int(now_ms / 150) % 4]
	var what: String = {
		"fetching": T.text("map_fetching", language),
		"merging": T.text("map_merging", language),
		"syncing": T.text("map_syncing", language),
		"building": T.text("map_building", language),
	}.get(stage, stage)
	# The fetcher's own line names where it loads from (an Overpass URL, the .pbf file).
	return "%s %s %s" % [spinner, T.text("map_loading", language), what] + ("\n" + detail if detail != "" else "")


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
	text["speed"] = T.text("on_foot", language) if on_foot else ("%d km/h" % roundi(absf(player.get("speed", 0.0)) * 3.6))
	if state.has("game_time_seconds"):
		var minutes := int(state["game_time_seconds"] / 60.0)
		text["clock"] = "%02d:%02d" % [minutes / 60 % 24, minutes % 60]
		var calendar = state.get("calendar")
		if typeof(calendar) == TYPE_DICTIONARY:  # the date first, " *" while time runs 1:1 (a fare)
			var temperature = state.get("weather", {}).get("temperature_c")  # "  +4.0 °C" after the time
			text["clock"] = "%s %s%s%s" % [calendar.get("date", ""), text["clock"],
				"  %+.1f °C" % temperature if typeof(temperature) in [TYPE_INT, TYPE_FLOAT] else "", " *" if calendar.get("time_scale", 60.0) == 1.0 else ""]
	else:
		text["clock"] = "--:--"
	if weather.has("weather_type"):
		text["weather"] = T.text("road_wet", language) % [T.weather(str(weather["weather_type"]), language), roundi(weather.get("wetness", 0.0) * 100)]
	else:
		text["weather"] = ""
	text["notice"] = str(taxi.get("notification_msg", "")) if taxi.get("notification_timer", 0.0) > 0.0 else ""
	text["notice_camera"] = text["notice"] != "" and taxi.get("speed_camera_notice", false)
	# The start hints: get in (until the driver first does), then start the engine.
	text["start_hint"] = ""
	if on_foot and not toggles.get("entered_taxi", true):
		text["start_hint"] = T.text("hint_enter_taxi", language)
	elif not on_foot and not player.get("engine_on", true) and player.get("fuel_l", 0.0) > 0.0:
		text["start_hint"] = T.text("hint_start_engine", language)
	if taxi.get("fuel_station_price_cents") != null:
		var fuel_hint := "fuel_hint_ready"
		if taxi.get("refueling") is Dictionary:
			fuel_hint = "fuel_hint_active"
		elif absf(float(player.get("speed", 0.0))) > 0.5:
			fuel_hint = "fuel_hint_stop"
		elif player.get("engine_on", false):
			fuel_hint = "fuel_hint_engine"
		elif not on_foot:
			fuel_hint = "fuel_hint_exit"
		text["start_hint"] = T.text(fuel_hint, language)
	var meet = state.get("meet")
	text["meet"] = "\n".join(meet.get("lines", [])) if typeof(meet) == TYPE_DICTIONARY else ""
	# The road line, in the F3 readout.
	var road = state.get("road")
	if typeof(road) != TYPE_DICTIONARY:
		text["road"] = ""
	else:
		text["road"] = "%s: %s" % [T.text("road", language), road["name"] if road.get("name") else T.text("off_road", language)]
		if road.get("speed_limit_kmh") != null:
			text["road"] += " [%s: %d km/h]" % [T.text("limit", language), int(road["speed_limit_kmh"])]
	if on_foot and preload("res://entity_layer.gd").player_fighting(state):
		text["hint"] = T.text("hint_brawl", language)
	elif on_foot and state.get("home_door", {}).get("available", false):
		var door: Dictionary = state["home_door"]
		text["hint"] = T.text("home_enter_prompt" if door.get("is_home", false) else "house_enter_prompt", language) + " · " + T.text("hint_foot", language)
	elif on_foot:
		text["hint"] = T.text("hint_foot", language)
	elif not player.get("engine_on", true):
		text["hint"] = T.text("hint_engine", language)
	else:  # no controls line while driving; F1 lists them all
		text["hint"] = ""
	return text


## A server speech line: "<name or Driver/Passenger>: <text>" for its
## duration in real seconds; a later one replaces it. No text: no subtitle.
func show_subtitle(event: Dictionary) -> void:
	var line := subtitle_text(event, language)
	if line == "":
		return
	_subtitle.text = line
	var duration = event.get("duration_s", 4.0)
	_subtitle_until = Time.get_ticks_msec() + int(1000.0 * clampf(float(duration) if typeof(duration) in [TYPE_INT, TYPE_FLOAT] else 4.0, 0.0, 15.0))
	_layout_subtitle()
	_subtitle.visible = true


static func subtitle_text(event: Dictionary, language := "en") -> String:
	var text = event.get("text")
	if typeof(text) != TYPE_STRING or text == "":
		return ""
	var name = event.get("speaker_name")
	var speaker: String = name if typeof(name) == TYPE_STRING and name != "" else (T.text("passenger", language) if event.get("speaker") == "passenger" else T.text("driver", language))
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
	_subtitle.position = Vector2((size.x - _subtitle.size.x) / 2.0, size.y - 82.0 - _subtitle.size.y / 2.0)  # centred at height - 82


## The next trains board: the station, "Next trains:" and
## "Departing trains:" (time, track, train, where from / to), "" when there's nothing.
static func next_train_text(railway, language := "en") -> String:
	if not railway is Dictionary:
		return ""
	var lines := []
	for section in [["arrivals", T.text("next_trains", language), "origin"], ["departures", T.text("departing_trains", language), "destination"]]:
		var rows = railway.get(section[0])
		if not rows is Array or rows.is_empty():
			continue
		lines.append(section[1] + ":")
		for row in rows.slice(0, 5):
			if not row is Dictionary:
				continue
			var track := str(row.get("track", ""))
			lines.append("%s%s  %s %s %s" % [str(row.get("time", "--:--")), (" " + T.text("track", language) + " " + track) if track != "" else "",
				str(row.get("train_type", "")), str(row.get("number", "")), str(row.get(section[2], ""))])
	if lines.is_empty():
		return ""
	return "\n".join([str(railway.get("nearest_station", ""))] + lines)


func show_summary(text: String) -> void:
	_summary.text = text
	_summary.visible = true


## The city summary's lines from state city_summary
## [city, score, fares, next_city, career_total_score]; a missing or
## malformed summary shows only that the city is done, never made-up values.
static func summary_text(state: Dictionary, language := "en") -> String:
	var summary = state.get("city_summary")
	if typeof(summary) != TYPE_ARRAY or summary.size() < 5 or typeof(summary[0]) != TYPE_STRING \
			or not typeof(summary[1]) in [TYPE_INT, TYPE_FLOAT] or not typeof(summary[2]) in [TYPE_INT, TYPE_FLOAT]:
		return "%s\n\n%s" % [T.text("city_summary", language), T.text("city_complete", language)]
	var lines := [T.text("city_summary", language), "", summary[0], "%s: %d" % [T.text("score", language), int(summary[1])], T.text("fares_completed", language) % int(summary[2])]
	if typeof(summary[3]) == TYPE_STRING and summary[3] != "":
		lines.append(T.text("next_city", language) % summary[3])
	else:
		lines.append(T.text("career_complete", language))
		if typeof(summary[4]) in [TYPE_INT, TYPE_FLOAT]:
			lines.append(T.text("career_score", language) % int(summary[4]))
	return "\n".join(lines)


## The fare's task for the phone's navigation app: who, and where to.
## "" without a passenger.
static func task_text(taxi: Dictionary, language := "en") -> String:
	var passenger = taxi.get("current_passenger")
	if typeof(passenger) != TYPE_DICTIONARY:
		return ""
	var who: String = passenger.get("name", T.text("passenger", language))
	match taxi.get("state", ""):
		"PICKUP":
			return T.text("pick_up", language) % [who, passenger.get("pickup", {}).get("address", "?")]
		"WALKING":
			return T.text("walking_taxi", language) % who
		"DROPOFF":
			return T.text("drive_to", language) % [who, passenger.get("dropoff", {}).get("address", "?")]
	return who


## The small line on the taximeter: the fare's distance, when available.
static func meter_info(taxi: Dictionary) -> String:
	if typeof(taxi.get("fare_distance_m")) in [TYPE_INT, TYPE_FLOAT]:
		return "%.2f km" % (taxi["fare_distance_m"] / 1000.0)
	return ""
