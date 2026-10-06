## Dashboard instruments from the shown state, laid out and drawn as
## Pygame's draw_hud (render/hud.py): the needle fuel gauge with its reserve
## zone and econometer, the rage face and bar, the water countdown, and the
## trip / odometer readout. Presentation only - every value comes from the
## simulation. Redrawn only when a displayed value changes.
extends Control

const RAGE_ATLAS := "../src/theroadragetrip/assets/ragefaceatlas.png"  # the same image Pygame uses
const WATER_LIMIT_S := 10.0  # main(): water_time_remaining = 10 - water_elapsed
const RESERVE_L := 10.0
const TEXT_OUTLINE := Color8(20, 24, 28, 230)
const TEXT_OUTLINE_PX := 4

var _faces: Array[Texture2D] = []
var _font: Font
var _shown := []  # the values last drawn
var _state: Dictionary = {}


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_font = ThemeDB.fallback_font
	_faces = load_rage_faces(ProjectSettings.globalize_path("res://").path_join(RAGE_ATLAS).simplify_path())


## The 11 face frames, cropped from the atlas as hud.py _load_rage_face_frames.
static func load_rage_faces(path: String) -> Array[Texture2D]:
	var faces: Array[Texture2D] = []
	var atlas := Image.load_from_file(path)
	if atlas == null:
		push_warning("instruments: no rage face atlas at %s" % path)
		return faces
	var crops := [Rect2i(0, 80, 296, 406), Rect2i(296, 80, 296, 406), Rect2i(592, 80, 296, 406),
		Rect2i(888, 80, 300, 406), Rect2i(1188, 80, 296, 406)]
	var column := atlas.get_width() / 6
	for i in 6:
		crops.append(Rect2i(i * column, 576, column, 414))
	for crop in crops:
		var frame := atlas.get_region(crop)
		var scale := minf(170.0 / frame.get_width(), 180.0 / frame.get_height())
		frame.resize(roundi(frame.get_width() * scale), roundi(frame.get_height() * scale), Image.INTERPOLATE_BILINEAR)
		faces.append(ImageTexture.create_from_image(frame))
	return faces


func show_state(state: Dictionary) -> void:
	var player: Dictionary = state.get("player", {})
	var values := [snappedf(player.get("fuel_l", 0.0), 0.1), roundi(state.get("rage_power", 0.0) * 100.0),
		snappedf(state.get("water_elapsed", 0.0), 0.1), roundi(player.get("trip_m", 0.0)), roundi(player.get("odometer_m", 0.0) / 100.0),
		snappedf(player.get("fuel_consumption_l_per_100km", 0.0), 0.1), absf(player.get("speed", 0.0)) > 0.5, size,
		speed_limit(state), price_text(state)]
	_state = state
	if values != _shown:
		_shown = values
		queue_redraw()


## render/hud.py _draw_fuel_meter's station line: the pump in refuelling
## range, priced by the server ("" without one, or with a malformed price).
static func price_text(state: Dictionary) -> String:
	var taxi = state.get("taxi", {})
	var cents = taxi.get("fuel_station_price_cents") if typeof(taxi) == TYPE_DICTIONARY else null
	if not typeof(cents) in [TYPE_INT, TYPE_FLOAT] or cents < 0:
		return ""
	return "G: REFUEL  %.2f €/L" % (int(cents) / 100.0)


## The limit of the road under the taxi, as the simulation says (0: none known).
static func speed_limit(state: Dictionary) -> int:
	var road = state.get("road")
	if typeof(road) != TYPE_DICTIONARY or road.get("speed_limit_kmh") == null:
		return 0
	return int(road["speed_limit_kmh"])


static func trip_text(trip_m: float, odometer_m: float) -> String:
	var trip := "%d m" % roundi(trip_m) if trip_m < 1000.0 else "%.2f km" % (trip_m / 1000.0)
	return "Trip: %s · Odometer: %.1f km" % [trip, odometer_m / 1000.0]


## Needle angle (radians, screen y down) for a fuel fraction: E at the left, F at the right.
static func dial_point(center: Vector2, fraction: float, distance: float, sweep := deg_to_rad(120.0)) -> Vector2:
	var angle := PI * 0.5 + sweep * (0.5 - fraction)
	return center + Vector2(cos(angle), -sin(angle)) * distance


