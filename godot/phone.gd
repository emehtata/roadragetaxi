## The driver's phone: an overlay presenting the simulation's phone rows
## (state "phone": ride offers and rail bookings). The player picks a row and
## asks to accept or reject it; the simulation decides (a "phone_result"
## event answers) - this never decides whether an offer exists.
##
## Keys (InputMap actions, added here): P/N open/close, 1-3 pick a
## row, Enter accept, X reject. None of them drive the taxi, and driving
## keys keep working while the phone is open (the simulation doesn't pause).
class_name Phone
extends PanelContainer

const T := preload("res://i18n.gd")
const DEVICE_SIZE := Vector2(390, 660)
const DEVICE_SCALE := 270.0 / DEVICE_SIZE.x

signal request(action: String, item_id: String, request_id: int)  # main sends it to the simulation
signal sound(group: String, variation: int)  # main plays it (ui.phone_open: 0 opens, 1 closes)

const ACTIONS := {
	"phone_toggle": [KEY_P, KEY_N],
	"phone_accept": [KEY_ENTER, KEY_KP_ENTER],
	"phone_reject": [KEY_X],
	"phone_pick_1": [KEY_1, KEY_KP_1],
	"phone_pick_2": [KEY_2, KEY_KP_2],
	"phone_pick_3": [KEY_3, KEY_KP_3],
}
const ANSWERABLE := ["AVAILABLE", "PENDING"]  # offer / booking statuses the simulation still takes an answer for

var is_open := false
var connected := false
var items: Array = []  # rows of the last state, in the simulation's order
var busy := false  # a fare is under way: the simulation offers nothing new
var selected_id := ""
var pending: Dictionary = {}  # request_id -> {"action", "item_id"}: asked, not yet answered
var notice := ""  # the last answer worth telling ("no longer available")
var language := "en"

var handle_result_hook = null  # selftest: sees each answer
var _next_request := 1
var _structure := ""  # what the row buttons were built for
var _rows: VBoxContainer
var _status: Label
var _protest_note: Label
var protest_active := false
var _details: Label
var _accept: Button
var _reject: Button
var _title: Label
var _close: Button
var _clock: Label
var clock_text := ""  # the game clock in the status bar (main.gd)
const BATTERY_DRAIN_PER_HOUR := 8.0  # % per game hour: a full phone lasts a working day
const BATTERY_CHARGER_AT := 20.0  # % left when it goes on the charger
const BATTERY_CHARGE_PER_HOUR := 80.0  # % per game hour: 20% to full in about an hour
var battery := randf_range(BATTERY_CHARGER_AT + 1.0, 100.0)  # each game: a phone as it happens to be
var charging := false
var _battery_label: Label
var _battery_icon: Control
var _last_game_seconds := -1.0
var _expiry_max := {}  # item id -> the longest time left seen (the card's countdown bar)
var layout = preload("res://hud_layout.gd").new(false)
var navigation: VBoxContainer
var _offers: ScrollContainer
var _buttons: HBoxContainer


