## Godot-owned application shell: main/city/settings menus and the Python
## simulation process. The game scene remains a pure network client.
extends Control

const PORT := 8765
const FINLAND_PBF_URL := "https://download.geofabrik.de/europe/finland-latest.osm.pbf"
const PBF_MAX_AGE_S := 30 * 24 * 60 * 60
const T := preload("res://i18n.gd")
const Paths := preload("res://paths.gd")
const MapBrowser := preload("res://map_browser.gd")
const Graphics := preload("res://graphics_settings.gd")

var _server_pid := -1
var _game: Node
var _panel: PanelContainer
var _body: VBoxContainer
var _cities: Array = []
var _city_locations: Array = []  # the menu's cities
var _municipalities: Array = []  # every municipality: the map picker's nearest settings
var _city := "Oulu"
var _start_place := ""  # its name from the picker's reverse geocode; "": unknown
var _start_point := Vector2.INF  # a custom gig start (latitude, longitude); INF: the city's centre
var _language := "en"
var _settings := ConfigFile.new()
var _server_extra: Array[String] = []
var _loading := false
var _startup_path := ""
var _startup_started := 0
var _startup_poll := 0.0
var _startup_stage: Label
var _startup_detail: Label
var _startup_elapsed: Label
var _startup_history: Label
var _startup_bar: ProgressBar
var _startup_last: Dictionary = {}
var _startup_changed_at := 0
var _focusables: Array[Control] = []
var _back_action := Callable()
var _logo: TextureRect
var _start_time := {}  # the gig start (year, month, day, hour, minute): now, each time the picker opens
var _back: CanvasLayer  # the backdrop and logo: hidden while the game runs


func _t(key: String) -> String:
	return T.text(key, _language)


func _ready() -> void:
	var first_run := _settings.load("user://settings.cfg") != OK or not _settings.has_section_key("game", "language")
	_language = _settings.get_value("game", "language", "en")
	var command_line := OS.get_cmdline_user_args()
	var log_level := command_line.find("--log-level")
	if log_level >= 0 and log_level + 1 < command_line.size():
		_server_extra.assign(["--log-level", command_line[log_level + 1]])
	for option in ["--osm-source", "--osm-pbf-path"]:  # make run-pbf: passed on, over the settings
		var at := command_line.find(option)
		if at >= 0 and at + 1 < command_line.size():
			_server_extra.append_array([option, command_line[at + 1]])
	_municipalities = _server_query("--list-city-locations")
	_city_locations = _municipalities.filter(func(city): return city.get("menu", true))
	_cities.assign(_city_locations.map(func(city): return str(city["name"])))
	print("startup: %d cities from the simulation (%s)" % [_cities.size(), "release" if Paths.exported() else "repo"])
	if _cities.is_empty():
		_cities = ["Oulu"]
		_city_locations = [{"name": "Oulu", "latitude": 65.012, "longitude": 25.468}]
		_municipalities = _city_locations
	_city = _settings.get_value("gig", "city", _cities[0])  # the last gig city, remembered
	if not _city in _cities:
		_city = _cities[0]
	_build_shell()
	for flag in ["--skip-menu", "--selftest", "--audiotest", "--inputtest", "--screenshot", "--bench"]:
		if flag in command_line:
			_game = preload("res://main.tscn").instantiate()
			_game.language = _language
			_game.set_graphics(Graphics.read(_settings))
			add_child(_game)
			move_child(_game, 1)
			_panel.visible = false
			_back.visible = false
			return
	if first_run:
		_language_menu()
	else:
		_main_menu()


func _build_shell() -> void:
	# Own canvas layers: as plain children of this Control the game's
	# Camera2D moved them with the world (a backdrop/logo from mid-screen).
	_back = CanvasLayer.new()
	var back := _back
	back.layer = -1  # behind the game's world
	add_child(back)
	var front := CanvasLayer.new()
	front.layer = 100  # over the game's UI
	add_child(front)
	var backdrop := ColorRect.new()
	backdrop.color = Color8(10, 14, 20)
	backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	back.add_child(backdrop)
	_logo = TextureRect.new()
	var image := Image.load_from_file(Paths.package_path("img/theroadragetrip_1672_941.png"))
	if not image.is_empty():
		_logo.texture = ImageTexture.create_from_image(image)
	_logo.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_logo.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_logo.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_logo.mouse_filter = Control.MOUSE_FILTER_IGNORE
	back.add_child(_logo)
	_panel = PanelContainer.new()
	_panel.custom_minimum_size = Vector2(520, 0)
	# Centred on the screen, whatever its content and the window size.
	_panel.resized.connect(_center_panel)
	get_viewport().size_changed.connect(_center_panel)
	var panel_style := StyleBoxFlat.new()
	panel_style.bg_color = Color8(17, 23, 31, 245)
	panel_style.border_color = Color8(255, 199, 0)
	panel_style.set_border_width_all(3)
	panel_style.set_corner_radius_all(14)
	panel_style.set_content_margin_all(28)
	_panel.add_theme_stylebox_override("panel", panel_style)
	front.add_child(_panel)
	_body = VBoxContainer.new()
	_body.add_theme_constant_override("separation", 12)
	_panel.add_child(_body)


func _center_panel() -> void:
	_panel.reset_size()  # shrink back to the new content's size first
	_panel.position = ((get_viewport().get_visible_rect().size - _panel.size) / 2.0).floor()


func _clear() -> void:
	for child in _body.get_children():
		_body.remove_child(child)
		child.queue_free()
	_focusables.clear()
	_back_action = Callable()


