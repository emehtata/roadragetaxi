## Moving things from "state" messages, redrawn every frame from the
## interpolation buffer (StateBuffer): positions and headings are blended
## between the two states around the render time; everything discrete (an
## entity appearing, its colour, a train's cars, lamps) comes from the
## earlier one.
##
## What is drawn, and how, follows Pygame's renderers (named per function)
## at the same scale in metres. Draw order matches Pygame's: pedestrians,
## the job target, the taxi, NPC vehicles, smoke, then trains on top.
## Entities outside the visible area (plus a margin) are skipped. Text and
## a few minimum sizes are in screen pixels, as in Pygame.
extends Node2D

const RS := preload("res://render_style.gd")
const CULL_MARGIN_M := 30.0
const TWO_WHEELERS := ["motorcycle", "moped", "bicycle"]
const INDOORS := ["entering_building", "in_building"]

var origin := Vector2.ZERO
var buffer := StateBuffer.new()
var px_per_m := 9.0  # the camera's zoom (main.gd): screen pixels per metre
var drawn_entities := 0  # last frame (performance readout)
var interp_usec := 0  # time spent sampling and blending last frame
var view_rect := Rect2()  # visible area in this layer's coordinates, with margin

var _frame: Dictionary = {}  # this frame's sample: {"a", "b", "t"}
var _clock := 0.0  # local seconds, for purely presentational loops (exhaust puffs)
var _font: Font
var reflectors_on := false  # the sun below -7.5 degrees (main.gd, from state calendar)
var lamp_near := func(_at: Vector2, _radius: float) -> bool: return false  # MapLayer.lamp_near
var _reflectors: Node2D  # made in _ready (an instance never in the tree leaks nothing)
var underground := false  # the taxi below ground (state player.map_level): only it and the walker are shown
var covered := func(_at: Vector2, _layer: int) -> bool: return false  # MapLayer.covered (headlights under a bridge)
var _trains: Node2D  # trains, z 12: above the canopies and rail bridges (z 11), as Pygame draws them last
var _trains_drawn := 0
var _tracks: Node2D  # tyre tracks, z 8 (render/roads.py draw_tire_tracks, before roadworks and signs)
var _trails: Array = []  # [kind, [[position, heading, intensity, front], ...]]
var _track_points := 0
var _last_track = null  # where the last mark was laid (null: the trail is broken)
var _last_track_px := 0.0
const TRACK_STYLES := {  # render/roads.py draw_tire_tracks: [faint, dark, width m]
	"rubber": [Color8(110, 110, 110), Color8(28, 28, 28), 0.24], "dirt": [Color8(150, 138, 118), Color8(105, 68, 38), 0.75],
	"sand": [Color8(222, 208, 170), Color8(178, 158, 114), 0.75], "snow": [Color8(214, 226, 232), Color8(142, 169, 181), 0.75],
}


func _ready() -> void:
	_font = ThemeDB.fallback_font
	_reflectors = Node2D.new()
	_reflectors.z_index = 12  # above the night tint (20) and the street lights (21): 10 + 12
	_reflectors.draw.connect(_draw_reflectors)
	add_child(_reflectors)
	_trains = Node2D.new()
	_trains.z_index = 2
	_trains.draw.connect(_draw_trains)
	add_child(_trains)
	_tracks = Node2D.new()
	_tracks.z_index = -2
	_tracks.draw.connect(_draw_tracks)
	add_child(_tracks)


func now() -> float:
	return Time.get_ticks_usec() / 1000000.0


## The state the picture currently shows (discrete values: HUD, sound).
func shown_state() -> Dictionary:
	return _frame.get("a", {})


## The player's interpolated position (the camera follows it).
func player_position() -> Vector2:
	if _frame.is_empty():
		return Vector2.ZERO
	var key := "player_pedestrian" if _frame["a"].get("on_foot", false) else "player"
	var p := StateBuffer.blend(_frame["a"][key], _frame["b"].get(key, _frame["a"][key]), _frame["t"], origin)
	return Vector2(p.x, p.y)


## The job's target this frame (pickup or drop-off, as TaxiManager.get_current_target),
## or {} - shared with the screen-space arrow and compass (nav_overlay.gd).
static func current_target(state: Dictionary) -> Dictionary:
	var taxi: Dictionary = state.get("taxi", {})
	var passenger = taxi.get("current_passenger")
	if typeof(passenger) != TYPE_DICTIONARY:
		return {}
	match taxi.get("state", ""):
		"PICKUP", "WALKING":
			return passenger.get("pickup", {}).merged({"is_pickup": true})
		"DROPOFF":
			return passenger.get("dropoff", {}).merged({"is_pickup": false})
	return {}