func _ready() -> void:
	for action in ACTIONS:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
			for key in ACTIONS[action]:
				var event := InputEventKey.new()
				event.physical_keycode = key
				InputMap.action_add_event(action, event)
	visible = false
	custom_minimum_size = DEVICE_SIZE
	set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT, Control.PRESET_MODE_MINSIZE)
	size = DEVICE_SIZE
	scale = Vector2.ONE * DEVICE_SCALE
	var body := device_style()
	add_theme_stylebox_override("panel", body)
	var screen := PanelContainer.new()
	screen.add_theme_stylebox_override("panel", screen_style())
	add_child(screen)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	screen.add_child(box)
	var bar_margin := make_status_bar()
	box.add_child(bar_margin)
	_clock = bar_margin.get_node("Bar/Clock")
	_battery_label = bar_margin.get_node("Bar/BatteryLabel")
	_battery_icon = bar_margin.get_node("Bar/BatteryIcon")
	_battery_icon.draw.connect(_draw_battery)
	# The app's header.
	var header := PanelContainer.new()
	var header_style := StyleBoxFlat.new()
	header_style.bg_color = Color8(255, 199, 0)
	header_style.set_content_margin_all(10)
	header_style.content_margin_left = 18
	header.add_theme_stylebox_override("panel", header_style)
	var header_rows := VBoxContainer.new()
	header_rows.add_theme_constant_override("separation", 0)
	header.add_child(header_rows)
	_title = _label(29, Color8(20, 20, 20))
	header_rows.add_child(_title)
	_status = _label(14, Color8(45, 40, 20))
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	header_rows.add_child(_status)
	_protest_note = _label(16, Color8(100, 30, 15))
	_protest_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_protest_note.visible = false
	header_rows.add_child(_protest_note)
	box.add_child(header)
	var list_margin := MarginContainer.new()
	for side in ["left", "right"]:
		list_margin.add_theme_constant_override("margin_" + side, 12)
	list_margin.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(list_margin)
	_offers = ScrollContainer.new()
	_offers.focus_mode = Control.FOCUS_NONE
	_offers.get_v_scroll_bar().focus_mode = Control.FOCUS_NONE
	_offers.get_h_scroll_bar().focus_mode = Control.FOCUS_NONE
	_offers.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	list_margin.add_child(_offers)
	_rows = VBoxContainer.new()
	_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_rows.add_theme_constant_override("separation", 10)
	_offers.add_child(_rows)
	navigation = preload("res://navigation_phone.gd").new()
	navigation.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list_margin.add_child(navigation)
	_details = _label(13, Color8(150, 160, 170))
	_details.visible = false
	box.add_child(_details)
	var buttons := HBoxContainer.new()
	_buttons = buttons
	buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	buttons.add_theme_constant_override("separation", 10)
	box.add_child(buttons)
	_reject = _app_button(Color8(70, 40, 40), Color8(255, 190, 180))
	_reject.pressed.connect(reject_selected)
	buttons.add_child(_reject)
	_accept = _app_button(Color8(40, 150, 75), Color.WHITE)
	_accept.pressed.connect(accept_selected)
	buttons.add_child(_accept)
	_close = _app_button(Color8(48, 54, 62), Color8(220, 225, 230))
	_close.pressed.connect(close)
	buttons.add_child(_close)
	box.add_child(home_indicator())
	set_language(language)
	_refresh()
	resized.connect(update_layout)
	visibility_changed.connect(update_layout)
	get_viewport().size_changed.connect(update_layout)
	update_layout()


func update_layout() -> void:
	if not is_visible_in_tree():
		layout.rects.erase("navigation_phone")
		return
	var physical_size := size * scale
	# Seed the new default in the old offset coordinates, preserving saved placements.
	if not layout.offsets.has("navigation_phone"):
		layout.offsets["navigation_phone"] = Vector2(maxf(16.0, get_viewport_rect().size.x - physical_size.x - 206.0) - 16.0, 0.0)
	position = layout.place("navigation_phone", Rect2(Vector2(16, 125), physical_size), get_viewport_rect().size).position
	# Only the header drags; offer cards, scrolling and buttons remain clickable.
	layout.rects["navigation_phone"] = Rect2(position, Vector2(physical_size.x, 100 * scale.y))


func show_navigation(route: Dictionary, task := "") -> void:
	navigation.language = language
	navigation.show_navigation(route, task)


static func device_style() -> StyleBoxFlat:
	var body := StyleBoxFlat.new()
	body.bg_color = Color8(14, 16, 20)
	body.border_color = Color8(70, 78, 88)
	body.set_border_width_all(3)
	body.set_corner_radius_all(34)
	body.set_content_margin_all(14)
	return body


static func screen_style() -> StyleBoxFlat:
	var glass := StyleBoxFlat.new()
	glass.bg_color = Color8(24, 27, 33)
	glass.set_corner_radius_all(24)
	glass.set_content_margin_all(0)
	return glass


