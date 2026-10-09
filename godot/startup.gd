## Godot-owned application shell: main/city/settings menus and the Python
## simulation process. The game scene remains a pure network client.
extends Control

const PORT := 8765
const T := preload("res://i18n.gd")
const Paths := preload("res://paths.gd")

var _server_pid := -1
var _game: Node
var _panel: PanelContainer
var _body: VBoxContainer
var _cities: Array = []
var _city := "Oulu"
var _language := "en"
var _settings := ConfigFile.new()
var _server_extra: Array[String] = []
var _loading := false
var _focusables: Array[Control] = []
var _back_action := Callable()
var _logo: TextureRect
var _start_time := {}  # the gig start (year, month, day, hour, minute): now, each time the picker opens
var _back: CanvasLayer  # the backdrop and logo: hidden while the game runs


func _t(key: String, english: String) -> String:
	return T.text(key, _language, english)


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
	_cities = _server_query("--list-cities")
	print("startup: %d cities from the simulation (%s)" % [_cities.size(), "release" if Paths.exported() else "repo"])
	if _cities.is_empty():
		_cities = ["Oulu"]
	_city = _settings.get_value("gig", "city", _cities[0])  # the last gig city, remembered
	if not _city in _cities:
		_city = _cities[0]
	_build_shell()
	for flag in ["--skip-menu", "--selftest", "--audiotest", "--inputtest", "--screenshot", "--bench"]:
		if flag in command_line:
			_game = preload("res://main.tscn").instantiate()
			_game.language = _language
			add_child(_game)
			move_child(_game, 1)
			_panel.visible = false
			_back.visible = false
			return
	if first_run:
		_language_menu()
	elif not (_settings.has_section_key("game", "historical_weather") and _settings.has_section_key("game", "train_timetable")):
		_online_menu()  # asked once, also of players from before the question existed
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
	_focusables[0].call_deferred("grab_focus")


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
	_title("CHOOSE LANGUAGE / VALITSE KIELI")
	_button("English", func(): _choose_language("en"))
	_button("Suomi", func(): _choose_language("fi"))
	_focus_menu()


func _choose_language(language: String) -> void:
	_language = language
	_settings.set_value("game", "language", language)
	_settings.save("user://settings.cfg")
	if _settings.has_section_key("game", "historical_weather") and _settings.has_section_key("game", "train_timetable"):
		_main_menu()
	else:
		_online_menu()  # the first run: ask once (Settings changes it later)


## First run: the real-world data, each a choice - FMI's weather for the
## city and time, Digitraffic's train timetable (off: trains at a fixed
## interval). Both on by default; Continue saves them.
func _online_menu() -> void:
	_clear()
	_title(_t("real_data", "REAL-WORLD DATA"), _t("real_data_detail", "The game can use real data for the city and time you play in."))
	var choices := {"historical_weather": [_t("realtime_weather", "Real-time weather (FMI)"), true],
		"train_timetable": [_t("realtime_trains", "Real train timetables (Digitraffic)"), true]}
	for key in choices:
		var check := CheckButton.new()
		check.text = choices[key][0]
		check.button_pressed = _settings.get_value("game", key, choices[key][1])
		_settings.set_value("game", key, check.button_pressed)
		check.toggled.connect(func(on: bool): _settings.set_value("game", key, on))
		_body.add_child(check)
		_focusables.append(check)
	var go := _button(_t("continue", "Continue"), func():
		_settings.save("user://settings.cfg")
		_main_menu())
	_back_action = Callable()
	_focus_menu()
	go.call_deferred("grab_focus")


func _main_menu() -> void:
	get_tree().paused = false
	_clear()
	_title("ROAD RAGE TRIP", _t("choose_start", "Choose how to start"))
	var career := _button(_t("career", "Career"), func(): _start("career"))
	var gig := _button(_t("gig_driver", "Gig driver"), _city_menu)
	_button(_t("settings", "Settings"), _settings_menu)
	_button(_t("clear_cache", "Clear all map cache"), _confirm_clear_cache)
	_button(_t("quit", "Quit"), get_tree().quit)
	_focus_menu()
	# Enter: the mode played last time (gig driving the first time).
	(career if _settings.get_value("menu", "mode", "gig_driver") == "career" else gig).call_deferred("grab_focus")


