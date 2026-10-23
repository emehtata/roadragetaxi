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
var _menu_scroll: ScrollContainer
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
var _startup_activity: Label
var _startup_busy_bar: ProgressBar
var _startup_last: Dictionary = {}
var _startup_changed_at := 0
var _focusables: Array[Control] = []
var _back_action := Callable()
var _logo: TextureRect
var _start_time := {}  # the gig start (year, month, day, hour, minute): now, each time the picker opens
var _pause_status: Label  # the pause menu's line under its title: "Saving…", "Saved"
const THUMBS := "user://save_thumbs"  # NAME.png: the game as it was when the slot was saved
const THUMB_SIZE := Vector2i(160, 90)
var _pause_shot: Image  # the frame just before the pause menu opened: a save's thumbnail
const MAX_GIG_SLOTS := 5  # gig saves; a new game beyond them replaces one (career keeps its single save)
var _save_slot := ""  # the gig's save slot (server saves/NAME.json): loaded if it exists, saved by the pause menu
var _back: CanvasLayer  # the backdrop and logo: hidden while the game runs
var _menu_music: AudioStreamPlayer


func _t(key: String) -> String:
	return T.text(key, _language)


func _ready() -> void:
	var first_run := _settings.load("user://settings.cfg") != OK or not _settings.has_section_key("game", "language")
	_language = _settings.get_value("game", "language", "en")
	AudioManager.ensure_buses()
	for bus in ["Master"] + AudioManager.BUSES:
		AudioServer.set_bus_volume_db(AudioServer.get_bus_index(bus), linear_to_db(maxf(float(_settings.get_value("audio", bus, 1.0)), 0.0001)))
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
	_play_menu_music()
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
	_body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_menu_scroll = ScrollContainer.new()
	_menu_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	# Never a scroll bar: the container takes all of its content's height
	# (at every relayout); _center_panel scales a too-tall menu to fit instead.
	_menu_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_panel.add_child(_menu_scroll)
	_menu_scroll.add_child(_body)
	# Text that wraps after the menu is built (the calendar's key help) grows
	# the content later: fit again then, or it ends up scrolling after all.
	_body.minimum_size_changed.connect(_center_panel)


func _center_panel() -> void:
	if _menu_scroll == null:
		return
	# The whole menu, never a scroll: a menu taller than the window (the
	# calendar in a small window, the city map) is scaled down to fit instead.
	_menu_scroll.custom_minimum_size.y = _body.get_combined_minimum_size().y
	_panel.reset_size()  # shrink back to the new content's size first
	var screen := get_viewport().get_visible_rect().size
	var fit := panel_fit(_panel.size, screen)
	_panel.scale = Vector2(fit, fit)
	_panel.position = ((screen - _panel.size * fit) / 2.0).floor()


## The menu panel's scale: 1, or smaller so all of it fits the window with a margin.
static func panel_fit(panel: Vector2, screen: Vector2) -> float:
	if panel.x <= 0.0 or panel.y <= 0.0:
		return 1.0
	return minf(1.0, minf((screen.x - 24.0) / panel.x, (screen.y - 24.0) / panel.y))


func _clear() -> void:
	_menu_scroll.scroll_vertical = 0
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
	question.focus_mode = Control.FOCUS_ALL
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
		"Menu music generated with Stable Audio Open 1.0 (Stability AI), using ai-audio-studio.",
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


func _play_menu_music() -> void:
	if _menu_music == null:
		var stream := AudioStreamOggVorbis.load_from_file(Paths.package_path("assets/music/menu/menu_music_1.ogg"))
		if stream == null:
			push_warning("Menu music could not be loaded")
			return
		stream.loop = true
		_menu_music = AudioStreamPlayer.new()
		_menu_music.process_mode = Node.PROCESS_MODE_ALWAYS
		_menu_music.stream = stream
		_menu_music.bus = "Music"
		_menu_music.volume_db = -12.0
		add_child(_menu_music)
	if not _menu_music.playing:
		_menu_music.play()