func _focus_menu() -> void:
	_center_panel.call_deferred()  # after this menu's rows are laid out (a smaller menu doesn't resize the panel)
	if _focusables.is_empty():
		return
	for i in _focusables.size():
		var control := _focusables[i]
		control.focus_neighbor_top = control.get_path_to(_focusables[(i - 1 + _focusables.size()) % _focusables.size()])
		control.focus_neighbor_bottom = control.get_path_to(_focusables[(i + 1) % _focusables.size()])
	var first_id := _focusables[0].get_instance_id()
	(func():
		var first := instance_from_id(first_id) as Control
		if is_instance_valid(first) and first.is_inside_tree():
			first.grab_focus()).call_deferred()


func _title(text: String, subtitle := "") -> void:
	var title := Label.new()
	title.text = text
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 34)
	title.add_theme_color_override("font_color", Color8(255, 205, 26))
	_body.add_child(title)
	if subtitle:
		var sub := Label.new()
		sub.text = subtitle
		sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_body.add_child(sub)


func _button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size.y = 44
	button.add_theme_font_size_override("font_size", 18)
	button.add_theme_color_override("font_focus_color", Color.BLACK)
	button.add_theme_color_override("font_hover_color", Color.BLACK)
	for state in ["hover", "focus", "pressed"]:
		var style := StyleBoxFlat.new()
		style.bg_color = Color8(255, 199, 0)
		style.set_corner_radius_all(7)
		button.add_theme_stylebox_override(state, style)
	button.pressed.connect(action)
	_body.add_child(button)
	_focusables.append(button)
	return button


func _language_menu() -> void:
	_clear()
	_title("LANGUAGE / KIELI / SPRACHE")
	for code in T.LANGUAGES:
		_button(T.LANGUAGE_NAMES[code], _choose_language.bind(code))
	_focus_menu()


func _choose_language(language: String) -> void:
	_language = language
	_settings.set_value("game", "language", language)
	_settings.save("user://settings.cfg")
	# The first run: the settings next, real-world data on unless chosen otherwise.
	for key in ["historical_weather", "train_timetable"]:
		if not _settings.has_section_key("game", key):
			_settings.set_value("game", key, true)
	_settings.save("user://settings.cfg")
	_settings_menu()


## The help tooltips: an opaque dark panel with light text (the default one
## is see-through: hard to read over the menu).
static func help_tooltip_theme() -> Theme:
	var theme := Theme.new()
	var panel := StyleBoxFlat.new()
	panel.bg_color = Color8(24, 28, 34)
	panel.border_color = Color8(255, 199, 0)
	panel.set_border_width_all(1)
	panel.set_corner_radius_all(6)
	panel.set_content_margin_all(10)
	theme.set_stylebox("panel", "TooltipPanel", panel)
	theme.set_color("font_color", "TooltipLabel", Color8(235, 238, 242))
	theme.set_font_size("font_size", "TooltipLabel", 16)
	return theme


## `text` broken into lines of at most `width` characters, at spaces.
static func wrap_lines(text: String, width: int) -> String:
	var lines: PackedStringArray = []
	var line := ""
	for word in text.split(" "):
		if line != "" and line.length() + 1 + word.length() > width:
			lines.append(line)
			line = word
		else:
			line = word if line == "" else line + " " + word
	lines.append(line)
	return "\n".join(lines)


## A setting with its "?": hovering shows the explanation as a tooltip,
## clicking opens it under the setting (and closes it again).
func _with_help(control: Control, help_key: String) -> void:
	var box := VBoxContainer.new()
	var row := HBoxContainer.new()
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if control.get_parent() != null:  # _button already placed it in the list
		control.get_parent().remove_child(control)
	row.add_child(control)
	var help := Label.new()
	help.text = _t(help_key)
	help.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	help.custom_minimum_size.x = 420
	help.modulate = Color(0.8, 0.85, 0.9)
	help.visible = false
	var question := Button.new()
	question.text = "?"
	question.focus_mode = Control.FOCUS_NONE
	question.custom_minimum_size = Vector2(32, 32)
	question.tooltip_text = wrap_lines(help.text, 60)  # a tooltip doesn't wrap: one long line ran off screen
	question.theme = help_tooltip_theme()
	question.pressed.connect(func():
		help.visible = not help.visible
		_center_panel())
	row.add_child(question)
	box.add_child(row)
	box.add_child(help)
	_body.add_child(box)


## The data, sounds and software the game uses and their licences
## (LICENSE_AUDIT.md, THIRD_PARTY_LICENSES.md, assets/DATA_LICENSES.txt), as
## BBCode. In English: licence names and attribution lines stay as their
## licensors write them.
static func credits_text() -> String:
	var lines := PackedStringArray([
		"[b]Road Rage Trip[/b] © 2026 Esa Mehtätalo. The game's own code is under the MIT License; the data, sounds and software below are not.",
		"",
		"[b]Map data[/b]",
		"© OpenStreetMap contributors. Map data is available under the Open Database License (ODbL) 1.0: [url=https://www.openstreetmap.org/copyright]openstreetmap.org/copyright[/url]. Read live from Overpass API servers or from a Geofabrik extract of Finland; airports and stations (places.json.gz) and the Finland minimap are derived from it and likewise under the ODbL.",
		"Start-map tiles © OpenStreetMap contributors (tile.openstreetmap.org); place names by Nominatim.",
		"",
		"[b]Trains[/b]",
		"Source: Fintraffic / digitraffic.fi, license CC 4.0 BY ([url=https://creativecommons.org/licenses/by/4.0/]creativecommons.org/licenses/by/4.0[/url]). Modified: the passenger timetable and train compositions are condensed for the game.",
		"",
		"[b]Weather[/b]",
		"Finnish Meteorological Institute (FMI) open data, CC BY 4.0. Modified: resampled and combined from the nearest stations.",
		"",
		"[b]Resident names[/b]",
		"Digital and Population Data Services Agency (DVV) name data, CC BY 4.0 ([url=https://nimipalvelu.dvv.fi/]nimipalvelu.dvv.fi[/url]). Modified: the most common names selected.",
		"",
		"[b]Municipalities[/b]",
		"Compiled from Wikipedia, © Wikipedia contributors, CC BY-SA 4.0 ([url=https://creativecommons.org/licenses/by-sa/4.0/]creativecommons.org/licenses/by-sa/4.0[/url]). Modified: tables combined; the data file is likewise CC BY-SA 4.0.",
		"",
		"[b]Ice hockey and football fixtures[/b]",
		"Schedules, results and attendances from the public Liiga and Veikkausliiga result services; the source data remains copyright of Liiga, Veikkausliiga and their data providers.",
		"",
		"[b]Sounds[/b]",
		"Sound effects generated with Stable Audio Open (Stability AI). Speech and station announcements generated with Chatterbox (Resemble AI) and Microsoft Azure Speech.",
		"",
		"[b]Software[/b]",
		"Godot Engine (MIT, © Godot Engine contributors), its components below, Python and its libraries, and osmium-tool (GPL-3.0; its source is published with every release). Full notices: THIRD_PARTY_LICENSES.md in the game folder.",
	])
	return "\n".join(lines)