static func make_status_bar() -> MarginContainer:
	var bar := HBoxContainer.new()
	bar.name = "Bar"
	bar.add_theme_constant_override("separation", 6)
	var bar_margin := MarginContainer.new()
	for side in ["left", "right"]:
		bar_margin.add_theme_constant_override("margin_" + side, 22)
	bar_margin.add_theme_constant_override("margin_top", 10)
	bar_margin.add_child(bar)
	var clock := _label(20, Color8(235, 238, 242))
	clock.name = "Clock"
	bar.add_child(clock)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bar.add_child(spacer)
	bar.add_child(_label(19, Color8(235, 238, 242), "▂▄▆█ 5G"))
	var battery_label := _label(19, Color8(235, 238, 242))
	battery_label.name = "BatteryLabel"
	bar.add_child(battery_label)
	var battery_icon := Control.new()
	battery_icon.name = "BatteryIcon"
	battery_icon.custom_minimum_size = Vector2(38, 20)
	battery_icon.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	bar.add_child(battery_icon)
	return bar_margin


static func home_indicator() -> MarginContainer:
	var home := ColorRect.new()  # the home indicator
	home.color = Color8(120, 126, 134)
	home.custom_minimum_size = Vector2(120, 4)
	home.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	var home_margin := MarginContainer.new()
	home_margin.add_theme_constant_override("margin_bottom", 8)
	home_margin.add_child(home)
	return home_margin


static func _label(font_size: int, color: Color, text := "") -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _app_button(fill: Color, text_color: Color) -> Button:
	var button := Button.new()
	button.focus_mode = Control.FOCUS_NONE
	button.custom_minimum_size = Vector2(108, 38)
	button.add_theme_color_override("font_color", text_color)
	button.add_theme_color_override("font_disabled_color", text_color.darkened(0.5))
	for state in ["normal", "hover", "pressed", "focus", "disabled"]:
		var style := StyleBoxFlat.new()
		style.bg_color = fill.lightened(0.12) if state == "hover" else (fill.darkened(0.5) if state == "disabled" else fill)
		style.set_corner_radius_all(19)
		button.add_theme_stylebox_override(state, style)
	return button


func set_language(value: String) -> void:
	language = value
	if _title == null:
		return
	_title.text = "RageCab"
	_accept.text = T.text("phone_accept", language)
	_reject.text = T.text("phone_decline", language)
	_close.text = T.text("phone_close", language)
	_refresh()


## The battery runs on game time (`game_seconds`: since local midnight, from
## the state): it drains, goes on the charger at 20% and charges to full.
func set_game_seconds(game_seconds: float) -> void:
	var dt := game_seconds - _last_game_seconds
	if dt < 0.0:
		dt += 86400.0  # past midnight
	if _last_game_seconds >= 0.0 and dt < 3600.0:  # a bigger jump: a new game or a restart, not time passing
		var next := battery_step(battery, charging, dt)
		battery = next[0]
		charging = next[1]
	_last_game_seconds = game_seconds
	if _battery_label != null:
		_battery_label.text = "  %d%%" % roundi(battery)
		_battery_icon.queue_redraw()


static func battery_step(level: float, on_charger: bool, game_dt: float) -> Array:
	if on_charger:
		level = minf(100.0, level + BATTERY_CHARGE_PER_HOUR * game_dt / 3600.0)
		return [level, level < 100.0]
	level = maxf(0.0, level - BATTERY_DRAIN_PER_HOUR * game_dt / 3600.0)
	return [level, level <= BATTERY_CHARGER_AT]


func _draw_battery() -> void:
	draw_battery(_battery_icon, battery, charging)