## This frame's picture: main.gd calls it once per frame before placing
## the camera, so the camera and every drawn entity use the same sample.
## (Sampling in this node's own _process ran after main's - the camera then
## followed the previous frame's taxi: up to ~5 px of wobble at 30 km/h with
## uneven frame times, godot-08.)
func update_frame(delta: float) -> void:
	_clock += delta
	_frame = buffer.sample(now())
	queue_redraw()
	if _reflectors != null and (reflectors_on or _reflectors_drawn):
		_reflectors.queue_redraw()
	if _trains != null:
		_trains.queue_redraw()
		_lay_track()


## The server says each tick whether the taxi marks the ground (state
## tire_mark: kind, intensity, front); the trail follows the drawn taxi,
## a point every 0.5 m or 4 degrees (main()'s sampling), at most 4000
## points (the oldest trails go, down to 3500).
func _lay_track() -> void:
	if not is_equal_approx(_last_track_px, px_per_m):
		_last_track_px = px_per_m
		_tracks.queue_redraw()
	if _frame.is_empty():
		return
	var a: Dictionary = _frame["a"]
	var mark = a.get("tire_mark")
	if typeof(mark) != TYPE_DICTIONARY or a.get("on_foot", false):
		_last_track = null
		return
	var taxi := StateBuffer.blend(a["player"], _frame["b"].get("player", a["player"]), _frame["t"], origin)
	var at := Vector2(taxi.x, taxi.y)
	var kind := str(mark.get("kind", "rubber"))
	if _last_track == null or _trails.is_empty() or _trails[-1][0] != kind:
		_trails.append([kind, []])
	elif at.distance_to(_last_track[0]) < 0.5 and absf(angle_difference(taxi.z, _last_track[1])) < deg_to_rad(4.0):
		return
	_trails[-1][1].append([at, taxi.z, float(mark.get("intensity", 1.0)), bool(mark.get("front", false))])
	_last_track = [at, taxi.z]
	_track_points += 1
	if _track_points > 4000:
		while not _trails.is_empty() and _track_points > 3500:
			_track_points -= _trails.pop_front()[1].size()
	_tracks.queue_redraw()


## Each trail's tyre lines: the rear axle (1.2 m behind the centre), the
## front one too where the fronts locked; faint to dark by intensity. One
## call per kind.
func _draw_tracks() -> void:
	var started := Time.get_ticks_usec()
	var lines := {}
	for trail in _trails:
		var kind: String = trail[0]
		if not lines.has(kind):
			lines[kind] = [PackedVector2Array(), PackedColorArray()]
		var style: Array = TRACK_STYLES.get(kind, TRACK_STYLES["rubber"])
		var previous = null
		for point in trail[1]:
			if previous != null:
				var color: Color = style[0].lerp(style[1], point[2])
				for axle: float in ([-1.2, 1.2] if point[3] else [-1.2]):
					for side: float in [-0.72, 0.72]:
						lines[kind][0].append(previous[0] + _forward(previous[1]) * axle + _right(previous[1]) * side)
						lines[kind][0].append(point[0] + _forward(point[1]) * axle + _right(point[1]) * side)
						lines[kind][1].append(color)
			previous = point
	for kind in lines:
		if not lines[kind][1].is_empty():
			_tracks.draw_multiline_colors(lines[kind][0], lines[kind][1], maxf(_px(3.0), TRACK_STYLES[kind][2]))
	preload("res://perf.gd").add("tracks_draw", Time.get_ticks_usec() - started)


func _process(_delta: float) -> void:
	view_rect = (get_canvas_transform().affine_inverse() * get_viewport_rect()).grow(CULL_MARGIN_M)


var _reflectors_drawn := false


## render/pedestrians.py draw_pedestrian_reflectors: at deep night a bright
## point on everyone not lit - not in the taxi's beam cone, not within 10 m
## of a working street light.
func _draw_reflectors() -> void:
	_reflectors_drawn = reflectors_on and not _frame.is_empty()
	if not _reflectors_drawn:
		return
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var taxi := StateBuffer.blend(a["player"], b.get("player", a["player"]), t, origin)
	var walkers: Array = []
	var later := _by_id(b.get("pedestrians", []))
	for ped in a.get("pedestrians", []):
		walkers.append(StateBuffer.blend(ped, later.get(ped["id"], ped), t, origin))
	var later_npcs := _by_id(b.get("npcs", []))
	for npc in a.get("npcs", []):
		if npc.get("is_on_foot", false):
			walkers.append(StateBuffer.blend(npc, later_npcs.get(npc["id"], npc), t, origin))
	if a.get("on_foot", false):
		walkers.append(StateBuffer.blend(a["player_pedestrian"], b.get("player_pedestrian", a["player_pedestrian"]), t, origin))
	var area := view_rect.grow(15.0 - CULL_MARGIN_M)
	for walker in walkers:
		var at := Vector2(walker.x, walker.y)
		if area.has_point(at) and not reflector_lit(at, Vector2(taxi.x, taxi.y), taxi.z) and not lamp_near.call(at, 10.0):
			_reflectors.draw_circle(at, maxf(_px(1.0), 0.35), Color8(255, 255, 245))