func _credits_menu() -> void:
	_clear()
	_title(_t("credits").to_upper())
	var text := RichTextLabel.new()
	text.bbcode_enabled = true
	text.custom_minimum_size = Vector2(640, 420)
	text.scroll_active = true
	text.text = credits_text() + "\n\n[b]Godot Engine[/b]\n" + Engine.get_license_text() + "\n" + _godot_components()
	text.meta_clicked.connect(func(meta): OS.shell_open(str(meta)))
	_body.add_child(text)
	_focusables.append(text)
	_button(_t("back"), _main_menu)
	_back_action = _main_menu
	_focus_menu()


## Godot's third-party components and their licences (Engine.get_copyright_info).
static func _godot_components() -> String:
	var lines := PackedStringArray()
	var licences: Dictionary = Engine.get_license_info()
	for component in Engine.get_copyright_info():
		for part in component["parts"]:
			lines.append("%s: %s, %s" % [component["name"], ", ".join(part["copyright"]), part["license"]])
	lines.append("")
	for name in licences:
		lines.append("[b]%s[/b]\n%s" % [name, licences[name]])
	return "\n".join(lines)


func _main_menu() -> void:
	get_tree().paused = false
	_clear()
	_title("ROAD RAGE TRIP", _t("choose_start"))
	var career := _button(_t("career"), func(): _start("career"))
	var gig := _button(_t("gig_driver"), _city_menu)
	_button(_t("settings"), _settings_menu)
	_button(_t("credits"), _credits_menu)
	_button(_t("clear_cache"), _confirm_clear_cache)
	_button(_t("quit"), get_tree().quit)
	_focus_menu()
	# Enter: the mode played last time (gig driving the first time).
	(career if _settings.get_value("menu", "mode", "gig_driver") == "career" else gig).call_deferred("grab_focus")


## "Clear all map cache": asked first; then the server deletes
## the OSM downloads and the built worlds, and maps load fresh next time.
func _confirm_clear_cache() -> void:
	_clear()
	_title(_t("clear_cache").to_upper(), _t("confirm_clear_cache"))
	var no := _button(_t("cancel"), _main_menu)
	_button(_t("clear"), func():
		_clear()
		_title(_t("clearing"))
		await get_tree().process_frame
		var removed := _server_query("--clear-cache")
		_clear()
		_title(_t("clear_cache").to_upper(),
			_t("cache_cleared_done") if removed.size() == 2 else _t("cache_clear_failed"))
		_button(_t("back"), _main_menu)
		_back_action = _main_menu
		_focus_menu())
	_back_action = _main_menu
	_focus_menu()
	no.call_deferred("grab_focus")  # Enter does not delete anything


## "Reset taxi home": asked first; then every city's home is forgotten.
func _confirm_reset_home() -> void:
	_clear()
	_title(_t("reset_home").to_upper(), _t("confirm_reset_home"))
	var no := _button(_t("cancel"), _settings_menu)
	_button(_t("delete"), func():
		_server_query("--reset-home")
		_settings_menu())
	_back_action = _settings_menu
	_focus_menu()
	no.call_deferred("grab_focus")  # Enter does not delete anything


func _city_menu() -> void:
	_clear()
	_title(_t("choose_city"), _t("gig_driver"))
	var choices := OptionButton.new()
	for city in _cities:
		choices.add_item(str(city))
	choices.selected = maxi(0, _cities.find(_city))
	var select_city := func(index: int):
		_city = str(_cities[index])
		_start_point = Vector2.INF
		choices.select(index)
		_settings.set_value("gig", "city", _city)
		_settings.save("user://settings.cfg")
	choices.item_selected.connect(select_city)

	var map_size := Vector2(420, 360)
	var map := Control.new()
	map.custom_minimum_size = map_size
	map.size = map_size
	map.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	var map_image := TextureRect.new()
	var svg := FileAccess.get_file_as_string("res://finland_minimap.svg")
	var image := Image.new()
	if not svg.is_empty() and image.load_svg_from_string(svg) == OK:
		map_image.texture = ImageTexture.create_from_image(image)
	map_image.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	map_image.stretch_mode = TextureRect.STRETCH_SCALE
	map_image.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	map_image.mouse_filter = Control.MOUSE_FILTER_IGNORE
	map.add_child(map_image)
	for i in _city_locations.size():
		var location: Dictionary = _city_locations[i]
		var city_index := i
		var marker := Button.new()
		marker.tooltip_text = str(location["name"])
		marker.focus_mode = Control.FOCUS_NONE  # the synced dropdown owns keyboard/controller selection
		marker.custom_minimum_size = Vector2(12, 12)
		marker.size = Vector2(12, 12)
		marker.position = city_map_position(
			float(location["latitude"]), float(location["longitude"]), map_size
		) - marker.size / 2.0
		for state in ["normal", "hover", "pressed"]:
			var dot := StyleBoxFlat.new()
			dot.bg_color = Color.WHITE if state == "hover" else Color8(255, 205, 26)
			dot.set_corner_radius_all(6)
			marker.add_theme_stylebox_override(state, dot)
		marker.pressed.connect(func(): select_city.call(city_index))
		map.add_child(marker)
	_body.add_child(map)
	_body.add_child(choices)
	_focusables.append(choices)
	var drive := _button(_t("drive"), func():
		_start_point = Vector2.INF
		_time_menu())
	_button(_t("custom_map_point"), _map_point_menu)
	_button(_t("back"), _main_menu)
	_back_action = _main_menu
	_focus_menu()
	drive.call_deferred("grab_focus")  # Enter: on to the start time (the remembered city)