func _stop_menu_music() -> void:
	if is_instance_valid(_menu_music):
		_menu_music.stop()


func _main_menu() -> void:
	get_tree().paused = false
	_play_menu_music()
	_clear()
	_title("ROAD RAGE TRIP", _t("choose_start"))
	var career := _button(_t("career"), func(): _start("career"))
	var gig := _button(_t("gig_driver"), _slot_menu)
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


## Clear only the running game's homes.
func _confirm_reset_home() -> void:
	_clear()
	_title(_t("reset_home").to_upper(), _t("confirm_reset_home"))
	var no := _button(_t("cancel"), _gameplay_menu)
	_button(_t("delete"), func():
		var sim: SimClient = _game.sim
		if sim.send_clear_home():
			_gameplay_menu())
	_back_action = _gameplay_menu
	_focus_menu()
	no.call_deferred("grab_focus")  # Enter does not delete anything


## Gig driving: continue a saved game, or start a new one in a new slot.
func _slot_menu() -> void:
	_clear()
	_title(_t("save_slots"), _t("gig_driver"))
	var slots := _server_query("--list-saves").filter(func(slot): return slot is Dictionary)
	_button(_t("new_game"), func():
		if slots.size() >= MAX_GIG_SLOTS:
			_replace_slot_menu(slots)
		else:
			_save_slot = "gig-%d" % int(Time.get_unix_time_from_system())
			_city_menu())
	for slot in slots:
		var name := str(slot.get("name", ""))
		var button := _button(slot_label(slot, _t("fare_in_progress")), func():
			_save_slot = name
			_start_point = Vector2.INF
			_start_time = clamp_start(Time.get_datetime_dict_from_system(), Time.get_date_dict_from_system())
			_start("gig_driver"))  # the server takes the slot's city, place and time
		button.icon = _thumb(name)
		button.custom_minimum_size.y = THUMB_SIZE.y + 10 if button.icon != null else button.custom_minimum_size.y
	if not slots.is_empty():
		_button(_t("delete_slot"), _delete_slot_menu.bind(slots))
	_button(_t("back"), _main_menu)
	_back_action = _main_menu
	_focus_menu()


## Pick a saved game to delete; it is asked once more before it goes.
func _delete_slot_menu(slots: Array) -> void:
	_clear()
	_title(_t("delete_slot").to_upper())
	for slot in slots:
		var label := slot_label(slot, _t("fare_in_progress"))
		var path := str(slot.get("path", ""))
		_button(label, func():
			_clear()
			_title(_t("delete_slot").to_upper(), _t("confirm_delete_slot") % label)
			var no := _button(_t("cancel"), _slot_menu)
			_button(_t("delete"), func():
				if path.ends_with(str(slot.get("name", "")) + ".json"):  # only a slot file, nothing else
					DirAccess.remove_absolute(path)
					DirAccess.remove_absolute(THUMBS.path_join(str(slot.get("name", "")) + ".png"))
				_slot_menu())
			_back_action = _slot_menu
			_focus_menu()
			no.call_deferred("grab_focus"))  # Enter does not delete anything
	_button(_t("back"), _slot_menu)
	_back_action = _slot_menu
	_focus_menu()


## All gig slots are in use: the new game replaces the chosen one.
func _replace_slot_menu(slots: Array) -> void:
	_clear()
	_title(_t("save_slots"), _t("replace_slot") % MAX_GIG_SLOTS)
	for slot in slots:
		var name := str(slot.get("name", ""))
		var path := str(slot.get("path", ""))
		_button(slot_label(slot, _t("fare_in_progress")), func():
			if path.ends_with(name + ".json"):
				DirAccess.remove_absolute(path)
				DirAccess.remove_absolute(THUMBS.path_join(name + ".png"))
			_save_slot = name
			_city_menu())
	_button(_t("back"), _slot_menu)
	_back_action = _slot_menu
	_focus_menu()