## In the taxi's headlight cone (render/pedestrians.py is_lit): ahead within
## 15 m, sideways within 1.5 m + 0.35 per metre ahead.
static func reflector_lit(at: Vector2, taxi: Vector2, heading: float) -> bool:
	var delta := at - taxi
	var ahead := delta.dot(_forward(heading))
	return ahead > 0.0 and ahead <= 15.0 and absf(delta.dot(_right(heading))) <= 1.5 + ahead * 0.35


## render/vehicles.py draw_headlight_beams, in metres: two beams per vehicle
## with its engine on (the taxi first, then NPCs near the view, at most 80),
## each a quad from the lamp to 15 m ahead and a round cap; an NPC far from a
## street light (22 m) with nothing oncoming (45 m) has long beams (45 m).
## Polygons in layer coordinates, from this frame's sample.
func headlight_beams() -> Array:
	var polygons: Array = []
	if _frame.is_empty():
		return polygons
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var vehicles: Array = []  # [position, heading, width, is_npc]
	var player: Dictionary = a["player"]
	var road: Dictionary = a.get("road", {}) if typeof(a.get("road")) == TYPE_DICTIONARY else {}
	if player.get("engine_on", false):
		var p := StateBuffer.blend(player, b.get("player", player), t, origin)
		# Under a higher road (render/vehicles.py): no beams - unless on a bridge itself.
		if road.get("bridge", false) or not covered.call(Vector2(p.x, p.y), int(road.get("layer", 0))):
			vehicles.append([Vector2(p.x, p.y), p.z, player.get("width_m", 1.8), false])
	var later := _by_id(b.get("npcs", []))
	var area := view_rect.grow(45.0 - CULL_MARGIN_M)
	for npc in a.get("npcs", []):
		if npc.get("is_on_foot", false) or npc.get("state", "") == "PARKED":
			continue
		var p := StateBuffer.blend(npc, later.get(npc["id"], npc), t, origin)
		var layer := int(npc.get("layer", 0))  # an NPC on a raised layer counts as on its bridge
		if area.has_point(Vector2(p.x, p.y)) and not underground and (layer > 0 or not covered.call(Vector2(p.x, p.y), layer)):
			vehicles.append([Vector2(p.x, p.y), p.z, npc.get("width_m", 1.8), true])
	var shown := view_rect.grow(30.0 - CULL_MARGIN_M)
	var drawn := 0
	for vehicle in vehicles:
		if drawn >= 80:
			break
		var c: Vector2 = vehicle[0]
		if not shown.has_point(c):
			continue
		var length := 15.0
		if vehicle[3] and not lamp_near.call(c, 22.0) and not oncoming(vehicle, vehicles):
			length = 45.0
		polygons.append_array(beam_polygons(c, vehicle[1], maxf(_px(3.0), vehicle[2]), length))
		drawn += 1
	return polygons


## Another vehicle within 45 m ahead, heading the other way (Pygame's has_oncoming_vehicle).
static func oncoming(vehicle: Array, vehicles: Array) -> bool:
	var f := _forward(vehicle[1])
	for other in vehicles:
		if other == vehicle:
			continue
		var delta: Vector2 = other[0] - vehicle[0]
		var distance := delta.length()
		if distance > 0.1 and distance <= 45.0 and delta.dot(f) / distance > 0.2 and f.dot(_forward(other[1])) < -0.5:
			return true
	return false