## "Custom map point >": a map browser; the gig starts on the road
## nearest the pin, with the nearest city's settings (weather, traffic).
func _map_point_menu() -> void:
	_clear()
	_title(_t("custom_map_point").trim_suffix(" >").to_upper(), _t("map_point_help"))
	var browser := MapBrowser.new()
	var saved := Vector2(_settings.get_value("gig", "point_latitude", INF), _settings.get_value("gig", "point_longitude", INF))
	if saved.x != INF:
		browser.pin = saved
		browser.show_point(saved.x, saved.y)
	else:
		var location: Dictionary = _city_locations[maxi(0, _cities.find(_city))]
		browser.show_point(float(location["latitude"]), float(location["longitude"]))
	_body.add_child(browser)
	_focusables.append(browser)
	var place := Label.new()
	place.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_body.add_child(place)
	var drive := _button(_t("drive"), func():
		_start_point = browser.pin
		_city = nearest_city(_municipalities, browser.pin.x, browser.pin.y)
		_time_menu())
	var show_pin := func():
		drive.disabled = browser.pin == Vector2.INF
		if not drive.disabled:
			var pin := browser.pin
			var settings: String = _t("map_point_settings") % nearest_city(_municipalities, pin.x, pin.y)
			place.text = "%.5f, %.5f  (%s)" % [pin.x, pin.y, settings]
			_start_place = ""
			_reverse_geocode(pin, func(name: String):
				if browser.pin == pin and is_instance_valid(place):  # not a stale answer
					_start_place = name
					place.text = "%s  (%s)" % [name, settings])
	show_pin.call()
	browser.picked.connect(func(latitude: float, longitude: float):
		_settings.set_value("gig", "point_latitude", latitude)
		_settings.set_value("gig", "point_longitude", longitude)
		_settings.save("user://settings.cfg")
		show_pin.call())
	_button(_t("back"), _city_menu)
	_back_action = _city_menu
	_focus_menu()


## The pin's municipality/village name from OSM Nominatim (one request per
## click, within its 1 request/s policy); offline, callback never fires.
func _reverse_geocode(pin: Vector2, callback: Callable) -> void:
	var request := HTTPRequest.new()
	add_child(request)
	request.request_completed.connect(func(result: int, code: int, _headers, body: PackedByteArray):
		request.queue_free()
		if result != HTTPRequest.RESULT_SUCCESS or code != 200:
			return
		var data = JSON.parse_string(body.get_string_from_utf8())
		if data is Dictionary and data.has("address"):
			var address: Dictionary = data["address"]
			for key in ["village", "town", "city", "municipality", "hamlet"]:
				if address.has(key):
					callback.call(str(address[key]))
					return)
	var agent := "RoadRageTrip/%s (Godot)" % ProjectSettings.get_setting("application/config/version")
	request.request("https://nominatim.openstreetmap.org/reverse?format=json&zoom=10&lat=%.5f&lon=%.5f&accept-language=%s"
		% [pin.x, pin.y, _language], ["User-Agent: " + agent])


static func nearest_city(locations: Array, latitude: float, longitude: float) -> String:
	var best := ""
	var best_d := INF
	for location in locations:
		var d := Vector2(float(location["latitude"]) - latitude,
			(float(location["longitude"]) - longitude) * cos(deg_to_rad(latitude))).length_squared()
		if d < best_d:
			best_d = d
			best = str(location["name"])
	return best


## The gig's --bbox around a custom start: 3 km square, like the city presets.
static func point_bbox(latitude: float, longitude: float) -> String:
	var dlat := 1.5 / 111.0
	var dlon := dlat / maxf(0.1, cos(deg_to_rad(latitude)))
	return "%.6f,%.6f,%.6f,%.6f" % [latitude - dlat, longitude - dlon, latitude + dlat, longitude + dlon]


static func city_map_position(latitude: float, longitude: float, size: Vector2) -> Vector2:
	var scale := size.y / 11.0
	return Vector2(
		size.x / 2.0 + (longitude - 25.5) * cos(deg_to_rad(65.0)) * scale,
		clampf((70.5 - latitude) / 11.0, 0.0, 1.0) * size.y,
	)