func _draw() -> void:
	if _state.is_empty():
		return
	var player: Dictionary = _state.get("player", {})
	_draw_fuel(Vector2(210, size.y - 100), player)
	_draw_rage(Vector2(size.x - 190, size.y - 246), _state.get("rage_power", 0.0))
	var water: float = _state.get("water_elapsed", 0.0)
	if water > 0.0:
		var text := "In water: %.1f s" % (WATER_LIMIT_S - water)
		var text_size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 18)
		var box := Rect2(Vector2(size.x / 2.0 - text_size.x / 2.0 - 12.0, 78.0 - text_size.y / 2.0 - 5.0), text_size + Vector2(24, 10))
		draw_rect(box, Color8(35, 25, 15, 225))
		draw_rect(box, Color8(230, 120, 60), false, 2.0)
		draw_string(_font, box.position + Vector2(12, text_size.y), text, HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color8(255, 210, 140))
	var limit := speed_limit(_state)
	if limit > 0:  # hud.py: the round limit sign under the clock
		var sign_at := Vector2(size.x - 48.0, 76.0)
		draw_circle(sign_at, 31.0, Color8(255, 210, 0))
		draw_arc(sign_at, 27.0, 0.0, TAU, 40, Color8(210, 35, 35), 8.0)
		var digits := str(limit)
		var digits_size := _font.get_string_size(digits, HORIZONTAL_ALIGNMENT_LEFT, -1, 26)
		draw_string(_font, sign_at + Vector2(-digits_size.x / 2.0, digits_size.y / 2.0 - 5.0), digits, HORIZONTAL_ALIGNMENT_LEFT, -1, 26, Color8(20, 20, 20))
	# A dark outline keeps the light text readable on snow and on grass alike (godot-16).
	var trip := trip_text(player.get("trip_m", 0.0), player.get("odometer_m", 0.0))
	draw_string_outline(_font, Vector2(10, size.y - 230), trip, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, TEXT_OUTLINE_PX, TEXT_OUTLINE)
	draw_string(_font, Vector2(10, size.y - 230), trip, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color8(205, 215, 220))


func _draw_fuel(at: Vector2, player: Dictionary) -> void:
	var capacity := maxf(0.001, player.get("fuel_capacity_l", 50.0))
	var fraction := clampf(player.get("fuel_l", 0.0) / capacity, 0.0, 1.0)
	draw_rect(Rect2(at, Vector2(230, 78)), Color8(20, 25, 30, 220))
	draw_rect(Rect2(at, Vector2(230, 78)), Color8(130, 140, 150), false, 1.0)
	var center := at + Vector2(36, 50)
	var radius := 30.0
	var face := PackedVector2Array([center])
	for step in 25:
		face.append(dial_point(center, step / 24.0, radius, PI))
	draw_colored_polygon(face, Color8(12, 16, 20))
	var reserve := minf(RESERVE_L, capacity) / capacity
	var reserve_steps := maxi(1, roundi(reserve * 24))
	var arc := PackedVector2Array()
	for step in reserve_steps + 1:
		arc.append(dial_point(center, reserve * step / reserve_steps, radius - 3))
	draw_polyline(arc, Color8(230, 55, 45), 4.0)
	for tick in 5:
		draw_line(dial_point(center, tick / 4.0, radius - 9), dial_point(center, tick / 4.0, radius - 2), Color8(235, 220, 170), 3.0 if tick in [0, 4] else 2.0)
	var outline := face.duplicate()
	outline.append(face[0])
	draw_polyline(outline, Color8(130, 140, 150), 2.0)
	for label in [["E", 0.0], ["F", 1.0]]:
		var x := dial_point(center, label[1], radius - 13).x
		draw_string(_font, Vector2(x - 4, center.y - 2), label[0], HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color8(220, 225, 215))
	draw_line(center, dial_point(center, fraction, radius - 6), Color8(230, 65, 45), 3.0)
	draw_circle(center, 4.0, Color8(240, 220, 170))
	var economy := "%.1f l/100 km" % player.get("fuel_consumption_l_per_100km", 0.0) if absf(player.get("speed", 0.0)) > 0.5 \
		else "%.1f l/h" % player.get("idle_fuel_consumption_l_per_hour", 0.0)
	draw_string(_font, at + Vector2(74, 22), economy, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color8(205, 215, 220))
	draw_string(_font, at + Vector2(74, 40), "FUEL", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color8(205, 215, 220))
	var price := price_text(_state)
	if price != "":
		draw_string(_font, at + Vector2(74, 62), price, HORIZONTAL_ALIGNMENT_LEFT, 150, 14, Color8(255, 215, 90))


func _draw_rage(at: Vector2, rage: float) -> void:
	var text := "Rage: %d%%" % roundi(rage * 100.0)
	var text_size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 16)
	var face: Texture2D = _faces[mini(10, maxi(0, int(clampf(rage, 0.0, 1.0) * 10.0)))] if _faces.size() == 11 else null
	var face_size := face.get_size() if face != null else Vector2.ZERO
	var box := Rect2(at, Vector2(maxf(text_size.x, face_size.x) + 20.0, face_size.y + text_size.y + 24.0))
	draw_rect(box, Color8(20, 25, 30, 220))
	draw_rect(box, Color8(130, 140, 150), false, 1.0)
	if face != null:
		draw_texture(face, at + Vector2((box.size.x - face_size.x) / 2.0, 6.0))
	var text_y := at.y + face_size.y + 10.0
	draw_string(_font, Vector2(at.x + 10, text_y + text_size.y - 4), text, HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color8(255, 120, 100))
	var bar := Rect2(at.x + 10, text_y + text_size.y + 2, box.size.x - 20, 6)
	draw_rect(bar, Color8(45, 30, 30))
	draw_rect(Rect2(bar.position, Vector2(bar.size.x * clampf(rage, 0.0, 1.0), bar.size.y)), Color8(220, 55, 35))