## One vehicle's two beams and caps (Pygame's quad and circle per side).
static func beam_polygons(c: Vector2, heading: float, width: float, length: float) -> Array:
	var f := _forward(heading)
	var r := _right(heading)
	var front := c + f * (1.0 + width * 0.55)
	var polygons: Array = []
	for side: float in [-1.0, 1.0]:
		var side_v := r * side
		var lamp := front + side_v * width * 0.35
		var tip := c + f * length + r * (3.0 if side < 0.0 else 2.25)
		var near := lamp + side_v * minf(4.5 * 0.08, width * 0.10)
		var far_width := 4.5 * 1.7
		polygons.append(PackedVector2Array([lamp, near, tip + side_v * far_width, tip]))
		var cap := PackedVector2Array()
		for i in 12:
			cap.append(tip + side_v * far_width * 0.5 + Vector2(cos(TAU * i / 12.0), sin(TAU * i / 12.0)) * far_width * 0.5)
		polygons.append(cap)
	return polygons


## Pygame's draw_npc_cars draws neither police (their own renderer) nor
## drivers on foot, nor the far level-of-detail band.
static func drawn_as_vehicle(npc: Dictionary) -> bool:
	return not npc.get("is_police", false) and not npc.get("is_on_foot", false) and npc.get("lod_level", 0) < 2


func _by_id(items: Array) -> Dictionary:
	var found := {}
	for item in items:
		found[item["id"]] = item
	return found


## Screen pixels -> metres at the current zoom.
func _px(pixels: float) -> float:
	return pixels / px_per_m


static func _forward(heading: float) -> Vector2:
	return Vector2(cos(heading), -sin(heading))


static func _right(heading: float) -> Vector2:
	return Vector2(sin(heading), cos(heading))


## Vehicle-local rectangle (Pygame's _vehicle_point convention: +long is
## forward, +lat is the vehicle's right side), as a polygon.
static func _rect(c: Vector2, f: Vector2, r: Vector2, front: float, rear: float, half_width: float) -> PackedVector2Array:
	return PackedVector2Array([c + f * front + r * half_width, c + f * front - r * half_width,
		c + f * rear - r * half_width, c + f * rear + r * half_width])


func _poly(points: PackedVector2Array, fill: Color, outline = null, width := -1.0) -> void:
	draw_colored_polygon(points, fill)
	if outline != null:
		var closed := points.duplicate()
		closed.append(points[0])
		draw_polyline(closed, outline, width)


## A vehicle body by type (render/vehicles.py _draw_vehicle, _draw_bus,
## _draw_truck; two-wheelers are sprites in Pygame, a body and rider here),
## then its lamps (_draw_vehicle_lights).
func _vehicle(c: Vector2, heading: float, length: float, width: float, color: Color, kind: String,
		is_taxi: bool, engine_on: bool, braking: bool, turn_signal: String, signal_elapsed: float, fallen := false) -> void:
	length = maxf(length, _px(5.0))
	width = maxf(width, _px(2.5))
	var f := _forward(heading)
	var r := _right(heading)
	var hl := length * 0.5
	var hw := width * 0.5
	if kind in TWO_WHEELERS:
		if fallen:  # lying on its side
			f = _forward(heading - PI / 2.0)
			r = _right(heading - PI / 2.0)
		_poly(_rect(c, f, r, hl, -hl, hw), color, RS.OUTLINE)
		draw_circle(c - f * hl * 0.1, hw * 0.9, RS.CABIN)  # rider
		return
	match kind:
		"bus":
			var body := PackedVector2Array([c + f * hl + r * hw * 0.72, c + f * hl - r * hw * 0.72, c + f * hl * 0.9 - r * hw,
				c - f * hl - r * hw, c - f * hl + r * hw, c + f * hl * 0.9 + r * hw])
			_poly(body, color, RS.OUTLINE)
			var detail := color.darkened(28.0 / 255.0)
			for hatch: float in [hl * 0.55, -hl * 0.62]:
				_poly(_rect(c, f, r, hatch + hl * 0.07, hatch - hl * 0.07, hw * 0.30), detail, Color8(30, 30, 30))
			_poly(_rect(c, f, r, hl * 0.05, -hl * 0.26, hw * 0.28), detail, Color8(30, 30, 30))
		"truck":
			_poly(_rect(c, f, r, hl * 0.18, -hl, hw), color, RS.OUTLINE)
			_poly(_rect(c, f, r, hl * 0.08, -hl * 0.86, hw * 0.78), color.lightened(28.0 / 255.0))
			_poly(_rect(c, f, r, hl, hl * 0.24, hw * 0.92), color, RS.OUTLINE)
			_poly(_rect(c, f, r, hl * 0.72, hl * 0.52, hw * 0.72), RS.TRUCK_WINDSHIELD)
			draw_line(c + f * hl * 0.20 - r * hw, c + f * hl * 0.20 + r * hw, Color8(35, 35, 35), _px(2.0))
		_:
			_poly(_rect(c, f, r, hl, -hl, hw), color, RS.OUTLINE)
			var cabin_hl := hl * 0.45
			_poly(_rect(c, f, r, cabin_hl * 0.4, -cabin_hl * 0.8, hw * 0.75), RS.CABIN)
			if is_taxi:
				_poly(_rect(c, f, r, hl * 0.2, -hl * 0.2, hw * 0.4), RS.TAXI_SIGN, Color8(30, 30, 30))
	# Lamps (inset, sizes and colours as _draw_vehicle_lights, in metres).
	var light_r := maxf(_px(1.2), width * 0.18)
	var light_len := minf(width * 0.25, maxf(_px(1.0), light_r * 2.4))
	var light_w := minf(length * 0.08, maxf(_px(1.0), light_r * 0.75))
	var inset := hw * 0.7
	var tip := hl - _px(0.5)
	for side: float in [1.0, -1.0]:
		var front: Vector2 = c + f * tip + r * inset * side
		_poly(_rect(front, f, r, light_w * 0.5, -light_w * 0.5, light_len * 0.5), RS.HEADLIGHT if engine_on else RS.HEADLIGHT_OFF)
		var rear: Vector2 = c - f * tip + r * inset * side
		var scale := 1.2 if braking else 1.0
		var tail := RS.BRAKE_LIGHT if braking else (RS.TAILLIGHT if engine_on else RS.TAILLIGHT_OFF)
		_poly(_rect(rear, f, r, light_w * 0.5 * scale, -light_w * 0.5 * scale, light_len * 0.5 * scale), tail)
	if turn_signal != "" and RS.signal_lit(signal_elapsed):
		var signal_side := 1.0 if turn_signal == "right" else -1.0
		for end: float in [1.0, -1.0]:
			var lamp: Vector2 = c + f * tip * end + r * hw * 0.88 * signal_side
			_poly(_rect(lamp, f, r, light_w * 0.6, -light_w * 0.6, maxf(_px(1.0), light_len * 0.45) * 0.5), RS.TURN_SIGNAL)