static func draw_battery(icon: Control, level: float, on_charger: bool) -> void:
	var s := icon.size
	var body := Rect2(1, 2, s.x - 5, s.y - 4)
	var ink := Color8(235, 238, 242)
	icon.draw_rect(body, ink, false, 1.5)
	icon.draw_rect(Rect2(body.end.x, body.position.y + body.size.y * 0.3, 2, body.size.y * 0.4), ink)
	var fill := Color8(90, 210, 110) if on_charger else (Color8(235, 80, 70) if level <= BATTERY_CHARGER_AT else ink)
	icon.draw_rect(Rect2(body.position + Vector2(2, 2), Vector2((body.size.x - 4) * level / 100.0, body.size.y - 4)), fill)
	if on_charger:
		var c := body.get_center()
		icon.draw_colored_polygon(PackedVector2Array([c + Vector2(1, -6), c + Vector2(-4, 1), c + Vector2(0, 1),
			c + Vector2(-1, 6), c + Vector2(4, -1), c + Vector2(0, -1)]), Color8(255, 220, 40))


func open() -> void:
	if is_open:
		return
	is_open = true
	visible = true
	notice = ""
	sound.emit("ui.phone_open", 0)
	_refresh()


func close() -> void:
	if not is_open:
		return
	is_open = false
	visible = false
	sound.emit("ui.phone_open", 1)


func toggle() -> void:
	if is_open:
		close()
	else:
		open()


## The simulation's phone rows from the state on screen (every state; the
## row buttons are only rebuilt when the rows themselves change).
func show_phone(phone: Dictionary) -> void:
	items = phone.get("items", [])
	busy = phone.get("busy", false)
	var ids := items.map(func(item): return item["id"])
	for request_id in pending.keys():  # asked about a row that is gone: the answer can only be "gone"
		if not ids.has(pending[request_id]["item_id"]):
			pending.erase(request_id)
	if not ids.has(selected_id):
		selected_id = ids[0] if not ids.is_empty() else ""
	if is_open:
		_refresh()


## The connection to the simulation (SimClient.connection_changed). Without
## it nothing can be answered, and rows from the old session are stale.
func set_connected(up: bool) -> void:
	connected = up
	if not up:
		protest_active = false
		items = []
		busy = false
		pending.clear()
		selected_id = ""
		notice = ""
	_refresh()


func select(index: int) -> void:
	if index >= 0 and index < items.size():
		selected_id = items[index]["id"]
		_refresh()


func selected() -> Dictionary:
	for item in items:
		if item["id"] == selected_id:
			return item
	return {}


func can_answer() -> bool:
	var item := selected()
	return connected and not busy and not item.is_empty() and item.get("status") in ANSWERABLE and not is_pending(item["id"])


func is_pending(item_id: String) -> bool:
	return pending.values().any(func(asked): return asked["item_id"] == item_id)


func accept_selected() -> bool:
	return _ask("accept")


func reject_selected() -> bool:
	return _ask("reject")


func _ask(action: String) -> bool:
	if not can_answer():
		return false  # no connection, nothing answerable, or already asked: never a second request
	var request_id := _next_request
	_next_request += 1
	pending[request_id] = {"action": action, "item_id": selected_id}
	notice = ""
	request.emit(action, selected_id, request_id)
	_refresh()
	return true


## The simulation's answer (a "phone_result" event).
func handle_result(result: Dictionary) -> void:
	if handle_result_hook != null:
		handle_result_hook.call(result)
	var request_id := int(result.get("request_id", -1))  # JSON numbers arrive as floats; pending is keyed by int
	var asked = pending.get(request_id)
	pending.erase(request_id)
	if asked == null:
		return  # not ours, or already resolved by the row disappearing
	if not result.get("ok", false):
		notice = T.text("phone_gone" if result.get("reason") == "gone" else "phone_answer_failed", language)
	_refresh()


func _unhandled_input(event: InputEvent) -> void:
	if not event.is_pressed() or event.is_echo():
		return
	var handled := true
	if event.is_action("phone_toggle"):
		toggle()
	elif not is_open:
		return
	elif busy:
		return  # navigation must not consume fare-selection or driving keys
	elif event.is_action("phone_accept"):
		accept_selected()
	elif event.is_action("phone_reject"):
		reject_selected()
	else:
		handled = false
		for i in 3:
			if event.is_action("phone_pick_%d" % (i + 1)):
				select(i)  # the number accepts that offer at once
				accept_selected()
				handled = true
	if handled:
		get_viewport().set_input_as_handled()