## A slot's thumbnail, or null if it was saved before thumbnails (or the file is gone).
func _thumb(name: String) -> Texture2D:
	var path := THUMBS.path_join(name + ".png")
	if not FileAccess.file_exists(path):
		return null
	var image := Image.load_from_file(path)
	return ImageTexture.create_from_image(image) if image != null else null


## One saved game in the slot menu: where, the game time, the money.
static func slot_label(slot: Dictionary, fare_text: String) -> String:
	var place := str(slot.get("place_name", "")) if str(slot.get("place_name", "")) != "" else str(slot.get("city", ""))
	var when := str(slot.get("game_time", "")).replace("T", " ").left(16)
	var label := "%s · %s · %.2f €" % [place, when, float(slot.get("balance_cents", 0)) / 100.0]
	return label + (" · " + fare_text if slot.get("fare", false) else "")


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
				if is_instance_valid(browser) and is_instance_valid(place) and browser.pin == pin:  # not a stale answer (or a closed menu)
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


## The gig start picker: a calendar plus hour/minute, within the last year.
func _time_menu() -> void:
	var resume: Dictionary = _settings.get_value("gig", "left_at", {})
	var from_now: bool = _settings.get_value("gig", "start_now", true) or resume.is_empty()
	var today := Time.get_date_dict_from_system()
	_start_time = clamp_start(Time.get_datetime_dict_from_system() if from_now else resume, today)
	_clear()
	_title(_t("start_time"), _city)
	var calendar := preload("res://date_picker.gd").new()
	var earliest := clamp_start({"year": 1900, "month": 1, "day": 1}, today)
	calendar.configure(_start_time, earliest, today, _language)
	calendar.date_changed.connect(func(date: Dictionary):
		for part in ["year", "month", "day"]:
			_start_time[part] = date[part]
		_settings.set_value("gig", "start_now", false))
	_body.add_child(calendar)
	_focusables.append_array([calendar.previous, calendar, calendar.next])
	var row := HBoxContainer.new()
	_body.add_child(row)
	var spins := {}
	for key in ["hour", "minute"]:
		var label := Label.new()
		label.text = _t(key)
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(label)
		var spin := SpinBox.new()
		spin.min_value = 0
		spin.max_value = 23 if key == "hour" else 59
		spin.custom_minimum_size.x = 110
		spin.value = _start_time[key]
		spin.value_changed.connect(func(value: float):
			_start_time[key] = int(value)
			_settings.set_value("gig", "start_now", false))
		spins[key] = spin
		row.add_child(spin)
		_focusables.append(spin.get_line_edit())
	var actions := HBoxContainer.new()
	_body.add_child(actions)
	var now := _button(_t("now"), func():
		_start_time = clamp_start(Time.get_datetime_dict_from_system(), Time.get_date_dict_from_system())
		_settings.set_value("gig", "start_now", true)
		calendar.set_value(_start_time)
		for key in spins:
			spins[key].set_value_no_signal(_start_time[key]))
	var start := _button(_t("start"), func():
		for key in spins:
			spins[key].apply()
		_start("gig_driver"))
	var back := _button(_t("back"), _city_menu)
	for button in [now, start, back]:
		_body.remove_child(button)
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		actions.add_child(button)
	# Keep Tab order aligned with the header, grid, time fields and action row.
	var tab_order: Array[Control] = [calendar.previous, calendar.next, calendar,
		spins["hour"].get_line_edit(), spins["minute"].get_line_edit(), now, start, back]
	for i in tab_order.size():
		tab_order[i].focus_next = tab_order[i].get_path_to(tab_order[(i + 1) % tab_order.size()])
		tab_order[i].focus_previous = tab_order[i].get_path_to(tab_order[(i - 1 + tab_order.size()) % tab_order.size()])
	_back_action = _city_menu
	_focus_menu()
	start.call_deferred("grab_focus")


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
	_button(_t("settings_general") + " >", _general_menu)
	_button(_t("settings_gameplay") + " >", _gameplay_menu)
	_button(_t("graphics") + " >", _graphics_menu)
	_button(_t("settings_audio") + " >", _audio_menu)
	_button(_t("settings_maps") + " >", _maps_menu)
	var back := _pause_menu if _game != null else _main_menu
	_button(_t("back"), back)
	_back_action = back
	_focus_menu()