## The gig start picker: year, month, day, hour and minute of the
## gig's start, a calendar year back at most, no later than today.
func _time_menu() -> void:
	var resume: Dictionary = _settings.get_value("gig", "left_at", {})  # where the last gig ended, unless Now was picked
	var from_now: bool = _settings.get_value("gig", "start_now", true) or resume.is_empty()
	_start_time = clamp_start(Time.get_datetime_dict_from_system() if from_now else resume, Time.get_date_dict_from_system())
	_clear()
	_title(_t("start_time"), _city)
	var fields := [["year", _t("year")], ["month", _t("month")], ["day", _t("day")],
		["hour", _t("hour")], ["minute", _t("minute")]]
	var spins := {}
	for field in fields:
		var row := HBoxContainer.new()
		var label := Label.new()
		label.text = field[1]
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(label)
		var spin := SpinBox.new()
		spin.min_value = {"year": 1900, "month": 1, "day": 1, "hour": 0, "minute": 0}[field[0]]
		spin.max_value = {"year": 9999, "month": 12, "day": 31, "hour": 23, "minute": 59}[field[0]]
		spin.custom_minimum_size.x = 160
		spins[field[0]] = spin
		row.add_child(spin)
		_body.add_child(row)
		_focusables.append(spin.get_line_edit())
	var show := func():
		for key in spins:
			spins[key].set_value_no_signal(_start_time[key])
	for key in spins:
		spins[key].value_changed.connect(func(value: float):
			_start_time[key] = int(value)
			_start_time = clamp_start(_start_time, Time.get_date_dict_from_system())
			_settings.set_value("gig", "start_now", false)
			show.call())
	show.call()
	_button(_t("now"), func():
		_start_time = clamp_start(Time.get_datetime_dict_from_system(), Time.get_date_dict_from_system())
		_settings.set_value("gig", "start_now", true)
		show.call())
	var start := _button(_t("start"), func(): _start("gig_driver"))
	_button(_t("back"), _city_menu)
	_back_action = _city_menu
	_focus_menu()
	start.call_deferred("grab_focus")  # Enter plays from now


## A start time inside [the same day a year ago, today] (calendar.py
## clamp_start_datetime; 29 February a year back is the 28th), the day
## within its month.
static func clamp_start(value: Dictionary, today: Dictionary) -> Dictionary:
	var out := {}
	for key in ["year", "month", "day", "hour", "minute"]:
		out[key] = int(value.get(key, today.get(key, 0)))
	out["month"] = clampi(out["month"], 1, 12)
	out["hour"] = clampi(out["hour"], 0, 23)
	out["minute"] = clampi(out["minute"], 0, 59)
	var earliest := {"year": int(today["year"]) - 1, "month": int(today["month"]), "day": mini(int(today["day"]), _days_in(int(today["year"]) - 1, int(today["month"])))}
	out["day"] = clampi(out["day"], 1, _days_in(out["year"], out["month"]))
	var key := func(d: Dictionary) -> int: return int(d["year"]) * 10000 + int(d["month"]) * 100 + int(d["day"])
	for limit in [[earliest, key.call(out) < key.call(earliest)], [today, key.call(out) > key.call(today)]]:
		if limit[1]:
			for part in ["year", "month", "day"]:
				out[part] = int(limit[0][part])
	return out


## The server's map source options from the settings ("" source: the
## server's own config decides).
static func map_source_args(source: String, pbf_path: String) -> Array:
	if source == "pbf":
		return ["--osm-source", "pbf"] + (["--osm-pbf-path", pbf_path] if pbf_path != "" else [])
	if source == "overpass":
		return ["--osm-source", "overpass"]
	return []


static func downloaded_pbf_path() -> String:
	return ProjectSettings.globalize_path("user://maps/finland-latest.osm.pbf")


func _pbf_path() -> String:
	var configured := str(_settings.get_value("map", "osm_pbf_path", "")).strip_edges()
	if configured != "" and FileAccess.file_exists(configured):
		return configured
	var packaged := Paths.package_path("assets/osm/finland-latest.osm.pbf")
	if configured == "" and FileAccess.file_exists(packaged):
		return packaged
	var downloaded := downloaded_pbf_path()
	return downloaded if FileAccess.file_exists(downloaded) else ""


static func pbf_is_old(path: String, now: int) -> bool:
	var modified := FileAccess.get_modified_time(path)
	return modified > 0 and now - modified > PBF_MAX_AGE_S


static func replace_download(partial: String, target: String) -> bool:
	var backup := target + ".old"
	if FileAccess.file_exists(backup):
		DirAccess.remove_absolute(backup)
	if FileAccess.file_exists(target) and DirAccess.rename_absolute(target, backup) != OK:
		return false
	if DirAccess.rename_absolute(partial, target) == OK:
		if FileAccess.file_exists(backup):
			DirAccess.remove_absolute(backup)
		return true
	if FileAccess.file_exists(backup):
		DirAccess.rename_absolute(backup, target)
	return false


static func download_percent(downloaded: int, total: int) -> float:
	return clampf(float(downloaded) / float(total) * 100.0, 0.0, 100.0) if total > 0 else 0.0


static func _days_in(year: int, month: int) -> int:
	if month == 2:
		return 29 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 28
	return 30 if month in [4, 6, 9, 11] else 31