## Four rising, fading puffs (render/vehicles.py crash smoke and exhaust;
## sizes in Pygame's screen pixels). `behind` trails them out of the back.
func _smoke(c: Vector2, heading: float, length: float, t: float, behind := false) -> void:
	var f := _forward(heading)
	var r := _right(heading)
	var base := c + f * (length * 0.4) * (-1.0 if behind else 1.0)
	for i in 4:
		var offset_t := fmod(t * 2.5 + i * 0.7, 2.0)
		var puff := base
		if behind:
			puff += -f * _px(offset_t * 14.0) + Vector2(0, -_px(offset_t * 3.0)) + r * _px(sin(t * 3.0 + i) * 2.0 * offset_t)
		else:
			puff += r * _px(sin(t * 3.0 + i) * 4.0 * offset_t) + Vector2(0, -_px(offset_t * 14.0))
		var smoke := RS.SMOKE
		smoke.a = clampf((1.0 - offset_t / 2.0) * RS.SMOKE_MAX_ALPHA, 0.0, RS.SMOKE_MAX_ALPHA)
		draw_circle(puff, _px(3.0 + offset_t * 5.0), smoke)


func _ellipse(c: Vector2, rx: float, ry: float, color: Color) -> void:
	draw_set_transform(c, 0.0, Vector2(rx, ry))
	draw_circle(Vector2.ZERO, 1.0, color)
	draw_set_transform(Vector2.ZERO)