func _general_menu() -> void:
	_clear()
	_title(_t("settings_general").to_upper())
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
		_general_menu.call_deferred())
	_with_help(language, "help_language")
	_focusables.append(language)
	_button(_t("back"), _settings_menu)
	_back_action = _settings_menu
	_focus_menu()


func _gameplay_menu() -> void:
	_clear()
	_title(_t("settings_gameplay").to_upper())
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
	var intercity := CheckButton.new()
	intercity.text = _t("enable_intercity_fares")
	intercity.button_pressed = _settings.get_value("game", "intercity_fares", false)
	intercity.toggled.connect(func(on: bool):
		_settings.set_value("game", "intercity_fares", on)
		_settings.save("user://settings.cfg"))
	_with_help(intercity, "help_intercity_fares")
	_focusables.append(intercity)
	var intercity_note := Label.new()
	intercity_note.text = _t("intercity_requirements")
	intercity_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	intercity_note.custom_minimum_size.x = 500
	_body.add_child(intercity_note)
	if is_instance_valid(_game):
		_with_help(_button(_t("reset_home"), _confirm_reset_home), "help_reset_home")
	_button(_t("back"), _settings_menu)
	_back_action = _settings_menu
	_focus_menu()


func _maps_menu() -> void:
	_clear()
	_title(_t("settings_maps").to_upper())
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
	_with_help(_button(_t("manage_pbf") + " >", _pbf_menu), "help_manage_pbf")
	_button(_t("back"), _settings_menu)
	_back_action = _settings_menu
	_focus_menu()


func _audio_menu() -> void:
	_clear()
	_title(_t("settings_audio").to_upper())
	for item in [[_t("master_volume"), "Master", "help_master_volume"], [_t("game_volume"), "Game", "help_game_volume"],
			[_t("environment_volume"), "Environment", "help_environment_volume"], [_t("ui_volume"), "UI", "help_ui_volume"],
			[_t("music_volume"), "Music", "help_music_volume"]]:
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
	_button(_t("back"), _settings_menu)
	_back_action = _settings_menu
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
	if (_settings.get_value("map", "osm_source", "") == "pbf" or _settings.get_value("game", "intercity_fares", false)) and not skip_pbf_offer:
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
	_startup_busy_bar = ProgressBar.new()
	_startup_busy_bar.indeterminate = true
	_startup_busy_bar.show_percentage = false
	_startup_busy_bar.custom_minimum_size = Vector2(520, 8)
	_startup_busy_bar.visible = false
	_body.add_child(_startup_busy_bar)
	_startup_activity = Label.new()
	_startup_activity.visible = false
	_startup_activity.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_startup_activity.custom_minimum_size.x = 520
	_body.add_child(_startup_activity)
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
		if _save_slot != "":
			args.append_array(["--save-slot", _save_slot])
		if _start_point != Vector2.INF:
			args.append_array(["--bbox", point_bbox(_start_point.x, _start_point.y)])
			if _start_place != "":
				args.append_array(["--place-name", _start_place])
	args.append_array(map_source_args(_settings.get_value("map", "osm_source", ""), _pbf_path()))
	args.append("--intercity-fares" if _settings.get_value("game", "intercity_fares", false) else "--no-intercity-fares")
	if _settings.get_value("game", "intercity_fares", false) and _pbf_path() != "":
		args.append_array(["--osm-pbf-path", _pbf_path()])
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
	for bus in ["Master"] + AudioManager.BUSES:
		_set_volume(bus, _settings.get_value("audio", bus, 1.0))