func _settings_menu() -> void:
	_clear()
	_title(_t("settings").to_upper())
	var language := OptionButton.new()
	for code in T.LANGUAGES:
		language.add_item(T.LANGUAGE_NAMES[code])
	language.selected = maxi(0, T.LANGUAGES.find(_language))
	language.item_selected.connect(func(index: int):
		_language = T.LANGUAGES[index]
		_settings.set_value("game", "language", _language)
		_settings.save("user://settings.cfg")
		if _game != null:
			_game.set_language(_language)
		_settings_menu.call_deferred())
	_with_help(language, "help_language")
	_focusables.append(language)
	_button(_t("graphics"), _graphics_menu)
	var historical := CheckButton.new()  # FMI weather for the city and game time
	historical.text = _t("historical_weather")
	historical.button_pressed = _settings.get_value("game", "historical_weather", false)
	historical.toggled.connect(func(on: bool):
		_settings.set_value("game", "historical_weather", on)
		_settings.save("user://settings.cfg"))
	_with_help(historical, "help_historical_weather")
	_focusables.append(historical)
	var timetable := CheckButton.new()  # the real Digitraffic timetable, else trains at a fixed interval
	timetable.text = _t("realtime_trains")
	timetable.button_pressed = _settings.get_value("game", "train_timetable", true)
	timetable.toggled.connect(func(on: bool):
		_settings.set_value("game", "train_timetable", on)
		_settings.save("user://settings.cfg"))
	_with_help(timetable, "help_train_timetable")
	_focusables.append(timetable)
	var source := OptionButton.new()  # --osm-source: the map from Overpass, or a local .osm.pbf via osmium
	source.add_item(_t("map_overpass"))
	source.add_item(_t("map_pbf"))
	source.selected = 1 if _settings.get_value("map", "osm_source", "overpass") == "pbf" else 0
	_with_help(source, "help_map_source")
	_focusables.append(source)
	var pbf_path := LineEdit.new()
	pbf_path.placeholder_text = downloaded_pbf_path()
	pbf_path.text = _settings.get_value("map", "osm_pbf_path", "")
	pbf_path.text_changed.connect(func(text: String):
		_settings.set_value("map", "osm_pbf_path", text.strip_edges())
		_settings.save("user://settings.cfg"))
	source.item_selected.connect(func(index: int):
		_settings.set_value("map", "osm_source", "pbf" if index == 1 else "overpass")
		_settings.save("user://settings.cfg")
		pbf_path.get_parent().get_parent().visible = index == 1)
	_with_help(pbf_path, "help_pbf_path")
	pbf_path.get_parent().get_parent().visible = source.selected == 1
	_focusables.append(pbf_path)
	_with_help(_button(_t("manage_pbf"), _pbf_menu), "help_manage_pbf")
	if _game == null:  # a running server keeps its home in memory
		_with_help(_button(_t("reset_home"), _confirm_reset_home), "help_reset_home")
	for item in [[_t("master_volume"), "Master", "help_master_volume"], [_t("game_volume"), "Game", "help_game_volume"],
			[_t("environment_volume"), "Environment", "help_environment_volume"], [_t("ui_volume"), "UI", "help_ui_volume"]]:
		var row := HBoxContainer.new()
		var label := Label.new()
		label.text = item[0]
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(label)
		var slider := HSlider.new()
		slider.min_value = 0.0
		slider.max_value = 1.0
		slider.step = 0.05
		slider.custom_minimum_size.x = 240
		slider.value = _settings.get_value("audio", item[1], 1.0)
		slider.value_changed.connect(func(value: float): _set_volume(item[1], value))
		row.add_child(slider)
		_with_help(row, item[2])
		_focusables.append(slider)
	var back := _pause_menu if _game != null else _main_menu
	_button(_t("back"), back)
	_back_action = back
	_focus_menu()


func _graphics_menu() -> void:
	_clear()
	_title(_t("graphics").to_upper())
	var options := Graphics.read(_settings)
	var toggles := {}
	for key in Graphics.DEFAULTS:
		var toggle := CheckButton.new()
		toggles[key] = toggle
		toggle.text = _t("graphics_" + key)
		toggle.button_pressed = options[key]
		toggle.toggled.connect(func(on: bool):
			_settings.set_value("graphics", key, on)
			_settings.save("user://settings.cfg")
			if key == "buildings_3d":
				toggles["shadows"].disabled = not on
			if _game != null:
				_game.set_graphics(Graphics.read(_settings)))
		_with_help(toggle, "help_graphics_" + key)
		_focusables.append(toggle)
	toggles["shadows"].disabled = not options["buildings_3d"]
	_button(_t("back"), _settings_menu)
	_back_action = _settings_menu
	_focus_menu()


func _set_volume(bus: String, value: float) -> void:
	var index := AudioServer.get_bus_index(bus)
	if index >= 0:
		AudioServer.set_bus_volume_db(index, linear_to_db(maxf(value, 0.0001)))
	_settings.set_value("audio", bus, value)
	_settings.save("user://settings.cfg")