## Pygame's "Clear all map cache": asked first; then the server deletes
## the OSM downloads and the built worlds, and maps load fresh next time.
func _confirm_clear_cache() -> void:
	_clear()
	_title(_t("clear_cache", "Clear all map cache").to_upper(), _t("confirm_clear_cache", "Clear the map cache? Maps will be downloaded again."))
	var no := _button(_t("cancel", "Cancel"), _main_menu)
	_button(_t("clear", "Clear"), func():
		_clear()
		_title(_t("clearing", "Clearing…"))
		await get_tree().process_frame
		var removed := _server_query("--clear-cache")
		_clear()
		_title(_t("clear_cache", "Clear all map cache").to_upper(),
			_t("cache_cleared_done", "Map cache cleared.") if removed.size() == 2 else _t("cache_clear_failed", "Could not clear the map cache."))
		_button(_t("back", "Back"), _main_menu)
		_back_action = _main_menu
		_focus_menu())
	_back_action = _main_menu
	_focus_menu()
	no.call_deferred("grab_focus")  # Enter does not delete anything


func _city_menu() -> void:
	_clear()
	_title(_t("choose_city", "CHOOSE CITY"), _t("gig_driver", "Gig driver"))
	var choices := OptionButton.new()
	for city in _cities:
		choices.add_item(str(city))
	choices.selected = maxi(0, _cities.find(_city))
	choices.item_selected.connect(func(index: int):
		_city = str(_cities[index])
		_settings.set_value("gig", "city", _city)
		_settings.save("user://settings.cfg"))
	_body.add_child(choices)
	_focusables.append(choices)
	var drive := _button(_t("drive", "Drive"), _time_menu)
	_button(_t("back", "Back"), _main_menu)
	_back_action = _main_menu
	_focus_menu()
	drive.call_deferred("grab_focus")  # Enter: on to the start time (the remembered city)


## Pygame's choose_start_datetime: year, month, day, hour and minute of the
## gig's start, a calendar year back at most, no later than today.
func _time_menu() -> void:
	_start_time = clamp_start(Time.get_datetime_dict_from_system(), Time.get_date_dict_from_system())
	_clear()
	_title(_t("start_time", "START TIME"), _city)
	var fields := [["year", _t("year", "Year")], ["month", _t("month", "Month")], ["day", _t("day", "Day")],
		["hour", _t("hour", "Hour")], ["minute", _t("minute", "Minute")]]
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
			show.call())
	show.call()
	_button(_t("now", "Now"), func():
		_start_time = clamp_start(Time.get_datetime_dict_from_system(), Time.get_date_dict_from_system())
		show.call())
	var start := _button(_t("start", "Start"), func(): _start("gig_driver"))
	_button(_t("back", "Back"), _city_menu)
	_back_action = _city_menu
	_focus_menu()
	start.call_deferred("grab_focus")  # Enter plays from now


## A start time inside [the same day a year ago, today] (startup_screens.py
## _clamp_start_datetime; 29 February a year back is the 28th), the day
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


static func _days_in(year: int, month: int) -> int:
	if month == 2:
		return 29 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 28
	return 30 if month in [4, 6, 9, 11] else 31


func _settings_menu() -> void:
	_clear()
	_title(_t("settings", "SETTINGS").to_upper())
	var language := OptionButton.new()
	language.add_item("English")
	language.add_item("Suomi")
	language.selected = 1 if _language == "fi" else 0
	language.item_selected.connect(func(index: int):
		_language = "fi" if index == 1 else "en"
		_settings.set_value("game", "language", _language)
		_settings.save("user://settings.cfg")
		if _game != null:
			_game.set_language(_language))
	_body.add_child(language)
	_focusables.append(language)
	var historical := CheckButton.new()  # Pygame's settings: FMI weather for the city and game time
	historical.text = _t("historical_weather", "Historical weather (FMI)")
	historical.button_pressed = _settings.get_value("game", "historical_weather", false)
	historical.toggled.connect(func(on: bool):
		_settings.set_value("game", "historical_weather", on)
		_settings.save("user://settings.cfg"))
	_body.add_child(historical)
	_focusables.append(historical)
	var timetable := CheckButton.new()  # the real Digitraffic timetable, else trains at a fixed interval
	timetable.text = _t("realtime_trains", "Real train timetables (Digitraffic)")
	timetable.button_pressed = _settings.get_value("game", "train_timetable", true)
	timetable.toggled.connect(func(on: bool):
		_settings.set_value("game", "train_timetable", on)
		_settings.save("user://settings.cfg"))
	_body.add_child(timetable)
	_focusables.append(timetable)
	var source := OptionButton.new()  # --osm-source: the map from Overpass, or a local .osm.pbf via osmium
	source.add_item(_t("map_overpass", "Map data: Overpass (online)"))
	source.add_item(_t("map_pbf", "Map data: local .osm.pbf file"))
	source.selected = 1 if _settings.get_value("map", "osm_source", "overpass") == "pbf" else 0
	_body.add_child(source)
	_focusables.append(source)
	var pbf_path := LineEdit.new()
	pbf_path.placeholder_text = _t("pbf_default", "assets/osm/finland-latest.osm.pbf (default)")
	pbf_path.text = _settings.get_value("map", "osm_pbf_path", "")
	pbf_path.visible = source.selected == 1
	pbf_path.text_changed.connect(func(text: String):
		_settings.set_value("map", "osm_pbf_path", text.strip_edges())
		_settings.save("user://settings.cfg"))
	source.item_selected.connect(func(index: int):
		_settings.set_value("map", "osm_source", "pbf" if index == 1 else "overpass")
		_settings.save("user://settings.cfg")
		pbf_path.visible = index == 1)
	_body.add_child(pbf_path)
	_focusables.append(pbf_path)
	for item in [[_t("master_volume", "Master volume"), "Master"], [_t("game_volume", "Game volume"), "Game"], [_t("environment_volume", "Environment volume"), "Environment"], [_t("ui_volume", "UI volume"), "UI"]]:
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
		_body.add_child(row)
		_focusables.append(slider)
	var back := _pause_menu if _game != null else _main_menu
	_button(_t("back", "Back"), back)
	_back_action = back
	_focus_menu()