static func startup_status(text: String) -> Dictionary:
	var parsed = JSON.parse_string(text)
	return parsed if parsed is Dictionary and parsed.get("stage") is String and parsed.get("detail") is String and parsed.get("history") is Array else {}


static func intercity_progress(detail: String) -> Dictionary:
	if not detail.begins_with("Initializing intercity navigation database...|"):
		return {}
	var counter := detail.split("|", true, 1)[1].split(" · ", true, 1)
	var phase := counter[0].split("/")
	if phase.size() != 2 or phase[1] != "4" or not phase[0].is_valid_int():
		return {}
	var step := int(phase[0])
	if step < 1 or step > 4:
		return {}
	var value := float(step - 1)
	if step == 4 and counter.size() == 2:
		var towns := counter[1].split("/")
		if towns.size() == 2 and towns[0].is_valid_int() and towns[1].is_valid_int() and int(towns[1]) > 0:
			value += clampf(float(towns[0]) / float(towns[1]), 0.0, 1.0)
	return {"step": step, "value": value}


func _startup_feedback(now: int) -> void:
	_startup_elapsed.text = _t("startup_elapsed") % [(now - _startup_started) / 1000, (now - _startup_changed_at) / 1000]
	var detail: String = _startup_last.get("detail", "")
	var preparing := detail.begins_with("Initializing intercity navigation database...")
	var progress := intercity_progress(detail)
	if _startup_busy_bar != null:
		_startup_busy_bar.visible = preparing and not progress.is_empty()
	_startup_bar.indeterminate = progress.is_empty()
	_startup_bar.show_percentage = false  # stage counts are not an estimate of remaining time
	if not progress.is_empty():
		_startup_bar.max_value = 4
		_startup_bar.value = progress.value
		_startup_detail.text = _t("startup_intercity_step") % [progress.step, _t("startup_intercity_" + str(progress.step))]
		var parts := detail.split(" · ", true, 1)
		if parts.size() == 2:
			_startup_detail.text += " · " + parts[1]
	if _startup_activity != null:
		_startup_activity.visible = preparing
		if preparing:
			var dots := ".".repeat(int((now - _startup_started) / 400) % 4)
			_startup_activity.text = _t("startup_intercity_wait") % dots


func _process(delta: float) -> void:
	if not _loading:
		return
	var now := Time.get_ticks_msec()
	_startup_feedback(now)  # local animation/timers must not depend on server/file updates
	_startup_poll -= delta
	if _startup_poll > 0.0:
		return
	_startup_poll = 0.5
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
	_startup_feedback(now)
	if _startup_last.get("stage", "") == "error" or not OS.is_process_running(_server_pid):
		_loading = false
		_startup_bar.indeterminate = false
		if _startup_busy_bar != null:
			_startup_busy_bar.visible = false
		if _startup_activity != null:
			_startup_activity.visible = false
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
		_settings.set_value("game", "intercity_fares", false)
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
			_maps_menu()
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
		_button(_t("use_existing"), _maps_menu if settings_only else func(): _start(mode, true))
	var back := _maps_menu if settings_only else _main_menu
	_button(_t("cancel"), back)
	_back_action = back
	_focus_menu()


func _confirm_delete_pbf() -> void:
	_clear()
	if not FileAccess.file_exists(downloaded_pbf_path()):
		_title(_t("delete_pbf").to_upper(), _t("pbf_not_found"))
		_button(_t("back"), _maps_menu)
	else:
		_title(_t("delete_pbf").to_upper(), _t("confirm_delete_pbf"))
		_button(_t("delete"), func():
			if DirAccess.remove_absolute(downloaded_pbf_path()) == OK:
				_settings.set_value("map", "osm_pbf_path", "")
				_settings.save("user://settings.cfg")
			_maps_menu())
		_button(_t("cancel"), _maps_menu)
	_back_action = _maps_menu
	_focus_menu()