func _start(mode: String, skip_pbf_offer := false) -> void:
	if _settings.get_value("map", "osm_source", "") == "pbf" and not skip_pbf_offer:
		var pbf := _pbf_path()
		if pbf == "":
			_offer_pbf_download(mode)
			return
		if pbf_is_old(pbf, int(Time.get_unix_time_from_system())):
			_offer_pbf_update(mode)
			return
	_settings.set_value("menu", "mode", mode)  # the main menu's choice next time
	_settings.save("user://settings.cfg")
	_clear()
	_title(_t("loading"), _t("starting"))
	_startup_path = ProjectSettings.globalize_path("user://startup-%d.json" % OS.get_process_id())
	_remove_startup_status()
	_startup_started = Time.get_ticks_msec()
	_startup_poll = 0.0
	_startup_changed_at = _startup_started
	_startup_last = {}
	_startup_bar = ProgressBar.new()
	_startup_bar.indeterminate = true
	_startup_bar.show_percentage = false  # stages have no reliable total duration
	_startup_bar.custom_minimum_size = Vector2(520, 20)
	_body.add_child(_startup_bar)
	_startup_stage = Label.new()
	_startup_stage.text = _t("startup_starting")
	_body.add_child(_startup_stage)
	_startup_detail = Label.new()
	_startup_detail.custom_minimum_size.x = 520
	_startup_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_body.add_child(_startup_detail)
	_startup_elapsed = Label.new()
	_body.add_child(_startup_elapsed)
	_startup_history = Label.new()
	_startup_history.add_theme_color_override("font_color", Color8(170, 185, 200))
	_body.add_child(_startup_history)
	var args := ["--port", str(PORT), "--game-mode", mode, "--language", _language, "--parent-pid", str(OS.get_process_id())]
	args.append_array(["--startup-progress", _startup_path])
	if mode == "gig_driver":
		args.append_array(["--preset", _city, "--start-time", "%04d-%02d-%02dT%02d:%02d" % [_start_time["year"], _start_time["month"], _start_time["day"], _start_time["hour"], _start_time["minute"]]])
		if _start_point != Vector2.INF:
			args.append_array(["--bbox", point_bbox(_start_point.x, _start_point.y)])
			if _start_place != "":
				args.append_array(["--place-name", _start_place])
	args.append_array(map_source_args(_settings.get_value("map", "osm_source", ""), _pbf_path()))
	if _settings.has_section_key("game", "historical_weather"):  # else the server's config decides
		args.append("--historical-weather" if _settings.get_value("game", "historical_weather") else "--no-historical-weather")
	if _settings.has_section_key("game", "train_timetable"):
		args.append("--train-timetable" if _settings.get_value("game", "train_timetable") else "--no-train-timetable")
	args.append_array(_server_extra)
	var command := Paths.server_command(args)  # the repo's .venv, or the release's bundled server
	_server_pid = OS.create_process(command[0], command[1])
	if _server_pid <= 0:
		_clear()
		_title(_t("start_failed"), _t("start_failed_detail"))
		_button(_t("back"), _main_menu)
		_back_action = _main_menu
		_focus_menu()
		return
	_game = preload("res://main.tscn").instantiate()
	_game.language = _language
	_game.set_graphics(Graphics.read(_settings))
	_game.get_node("SimClient").connection_changed.connect(_server_connected)
	add_child(_game)
	move_child(_game, 1)
	_loading = true
	_button(_t("cancel"), _stop_game)
	_back_action = _stop_game
	_focus_menu()
	for bus in ["Master", "Game", "Environment", "UI"]:
		_set_volume(bus, _settings.get_value("audio", bus, 1.0))


static func startup_status(text: String) -> Dictionary:
	var parsed = JSON.parse_string(text)
	return parsed if parsed is Dictionary and parsed.get("stage") is String and parsed.get("detail") is String and parsed.get("history") is Array else {}


func _process(delta: float) -> void:
	if not _loading:
		return
	_startup_poll -= delta
	if _startup_poll > 0.0:
		return
	_startup_poll = 0.5
	var now := Time.get_ticks_msec()
	if FileAccess.file_exists(_startup_path):
		var file := FileAccess.open(_startup_path, FileAccess.READ)
		if file != null:
			var status := startup_status(file.get_as_text()) if file.get_length() <= 16384 else {}
			file.close()  # allow the Python process to replace the file on Windows too
			if not status.is_empty() and status != _startup_last:
				_startup_last = status
				_startup_changed_at = now
				_startup_stage.text = _t("startup_" + status.stage)
				_startup_detail.text = T.startup_detail(status.detail, _language)
				var previous: Array[String] = []
				for stage in status.history.slice(0, -1):
					previous.append("· " + _t("startup_" + str(stage)))
				_startup_history.text = "\n".join(previous)
	_startup_elapsed.text = _t("startup_elapsed") % [(now - _startup_started) / 1000, (now - _startup_changed_at) / 1000]
	if _startup_last.get("stage", "") == "error" or not OS.is_process_running(_server_pid):
		_loading = false
		_startup_bar.indeterminate = false
		_startup_stage.text = _t("start_failed")
		if _startup_last.get("stage", "") != "error":
			_startup_detail.text = _t("startup_exited") + "\n" + _startup_detail.text


func _remove_startup_status() -> void:
	if _startup_path != "":
		for path in [_startup_path, _startup_path + ".tmp"]:
			if FileAccess.file_exists(path):
				DirAccess.remove_absolute(path)


func _offer_pbf_download(mode: String) -> void:
	_clear()
	_title(_t("pbf_missing"),
		_t("pbf_download_offer"))
	_button(_t("download"), func(): _download_pbf(mode))
	_button(_t("use_overpass"), func():
		_settings.set_value("map", "osm_source", "overpass")
		_settings.save("user://settings.cfg")
		_start(mode))
	_button(_t("cancel"), _main_menu)
	_back_action = _main_menu
	_focus_menu()


func _offer_pbf_update(mode: String) -> void:
	_clear()
	_title(_t("pbf_old"),
		_t("pbf_update_offer"))
	_button(_t("download_newer"), func(): _download_pbf(mode, true))
	_button(_t("use_existing"), func(): _start(mode, true))
	_button(_t("cancel"), _main_menu)
	_back_action = _main_menu
	_focus_menu()