func _set_volume(bus: String, value: float) -> void:
	var index := AudioServer.get_bus_index(bus)
	if index >= 0:
		AudioServer.set_bus_volume_db(index, linear_to_db(maxf(value, 0.0001)))
	_settings.set_value("audio", bus, value)
	_settings.save("user://settings.cfg")


func _start(mode: String) -> void:
	_settings.set_value("menu", "mode", mode)  # the main menu's choice next time
	_settings.save("user://settings.cfg")
	_clear()
	_title(_t("loading", "LOADING"), _t("starting", "Starting the simulation…"))
	var args := ["--port", str(PORT), "--game-mode", mode, "--language", _language]
	if mode == "gig_driver":
		args.append_array(["--preset", _city, "--start-time", "%04d-%02d-%02dT%02d:%02d" % [_start_time["year"], _start_time["month"], _start_time["day"], _start_time["hour"], _start_time["minute"]]])
	args.append_array(map_source_args(_settings.get_value("map", "osm_source", ""), _settings.get_value("map", "osm_pbf_path", "")))
	if _settings.has_section_key("game", "historical_weather"):  # else the server's config decides
		args.append("--historical-weather" if _settings.get_value("game", "historical_weather") else "--no-historical-weather")
	if _settings.has_section_key("game", "train_timetable"):
		args.append("--train-timetable" if _settings.get_value("game", "train_timetable") else "--no-train-timetable")
	args.append_array(_server_extra)
	var command := Paths.server_command(args)  # the repo's .venv, or the release's bundled server
	_server_pid = OS.create_process(command[0], command[1])
	if _server_pid <= 0:
		_title(_t("start_failed", "START FAILED"), _t("start_failed_detail", "Could not launch the Python simulation"))
		_button(_t("back", "Back"), _main_menu)
		_back_action = _main_menu
		_focus_menu()
		return
	_game = preload("res://main.tscn").instantiate()
	_game.language = _language
	_game.get_node("SimClient").connection_changed.connect(_server_connected)
	add_child(_game)
	move_child(_game, 1)
	_loading = true
	for bus in ["Master", "Game", "Environment", "UI"]:
		_set_volume(bus, _settings.get_value("audio", bus, 1.0))


func _server_connected(up: bool) -> void:
	if not up or not _loading:
		return
	_loading = false
	_panel.visible = false
	_back.visible = false


func _pause_menu() -> void:
	get_tree().paused = true
	if _game != null and _game._help != null:
		_game._help.visible = false
	_panel.visible = true
	_back.visible = false
	_clear()
	_title(_t("paused", "PAUSED"))
	_button(_t("resume", "Resume"), _resume)
	_button(_t("settings", "Settings"), _settings_menu)
	_button(_t("main_menu", "Main menu"), _stop_game)
	_button(_t("quit", "Quit"), get_tree().quit)
	_back_action = _resume
	_focus_menu()


func _resume() -> void:
	_panel.visible = false
	get_tree().paused = false


func _stop_game() -> void:
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
	if _game != null:
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


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST or what == NOTIFICATION_PREDELETE:
		_stop_server()
