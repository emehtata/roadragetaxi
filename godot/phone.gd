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


func _ready() -> void:
	for action in ACTIONS:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
			for key in ACTIONS[action]:
				var event := InputEventKey.new()
				event.physical_keycode = key
				InputMap.action_add_event(action, event)
	visible = false
	custom_minimum_size = Vector2(420, 0)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	add_child(box)
	_title = Label.new()
	_title.add_theme_font_size_override("font_size", 22)
	_title.add_theme_color_override("font_color", Color(0.96, 0.86, 0.43))
	box.add_child(_title)
	_status = Label.new()
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_status)
	_rows = VBoxContainer.new()
	box.add_child(_rows)
	_details = Label.new()
	_details.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_details)
	var buttons := HBoxContainer.new()
	box.add_child(buttons)
	_accept = Button.new()
	_accept.text = "Hyväksy [Enter]" if language == "fi" else "Accept [Enter]"
	_accept.pressed.connect(accept_selected)
	buttons.add_child(_accept)
	_reject = Button.new()
	_reject.text = "Hylkää [X]" if language == "fi" else "Reject [X]"
	_reject.pressed.connect(reject_selected)
	buttons.add_child(_reject)
	_close = Button.new()
	_close.pressed.connect(close)
	buttons.add_child(_close)
	set_language(language)
	_refresh()


func set_language(value: String) -> void:
	language = value
	if _title == null:
		return
	_title.text = "TAKSIPUHELIN" if language == "fi" else "TAXI PHONE"
	_accept.text = "Hyväksy [Enter]" if language == "fi" else "Accept [Enter]"
	_reject.text = "Hylkää [X]" if language == "fi" else "Reject [X]"
	_close.text = "Sulje [P]" if language == "fi" else "Close [P]"
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
	else:
		handled = false
		for i in 3:
			if event.is_action("phone_pick_%d" % (i + 1)):
				select(i)
				handled = true
	if handled:
		get_viewport().set_input_as_handled()


func _refresh() -> void:
	if _rows == null:
		return
	var structure := "%s|%s|%s|%s" % [connected, busy, pending.keys(),
		items.map(func(item): return "%s:%s" % [item["id"], item.get("status", "")])]
	if structure != _structure:  # rows came, went or changed state: rebuild the (at most 3) row buttons
		_structure = structure
		for child in _rows.get_children():
			_rows.remove_child(child)  # out of the list now, freed after this frame
			child.queue_free()
		for i in items.size():
			var row := Button.new()
			row.alignment = HORIZONTAL_ALIGNMENT_LEFT
			row.toggle_mode = true
			row.pressed.connect(select.bind(i))
			_rows.add_child(row)
	for i in min(items.size(), _rows.get_child_count()):  # values and selection: in place, no rebuild
		var row: Button = _rows.get_child(i)
		row.text = row_text(i + 1, items[i], is_pending(items[i]["id"]), language)
		row.set_pressed_no_signal(items[i]["id"] == selected_id)
	_status.text = status_text(connected, busy, items, notice, language)
	var item := selected()
	_details.text = details_text(item, language) if not item.is_empty() else ""
	_accept.disabled = not can_answer()
	_reject.disabled = not can_answer()


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
	return "Valitse pyyntö (1–3)." if language == "fi" else "Pick a request (1-3)."


static func row_text(number: int, item: Dictionary, waiting: bool, language := "en") -> String:
	var who: String = item.get("name", "") if item.get("name", "") != "" else ("Asiakas" if language == "fi" else "Customer")
	var head := "[%d] %s" % [number, who]
	if item.get("kind") == "booking":
		head = ("[%d] Ennakkotilaus: %s, juna %s" if language == "fi" else "[%d] Pre-booked: %s, train %s") % [number, who, item.get("train", "?")]
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