## A pedestrian as render/pedestrians.py draw_pedestrians: shadow, legs
## stepping with animation_time, body, head facing the heading; fallen ones
## lie down, people going indoors are an outline; then any cursing bubble.
func _pedestrian(c: Vector2, heading: float, ped: Dictionary, animation_time: float) -> void:
	var radius := maxf(_px(4.0), ped.get("radius_m", 0.45))
	var clothing: Color = _rgb(ped.get("color", [200, 200, 200]))
	if ped.get("state", "") in INDOORS:
		draw_arc(c, radius, 0.0, TAU, 16, RS.PED_INDOORS, _px(1.0))
		return
	var h := Vector2(cos(heading), -sin(heading))
	var side := Vector2(-h.y, h.x)
	var down := Vector2(0, radius)
	_ellipse(c + down * 0.675, radius * 0.8, radius * 0.325, RS.PED_SHADOW)
	if ped.get("animation_state", "walking") == "fallen":
		_ellipse(c, radius * 1.15, radius * 0.35, clothing)
		draw_circle(c + Vector2(radius, -radius * 0.1), radius * 0.35, RS.PED_HEAD)
	else:
		var gait := sin(animation_time * 10.0) if ped.get("animation_state", "walking") == "walking" else 0.0
		var leg_start := c - h * radius * 0.15 + down * 0.45
		for leg_side: float in [-1.0, 1.0]:
			var leg_end: Vector2 = leg_start + side * radius * (0.42 * leg_side + gait * 0.10 * leg_side) + h * radius * 0.12 + down * 0.45
			draw_line(leg_start, leg_end, RS.PED_LEGS, maxf(_px(1.0), radius * 0.28))
		_ellipse(c + down * 0.425, radius * 0.72, radius * 0.775, RS.PED_SHADOW)
		_ellipse(c + down * 0.405, radius * 0.58, radius * 0.625, clothing)
		var head := c + h * radius * 0.6
		draw_circle(head, maxf(_px(2.0), radius * 0.48), RS.PED_HAIR)
		draw_circle(head, maxf(_px(1.0), radius * 0.35), RS.PED_HEAD)
	if ped.get("curse_timer", 0.0) > 0.0:
		var timer: float = ped["curse_timer"]
		_bubble(c - Vector2(0, radius + _px(6.0)), str(ped.get("curse_text", "@#*!%")), RS.CURSE_TEXT, RS.CURSE_BORDER,
			1.0 if timer >= 0.5 else timer / 0.5)


## A text bubble whose bottom centre is at `anchor`, drawn in screen
## pixels (constant size whatever the zoom), like Pygame's bubbles.
func _bubble(anchor: Vector2, text: String, text_color: Color, border: Color, alpha := 1.0, font_size := 14, tail := false) -> void:
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var box := Rect2(Vector2(-size.x / 2.0 - 4.0, -size.y - 4.0 - (8.0 if tail else 0.0)), size + Vector2(8.0, 4.0))
	draw_set_transform(anchor, 0.0, Vector2.ONE / px_per_m)
	draw_rect(box, Color(1, 1, 1, minf(240.0 / 255.0, alpha)))
	draw_rect(box, Color(border, alpha), false, 1.0)
	if tail:
		draw_colored_polygon(PackedVector2Array([Vector2(-7, -8), Vector2(7, -8), Vector2(0, 0)]), Color(1, 1, 1, alpha))
	draw_string(_font, box.position + Vector2(4.0, size.y - 2.0), text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color(text_color, alpha))
	draw_set_transform(Vector2.ZERO)


## A label with a dark background (Pygame's target and customer tags).
func _tag(anchor: Vector2, text: String, text_color: Color, border = null, font_size := 14) -> void:
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var box := Rect2(Vector2(-size.x / 2.0 - 4.0, -size.y / 2.0 - 2.0), size + Vector2(8.0, 4.0))
	draw_set_transform(anchor, 0.0, Vector2.ONE / px_per_m)
	draw_rect(box, Color8(20, 20, 20, 220))
	if border != null:
		draw_rect(box, border, false, 1.0)
	draw_string(_font, box.position + Vector2(4.0, size.y - 1.0), text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, text_color)
	draw_set_transform(Vector2.ZERO)


func _rgb(values: Array) -> Color:
	return Color8(int(values[0]), int(values[1]), int(values[2]))


## The job target and the waiting customer (render/navigation.py
## draw_taxi_target); the off-screen arrow is screen UI (nav_overlay.gd).
func _target(state: Dictionary) -> void:
	var target := current_target(state)
	if target.is_empty():
		return
	var main_color := RS.PICKUP if target["is_pickup"] else RS.DROPOFF
	var at := MapMath.point(origin, target["x"], target["y"])
	if view_rect.grow(-CULL_MARGIN_M).has_point(at):
		var radius := maxf(_px(8.0), target.get("radius_m", 10.0))
		draw_circle(at, radius, Color(main_color, 70.0 / 255.0))
		draw_arc(at, radius, 0.0, TAU, 48, main_color, _px(2.0))
		draw_circle(at, _px(7.0), main_color)
		draw_arc(at, _px(7.0), 0.0, TAU, 24, RS.OUTLINE, _px(2.0))
		_tag(at - Vector2(0, radius + _px(14.0)), "[%s] %s" % ["Pickup" if target["is_pickup"] else "Destination", target.get("address", "")],
			Color.WHITE, main_color)
	var passenger: Dictionary = state["taxi"]["current_passenger"]
	if target["is_pickup"] and not passenger.get("boarded", false) and not passenger.get("rail_booking", false) and passenger.has("ped"):
		var ped: Array = passenger["ped"]
		var c := MapMath.point(origin, ped[0], ped[1])
		var radius := maxf(_px(4.0), 0.5)
		draw_circle(c, radius + _px(2.0), RS.OUTLINE)
		draw_circle(c, radius, RS.CUSTOMER_COLOR)
		draw_circle(c + _forward(ped[2]) * radius * 0.9, maxf(_px(1.0), radius * 0.45), Color.WHITE)
		_tag(c - Vector2(0, radius + _px(12.0)), ("[TO TAXI] %s" if passenger.get("is_walking_to_car", false) else "[P] %s") % passenger.get("name", ""),
			Color8(255, 230, 80))