func _refresh() -> void:
	if _rows == null:
		return
	var structure := "%s|%s|%s|%s" % [connected, busy, pending.keys(),
		items.map(func(item): return "%s:%s" % [item["id"], item.get("status", "")])]
	if structure != _structure:  # cards came, went or changed state: rebuild the (at most 3) cards
		_structure = structure
		for child in _rows.get_children():
			_rows.remove_child(child)  # out of the list now, freed after this frame
			child.queue_free()
		for i in items.size():
			_rows.add_child(_card(i))
	for i in min(items.size(), _rows.get_child_count()):  # values and selection: in place, no rebuild
		_fill_card(_rows.get_child(i), i)
	_status.text = status_text(connected, busy, items, notice, language)
	_status.visible = not busy
	_protest_note.text = T.text("phone_protest", language)
	_protest_note.visible = protest_active
	_offers.visible = not busy
	navigation.visible = busy
	_buttons.visible = not busy
	_clock.text = clock_text
	var item := selected()
	_details.text = details_text(item, language) if not item.is_empty() else ""
	_accept.disabled = not can_answer()
	_reject.disabled = not can_answer()
	size = DEVICE_SIZE  # app changes must not retain a transient larger minimum size
	set_deferred("size", DEVICE_SIZE)


## One offer as the app shows it: a tappable card (the whole card selects;
## its own buttons answer it) - name and distance to the customer, pickup,
## destination, the trip, and a bar running down until it expires.
func _card(index: int) -> Button:
	var card := Button.new()
	card.toggle_mode = true
	card.focus_mode = Control.FOCUS_NONE
	card.custom_minimum_size = Vector2(0, 132)
	card.pressed.connect(select.bind(index))
	for state in ["normal", "hover", "pressed", "hover_pressed"]:
		var style := StyleBoxFlat.new()
		style.bg_color = Color8(36, 41, 49) if state in ["normal", "hover"] else Color8(44, 50, 40)
		style.border_color = Color8(255, 199, 0) if state in ["pressed", "hover_pressed"] else Color8(58, 64, 72)
		style.set_border_width_all(2)
		style.set_corner_radius_all(14)
		card.add_theme_stylebox_override(state, style)
	var lines := VBoxContainer.new()
	lines.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lines.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	lines.offset_left = 14
	lines.offset_right = -14
	lines.offset_top = 10
	lines.offset_bottom = -10
	lines.add_theme_constant_override("separation", 3)
	card.add_child(lines)
	var top := HBoxContainer.new()
	top.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var title := _label(21, Color8(245, 245, 240))
	title.name = "Title"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.clip_text = true
	top.add_child(title)
	var badge := _label(15, Color8(255, 215, 95))
	badge.name = "Badge"
	top.add_child(badge)
	lines.add_child(top)
	var body := _label(17, Color8(190, 205, 212))
	body.name = "Body"
	body.clip_text = true
	body.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	lines.add_child(body)
	var expiry := ProgressBar.new()
	expiry.name = "Expiry"
	expiry.show_percentage = false
	expiry.custom_minimum_size = Vector2(0, 5)
	expiry.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var fill := StyleBoxFlat.new()
	fill.bg_color = Color8(255, 199, 0)
	fill.set_corner_radius_all(2)
	var back := StyleBoxFlat.new()
	back.bg_color = Color8(58, 64, 72)
	back.set_corner_radius_all(2)
	expiry.add_theme_stylebox_override("fill", fill)
	expiry.add_theme_stylebox_override("background", back)
	lines.add_child(expiry)
	return card