func _pbf_menu() -> void:
	_clear()
	_title(_t("manage_pbf").to_upper())
	_button(_t("force_pbf_update"), func(): _download_pbf("", FileAccess.file_exists(downloaded_pbf_path()), true))
	_button(_t("delete_pbf"), _confirm_delete_pbf)
	_button(_t("back"), _maps_menu)
	_back_action = _maps_menu
	_focus_menu()


func _server_connected(up: bool) -> void:
	if not up or not _loading:
		return
	_loading = false
	_stop_menu_music()
	_remove_startup_status()
	_panel.visible = false
	_back.visible = false


func _pause_menu() -> void:
	if not get_tree().paused:  # the game itself, before the menu covers it
		_pause_shot = get_viewport().get_texture().get_image()
	get_tree().paused = true
	_play_menu_music()
	if _game != null and _game._help != null:
		_game._help.visible = false
	_panel.visible = true
	_back.visible = false
	_clear()
	_title(_t("paused"))
	_pause_status = Label.new()
	_pause_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_body.add_child(_pause_status)
	_button(_t("resume"), _resume)
	if _can_save():
		_button(_t("save_game"), func(): await _save_game(func(ok: bool): _pause_status.text = _t("saved") if ok else _t("save_failed")))
	_button(_t("settings"), _settings_menu)
	_button(_t("main_menu"), _stop_game)
	_button(_t("quit"), func():
		if _can_save():
			await _save_game(func(_ok: bool): get_tree().quit())
		else:
			get_tree().quit())
	_back_action = _resume
	_focus_menu()


func _can_save() -> bool:
	return _save_slot != "" and is_instance_valid(_game) and _settings.get_value("menu", "mode", "") == "gig_driver"


## Ask the server to write the save slot and wait (paused, so the client
## polls meanwhile) until its state acknowledges it, at most 3 s.
func _save_game(done: Callable) -> void:
	var sim: SimClient = _game.sim
	var before := sim.save_count
	if not sim.send_save():
		done.call(false)
		return
	if is_instance_valid(_pause_status):
		_pause_status.text = _t("saving")
	var mode := sim.process_mode
	sim.process_mode = Node.PROCESS_MODE_ALWAYS
	var waited := 0.0
	while sim.save_count <= before and waited < 3.0:
		await get_tree().create_timer(0.1, true).timeout
		waited += 0.1
	sim.process_mode = mode
	var ok := sim.save_count > before
	if ok and _pause_shot != null:
		var thumb := _pause_shot.duplicate() as Image
		thumb.resize(THUMB_SIZE.x, THUMB_SIZE.y, Image.INTERPOLATE_BILINEAR)
		DirAccess.make_dir_recursive_absolute(THUMBS)
		thumb.save_png(THUMBS.path_join(_save_slot + ".png"))
	done.call(ok)


func _resume() -> void:
	_stop_menu_music()
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
	# F12 in a menu (start menus, loading, pause): the running game handles
	# its own F12 first; paused or absent, it never sees the key.
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_F12:
		if is_instance_valid(_game):
			_game.save_screenshot()  # with the server's debug JSON beside it
		else:
			var path := preload("res://main.gd").screenshot_directory(OS.get_name(), OS.get_environment("USERPROFILE")).path_join(
				"screenshot_%d.png" % int(Time.get_unix_time_from_system() * 1e9))
			DirAccess.make_dir_recursive_absolute(path.get_base_dir())
			var error := get_viewport().get_texture().get_image().save_png(path)
			print("Screenshot " + (path if error == OK else "failed: %s" % error_string(error)))
		get_viewport().set_input_as_handled()
		return
	if not event.is_action_pressed("ui_cancel"):
		return
	if _loading:
		_stop_game()
	elif _panel.visible and _back_action.is_valid():
		_back_action.call()
	elif _game != null:  # the phone uses P/N, Enter, X and 1-3, never Esc
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
		_stop_menu_music()
		_remember_game_time()
		_stop_server()
