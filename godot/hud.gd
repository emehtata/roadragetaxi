## The player's HUD: money, speed, game time, weather, the fare and the
## simulation's notice, all read from the state being shown. Only formats
## what Python decided (`values` is a pure state -> text mapping); no game
## rules here. F3 toggles the developer readout (main.gd fills it).
extends Control

@onready var _money: Label = %Money
@onready var _speed: Label = %Speed
@onready var _clock: Label = %Clock
@onready var _weather: Label = %Weather
@onready var _fare: Label = %Fare
@onready var _notice: Label = %Notice
@onready var _hint: Label = %Hint

var _meet := Label.new()  # render/menus.py draw_meet_panel
var _summary := Label.new()  # render/menus.py draw_city_summary: covers everything once the career city is done
var _notice_style := StyleBoxFlat.new()


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
	add_child(_summary)  # last child: above the HUD rows
	_notice_style = _box(Color8(20, 30, 40, 235), Color8(255, 200, 50))
	_notice.add_theme_stylebox_override("normal", _notice_style)


static func _box(fill: Color, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(2)
	style.set_content_margin_all(8)
	return style


func show_state(state: Dictionary, toggles := {}) -> void:
	var text := values(state, toggles)
	_money.text = "%s   Score: %s" % [text["money"], text["score"]]
	_speed.text = text["speed"]
	_clock.text = text["clock"]
	_weather.text = text["weather"]
	_fare.text = text["fare"]
	_notice.text = text["notice"]
	_notice.visible = text["notice"] != ""
	# hud.py: a speed-camera hit is centred on screen with a red border, other notices at the top in amber.
	_notice_style.border_color = Color8(255, 70, 45) if text["notice_camera"] else Color8(255, 200, 50)
	var camera: bool = text["notice_camera"]
	_notice.anchor_top = 0.5 if camera else 0.0
	_notice.anchor_bottom = _notice.anchor_top
	_notice.offset_top = -15.0 if camera else 60.0
	_notice.offset_bottom = _notice.offset_top + 30.0
	_notice.reset_size()  # the box fits the text, as Pygame's
	_notice.position.x = (size.x - _notice.size.x) / 2.0
	_meet.text = text["meet"]
	_meet.visible = text["meet"] != ""
	_hint.text = text["hint"]


## Display text for one state. Every field is optional: a missing one shows
## a placeholder instead of failing.
static func values(state: Dictionary, toggles := {}) -> Dictionary:
	var player: Dictionary = state.get("player", {})
	var taxi: Dictionary = state.get("taxi", {})
	var weather: Dictionary = state.get("weather", {})
	var on_foot: bool = state.get("on_foot", true)
	var text := {}
	text["money"] = "%.2f €" % (taxi["balance_cents"] / 100.0) if taxi.has("balance_cents") else "– €"
	text["score"] = str(int(taxi["total_score"])) if typeof(taxi.get("total_score")) in [TYPE_INT, TYPE_FLOAT] else "–"
	text["speed"] = "on foot" if on_foot else ("%d km/h" % roundi(absf(player.get("speed", 0.0)) * 3.6))
	if state.has("game_time_seconds"):
		var minutes := int(state["game_time_seconds"] / 60.0)
		text["clock"] = "%02d:%02d" % [minutes / 60 % 24, minutes % 60]
		var calendar = state.get("calendar")
		if typeof(calendar) == TYPE_DICTIONARY:  # hud.py: the date first, " *" while time runs 1:1 (a fare)
			text["clock"] = "%s %s%s" % [calendar.get("date", ""), text["clock"], " *" if calendar.get("time_scale", 60.0) == 1.0 else ""]
	else:
		text["clock"] = "--:--"
	if weather.has("weather_type"):
		text["weather"] = "%s, road %d%% wet" % [str(weather["weather_type"]).capitalize(), roundi(weather.get("wetness", 0.0) * 100)]
	else:
		text["weather"] = ""
	var passenger = taxi.get("current_passenger")
	if passenger == null or typeof(passenger) != TYPE_DICTIONARY:
		text["fare"] = "No fare - %d done" % taxi.get("completed_fares", 0)
	else:
		var who: String = passenger.get("name", "Passenger")
		match taxi.get("state", ""):
			"PICKUP":
				text["fare"] = "Pick up %s at %s" % [who, passenger.get("pickup", {}).get("address", "?")]
			"WALKING":
				text["fare"] = "%s is walking to the taxi" % who
			"DROPOFF":
				text["fare"] = "Drive %s to %s" % [who, passenger.get("dropoff", {}).get("address", "?")] + fare_details(taxi)
			_:
				text["fare"] = who
	text["notice"] = str(taxi.get("notification_msg", "")) if taxi.get("notification_timer", 0.0) > 0.0 else ""
	text["notice_camera"] = text["notice"] != "" and taxi.get("speed_camera_notice", false)
	var meet = state.get("meet")
	text["meet"] = "\n".join(meet.get("lines", [])) if typeof(meet) == TYPE_DICTIONARY else ""
	# hud.py's road line (Pygame shows it in the debug HUD; here the F3 readout).
	var road = state.get("road")
	if typeof(road) != TYPE_DICTIONARY:
		text["road"] = ""
	else:
		text["road"] = "Road: %s" % (road["name"] if road.get("name") else "Off-road")
		if road.get("speed_limit_kmh") != null:
			text["road"] += " [Limit: %d km/h]" % int(road["speed_limit_kmh"])
	if on_foot:
		text["hint"] = "F get in the taxi · WASD walk · P phone"
	elif not player.get("engine_on", true):
		text["hint"] = "E start the engine · F get out · P phone"
	else:
		text["hint"] = "WASD drive · F get out · E engine · G refuel · V limiter %s · B red-light assist %s · N navigation %s · P phone · C compass · +/- zoom" % [
			"ON" if toggles.get("speed_limiter", true) else "OFF", "ON" if toggles.get("red_light_assist", false) else "OFF",
			"ON" if toggles.get("navigation", false) else "OFF"]
	return text


func show_summary(text: String) -> void:
	_summary.text = text
	_summary.visible = true


## render/menus.py draw_city_summary's lines from state city_summary
## [city, score, fares, next_city, career_total_score]; a missing or
## malformed summary shows only that the city is done, never made-up values.
static func summary_text(state: Dictionary) -> String:
	var summary = state.get("city_summary")
	if typeof(summary) != TYPE_ARRAY or summary.size() < 5 or typeof(summary[0]) != TYPE_STRING \
			or not typeof(summary[1]) in [TYPE_INT, TYPE_FLOAT] or not typeof(summary[2]) in [TYPE_INT, TYPE_FLOAT]:
		return "City summary\n\nThis city is complete."
	var lines := ["City summary", "", summary[0], "Score: %d" % int(summary[1]), "Fares completed: %d" % int(summary[2])]
	if typeof(summary[3]) == TYPE_STRING and summary[3] != "":
		lines.append("Next city: %s" % summary[3])
	else:
		lines.append("Career complete! Helsinki conquered.")
		if typeof(summary[4]) in [TYPE_INT, TYPE_FLOAT]:
			lines.append("Total career score: %d" % int(summary[4]))
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