func _fill_card(card: Button, index: int) -> void:
	var item: Dictionary = items[index]
	card.text = ""
	card.set_pressed_no_signal(item["id"] == selected_id)
	var title: Label = card.find_child("Title", true, false)
	title.text = row_text(index + 1, item, is_pending(item["id"]), language)
	var badge: Label = card.find_child("Badge", true, false)
	badge.text = ("%s %s" % [item.get("train", "?"), item.get("arrival", "")]).strip_edges() if item.get("kind") == "booking" \
		else distance_text(item.get("pickup_distance_m"), language)
	var body: Label = card.find_child("Body", true, false)
	body.text = card_text(item, language)
	var expiry: ProgressBar = card.find_child("Expiry", true, false)
	var left = item.get("time_remaining_s")
	expiry.visible = typeof(left) in [TYPE_INT, TYPE_FLOAT]
	if expiry.visible:
		_expiry_max[item["id"]] = maxf(float(left), _expiry_max.get(item["id"], 0.0))
		expiry.max_value = maxf(1.0, _expiry_max[item["id"]])
		expiry.value = float(left)


## A card's lines under its title (the details, without what the title
## and the distance badge already say).
static func card_text(item: Dictionary, language := "en") -> String:
	if item.get("kind") == "booking":  # the train is the badge; the status only once it isn't pending
		var booking: Array = [T.text("phone_prebooked_from", language) % item.get("pickup", "?"),
			T.text("phone_to_short", language) % item.get("dropoff", "?"),
			(T.text("phone_fee_short", language) % (item["surcharge_cents"] / 100.0)) if item.has("surcharge_cents") else ""]
		if item.get("status", "") != "PENDING":
			booking.append(T.text("phone_status", language) % T.value_label(item.get("status"), language))
		return "\n".join(booking.filter(func(line): return line != ""))
	var lines: Array = []
	lines.append(T.text("phone_pickup_short", language) % item.get("pickup", "?"))
	lines.append(T.text("phone_to_short", language) % item.get("dropoff", "?"))
	lines.append(T.text("phone_trip_meter", language) % distance_text(item.get("trip_distance_m"), language))
	return "\n".join(lines)


## --- pure text (tested) ---

static func distance_text(metres, language := "en") -> String:
	if metres == null:
		return T.text("phone_unavailable", language)
	return "%d m" % metres if metres < 1000 else "%.2f km" % (metres / 1000.0)


static func status_text(is_connected: bool, is_busy: bool, rows: Array, last_notice: String, language := "en") -> String:
	if not is_connected:
		return T.text("phone_no_connection", language)
	if last_notice != "":
		return last_notice
	if is_busy and rows.is_empty():
		return T.text("phone_finish_fare", language)
	if rows.is_empty():
		return T.text("phone_no_requests", language)
	return T.text("phone_keys", language)


static func row_text(number: int, item: Dictionary, waiting: bool, language := "en") -> String:
	var who: String = item.get("name", "") if item.get("name", "") != "" else T.text("phone_customer", language)
	var head := "[%d] %s" % [number, who]
	if item.get("kind") == "booking":
		head = "[%d] %s" % [number, who]  # the card says it is pre-booked; the train is its badge
	if waiting:
		return head + T.text("phone_waiting", language)
	if item.get("status", "") not in ANSWERABLE:
		return head + " - " + T.value_label(item.get("status"), language)
	return head


static func details_text(item: Dictionary, language := "en") -> String:
	var lines: Array = []
	if item.get("kind") == "booking":
		lines.append(T.text("phone_booking_pickup", language) % [item.get("pickup", "?"), item.get("arrival", "?")])
		lines.append(T.text("phone_to", language) % item.get("dropoff", "?"))
		lines.append((T.text("phone_fee", language) % (item["surcharge_cents"] / 100.0)) if item.has("surcharge_cents") else T.text("phone_fee_unavailable", language))
		lines.append(T.text("phone_status", language) % T.value_label(item.get("status"), language))
	else:
		lines.append(T.text("phone_pickup", language) % item.get("pickup", "?"))
		lines.append(T.text("phone_to", language) % item.get("dropoff", "?"))
		lines.append(T.text("phone_distances", language) % [distance_text(item.get("pickup_distance_m"), language), distance_text(item.get("trip_distance_m"), language)])
		lines.append(T.text("phone_fare_unknown", language))
		if item.has("time_remaining_s"):
			lines.append(T.text("phone_expires", language) % ceili(item["time_remaining_s"]))
	return "\n".join(lines)
