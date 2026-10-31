## The tutorial game (startup's "Tutorial"): a fresh gig with a coach panel.
## Each step says what to do and is done when the shown state shows it
## (read only: the simulation decides, this only watches). Tab skips a step.
class_name Tutorial
extends PanelContainer

## [text key, done(main, state, baseline)]. The baseline is taken when the
## step starts (position, zoom, fares, assists).
const STEPS := [
	["tut_walk", "_walked"],
	["tut_enter_taxi", "_in_taxi"],
	["tut_engine", "_engine_on"],
	["tut_drive", "_driving"],
	["tut_zoom", "_zoomed"],
	["tut_pan", "_panned"],
	["tut_inspect", "_inspected"],
	["tut_phone", "_phone_open"],
	["tut_accept", "_fare_accepted"],
	["tut_pickup", "_passenger_in"],
	["tut_dropoff", "_fare_done"],
	["tut_trains", "_train_board"],
	["tut_assists", "_assist_toggled"],
	["tut_help", "_help_open"],
	["tut_home", "_at_home_door"],
	["tut_house", "_indoors"],
	["tut_done", ""],
]

var main: Node
var step := 0
var _baseline := {}
var _title: Label
var _text: Label
var _done_flash := 0.0


func _ready() -> void:
	custom_minimum_size = Vector2(560, 0)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.06, 0.08, 0.1, 0.9)
	style.border_color = Color8(255, 199, 0)
	style.set_border_width_all(2)
	style.set_corner_radius_all(8)
	style.set_content_margin_all(12)
	add_theme_stylebox_override("panel", style)
	var box := VBoxContainer.new()
	add_child(box)
	_title = Label.new()
	_title.add_theme_color_override("font_color", Color8(255, 205, 26))
	_title.add_theme_font_size_override("font_size", 20)
	box.add_child(_title)
	_text = Label.new()
	_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text.custom_minimum_size.x = 536
	box.add_child(_text)
	_show()


func _t(key: String) -> String:
	return I18n.text(key, main.language if main != null else "en")


func _show(notice := "") -> void:
	_title.text = _t("tut_title") % [step + 1, STEPS.size()]
	var text := _t(notice) if notice != "" else _t(STEPS[step][0]) + "\n\n" + _t("tut_skip" if step < STEPS.size() - 1 else "tut_close")
	if text != _text.text:
		_text.text = text
	_text.add_theme_color_override("font_color", Color8(255, 110, 90) if notice == "tut_nausea" else Color8(235, 238, 242))


## What must be said now instead of the step: a sick passenger (any step:
## stopping now saves the taxi), or why J showed no train board.
static func notice_key(state: Dictionary, step_check: String, board_on: bool, board_shown: bool) -> String:
	var passenger = state.get("taxi", {}).get("current_passenger")
	if passenger is Dictionary and float(passenger.get("nausea_warning_timer", 0.0)) > 0.0:
		return "tut_nausea"
	if step_check == "_train_board" and board_on and not board_shown:
		var railway = state.get("railway")
		return "tut_no_trains" if railway is Dictionary and not railway.is_empty() else "tut_no_station"
	return ""


func _process(delta: float) -> void:
	# Bottom centre, above the hint line: between the gauges and the driver portrait.
	var view := get_viewport_rect().size
	position = Vector2((view.x - size.x) / 2.0, view.y - size.y - 44.0)
	if main == null:
		return
	if _done_flash > 0.0:
		_done_flash -= delta
		if _done_flash <= 0.0:
			advance()
		return
	var state: Dictionary = main.entities.shown_state()
	if state.is_empty() or STEPS[step][1] == "":
		return
	var notice := notice_key(state, STEPS[step][1], main.show_next_train, main.hud._board.visible)
	_show(notice)
	if notice == "tut_nausea":
		return
	if _baseline.is_empty():
		_baseline = baseline(main, state)
	if call(STEPS[step][1], main, state, _baseline):
		_title.text = _t("tut_well_done")
		_done_flash = 1.2


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_TAB:
		advance()
		get_viewport().set_input_as_handled()


func advance() -> void:
	_done_flash = 0.0
	if step >= STEPS.size() - 1:
		queue_free()
		return
	step += 1
	_baseline = {}
	_show()


static func baseline(m, state: Dictionary) -> Dictionary:
	return {
		"position": m.entities.player_position(),
		"zoom": m.camera.zoom.x,
		"fares": int(state.get("taxi", {}).get("completed_fares", 0)),
		"assists": [m.speed_limiter, m.red_light_assist, m.lane_assist],
	}


func _walked(m, state: Dictionary, base: Dictionary) -> bool:
	return state.get("on_foot", true) and m.entities.player_position().distance_to(base["position"]) > 5.0


func _in_taxi(_m, state: Dictionary, _base: Dictionary) -> bool:
	return not state.get("on_foot", true)


func _engine_on(_m, state: Dictionary, _base: Dictionary) -> bool:
	return not state.get("on_foot", true) and bool(state.get("player", {}).get("engine_on", false))


func _driving(_m, state: Dictionary, _base: Dictionary) -> bool:
	return absf(float(state.get("player", {}).get("speed", 0.0))) > 4.0


func _zoomed(m, _state: Dictionary, base: Dictionary) -> bool:
	return not is_equal_approx(m.camera.zoom.x, base["zoom"])


func _panned(m, _state: Dictionary, _base: Dictionary) -> bool:
	return m._focus.get("kind") == "pan"


func _inspected(m, _state: Dictionary, _base: Dictionary) -> bool:
	return m._focus.has("id")


func _phone_open(m, _state: Dictionary, _base: Dictionary) -> bool:
	return m.phone.is_open


func _fare_accepted(_m, state: Dictionary, _base: Dictionary) -> bool:
	return not (state.get("taxi", {}).get("current_passenger") in [null, {}])


func _passenger_in(_m, state: Dictionary, _base: Dictionary) -> bool:
	return state.get("taxi", {}).get("state") == "DROPOFF"


func _fare_done(_m, state: Dictionary, base: Dictionary) -> bool:
	return int(state.get("taxi", {}).get("completed_fares", 0)) > base["fares"]


func _train_board(m, _state: Dictionary, _base: Dictionary) -> bool:
	return m.show_next_train and m.hud._board.visible


func _assist_toggled(m, _state: Dictionary, base: Dictionary) -> bool:
	return [m.speed_limiter, m.red_light_assist, m.lane_assist] != base["assists"]


func _help_open(m, _state: Dictionary, _base: Dictionary) -> bool:
	return m._help.visible


func _at_home_door(_m, state: Dictionary, _base: Dictionary) -> bool:
	var door: Dictionary = state.get("home_door", {})
	return door.get("available", false) or door.get("indoors", false)


func _indoors(_m, state: Dictionary, _base: Dictionary) -> bool:
	return state.get("home_door", {}).get("indoors", false)