func _draw() -> void:
	if _frame.is_empty():
		return
	var started := Time.get_ticks_usec()
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var count := 0

	var later_peds := _by_id(b.get("pedestrians", []))
	for ped in ([] if underground else a.get("pedestrians", [])):  # below ground: the surface world isn't shown
		var next: Dictionary = later_peds.get(ped["id"], ped)
		var p := StateBuffer.blend(ped, next, t, origin)
		var c := Vector2(p.x, p.y)
		if not view_rect.has_point(c):
			continue
		_pedestrian(c, p.z, ped, lerpf(ped.get("animation_time", 0.0), next.get("animation_time", 0.0), t))
		count += 1
	var later_npc_rows := _by_id(b.get("npcs", []))
	for npc in a.get("npcs", []):  # NPC drivers out of their car: Pygame adds them to the pedestrians
		if underground or not npc.get("is_on_foot", false):
			continue
		var p := StateBuffer.blend(npc, later_npc_rows.get(npc["id"], npc), t, origin)
		var c := Vector2(p.x, p.y)
		if view_rect.has_point(c):
			_pedestrian(c, p.z, {"color": npc.get("color", [200, 200, 200])}, 0.0)
			count += 1
	if a.get("on_foot", false):
		var walker := StateBuffer.blend(a["player_pedestrian"], b.get("player_pedestrian", a["player_pedestrian"]), t, origin)
		_pedestrian(Vector2(walker.x, walker.y), walker.z, {"color": [255, 217, 64], "animation_state": "standing"}, 0.0)
		count += 1

	_target(a)

	var player: Dictionary = a["player"]
	var taxi := StateBuffer.blend(player, b.get("player", player), t, origin)
	var taxi_at := Vector2(taxi.x, taxi.y)
	var taxi_length: float = player.get("length_m", 4.4)
	if player.get("engine_on", false):
		_smoke(taxi_at, taxi.z, taxi_length, _clock, true)  # exhaust
	_vehicle(taxi_at, taxi.z, taxi_length, player.get("width_m", 1.8), RS.TAXI_BODY, "car", true,
		player.get("engine_on", false), player.get("braking", false), "", 0.0)
	var smoke_timer: float = a.get("taxi", {}).get("taxi_smoke_timer", 0.0)
	if smoke_timer > 0.0:
		_smoke(taxi_at, taxi.z, taxi_length, 5.0 - smoke_timer)
	count += 1

	var later_npcs := _by_id(b.get("npcs", []))
	for npc in a.get("npcs", []):
		if underground or not drawn_as_vehicle(npc):
			continue
		var p := StateBuffer.blend(npc, later_npcs.get(npc["id"], npc), t, origin)
		var c := Vector2(p.x, p.y)
		if not view_rect.has_point(c):
			continue
		_vehicle(c, p.z, npc["length_m"], npc["width_m"], _rgb(npc["color"]), npc.get("vehicle_type", "car"),
			npc.get("is_taxi", false), npc.get("state", "") != "PARKED", false,
			npc.get("turn_signal", ""), npc.get("turn_signal_elapsed", 0.0), npc.get("fallen", false))
		var crashed: float = npc.get("crashed_timer", 0.0)
		if crashed > 0.0:
			_smoke(c, p.z, npc["length_m"], crashed if is_finite(crashed) else _clock)
		count += 1

	if a.get("taxi", {}).get("current_passenger") is Dictionary:
		var passenger: Dictionary = a["taxi"]["current_passenger"]
		if a["taxi"].get("state") == "DROPOFF" and passenger.get("nausea_warning_timer", 0.0) > 0.0:
			_bubble(taxi_at - Vector2(0, maxf(_px(34.0), 2.5)), "I feel sick!", RS.NAUSEA_TEXT, RS.NAUSEA_TEXT, 1.0, 16, true)

	_booked_arrow(a, b, t, later_peds)

	drawn_entities = count + _trains_drawn
	interp_usec = Time.get_ticks_usec() - started
	preload("res://perf.gd").add("entities_draw", interp_usec)