func _download_pbf(mode: String, allow_existing := false, settings_only := false) -> void:
	_clear()
	_title(_t("downloading_map"), _t("download_wait"))
	var progress := ProgressBar.new()
	progress.custom_minimum_size = Vector2(420, 28)
	progress.indeterminate = true
	progress.show_percentage = true
	_body.add_child(progress)
	var progress_text := Label.new()
	progress_text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_body.add_child(progress_text)
	var directory := downloaded_pbf_path().get_base_dir()
	DirAccess.make_dir_recursive_absolute(directory)
	var partial := downloaded_pbf_path() + ".part"
	if FileAccess.file_exists(partial):
		DirAccess.remove_absolute(partial)
	var request := HTTPRequest.new()
	request.download_file = partial
	add_child(request)
	var response: Array = []
	request.request_completed.connect(func(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray):
		response.assign([result, response_code, headers, body]))
	var error := request.request(FINLAND_PBF_URL)
	if error != OK:
		request.queue_free()
		_pbf_download_failed(mode, allow_existing, settings_only)
		return
	while response.is_empty():
		var downloaded_bytes := request.get_downloaded_bytes()
		var total_bytes := request.get_body_size()
		progress.indeterminate = total_bytes <= 0
		if total_bytes > 0:
			progress.value = download_percent(downloaded_bytes, total_bytes)
			progress_text.text = "%.1f / %.1f MiB" % [downloaded_bytes / 1048576.0, total_bytes / 1048576.0]
		else:
			progress_text.text = "%.1f MiB" % [downloaded_bytes / 1048576.0]
		await get_tree().process_frame
	request.queue_free()
	var downloaded := FileAccess.open(partial, FileAccess.READ)
	var valid_file := downloaded != null and downloaded.get_length() > 0
	downloaded = null  # Windows cannot rename an open file.
	if int(response[0]) == HTTPRequest.RESULT_SUCCESS and int(response[1]) == 200 \
			and valid_file \
			and replace_download(partial, downloaded_pbf_path()):
		_settings.set_value("map", "osm_pbf_path", downloaded_pbf_path())
		_settings.save("user://settings.cfg")
		if settings_only:
			_settings_menu()
		else:
			_start(mode)
		return
	DirAccess.remove_absolute(partial)
	_pbf_download_failed(mode, allow_existing, settings_only)


func _pbf_download_failed(mode: String, allow_existing: bool, settings_only: bool) -> void:
	_clear()
	_title(_t("download_failed"), _t("pbf_download_failed"))
	_button(_t("retry"), func(): _download_pbf(mode, allow_existing, settings_only))
	if allow_existing:
		_button(_t("use_existing"), _settings_menu if settings_only else func(): _start(mode, true))
	var back := _settings_menu if settings_only else _main_menu
	_button(_t("cancel"), back)
	_back_action = back
	_focus_menu()


func _confirm_delete_pbf() -> void:
	_clear()
	if not FileAccess.file_exists(downloaded_pbf_path()):
		_title(_t("delete_pbf").to_upper(), _t("pbf_not_found"))
		_button(_t("back"), _settings_menu)
	else:
		_title(_t("delete_pbf").to_upper(), _t("confirm_delete_pbf"))
		_button(_t("delete"), func():
			if DirAccess.remove_absolute(downloaded_pbf_path()) == OK:
				_settings.set_value("map", "osm_pbf_path", "")
				_settings.save("user://settings.cfg")
			_settings_menu())
		_button(_t("cancel"), _settings_menu)
	_back_action = _settings_menu
	_focus_menu()


func _pbf_menu() -> void:
	_clear()
	_title(_t("manage_pbf").to_upper())
	_button(_t("force_pbf_update"), func(): _download_pbf("", FileAccess.file_exists(downloaded_pbf_path()), true))
	_button(_t("delete_pbf"), _confirm_delete_pbf)
	_button(_t("back"), _settings_menu)
	_back_action = _settings_menu
	_focus_menu()


func _server_connected(up: bool) -> void:
	if not up or not _loading:
		return
	_loading = false
	_remove_startup_status()
	_panel.visible = false
	_back.visible = false


func _pause_menu() -> void:
	get_tree().paused = true
	if _game != null and _game._help != null:
		_game._help.visible = false
	_panel.visible = true
	_back.visible = false
	_clear()
	_title(_t("paused"))
	_button(_t("resume"), _resume)
	_button(_t("settings"), _settings_menu)
	_button(_t("main_menu"), _stop_game)
	_button(_t("quit"), get_tree().quit)
	_back_action = _resume
	_focus_menu()


func _resume() -> void:
	_panel.visible = false
	get_tree().paused = false


## The gig's game date and time, so the next gig starts where this one left off.
func _remember_game_time() -> void:
	if not is_instance_valid(_game) or _settings.get_value("menu", "mode", "") != "gig_driver":
		return
	var state: Dictionary = _game.entities.shown_state()
	var calendar = state.get("calendar")
	if typeof(calendar) != TYPE_DICTIONARY or not state.has("game_time_seconds"):
		return
	var date := str(calendar.get("date", "")).split("-")
	var minutes := int(state["game_time_seconds"] / 60.0)
	if date.size() == 3:
		_settings.set_value("gig", "left_at", {"year": int(date[0]), "month": int(date[1]), "day": int(date[2]),
			"hour": minutes / 60 % 24, "minute": minutes % 60})
		_settings.save("user://settings.cfg")


func _stop_game() -> void:
	_remember_game_time()
	_loading = false
	get_tree().paused = false
	if _game != null:
		_game.queue_free()
		_game = null
	_stop_server()
	_panel.visible = true
	_back.visible = true
	_main_menu()


func _unhandled_input(event: InputEvent) -> void:
	if not event.is_action_pressed("ui_cancel"):
		return
	if _loading:
		_stop_game()
	elif _game != null:
		if _game.phone.is_open:
			return
		if get_tree().paused:
			_resume()
		else:
			_pause_menu()
	elif _back_action.is_valid():
		_back_action.call()
	get_viewport().set_input_as_handled()


func _server_query(flag: String) -> Array:
	var output: Array = []
	var command := Paths.server_command([flag])
	var code := OS.execute(command[0], command[1], output, true)
	if code != 0 or output.is_empty():
		return []
	var parsed = JSON.parse_string(output[-1].strip_edges())
	return parsed if parsed is Array else []


func _stop_server() -> void:
	if _server_pid > 0:
		OS.kill(_server_pid)
		_server_pid = -1
	_remove_startup_status()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST or what == NOTIFICATION_PREDELETE:
		_remember_game_time()
		_stop_server()
