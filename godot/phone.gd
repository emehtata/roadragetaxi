## The driver's phone: an overlay presenting the simulation's phone rows
## (state "phone": ride offers and rail bookings). The player picks a row and
## asks to accept or reject it; the simulation decides (a "phone_result"
## event answers) - this never decides whether an offer exists.
##
## Keys (InputMap actions, added here): P open/close, Esc close, 1-3 pick a
## row, Enter accept, X reject. None of them drive the taxi, and driving
## keys keep working while the phone is open (the simulation doesn't pause).
class_name Phone
extends PanelContainer

const T := preload("res://i18n.gd")

signal request(action: String, item_id: String, request_id: int)  # main sends it to the simulation
signal sound(group: String, variation: int)  # main plays it (ui.phone_open: 0 opens, 1 closes, as Pygame)

const ACTIONS := {
	"phone_toggle": [KEY_P],
	"phone_close": [KEY_ESCAPE],
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
var _details: Label
var _accept: Button
var _reject: Button
var _title: Label
var _close: Button
var _clock: Label
var clock_text := ""  # the game clock in the status bar (main.gd)
var _expiry_max := {}  # item id -> the longest time left seen (the card's countdown bar)


func _ready() -> void:
	for action in ACTIONS:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
			for key in ACTIONS[action]:
				var event := InputEventKey.new()
				event.physical_keycode = key
				InputMap.action_add_event(action, event)
	visible = false
	# The device: a portrait phone in the middle, the world dimmed around it
	# (a huge soft shadow is the dimming - no extra full-screen node).
	custom_minimum_size = Vector2(390, 660)
	set_anchors_and_offsets_preset(Control.PRESET_CENTER, Control.PRESET_MODE_MINSIZE)
	grow_horizontal = Control.GROW_DIRECTION_BOTH
	grow_vertical = Control.GROW_DIRECTION_BOTH
	var body := StyleBoxFlat.new()
	body.bg_color = Color8(14, 16, 20)
	body.border_color = Color8(70, 78, 88)
	body.set_border_width_all(3)
	body.set_corner_radius_all(34)
	body.set_content_margin_all(14)
	body.shadow_color = Color(0, 0, 0, 0.55)
	body.shadow_size = 2000
	add_theme_stylebox_override("panel", body)
	var screen := PanelContainer.new()
	var glass := StyleBoxFlat.new()
	glass.bg_color = Color8(24, 27, 33)
	glass.set_corner_radius_all(24)
	glass.set_content_margin_all(0)
	screen.add_theme_stylebox_override("panel", glass)
	add_child(screen)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	screen.add_child(box)
	# Status bar: the game clock, signal and battery (and the notch between).
	var bar := HBoxContainer.new()
	bar.add_theme_constant_override("separation", 6)
	var bar_margin := MarginContainer.new()
	for side in ["left", "right"]:
		bar_margin.add_theme_constant_override("margin_" + side, 22)
	bar_margin.add_theme_constant_override("margin_top", 10)
	bar_margin.add_child(bar)
	box.add_child(bar_margin)
	_clock = _label(14, Color8(235, 238, 242))
	bar.add_child(_clock)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bar.add_child(spacer)
	bar.add_child(_label(13, Color8(235, 238, 242), "▂▄▆█ 5G   82% ▮"))
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
	_title = _label(24, Color8(20, 20, 20))
	header_rows.add_child(_title)
	_status = _label(14, Color8(45, 40, 20))
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	header_rows.add_child(_status)
	box.add_child(header)
	var list_margin := MarginContainer.new()
	for side in ["left", "right"]:
		list_margin.add_theme_constant_override("margin_" + side, 12)
	list_margin.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(list_margin)
	_rows = VBoxContainer.new()
	_rows.add_theme_constant_override("separation", 10)
	list_margin.add_child(_rows)
	_details = _label(13, Color8(150, 160, 170))  # what the selected card can't fit (none today: kept for the tests' sake)
	_details.visible = false
	box.add_child(_details)
	var buttons := HBoxContainer.new()
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
	var home := ColorRect.new()  # the home indicator
	home.color = Color8(120, 126, 134)
	home.custom_minimum_size = Vector2(120, 4)
	home.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	var home_margin := MarginContainer.new()
	home_margin.add_theme_constant_override("margin_bottom", 8)
	home_margin.add_child(home)
	box.add_child(home_margin)
	set_language(language)
	_refresh()


func _label(font_size: int, color: Color, text := "") -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _app_button(fill: Color, text_color: Color) -> Button:
	var button := Button.new()
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
	_title.text = "TaxiGo"
	_accept.text = "Hyväksy ⏎" if language == "fi" else "Accept ⏎"
	_reject.text = "Hylkää X" if language == "fi" else "Decline X"
	_close.text = "Sulje P" if language == "fi" else "Close P"
	_refresh()


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
	return connected and not item.is_empty() and item.get("status") in ANSWERABLE and not is_pending(item["id"])


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
	if result.get("ok", false):
		if result.get("action") == "accept":
			close()  # as the Pygame phone: the fare is on, back to driving
	else:
		if language == "fi":
			notice = "Pyyntö ei ole enää saatavilla." if result.get("reason") == "gone" else "Pyyntöön ei voitu vastata."
		else:
			notice = "That request is no longer available." if result.get("reason") == "gone" else "The request could not be answered."
	_refresh()


func _unhandled_input(event: InputEvent) -> void:
	if not event.is_pressed() or event.is_echo():
		return
	var handled := true
	if event.is_action("phone_toggle"):
		toggle()
	elif not is_open:
		return
	elif event.is_action("phone_close"):
		close()
	elif event.is_action("phone_accept"):
		accept_selected()
	elif event.is_action("phone_reject"):
		reject_selected()
	elif event is InputEventKey and (event.physical_keycode in [KEY_UP, KEY_DOWN] or event.keycode in [KEY_UP, KEY_DOWN]) and not items.is_empty():
		var down: bool = event.physical_keycode == KEY_DOWN or event.keycode == KEY_DOWN
		var at := maxi(0, items.map(func(item): return item["id"]).find(selected_id))
		select(clampi(at + (1 if down else -1), 0, items.size() - 1))
	else:
		handled = false
		for i in 3:
			if event.is_action("phone_pick_%d" % (i + 1)):
				select(i)  # Pygame: the number accepts that offer at once
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
	_clock.text = clock_text
	var item := selected()
	_details.text = details_text(item, language) if not item.is_empty() else ""
	_accept.disabled = not can_answer()
	_reject.disabled = not can_answer()


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
	var title := _label(17, Color8(245, 245, 240))
	title.name = "Title"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.clip_text = true
	top.add_child(title)
	var badge := _label(15, Color8(255, 215, 95))
	badge.name = "Badge"
	top.add_child(badge)
	lines.add_child(top)
	var body := _label(13, Color8(190, 205, 212))
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
		var booking: Array = [("Ennakkotilaus · asemalta %s" if language == "fi" else "Pre-booked · from %s station") % item.get("pickup", "?"),
			("Kohde  %s" if language == "fi" else "To  %s") % item.get("dropoff", "?"),
			(("Ennakkotilauslisä +%.2f €" if language == "fi" else "Pre-booking fee +%.2f €") % (item["surcharge_cents"] / 100.0)) if item.has("surcharge_cents") else ""]
		if item.get("status", "") != "PENDING":
			booking.append(("Tila: %s" if language == "fi" else "Status: %s") % str(item.get("status", "?")).to_lower().replace("_", " "))
		return "\n".join(booking.filter(func(line): return line != ""))
	var lines: Array = []
	lines.append(("Nouto  %s" if language == "fi" else "Pickup  %s") % item.get("pickup", "?"))
	lines.append(("Kohde  %s" if language == "fi" else "To  %s") % item.get("dropoff", "?"))
	lines.append(("Kyyti %s · hinta mittarin mukaan" if language == "fi" else "Trip %s · fare by the meter") % distance_text(item.get("trip_distance_m"), language))
	return "\n".join(lines)


## --- pure text (tested) ---

static func distance_text(metres, language := "en") -> String:
	if metres == null:
		return "ei saatavilla" if language == "fi" else "unavailable"
	return "%d m" % metres if metres < 1000 else "%.2f km" % (metres / 1000.0)


static func status_text(is_connected: bool, is_busy: bool, rows: Array, last_notice: String, language := "en") -> String:
	if not is_connected:
		return "Ei yhteyttä simulaatioon." if language == "fi" else "No connection to the simulation."
	if last_notice != "":
		return last_notice
	if is_busy and rows.is_empty():
		return "Aja nykyinen kyyti ensin loppuun." if language == "fi" else "Finish the current fare first."
	if rows.is_empty():
		return "Ei kyytipyyntöjä juuri nyt." if language == "fi" else "No ride requests right now."
	return "1–3 hyväksyy · ↑↓ valitse · X hylkää" if language == "fi" else "1–3 accept · ↑↓ choose · X decline"


static func row_text(number: int, item: Dictionary, waiting: bool, language := "en") -> String:
	var who: String = item.get("name", "") if item.get("name", "") != "" else ("Asiakas" if language == "fi" else "Customer")
	var head := "[%d] %s" % [number, who]
	if item.get("kind") == "booking":
		head = "[%d] %s" % [number, who]  # the card says it is pre-booked; the train is its badge
	if waiting:
		return head + (" – odotetaan vastausta…" if language == "fi" else " - waiting for answer...")
	if item.get("status", "") not in ANSWERABLE:
		return head + " - " + str(item.get("status", "")).to_lower().replace("_", " ")
	return head


static func details_text(item: Dictionary, language := "en") -> String:
	var lines: Array = []
	if item.get("kind") == "booking":
		lines.append(("Nouto: %s, juna saapuu %s" if language == "fi" else "Pickup: %s station, train arrives %s") % [item.get("pickup", "?"), item.get("arrival", "?")])
		lines.append(("Määränpää: %s" if language == "fi" else "To: %s") % item.get("dropoff", "?"))
		lines.append((("Ennakkotilauslisä: +%.2f €" if language == "fi" else "Pre-booking fee: +%.2f €") % (item["surcharge_cents"] / 100.0)) if item.has("surcharge_cents") else ("Ennakkotilauslisä: ei saatavilla" if language == "fi" else "Pre-booking fee: unavailable"))
		lines.append(("Tila: %s" if language == "fi" else "Status: %s") % str(item.get("status", "?")).to_lower().replace("_", " "))
	else:
		lines.append(("Nouto: %s" if language == "fi" else "Pickup: %s") % item.get("pickup", "?"))
		lines.append(("Määränpää: %s" if language == "fi" else "To: %s") % item.get("dropoff", "?"))
		lines.append(("Asiakkaalle: %s · Kyyti: %s" if language == "fi" else "To the customer: %s · Trip: %s") % [distance_text(item.get("pickup_distance_m"), language), distance_text(item.get("trip_distance_m"), language)])
		lines.append("Hinta selviää kyydin aikana (taksamittari)" if language == "fi" else "Fare: unavailable until the ride (taximeter)")
		if item.has("time_remaining_s"):
			lines.append(("Pyyntö vanhenee %d sekunnissa" if language == "fi" else "Request expires in %d s") % ceili(item["time_remaining_s"]))
	return "\n".join(lines)