## Trains, last (render/vehicles.py draw_trains after the bridge rails),
## from the same sample as everything else.
func _draw_trains() -> void:
	_trains_drawn = 0
	if _frame.is_empty() or underground:
		return
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var later_trains := _by_id(b.get("trains", []))
	for train in a.get("trains", []):
		var next: Dictionary = later_trains.get(train["id"], train)
		var same_cars: bool = next["cars"].size() == train["cars"].size()
		for i in train["cars"].size():
			var car: Array = train["cars"][i]
			var to: Array = next["cars"][i] if same_cars else car
			var c := MapMath.point(origin, lerpf(car[0], to[0], t), lerpf(car[1], to[1], t))
			if not view_rect.has_point(c):
				continue
			_train_car(c, lerp_angle(car[2], to[2], t), car[3], str(car[4]), _trains)
		_trains_drawn += 1


## This frame's lightning flash alpha (main.gd shows it above the night
## tint, as Pygame draws lightning after it).
func lightning_now() -> float:
	return 0.0 if _frame.is_empty() else lightning_alpha(_frame["a"], _frame["b"], _frame["t"])


## The flash's alpha for this frame: the simulation's fading
## lightning_intensity, blended like a position (0 without one).
static func lightning_alpha(a: Dictionary, b: Dictionary, t: float) -> float:
	var from: float = a.get("weather", {}).get("lightning_intensity", 0.0)
	var to: float = b.get("weather", {}).get("lightning_intensity", from)
	return clampf(lerpf(from, to, t), 0.0, 1.0) * RS.LIGHTNING_FLASH_MAX_ALPHA


## Where the meet's arrow points this frame: the booked passenger where
## they are drawn (by id among the pedestrians), else where the simulation
## last put them; INF when the meet has no arrow.
static func booked_arrow_at(a: Dictionary, b: Dictionary, t: float, later_peds: Dictionary, origin: Vector2) -> Vector2:
	var meet = a.get("meet")
	if typeof(meet) != TYPE_DICTIONARY or typeof(meet.get("arrow")) != TYPE_DICTIONARY:
		return Vector2.INF
	var arrow: Dictionary = meet["arrow"]
	for ped in a.get("pedestrians", []):
		if arrow.get("id") != null and ped["id"] == arrow["id"]:
			var p := StateBuffer.blend(ped, later_peds.get(ped["id"], ped), t, origin)
			return Vector2(p.x, p.y)
	return MapMath.point(origin, arrow["x"], arrow["y"])


## render/pedestrians.py draw_booked_passenger_arrow: a downward arrow over
## the booked passenger, sized in screen pixels.
func _booked_arrow(a: Dictionary, b: Dictionary, t: float, later_peds: Dictionary) -> void:
	var at := booked_arrow_at(a, b, t, later_peds, origin)
	if at == Vector2.INF or not view_rect.has_point(at):
		return
	var radius := maxf(_px(4.0), a["meet"]["arrow"].get("radius_m", 0.45))
	var tip := at - Vector2(0, radius * 1.8)
	var size := maxf(_px(8.0), radius * 1.4)
	var arrow := PackedVector2Array([tip, tip + Vector2(-size, -size * 1.3), tip + Vector2(size, -size * 1.3)])
	_poly(arrow, RS.BOOKED_CUSTOMER, RS.OUTLINE, _px(2.0))


## One train vehicle (render/vehicles.py draw_trains): body in its profile
## colour, a white cab front on a locomotive, a white stripe along a
## restaurant car, a dark roof line.
func _train_car(c: Vector2, heading: float, length: float, profile: String, node: CanvasItem = self) -> void:
	var style: Array = RS.TRAIN_PROFILES.get(profile, RS.TRAIN_PROFILES["standard"])
	var f := _forward(heading)
	var r := _right(heading)
	var hl := length / 2.0
	var hw := RS.TRAIN_WIDTH_M / 2.0
	var body := _rect(c, f, r, hl, -hl, hw)
	node.draw_colored_polygon(body, style[0])
	if style[1] != null and profile == "locomotive":
		node.draw_colored_polygon(_rect(c, f, r, hl, hl - 3.0, hw), style[1])
	elif style[1] != null:
		node.draw_colored_polygon(_rect(c, f, r, hl - 1.0, -hl + 1.0, 0.5), style[1])
	var closed := body.duplicate()
	closed.append(body[0])
	node.draw_polyline(closed, RS.TRAIN_ROOF_LINE, _px(1.0))
