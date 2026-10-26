## Moving things from "state" messages, redrawn every frame from the
## interpolation buffer (StateBuffer): positions and headings are blended
## between the two states around the render time; everything discrete (an
## entity appearing, its colour, a train's cars, lamps) comes from the
## earlier one.
##
## Everything is drawn in metres. Draw order: pedestrians,
## the job target, the taxi, NPC vehicles, smoke, then trains on top.
## Entities outside the visible area (plus a margin) are skipped. Text and
## a few minimum sizes are in screen pixels.
extends Node2D

const RS := preload("res://render_style.gd")
const T := preload("res://i18n.gd")
const CULL_MARGIN_M := 30.0
const TWO_WHEELERS := ["motorcycle", "moped", "bicycle"]
const INDOORS := ["entering_building", "in_building"]

var origin := Vector2.ZERO
var buffer := StateBuffer.new()
var show_route := false  # N, from NavOverlay (main.gd)
var _route_source = null  # the last state's navigation.points, as received
var _route_points := PackedVector2Array()  # ... in layer coordinates
var px_per_m := 9.0  # the camera's zoom (main.gd): screen pixels per metre
var drawn_entities := 0  # last frame (performance readout)
var interp_usec := 0  # time spent sampling and blending last frame
var view_rect := Rect2()  # visible area in this layer's coordinates, with margin

var _frame: Dictionary = {}  # this frame's sample: {"a", "b", "t"}
var _clock := 0.0  # local seconds, for purely presentational loops (exhaust puffs)
var _exhaust := 0.0  # the taxi's eased throttle, how hard its exhaust puffs
var _font: Font
var reflectors_on := false  # the sun below -7.5 degrees (main.gd, from state calendar)
var lamp_near := func(_at: Vector2, _radius: float) -> bool: return false  # MapLayer.lamp_near
var light_at := func(_at: Vector2) -> float: return 0.0  # MapLayer.light_at: street light on a point
var ambient := Color.WHITE  # the world's ambient multiply (main.gd): lit vehicles are pre-brightened against it
var _tint = null  # while a vehicle is drawn: its light (ambient + street light); its shapes go to _cars
var _cars: Node2D  # the vehicles, unshaded: each tinted by its own light instead of the world's ambient
var _route_node: Node2D  # the navigation route, unshaded (_draw_route)
# People (and pucks) are drawn unshaded, each tinted by the light where they
# stand (ambient + street lights + floodlights, like the vehicles), so a
# floodlit rink shows its jerseys; text bubbles and tags go on _overlay,
# unshaded and untinted, never dimmed by the night. _draw collects both
# (_people_rows, _overlays); the helpers draw on _canvas with _lit colours.
var _people: Node2D
var _overlay: Node2D
var _people_rows: Array = []  # [position, heading, ped, animation time]
var _tennis_balls: Array = []
var _beach_balls: Array = []  # interpolated position, height and drawing scale
var _golf_rows: Array = []  # interpolated ball ground position, height, pin, holed
var _dog_rows: Array = []  # [owner position, dog position, heading, dog]
var _puck_frame: Array = []  # [a, b, t] for _pucks
var _overlays: Array[Callable] = []
var _canvas: CanvasItem = self
var _lit_tint := Color.WHITE
var _route_now := PackedVector2Array()
const ROUTE_NIGHT_VISIBILITY := 0.55  # 0: as dark as the night, 1: as clear as by day
var _car_shapes: Array = []  # [kind, ...] this frame: ["poly", points, fill, outline, width], ["circle", ...], ["line", ...]
const STREET_LIGHT_ON_VEHICLES := 0.55  # how strongly a lamp lights a car, like the pool on the road
var language := "en"
var _reflectors: Node2D  # made in _ready (an instance never in the tree leaks nothing)
var underground := false  # the taxi below ground (state player.map_level): only it and the walker are shown
var covered := func(_at: Vector2, _layer: int) -> bool: return false  # MapLayer.covered (headlights under a bridge)
var _trains: Node2D  # trains, z 14: above the canopies and rail bridges (z 13), drawn last
var _trains_drawn := 0
var _brawl_punches := {}  # brawl id -> [last action seq seen, when its punch began]
const BRAWL_JACKETS := [[40, 40, 48], [120, 30, 30]]
const PLAYER_JACKET := [255, 217, 64]  # the player's own on-foot colour
var _tracks: Node2D  # tyre tracks, z 8 (before roadworks and signs)
var _trails: Array = []  # [kind, [[position, heading, intensity, front, snowfall when laid], ...], its Node2D]
const TRACK_SEGMENT := 200  # points per trail segment: a new point redraws only its own segment
const TRACK_SNOW_COVER_S := 120.0  # seconds of snowfall that cover a tyre track completely
var _snowfall := 0.0  # seconds it has snowed (real time) since the client started
var _snow_clock := 0.0
var _snow_drawn := 0.0
var _track_points := 0
var _last_track = null  # where the last mark was laid (null: the trail is broken)
var _last_track_px := 0.0
# Vehicle lamps: drawn unshaded (the night's ambient multiply leaves them
# bright) and, as it gets dark, with an additive glow - tail lamps a red
# halo, brake lamps a bigger, brighter one, the reversing lamp a white wash
# behind the car (godot-lights-01 style).
var light_level := 0.0  # Daylight.artificial (main.gd)
var _lamps: Node2D
var _glow: Node2D
var _lamp_polys: Array = []  # [points, colour] this frame
var _cars_under: Node2D  # vehicles under a bridge: below the decks (z 2+), their shapes and lamps
var _under_shapes: Array = []
var _under_lamps: Array = []
var glow_points := PackedVector2Array()
var glow_colors := PackedColorArray()
var glow_triangles := PackedInt32Array()
const GLOW_STEPS := 10
const TAIL_GLOW := [Color(0.30, 0.03, 0.02), 0.9]  # added colour at the lamp, reach in metres
const BRAKE_GLOW := [Color(0.65, 0.05, 0.03), 2.2]
const REVERSE_GLOW := [Color(0.55, 0.55, 0.50), 4.5]
const TAXI_SIGN_GLOW := [Color(0.35, 0.30, 0.05), 1.6]  # the roof light of a free taxi, a small yellow halo
var body_style := 0  # an NPC car's body (CAR_SHAPES), from its id: the same car keeps its look
# Car bodies from above, in half-lengths from the centre (+ front): windshield
# front, roof front, roof rear, rear window rear, roof half-width, an extra.
const CAR_SHAPES := [
	[0.42, 0.12, -0.42, -0.62, 0.74, ""],  # sedan (the taxi)
	[0.40, 0.10, -0.58, -0.76, 0.76, ""],  # hatchback: the roof runs far back
	[0.42, 0.12, -0.74, -0.88, 0.76, "rails"],  # estate: a long roof, roof rails
	[0.40, 0.16, -0.66, -0.80, 0.80, "rails"],  # SUV: big, boxy roof
	[0.46, 0.20, -0.16, -0.24, 0.76, "bed"],  # pickup: a short cab, an open bed
	[0.18, -0.06, -0.36, -0.52, 0.64, "stripes"],  # sports coupe: long bonnet, small cabin
	[0.36, 0.06, -0.46, -0.66, 0.76, ""],  # city car
]
const VAN_SHAPE := [0.78, 0.56, -0.96, -0.96, 0.84, "door"]  # a van: short nose, one long roof
var taxi_sign_on := false  # the taxi being drawn is free for a fare (its roof light lit)
var ploughing := false  # snowing: tractors carry a plough blade and a flashing beacon
var smoke_enabled := true
const TRACK_STYLES := {  # [faint, dark, width m]
	"rubber": [Color8(110, 110, 110), Color8(28, 28, 28), 0.24], "dirt": [Color8(150, 138, 118), Color8(105, 68, 38), 0.75],
	"sand": [Color8(222, 208, 170), Color8(178, 158, 114), 0.75], "snow": [Color8(214, 226, 232), Color8(142, 169, 181), 0.30],
}


func _ready() -> void:
	_font = ThemeDB.fallback_font
	_reflectors = Node2D.new()
	_reflectors.z_index = 10  # above the night tint (20): 12 + 10
	_reflectors.draw.connect(_draw_reflectors)
	add_child(_reflectors)
	_trains = Node2D.new()
	_trains.z_index = 2
	_trains.draw.connect(_draw_trains)
	add_child(_trains)
	_tracks = Node2D.new()
	_tracks.z_index = -2
	add_child(_tracks)
	_glow = Node2D.new()
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	add.light_mode = CanvasItemMaterial.LIGHT_MODE_UNSHADED
	_glow.material = add
	_glow.draw.connect(func(): if not glow_triangles.is_empty():
		RenderingServer.canvas_item_add_triangle_array(_glow.get_canvas_item(), glow_triangles, glow_points, glow_colors))
	add_child(_glow)
	_route_node = Node2D.new()
	_route_node.material = preload("res://emissive.tres")
	_route_node.draw.connect(_draw_route)
	add_child(_route_node)  # before the vehicles' node: under them
	_people = Node2D.new()  # before the vehicles' node: under them
	_people.material = preload("res://emissive.tres")
	_people.draw.connect(_draw_people)
	add_child(_people)
	_cars = Node2D.new()
	_cars.material = preload("res://emissive.tres")  # lit by vehicle_light, not the ambient multiply
	_cars.draw.connect(func(): _paint(_cars, _car_shapes))
	add_child(_cars)
	_overlay = Node2D.new()
	_overlay.z_index = 5  # text over everything on the map
	_overlay.material = preload("res://emissive.tres")
	_overlay.draw.connect(func():
		_canvas = _overlay
		for overlay in _overlays:
			overlay.call()
		_canvas = self)
	add_child(_overlay)
	_cars_under = Node2D.new()
	_cars_under.z_index = -11  # 12 - 11: ground roads (1), under every bridge deck
	_cars_under.material = preload("res://emissive.tres")
	_cars_under.draw.connect(func():
		_paint(_cars_under, _under_shapes)
		_paint_lamps(_cars_under, _under_lamps))
	add_child(_cars_under)
	_lamps = Node2D.new()
	_lamps.material = preload("res://emissive.tres")
	_lamps.draw.connect(func(): _paint_lamps(_lamps, _lamp_polys))
	add_child(_lamps)


func now() -> float:
	return Time.get_ticks_usec() / 1000000.0


## The state the picture currently shows (discrete values: HUD, sound).
func shown_state() -> Dictionary:
	return _frame.get("a", {})


## The player's interpolated position (the camera follows it).
## The taxi's velocity in canvas metres per second (y down); zero on foot.
func player_velocity() -> Vector2:
	if _frame.is_empty() or _frame["a"].get("on_foot", false):
		return Vector2.ZERO
	var player: Dictionary = _frame["a"]["player"]
	return _forward(float(player.get("heading", 0.0))) * float(player.get("speed", 0.0))


func player_position() -> Vector2:
	if _frame.is_empty():
		return Vector2.ZERO
	var key := "player_pedestrian" if _frame["a"].get("on_foot", false) else "player"
	var p := StateBuffer.blend(_frame["a"][key], _frame["b"].get(key, _frame["a"][key]), _frame["t"], origin)
	return Vector2(p.x, p.y)


func entity_position(kind: String, id) -> Vector2:
	if _frame.is_empty():
		return Vector2.INF
	if kind == "train":
		for train in _frame["a"].get("trains", []):
			if train.get("id") == id and not train.get("cars", []).is_empty():
				return MapMath.point(origin, train["cars"][0][0], train["cars"][0][1])
		return Vector2.INF
	var key := "pedestrians" if kind == "pedestrian" else "npcs"
	var later := _by_id(_frame["b"].get(key, []))
	for row in _frame["a"].get(key, []):
		if row.get("id") == id:
			var p := StateBuffer.blend(row, later.get(id, row), _frame["t"], origin)
			return Vector2(p.x, p.y)
	if kind == "pedestrian":
		var later_npcs := _by_id(_frame["b"].get("npcs", []))
		for npc in _frame["a"].get("npcs", []):
			for person in npc.get("occupants", []):
				if person.get("id") == id:
					var p := StateBuffer.blend(npc, later_npcs.get(npc["id"], npc), _frame["t"], origin)
					return Vector2(p.x, p.y)
	return Vector2.INF


func entity_at(screen: Vector2, canvas: Transform2D) -> Dictionary:
	if _frame.is_empty() or underground:
		return {}
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	for key in ["pedestrians", "npcs"]:
		var later := _by_id(b.get(key, []))
		var best := {}
		var distance := INF
		for row in a.get(key, []):
			if key == "npcs" and not row.get("is_on_foot", false) and not drawn_as_vehicle(row):
				continue
			var p := StateBuffer.blend(row, later.get(row["id"], row), _frame["t"], origin)
			var pixels := screen.distance_to(canvas * Vector2(p.x, p.y))
			var radius := 12.0 if key == "pedestrians" or row.get("is_on_foot", false) else maxf(12.0, float(row.get("length_m", 4.5)) * px_per_m * 0.5)
			if pixels <= radius and pixels < distance:
				best = {"kind": "pedestrian" if key == "pedestrians" else "npc", "id": row["id"]}
				distance = pixels
		if not best.is_empty():
			return best
	var point := canvas.affine_inverse() * screen
	var later_trains := _by_id(b.get("trains", []))
	for train in a.get("trains", []):
		var next: Dictionary = later_trains.get(train["id"], train)
		for i in train.get("cars", []).size():
			var car: Array = train["cars"][i]
			var to: Array = next["cars"][i] if next.get("cars", []).size() == train["cars"].size() else car
			var centre := MapMath.point(origin, lerpf(car[0], to[0], _frame["t"]), lerpf(car[1], to[1], _frame["t"]))
			var local := (point - centre).rotated(lerp_angle(car[2], to[2], _frame["t"]))
			if absf(local.x) <= float(car[3]) * 0.5 and absf(local.y) <= maxf(1.6, 12.0 / px_per_m):
				return {"kind": "train", "id": train["id"]}
	return {}


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
## a point every 0.5 m or 4 degrees, at most 4000
## points (the oldest trails go, down to 3500); the oldest go once a
## viewport diagonal away.
func _lay_track() -> void:
	if not is_equal_approx(_last_track_px, px_per_m):
		_last_track_px = px_per_m
		for trail in _trails:  # line widths are in pixels
			trail[2].queue_redraw()
	if _frame.is_empty():
		return
	var a: Dictionary = _frame["a"]
	var now := Time.get_ticks_msec() / 1000.0
	if _snow_clock > 0.0 and str(a.get("weather", {}).get("weather_type", "")) == "snow":
		_snowfall += now - _snow_clock  # fresh snow covers the tracks laid before it
		if _snowfall - _snow_drawn > 0.25:
			_snow_drawn = _snowfall
			_bury_tracks()
	_snow_clock = now
	var mark = a.get("tire_mark")
	if typeof(mark) != TYPE_DICTIONARY or a.get("on_foot", false):
		_last_track = null
		return
	var taxi := StateBuffer.blend(a["player"], _frame["b"].get("player", a["player"]), _frame["t"], origin)
	var at := Vector2(taxi.x, taxi.y)
	var kind := str(mark.get("kind", "rubber"))
	if _last_track == null or _trails.is_empty() or _trails[-1][0] != kind:
		_new_trail(kind, [])
	elif at.distance_to(_last_track[0]) < 0.5 and absf(angle_difference(taxi.z, _last_track[1])) < deg_to_rad(4.0):
		return
	elif _trails[-1][1].size() >= TRACK_SEGMENT:  # full: carry on in a new segment from its last point
		_new_trail(kind, [_trails[-1][1][-1]])
		_track_points += 1
	_trails[-1][1].append([at, taxi.z, float(mark.get("intensity", 1.0)), bool(mark.get("front", false)), _snowfall])
	_last_track = [at, taxi.z]
	_track_points += 1
	# Out of view is gone for good: tracks are looks only, never played back.
	var view_m := get_viewport_rect().size.length() / maxf(px_per_m, 0.001)
	while _trails.size() > 1 and _trails[0][1][-1][0].distance_to(at) > view_m:
		var gone: Array = _trails.pop_front()
		_track_points -= gone[1].size()
		gone[2].queue_free()
	if _track_points > 4000:
		while not _trails.is_empty() and _track_points > 3500:
			var oldest: Array = _trails.pop_front()
			_track_points -= oldest[1].size()
			oldest[2].queue_free()
	_trails[-1][2].queue_redraw()


func _new_trail(kind: String, points: Array) -> void:
	var node := Node2D.new()
	_tracks.add_child(node)
	var trail := [kind, points, node]
	node.draw.connect(_draw_trail.bind(trail))
	_trails.append(trail)


## How much of a track point fresh snow has covered, 0..1.
func _snow_cover(point: Array) -> float:
	return clampf((_snowfall - point[4]) / TRACK_SNOW_COVER_S, 0.0, 1.0)


## Fresh snow fades each segment as a whole (its modulate: no redraw) by its
## newest point, and a segment snowed over completely goes.
func _bury_tracks() -> void:
	for trail in _trails:
		var cover := _snow_cover(trail[1][-1])
		trail[2].modulate.a = 1.0 - cover
		if cover >= 1.0:
			_track_points -= trail[1].size()
			trail[2].queue_free()
	_trails = _trails.filter(func(trail): return _snow_cover(trail[1][-1]) < 1.0)


## One trail segment's tyre lines: the rear axle (1.2 m behind the centre),
## the front one too where the fronts locked; faint to dark by intensity.
func _draw_trail(trail: Array) -> void:
	var started := Time.get_ticks_usec()
	var node: Node2D = trail[2]
	var style: Array = TRACK_STYLES.get(trail[0], TRACK_STYLES["rubber"])
	var points := PackedVector2Array()
	var colors := PackedColorArray()
	var previous = null
	for point in trail[1]:
		if previous != null:
			var color: Color = style[0].lerp(style[1], point[2])
			for axle: float in ([-1.2, 1.2] if point[3] else [-1.2]):
				for side: float in [-0.72, 0.72]:
					points.append(previous[0] + _forward(previous[1]) * axle + _right(previous[1]) * side)
					points.append(point[0] + _forward(point[1]) * axle + _right(point[1]) * side)
					colors.append(color)
		previous = point
	if not colors.is_empty():
		node.draw_multiline_colors(points, colors, maxf(_px(3.0), style[2]))
	preload("res://perf.gd").add("tracks_draw", Time.get_ticks_usec() - started)


func _process(_delta: float) -> void:
	view_rect = (get_canvas_transform().affine_inverse() * get_viewport_rect()).grow(CULL_MARGIN_M)


var _reflectors_drawn := false


## Reflectors: at deep night a bright
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


## Owned dogs at the same interpolated positions used by the renderer.
func dogs() -> Array:
	var result: Array = []
	if _frame.is_empty():
		return result
	var later := _by_id(_frame["b"].get("pedestrians", []))
	for ped in _frame["a"].get("pedestrians", []):
		var dog: Dictionary = ped.get("dog", {})
		if dog.is_empty():
			continue
		var next: Dictionary = later.get(ped["id"], ped).get("dog", dog)
		var at := MapMath.point(origin, lerpf(float(dog["x"]), float(next.get("x", dog["x"])), _frame["t"]),
			lerpf(float(dog["y"]), float(next.get("y", dog["y"])), _frame["t"]))
		result.append([ped["id"], at])
	return result


## Driving NPCs: [[id, interpolated layer position, npc row], ...].
func npc_cars() -> Array:
	var cars: Array = []
	if _frame.is_empty():
		return cars
	var a: Dictionary = _frame["a"]
	var later := _by_id(_frame["b"].get("npcs", []))
	for npc in a.get("npcs", []):
		if npc.get("is_on_foot", false) or npc.get("state", "") in ["PARKED", "CRASHED"]:
			continue
		var p := StateBuffer.blend(npc, later.get(npc["id"], npc), _frame["t"], origin)
		cars.append([npc["id"], Vector2(p.x, p.y), npc])
	return cars


## In the taxi's headlight cone: ahead within
## 15 m, sideways within 1.5 m + 0.35 per metre ahead.
static func reflector_lit(at: Vector2, taxi: Vector2, heading: float) -> bool:
	var delta := at - taxi
	var ahead := delta.dot(_forward(heading))
	return ahead > 0.0 and ahead <= 15.0 and absf(delta.dot(_right(heading))) <= 1.5 + ahead * 0.35


## Headlight beams, in metres: two beams per vehicle
## with its engine on (the taxi first, then NPCs near the view, at most 80),
## each a quad and round cap: dipped 15 m, high 150 m across both lanes.
## Polygons in layer coordinates, from this frame's sample.
func headlight_beams() -> Array:
	var polygons: Array = []
	if _frame.is_empty():
		return polygons
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var vehicles: Array = []  # [position, heading, width, is_npc, length]
	var player: Dictionary = a["player"]
	var road: Dictionary = a.get("road", {}) if typeof(a.get("road")) == TYPE_DICTIONARY else {}
	if player.get("engine_on", false):
		var p := StateBuffer.blend(player, b.get("player", player), t, origin)
		# Under a higher road: no beams - unless on a bridge itself.
		if road.get("bridge", false) or not covered.call(Vector2(p.x, p.y), int(road.get("layer", 0))):
			vehicles.append([Vector2(p.x, p.y), p.z, player.get("width_m", 1.8), false, player.get("length_m", 4.0)])
	var later := _by_id(b.get("npcs", []))
	var area := view_rect.grow(HIGH_BEAM_M - CULL_MARGIN_M)
	for npc in a.get("npcs", []):
		if npc.get("is_on_foot", false) or npc.get("state", "") == "PARKED":
			continue
		var p := StateBuffer.blend(npc, later.get(npc["id"], npc), t, origin)
		var layer := int(npc.get("layer", 0))  # an NPC on a raised layer counts as on its bridge
		if area.has_point(Vector2(p.x, p.y)) and not underground and (layer > 0 or not covered.call(Vector2(p.x, p.y), layer)):
			vehicles.append([Vector2(p.x, p.y), p.z, npc.get("width_m", 1.8), true, npc.get("length_m", 4.0)])
	var shown := view_rect.grow(HIGH_BEAM_M - CULL_MARGIN_M)
	var drawn := 0
	for vehicle in vehicles:
		if drawn >= 80:
			break
		var c: Vector2 = vehicle[0]
		if not shown.has_point(c):
			continue
		var length := beam_length(lamp_near.call(c, 22.0), oncoming(vehicle, vehicles))
		polygons.append_array(beam_polygons(c, vehicle[1], maxf(_px(3.0), vehicle[2]), length, false, vehicle[4] * 0.5))
		drawn += 1
	if not underground:
		var later_trains := _by_id(b.get("trains", []))
		for train in a.get("trains", []):
			var beams := train_beams(train, later_trains.get(train["id"], train), t, origin)
			if not beams.is_empty() and shown.grow(TRAIN_BEAM_M).has_point(beams[0][0]):
				polygons.append_array(beams)
	return polygons


const TRAIN_BEAM_M := 60.0
const HIGH_BEAM_M := 150.0


## A train's headlights: two long beams from the nose of its lead car (the
## first car, facing the way it runs), standing or moving; [] without cars.
static func train_beams(train: Dictionary, next: Dictionary, t: float, origin: Vector2) -> Array:
	var cars: Array = train.get("cars", [])
	if cars.is_empty():
		return []
	var car: Array = cars[0]
	var to: Array = next.get("cars", cars)[0] if not next.get("cars", []).is_empty() else car
	var heading := lerp_angle(float(car[2]), float(to[2]), t)
	var f := _forward(heading)
	var nose := MapMath.point(origin, lerpf(car[0], to[0], t), lerpf(car[1], to[1], t)) + f * float(car[3]) / 2.0
	var width: float = RS.TRAIN_WIDTH_M
	return beam_polygons(nose - f * (1.0 + width * 0.55), heading, width, TRAIN_BEAM_M, true)


## Automatic high beam, the taxi's as every NPC's: 150 m on a dark road, dipped to 15 m within 22 m of a street
## light or with a vehicle coming the other way.
static func beam_length(near_street_light: bool, has_oncoming: bool) -> float:
	return 15.0 if near_street_light or has_oncoming else HIGH_BEAM_M


## Another vehicle within high-beam reach ahead, heading the other way.
static func oncoming(vehicle: Array, vehicles: Array) -> bool:
	var f := _forward(vehicle[1])
	for other in vehicles:
		if other == vehicle:
			continue
		var delta: Vector2 = other[0] - vehicle[0]
		var distance := delta.length()
		if distance > 0.1 and distance <= HIGH_BEAM_M and delta.dot(f) / distance > 0.2 and f.dot(_forward(other[1])) < -0.5:
			return true
	return false


## One vehicle's two beams and caps (a quad and a circle per side).
## half_length: centre to the front bumper (a bus's lamps are 5.5 m ahead, not a car's 2).
static func beam_polygons(c: Vector2, heading: float, width: float, length: float, straight := false, half_length := 0.0) -> Array:
	var f := _forward(heading)
	var r := _right(heading)
	var front := c + f * maxf(1.0 + width * 0.55, half_length)
	var high := not straight and length > 15.0
	var polygons: Array = []
	var lamps := []
	var tips := []
	for side: float in [-1.0, 1.0]:
		var side_v := r * side
		var lamp := front + side_v * width * 0.35
		# Keep left/right endpoints ordered: crossed tips overlap the additive beams.
		var tip := c + f * length + r * (2.25 if side < 0.0 else 3.0)  # kerb bias
		if high:
			tip = c + f * length  # High beams illuminate both lanes, without the dipped beam's kerb bias.
		var near := lamp + side_v * minf(4.5 * 0.08, width * 0.10)
		if straight:  # a train's: straight ahead, each from just past the centre line outward - they overlap over the track
			tip = c + f * length - side_v * 0.5
			near = lamp - side_v * (width * 0.35 + 0.3)
		var far_width := 22.5 if high else 4.5 * 1.7
		polygons.append(PackedVector2Array([lamp, near, tip + side_v * far_width, tip]))
		lamps.append(lamp)
		tips.append(tip)
		var cap := PackedVector2Array()
		for i in 12:
			cap.append(tip + side_v * far_width * 0.5 + Vector2(cos(TAU * i / 12.0), sin(TAU * i / 12.0)) * far_width * 0.5)
		polygons.append(cap)
	# Between the two beams: lit too (the road straight ahead was a dark wedge).
	polygons.append(PackedVector2Array([lamps[0], lamps[1], tips[1], tips[0]]))
	return polygons


## The taxi's roof sign is lit while it is free for a fare, off with a fare
## on (from the job until the drop-off).
static func taxi_sign_lit(taxi: Dictionary) -> bool:
	return not (taxi.get("current_passenger") is Dictionary)


## NPC vehicles drawn as vehicles: not police (their own look), not
## drivers on foot, nor the far level-of-detail band.
static func drawn_as_vehicle(npc: Dictionary) -> bool:
	return not npc.get("is_police", false) and not npc.get("is_on_foot", false) and npc.get("lod_level", 0) < 2


static func is_reversing(speed: float) -> bool:
	return speed < -0.05


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


## Vehicle-local rectangle (+long is forward, +lat is the vehicle's right side), as a polygon.
## A quad across the car: `front_half` wide at `front`, `rear_half` at `rear`.
static func _trapezoid(c: Vector2, f: Vector2, r: Vector2, front: float, rear: float, front_half: float, rear_half: float) -> PackedVector2Array:
	return PackedVector2Array([c + f * front + r * front_half, c + f * front - r * front_half,
		c + f * rear - r * rear_half, c + f * rear + r * rear_half])


static func _rect(c: Vector2, f: Vector2, r: Vector2, front: float, rear: float, half_width: float) -> PackedVector2Array:
	return PackedVector2Array([c + f * front + r * half_width, c + f * front - r * half_width,
		c + f * rear - r * half_width, c + f * rear + r * half_width])


func _poly(points: PackedVector2Array, fill: Color, outline = null, width := -1.0) -> void:
	if _tint != null:  # a vehicle's: lit by its own light, drawn on _cars
		_car_shapes.append(["poly", points, _lit(fill), _lit(outline) if outline != null else null, width])
		return
	if not drawable(points):
		return
	draw_colored_polygon(points, fill)
	if outline != null:
		var closed := points.duplicate()
		closed.append(points[0])
		draw_polyline(closed, outline, width)


## A vehicle body by type (two-wheelers a body and rider),
## then its lamps (_draw_vehicle_lights).
## A vehicle's light: the world's ambient plus the street light on it, the
## LED pool's colour - its colours are multiplied by this (drawn unshaded),
## so under a lamp a yellow taxi is a brighter yellow, not the night's grey
## olive; white by day.
static func vehicle_light(light: float, ambient_color: Color) -> Color:
	var lamp := Color(1.0, 0.93, 0.78) * (maxf(light, 0.0) * STREET_LIGHT_ON_VEHICLES)
	return Color(minf(ambient_color.r + lamp.r, 1.0), minf(ambient_color.g + lamp.g, 1.0), minf(ambient_color.b + lamp.b, 1.0))


## A lamp's soft halo: a fan bright at `at` (glow[0] × level), nothing at
## glow[1] metres; none by day.
static func lamp_glow(at: Vector2, glow: Array, level: float, points: PackedVector2Array,
		colors: PackedColorArray, triangles: PackedInt32Array) -> void:
	if level <= 0.01:
		return
	var centre := points.size()
	points.append(at)
	colors.append(Color(glow[0] * level, 1.0))
	for k in GLOW_STEPS:
		var angle := TAU * k / GLOW_STEPS
		points.append(at + Vector2(cos(angle), sin(angle)) * float(glow[1]))
		colors.append(Color(0, 0, 0, 1))
		triangles.append_array(PackedInt32Array([centre, centre + 1 + k, centre + 1 + (k + 1) % GLOW_STEPS]))


func _vehicle(c: Vector2, heading: float, length: float, width: float, color: Color, kind: String,
		is_taxi: bool, engine_on: bool, braking: bool, reversing: bool, turn_signal: String, signal_elapsed: float, fallen := false,
		under := false) -> void:
	_tint = vehicle_light(light_level * float(light_at.call(c)), ambient)  # lit by the street lights it stands under
	var shapes := _car_shapes
	var lamps := _lamp_polys
	var level := light_level
	if under:  # under a bridge: drawn below its deck, lamps and all; no halos (they'd shine through it)
		_car_shapes = _under_shapes
		_lamp_polys = _under_lamps
		light_level = 0.0  # in the body only the halos read it
	_vehicle_body(c, heading, length, width, color, kind, is_taxi, engine_on, braking, reversing, turn_signal, signal_elapsed, fallen)
	_car_shapes = shapes
	_lamp_polys = lamps
	light_level = level
	_tint = null


static func _paint(node: Node2D, shapes: Array) -> void:
	for shape in shapes:
		match shape[0]:
			"poly":
				var indices := body_triangles(shape[1])
				if indices.is_empty():
					continue
				RenderingServer.canvas_item_add_triangle_array(node.get_canvas_item(), indices, shape[1], PackedColorArray([shape[2]]))
				if shape[3] != null:
					var closed: PackedVector2Array = shape[1].duplicate()
					closed.append(shape[1][0])
					node.draw_polyline(closed, shape[3], shape[4])
			"circle":
				node.draw_circle(shape[1], shape[2], shape[3])
			"line":
				node.draw_line(shape[1], shape[2], shape[3], shape[4])


## Body parts are convex: avoid the polygon triangulator's coordinate precision limits.
static func body_triangles(points: PackedVector2Array) -> PackedInt32Array:
	var indices := PackedInt32Array()
	if not drawable(points):
		return indices
	for i in range(1, points.size() - 1):
		indices.append_array(PackedInt32Array([0, i, i + 1]))
	return indices


## Lamps are quads already: submit their two triangles directly, avoiding
## Godot's polygon triangulator for sub-pixel shapes far from the origin.
static func lamp_mesh(lamps: Array) -> Array:
	var points := PackedVector2Array()
	var colors := PackedColorArray()
	var triangles := PackedInt32Array()
	for lamp in lamps:
		if lamp[0].size() != 4 or not drawable(lamp[0]):
			continue
		var base := points.size()
		points.append_array(lamp[0])
		colors.append_array(PackedColorArray([lamp[1], lamp[1], lamp[1], lamp[1]]))
		triangles.append_array(PackedInt32Array([base, base + 1, base + 2, base, base + 2, base + 3]))
	return [points, colors, triangles]


static func _paint_lamps(node: Node2D, lamps: Array) -> void:
	var mesh := lamp_mesh(lamps)
	if not mesh[2].is_empty():
		RenderingServer.canvas_item_add_triangle_array(node.get_canvas_item(), mesh[2], mesh[0], mesh[1])


## A polygon Godot can triangulate: finite points, some area. A lamp or a
## body part shrunk to a line (no width, a bad heading) is skipped instead
## of "Invalid polygon data, triangulation failed".
static func drawable(points: PackedVector2Array) -> bool:
	if points.size() < 3:
		return false
	# Points are 32-bit floats kilometres from the origin (~0.5 mm steps at
	# 5 km): a tiny lamp there that passes fixed limits still fails Godot's
	# triangulation. The limits grow with the distance - 5 mm at 5 km.
	var tolerance := maxf(1e-4, (absf(points[0].x) + absf(points[0].y)) * 1e-6)
	var tolerance_sq := tolerance * tolerance
	var winding := 0.0
	for i in points.size():
		var a := points[i]
		var b := points[(i + 1) % points.size()]
		var c := points[(i + 2) % points.size()]
		if not (is_finite(a.x) and is_finite(a.y)) or a.distance_squared_to(b) <= tolerance_sq:
			return false
		var cross := (b - a).cross(c - b)
		if absf(cross) <= tolerance_sq:
			return false
		if winding == 0.0:
			winding = signf(cross)
		elif cross * winding < 0.0:
			return false
	return true


func _lit(color: Color) -> Color:
	return Color(minf(color.r * _tint.r, 1.0), minf(color.g * _tint.g, 1.0), minf(color.b * _tint.b, 1.0), color.a)


## A trailer's body between two states: [x, y, heading, length, width, kind].
func _trailer(a: Array, b: Array, t: float) -> void:
	var c := Vector2(lerpf(a[0], b[0], t) - origin.x, -(lerpf(a[1], b[1], t) - origin.y))
	_tint = vehicle_light(light_level * float(light_at.call(c)), ambient)  # lit like a vehicle (_vehicle)
	_trailer_body(c, lerp_angle(a[2], b[2], t), float(a[3]), float(a[4]), str(a[5]))
	_tint = null


## A caravan from above: the white body, its window and stripes, the
## drawbar reaching forward to the hitch, and its own tail lights.
func _trailer_body(c: Vector2, heading: float, length: float, width: float, _kind: String) -> void:
	var f := _forward(heading)
	var r := _right(heading)
	var hl := length * 0.5
	var hw := width * 0.5
	var box := Color8(238, 234, 220)
	_car_shapes.append(["line", c + f * hl, c + f * (hl + 0.9), _lit(Color8(165, 168, 162)), maxf(_px(1.5), hw * 0.14)])  # the drawbar
	_poly(_rect(c, f, r, hl, -hl, hw), box, RS.OUTLINE)
	_poly(_rect(c, f, r, hl * 0.92, -hl * 0.92, hw * 0.84), box.lightened(0.05))
	_poly(_rect(c, f, r, hl * 0.55, hl * 0.2, hw * 0.34), Color8(120, 150, 160))  # the roof window
	for side: float in [1.0, -1.0]:
		_car_shapes.append(["line", c + f * hl * 0.9 + r * hw * 0.8 * side, c - f * hl * 0.9 + r * hw * 0.8 * side,
			_lit(Color8(156, 108, 66)), maxf(_px(1.0), hw * 0.07)])
		_poly(_rect(c - f * hl * 0.97 + r * hw * 0.7 * side, f, r, hl * 0.03, -hl * 0.03, hw * 0.16), Color8(183, 45, 39))  # tail lights


func _vehicle_body(c: Vector2, heading: float, length: float, width: float, color: Color, kind: String,
		is_taxi: bool, engine_on: bool, braking: bool, reversing: bool, turn_signal: String, signal_elapsed: float, fallen := false) -> void:
	length = maxf(length, _px(5.0))
	width = maxf(width, _px(2.5))
	var f := _forward(heading)
	var r := _right(heading)
	var hl := length * 0.5
	var hw := width * 0.5
	if kind == "bicycle":  # tyres, frame, bars; the rider (in `color`) only while riding (engine_on: not PARKED)
		var tyre := _lit(Color8(28, 28, 28))
		var thin := maxf(_px(1.0), hl * 0.12)
		var flat := fallen
		if flat:  # lying on its side, the rider gone (a pedestrian beside it)
			f = _forward(heading - PI / 2.0)
			r = _right(heading - PI / 2.0)
		for end: float in [0.62, -0.62]:
			_car_shapes.append(["line", c + f * hl * (end + 0.33), c + f * hl * (end - 0.33), tyre, maxf(_px(1.5), hw * 0.55)])
		_car_shapes.append(["line", c + f * hl * 0.62, c - f * hl * 0.62, _lit(color.darkened(0.25)), thin])  # frame
		_car_shapes.append(["line", c + f * hl * 0.5 + r * hw * 0.9, c + f * hl * 0.5 - r * hw * 0.9, tyre, thin])  # handlebar
		if engine_on and not flat:
			_poly(_rect(c - f * hl * 0.05, f, r, hl * 0.28, -hl * 0.32, hw * 0.95), color, RS.OUTLINE)  # back and shoulders
			_car_shapes.append(["circle", c + f * hl * 0.18, hw * 0.55, _lit(Color8(236, 196, 160))])  # head
		return
	if kind in TWO_WHEELERS:
		if fallen:  # lying on its side
			f = _forward(heading - PI / 2.0)
			r = _right(heading - PI / 2.0)
		_poly(_rect(c, f, r, hl, -hl, hw), color, RS.OUTLINE)
		_car_shapes.append(["circle", c - f * hl * 0.1, hw * 0.9, _lit(RS.CABIN)])  # rider
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
		"tractor":  # big rear wheels, small front ones, a narrow bonnet, the cab over the rear axle
			var tyre := Color8(25, 25, 25)
			for side: float in [1.0, -1.0]:
				_poly(_rect(c + r * hw * 0.80 * side, f, r, -hl * 0.20, -hl * 0.90, hw * 0.20), tyre)
				_poly(_rect(c + r * hw * 0.62 * side, f, r, hl * 0.90, hl * 0.50, hw * 0.13), tyre)
			_poly(_rect(c, f, r, hl, -hl * 0.10, hw * 0.36), color, RS.OUTLINE)
			_poly(_rect(c, f, r, -hl * 0.05, -hl * 0.95, hw * 0.58), color, RS.OUTLINE)
			_poly(_rect(c, f, r, -hl * 0.15, -hl * 0.85, hw * 0.48), RS.WINDSHIELD)
			_poly(_rect(c, f, r, -hl * 0.30, -hl * 0.72, hw * 0.40), color.darkened(0.12))
			if ploughing:  # an angled blade ahead, wider than the tractor, and the amber beacon on the cab
				_poly(PackedVector2Array([c + f * hl * 1.30 + r * hw * 1.2, c + f * hl * 1.16 + r * hw * 1.2,
					c + f * hl * 1.02 - r * hw * 1.2, c + f * hl * 1.16 - r * hw * 1.2]), Color8(240, 150, 20), RS.OUTLINE)
				_car_shapes.append(["line", c + f * hl * 1.02, c + f * hl * 0.9, _lit(Color8(60, 60, 60)), maxf(_px(1.0), hw * 0.12)])
				var beacon := _rect(c - f * hl * 0.5, f, r, hl * 0.08, -hl * 0.08, hw * 0.12)
				if fmod(_clock, 0.8) < 0.4:
					_lamp_polys.append([beacon, RS.TURN_SIGNAL])  # unshaded: it shines at night
				else:
					_poly(beacon, RS.TURN_SIGNAL.darkened(0.5))
		"camper_van":  # a motorhome: a van cab in its own colour, the long white living box over it
			var box := Color8(238, 234, 220)
			_poly(_rect(c, f, r, hl, -hl, hw), box, RS.OUTLINE)
			_poly(_rect(c, f, r, hl, hl * 0.62, hw * 0.92), color, RS.OUTLINE)  # the cab's bonnet
			_poly(_trapezoid(c, f, r, hl * 0.62, hl * 0.46, hw * 0.84, hw * 0.88), RS.WINDSHIELD)
			_poly(_rect(c, f, r, hl * 0.4, -hl * 0.92, hw * 0.86), box.lightened(0.05))
			_poly(_rect(c, f, r, hl * 0.05, -hl * 0.25, hw * 0.34), Color8(120, 150, 160))  # the roof window
			_poly(_rect(c, f, r, -hl * 0.45, -hl * 0.6, hw * 0.3), Color8(186, 185, 170))  # a roof vent
			for side: float in [1.0, -1.0]:  # the stripe along its side
				_car_shapes.append(["line", c + f * hl * 0.42 + r * hw * 0.93 * side, c - f * hl * 0.95 + r * hw * 0.93 * side,
					_lit(color.darkened(0.1)), maxf(_px(1.0), hw * 0.08)])
		"truck":
			_poly(_rect(c, f, r, hl * 0.18, -hl, hw), color, RS.OUTLINE)
			_poly(_rect(c, f, r, hl * 0.08, -hl * 0.86, hw * 0.78), color.lightened(28.0 / 255.0))
			_poly(_rect(c, f, r, hl, hl * 0.24, hw * 0.92), color, RS.OUTLINE)
			_poly(_rect(c, f, r, hl * 0.72, hl * 0.52, hw * 0.72), RS.TRUCK_WINDSHIELD)
			_car_shapes.append(["line", c + f * hl * 0.20 - r * hw, c + f * hl * 0.20 + r * hw, _lit(Color8(35, 35, 35)), _px(2.0)])
		_:
			# A car from above: body, the roof in its own (darker) colour, the
			# windshield sloping down to the bonnet, the smaller rear window,
			# and on a taxi the roof light - lit while a fare is on.
			_poly(_rect(c, f, r, hl, -hl, hw), color, RS.OUTLINE)
			var shape: Array = VAN_SHAPE if kind == "van" else CAR_SHAPES[0 if is_taxi else body_style % CAR_SHAPES.size()]
			var glass_front: float = shape[0]
			var roof_front: float = shape[1]
			var roof_rear: float = shape[2]
			var glass_rear: float = shape[3]
			var roof_half: float = shape[4]
			_poly(_trapezoid(c, f, r, hl * glass_front, hl * roof_front, hw * 0.86, hw * roof_half), RS.WINDSHIELD)
			_poly(_rect(c, f, r, hl * roof_front, hl * roof_rear, hw * roof_half), color.darkened(0.12))
			if glass_rear < roof_rear:
				_poly(_trapezoid(c, f, r, hl * roof_rear, hl * glass_rear, hw * roof_half, hw * minf(roof_half + 0.08, 0.86)), RS.WINDSHIELD)
			match shape[5]:
				"bed":  # a pickup's open load bed behind the cab
					_poly(_rect(c, f, r, hl * (glass_rear - 0.06), -hl * 0.92, hw * 0.8), color.darkened(0.35), color.darkened(0.55))
				"rails":  # roof rails: an estate or an SUV
					for side: float in [1.0, -1.0]:
						_car_shapes.append(["line", c + f * hl * roof_front + r * hw * roof_half * 0.82 * side,
							c + f * hl * roof_rear + r * hw * roof_half * 0.82 * side, _lit(color.darkened(0.5)), maxf(_px(1.0), hw * 0.08)])
				"stripes":  # a sports car's bonnet stripes
					for side: float in [1.0, -1.0]:
						_car_shapes.append(["line", c + f * hl * 0.98 + r * hw * 0.18 * side,
							c + f * hl * glass_front + r * hw * 0.18 * side, _lit(color.lightened(0.55)), maxf(_px(1.0), hw * 0.12)])
				"door":  # a van's sliding door seam
					_car_shapes.append(["line", c + f * hl * 0.1 + r * hw, c - f * hl * 0.35 + r * hw, _lit(color.darkened(0.45)), maxf(_px(1.0), hw * 0.06)])
			if is_taxi:
				var roof_light := _rect(c, f, r, -hl * 0.06, -hl * 0.22, hw * 0.42)
				_poly(_rect(c, f, r, -hl * 0.04, -hl * 0.24, hw * 0.48), Color8(30, 30, 30))  # its frame, readable on a yellow roof
				if engine_on and taxi_sign_on:
					_lamp_polys.append([roof_light, RS.TAXI_SIGN])  # unshaded: it shines at night
					lamp_glow(c - f * hl * 0.14, TAXI_SIGN_GLOW, light_level, glow_points, glow_colors, glow_triangles)
				else:
					_poly(roof_light, RS.TAXI_SIGN.darkened(0.45), Color8(30, 30, 30))
	# Lamps (inset, sizes and colours as _draw_vehicle_lights, in metres).
	var light_r := maxf(_px(1.2), width * 0.18)
	var light_len := minf(width * 0.25, maxf(_px(1.0), light_r * 2.4))
	var light_w := minf(length * 0.08, maxf(_px(1.0), light_r * 0.75))
	var inset := hw * 0.7
	var tip := hl - _px(0.5)
	for side: float in [1.0, -1.0]:
		var front: Vector2 = c + f * tip + r * inset * side
		_lamp_polys.append([_rect(front, f, r, light_w * 0.5, -light_w * 0.5, light_len * 0.5), RS.HEADLIGHT if engine_on else RS.HEADLIGHT_OFF])
		var rear: Vector2 = c - f * tip + r * inset * side
		var scale := 1.2 if braking else 1.0
		var tail := RS.BRAKE_LIGHT if braking else (RS.TAILLIGHT if engine_on else RS.TAILLIGHT_OFF)
		_lamp_polys.append([_rect(rear, f, r, light_w * 0.5 * scale, -light_w * 0.5 * scale, light_len * 0.5 * scale), tail])
		if braking or engine_on:
			lamp_glow(rear - f * 0.15, BRAKE_GLOW if braking else TAIL_GLOW, light_level, glow_points, glow_colors, glow_triangles)
	if reversing:
		var rear := c - f * tip
		_lamp_polys.append([_rect(rear, f, r, light_r * 0.325, -light_r * 0.325, light_len * 0.325), RS.REVERSE_LIGHT])
		lamp_glow(rear - f * REVERSE_GLOW[1] * 0.45, REVERSE_GLOW, light_level, glow_points, glow_colors, glow_triangles)
	if turn_signal != "" and RS.signal_lit(signal_elapsed):
		for signal_side: float in ([1.0, -1.0] if turn_signal == "hazard" else [1.0 if turn_signal == "right" else -1.0]):
			for end: float in [1.0, -1.0]:
				var lamp: Vector2 = c + f * tip * end + r * hw * 0.88 * signal_side
				_lamp_polys.append([_rect(lamp, f, r, light_w * 0.6, -light_w * 0.6, maxf(_px(1.0), light_len * 0.45) * 0.5), RS.TURN_SIGNAL])


## Four rising, fading puffs (crash smoke and exhaust; sizes in screen
## pixels). `behind` trails them out of the back; `strength` (exhaust: the
## throttle) makes them thicker, darker, bigger and faster - an idling
## engine only breathes faintly.
func _smoke(c: Vector2, heading: float, length: float, t: float, behind := false, strength := 1.0) -> void:
	if not smoke_enabled:
		return
	var f := _forward(heading)
	var r := _right(heading)
	var base := c + f * (length * 0.4) * (-1.0 if behind else 1.0)
	for i in 4:
		var offset_t := fmod(t * lerpf(1.5, 3.5, strength) + i * 0.7, 2.0)
		var puff := base
		if behind:
			puff += -f * _px(offset_t * lerpf(8.0, 18.0, strength)) + Vector2(0, -_px(offset_t * 3.0)) + r * _px(sin(t * 3.0 + i) * 2.0 * offset_t)
		else:
			puff += r * _px(sin(t * 3.0 + i) * 4.0 * offset_t) + Vector2(0, -_px(offset_t * 14.0))
		var smoke: Color = RS.SMOKE.darkened(0.35 * strength) if behind else RS.SMOKE
		var max_alpha: float = RS.SMOKE_MAX_ALPHA * (lerpf(0.35, 1.3, strength) if behind else 1.0)
		smoke.a = clampf((1.0 - offset_t / 2.0) * max_alpha, 0.0, max_alpha)
		draw_circle(puff, _px((3.0 + offset_t * 5.0) * (lerpf(0.7, 1.4, strength) if behind else 1.0)), smoke)


## Someone lying flat along `h` (their heading, head first): spread out -
## legs splayed behind, arms flung to the sides; a hockey player's stick
## dropped beside them.
func _fallen(c: Vector2, h: Vector2, side: Vector2, radius: float, clothing: Color, hockey: bool) -> void:
	var hip := c - h * radius * 0.35
	var shoulders := c + h * radius * 0.45
	_rotated_ellipse(c + Vector2(0, radius * 0.25), h, radius * 1.5, radius * 0.75, RS.PED_SHADOW)
	if hockey:
		_canvas.draw_line(c + side * radius * 1.15 - h * radius * 0.9, c + side * radius * 1.15 + h * radius * 1.3,
			_person_lit(STICK_SHAFT), maxf(_px(1.0), radius * 0.12))
	for limb_side: float in [-1.0, 1.0]:
		_canvas.draw_line(hip, hip - h * radius * 0.95 + side * radius * 0.45 * limb_side, _person_lit(RS.PED_LEGS), maxf(_px(1.0), radius * 0.28))
		_canvas.draw_line(shoulders, shoulders + h * radius * 0.2 + side * radius * 0.9 * limb_side, _person_lit(clothing), maxf(_px(1.0), radius * 0.22))
	_rotated_ellipse(c, h, radius * 0.8, radius * 0.5, clothing)
	var head := shoulders + h * radius * 0.5
	_canvas.draw_circle(head, maxf(_px(2.0), radius * 0.42), _person_lit(RS.PED_HAIR))
	_canvas.draw_circle(head + h * radius * 0.08, maxf(_px(1.0), radius * 0.3), _person_lit(RS.PED_HEAD))


## An ellipse with its `rx` axis along `along`.
func _rotated_ellipse(c: Vector2, along: Vector2, rx: float, ry: float, color: Color) -> void:
	_canvas.draw_set_transform(c, along.angle(), Vector2(rx, ry))
	_canvas.draw_circle(Vector2.ZERO, 1.0, _person_lit(color))
	_canvas.draw_set_transform(Vector2.ZERO)


const VOMIT_EDGE := [Vector2(-1.15, -0.12), Vector2(-0.77, -0.34), Vector2(-0.89, -0.59),
	Vector2(-0.3, -0.5), Vector2(0.05, -0.72), Vector2(0.33, -0.48), Vector2(0.88, -0.55),
	Vector2(0.8, -0.24), Vector2(1.24, 0.02), Vector2(0.91, 0.19), Vector2(1.04, 0.43),
	Vector2(0.47, 0.4), Vector2(0.13, 0.67), Vector2(-0.18, 0.46), Vector2(-0.69, 0.57),
	Vector2(-0.6, 0.3), Vector2(-1.06, 0.28), Vector2(-0.93, 0.06)]
const VOMIT_SPLASHES := [Vector3(-1.46, -0.3, 0.11), Vector3(-1.24, -0.75, 0.07),
	Vector3(-0.44, -0.91, 0.12), Vector3(0.32, -1.02, 0.06), Vector3(1.09, -0.78, 0.09),
	Vector3(1.52, -0.2, 0.14), Vector3(1.73, 0.12, 0.05), Vector3(1.34, 0.58, 0.08),
	Vector3(0.56, 0.85, 0.13), Vector3(-0.16, 0.94, 0.06), Vector3(-0.99, 0.79, 0.09)]
const VOMIT_BITS := [Vector3(-0.66, -0.15, 0.12), Vector3(-0.3, 0.26, 0.09),
	Vector3(0.07, -0.32, 0.1), Vector3(0.39, 0.08, 0.15), Vector3(0.75, -0.23, 0.07),
	Vector3(0.14, 0.39, 0.06), Vector3(-0.38, -0.37, 0.05)]
var _vomit_edge := PackedVector2Array(VOMIT_EDGE)
var _vomit_triangles := Geometry2D.triangulate_polygon(_vomit_edge)


func _vomit_puddle(at: Vector2, world_position: Vector2) -> void:
	# Stable world-space variation, never animated or affected by the camera origin.
	var angle := fposmod(world_position.dot(Vector2(0.73, 0.37)), TAU)
	draw_set_transform(at, angle)
	RenderingServer.canvas_item_add_triangle_array(get_canvas_item(), _vomit_triangles, _vomit_edge, PackedColorArray([Color8(105, 115, 62)]))
	for splash in VOMIT_SPLASHES:
		draw_circle(Vector2(splash.x, splash.y), splash.z, Color8(112, 120, 64, 220))
	for i in VOMIT_BITS.size():
		var bit: Vector3 = VOMIT_BITS[i]
		draw_circle(Vector2(bit.x, bit.y), bit.z, Color8(151, 143, 79) if i % 2 == 0 else Color8(78, 88, 43))
	draw_set_transform(Vector2.ZERO)


func _ellipse(c: Vector2, rx: float, ry: float, color: Color) -> void:
	_canvas.draw_set_transform(c, 0.0, Vector2(rx, ry))
	_canvas.draw_circle(Vector2.ZERO, 1.0, _person_lit(color))
	_canvas.draw_set_transform(Vector2.ZERO)


const SANTA_HAT := [Vector2(0, -0.4), Vector2(0, 0.4), Vector2(-0.65, 0.3)]

## A pedestrian: shadow, legs
## stepping with animation_time, body, head facing the heading; fallen ones
## lie down, people going indoors are an outline; then any cursing bubble.
## A bottle in the right hand (server "bottle"); while drinking (hanging
## out) it goes up to the mouth for a sip now and then, on each person's
## own beat.
func _bottle(c: Vector2, h: Vector2, side: Vector2, radius: float, ped: Dictionary, head: Vector2) -> void:
	if not ped.get("bottle", false):
		return
	var hand := c + side * radius * 0.62 + h * radius * 0.25
	var sipping := false
	if ped.get("drinking", false):
		var beat := fmod(_clock + float(absi(hash(ped.get("id", 0))) % 97) * 0.37, 9.0)
		sipping = beat < 1.5
	var neck_dir := (h * 0.8 + side * 0.25).normalized()
	if sipping:  # at the mouth, tipped up
		hand = head + side * radius * 0.2 + h * radius * 0.15
		neck_dir = (h + side * 0.1).normalized()
	var glass := _person_lit(Color8(52, 104, 58))
	_canvas.draw_line(hand - neck_dir * radius * 0.25, hand + neck_dir * radius * 0.2, glass, maxf(_px(1.5), radius * 0.2))
	_canvas.draw_line(hand + neck_dir * radius * 0.2, hand + neck_dir * radius * 0.38, _person_lit(Color8(40, 80, 44)), maxf(_px(1.0), radius * 0.1))


func _pedestrian(c: Vector2, heading: float, ped: Dictionary, animation_time: float) -> void:
	if _canvas == self:  # drawn lit on _people (_draw_people)
		_people_rows.append([c, heading, ped, animation_time])
		return
	var radius := maxf(_px(4.0), ped.get("radius_m", 0.45))
	var clothing: Color = _rgb(ped.get("color", [200, 200, 200]))
	var santa: bool = ped.get("costume", "") == "santa"
	if santa:
		clothing = Color8(190, 30, 35)
	if ped.get("state", "") in INDOORS:
		_canvas.draw_arc(c, radius, 0.0, TAU, 16, _person_lit(RS.PED_INDOORS), _px(1.0))
		return
	var h := Vector2(cos(heading), -sin(heading))
	var side := Vector2(-h.y, h.x)
	var down := Vector2(0, radius)
	if ped.get("animation_state", "") in ["sunbathing", "swimming"]:
		_beach_person(c, h, side, radius, clothing, ped["animation_state"] == "swimming", animation_time)
		return
	_ellipse(c + down * 0.675, radius * 0.8, radius * 0.325, RS.PED_SHADOW)
	if ped.get("animation_state", "") == "riding":
		_canvas.draw_set_transform(c, -heading)
		_canvas.draw_rect(Rect2(Vector2(-radius * 1.7, -radius * 1.1), Vector2(radius * 3.4, radius * 2.2)), _person_lit(Color8(224, 93, 46)))
		_canvas.draw_set_transform(Vector2.ZERO)
		_ellipse(c, radius * 0.65, radius * 0.55, clothing)
		_ellipse(c - down * 0.4, radius * 0.4, radius * 0.4, RS.PED_HEAD)
		_canvas.draw_line(c - side * radius, c + side * radius, _person_lit(Color8(223, 223, 211)), radius * 0.22)
		return
	if ped.get("animation_state", "walking") == "sitting":
		for sign_side: float in [-1.0, 1.0]:
			var knee := c + h * radius * 0.8 + side * radius * sign_side * 0.7
			_canvas.draw_line(c, knee, _person_lit(RS.PED_LEGS), radius * 0.4)
			_canvas.draw_line(knee, knee - h * radius * 0.6, _person_lit(RS.PED_LEGS), radius * 0.3)
		_ellipse(c, radius * 0.7, radius * 0.55, clothing)
		_canvas.draw_circle(c - h * radius * 0.25, radius * 0.4, _person_lit(RS.PED_HEAD))
		_bottle(c, h, side, radius, ped, c - h * radius * 0.25)
	elif ped.get("animation_state", "walking") == "fallen":
		_fallen(c, h, side, radius, clothing, ped.get("activity", "") == "ice_hockey")
	else:
		var gait := sin(animation_time * 10.0) if ped.get("animation_state", "walking") == "walking" else 0.0
		var leg_start := c - h * radius * 0.15 + down * 0.45
		for leg_side: float in [-1.0, 1.0]:
			var leg_end: Vector2 = leg_start + side * radius * 0.42 * leg_side + h * radius * (0.12 + gait * 0.45 * leg_side) + down * 0.45
			_canvas.draw_line(leg_start, leg_end, _person_lit(RS.PED_LEGS), maxf(_px(1.0), radius * 0.28))
		_ellipse(c + down * 0.425, radius * 0.72, radius * 0.775, RS.PED_SHADOW)
		_ellipse(c + down * 0.405, radius * 0.58, radius * 0.625, clothing)
		var head := c + h * radius * 0.6
		_canvas.draw_circle(head, maxf(_px(2.0), radius * 0.48), _person_lit(RS.PED_HAIR))
		_canvas.draw_circle(head, maxf(_px(1.0), radius * 0.35), _person_lit(RS.PED_HEAD))
		_bottle(c, h, side, radius, ped, head)
		if santa:
			_canvas.draw_line(c - side * radius * 0.5, c + side * radius * 0.5, _person_lit(Color.WHITE), radius * 0.20)
			_canvas.draw_line(head - side * radius * 0.38, head + side * radius * 0.38, _person_lit(Color.WHITE), radius * 0.22)
			_canvas.draw_circle(head + h * radius * 0.26, radius * 0.3, _person_lit(Color.WHITE))  # beard
			var tip := head - h * radius * 0.65 + side * radius * 0.3
			# Triangulate near zero: tiny world-coordinate hats lose precision far from the origin.
			_canvas.draw_set_transform(head, -heading, Vector2.ONE * radius)
			_canvas.draw_colored_polygon(PackedVector2Array(SANTA_HAT), _person_lit(clothing))
			_canvas.draw_set_transform(Vector2.ZERO)
			_canvas.draw_circle(tip, radius * 0.17, _person_lit(Color.WHITE))
		if ped.get("activity", "") == "ice_hockey":
			var goalie: bool = ped.get("hockey_goalie", false)
			if goalie:  # leg pads, either side
				for pad_side: float in [-1.0, 1.0]:
					_ellipse(c + side * radius * 0.55 * pad_side + down * 0.2, radius * 0.22, radius * 0.5, GOALIE_PADS)
			_hockey_stick(c, h, side, radius, float(ped.get("stick_swing", 0.0)), goalie)
		if ped.get("activity", "") == "beach_volleyball":
			var swing := float(ped.get("stick_swing", 0.0))
			for arm_side: float in [-1.0, 1.0]:
				var shoulder := c + side * radius * .55 * arm_side
				var hand := c + h * radius * (1.0 + swing) + side * radius * .25 * arm_side - Vector2(0, swing * radius)
				_canvas.draw_line(shoulder, hand, _person_lit(RS.PED_HEAD), radius * .28)
		if ped.get("activity", "") == "brawl":  # fists up; the striking one thrown forward
			var punch := float(ped.get("stick_swing", 0.0))
			for arm_side: float in [-1.0, 1.0]:
				var reach := 0.8 + (punch * 0.9 if arm_side > 0.0 else 0.0)
				_canvas.draw_line(c + side * radius * .55 * arm_side, c + h * radius * reach + side * radius * .3 * arm_side,
					_person_lit(RS.PED_HEAD), radius * .26)
		if ped.get("activity", "") == "tennis":
			var swing := float(ped.get("stick_swing", 0.0))
			var forward := h.rotated(sin(swing * PI) * 1.2)
			var hand := c + side * radius * .65
			var grip := hand + forward * radius * 1.3
			_canvas.draw_line(hand, grip, _person_lit(RS.PED_HEAD), radius * .3)
			var head_at := grip + forward * radius * .65
			_canvas.draw_line(grip, head_at, _person_lit(Color8(85, 85, 95)), radius * .15)
			_canvas.draw_arc(head_at, radius * .6, 0, TAU, 16, _person_lit(Color8(225, 225, 215)), radius * .14)
			_canvas.draw_line(head_at - side * radius * .45, head_at + side * radius * .45, _person_lit(Color8(170, 190, 180)), radius * .08)
		if ped.has("golf"):
			_golf_club(c, h, side, radius, ped["golf"])
	if ped.get("curse_timer", 0.0) > 0.0:
		var timer: float = ped["curse_timer"]
		_bubble(c - Vector2(0, radius + _px(6.0)), str(ped.get("curse_text", "@#*!%")), RS.CURSE_TEXT, RS.CURSE_BORDER,
			1.0 if timer >= 0.5 else timer / 0.5)


## The player is out of the taxi in a brawl: its figure stands in for theirs.
static func player_fighting(state: Dictionary) -> bool:
	for brawl in state.get("brawls", []):
		for f in brawl.get("fighters", []):
			if f.get("kind", "") == "player" and not f.get("in_car", false):
				return true
	return false


## Taxi drivers' quarrels (server "brawls": current state only). Each fighter
## is a pedestrian figure; a punch plays once per server action seq, so a
## duplicated or late update never swings twice and a fresh snapshot shows
## no more than the current blow.
func _brawls(a: Dictionary, b: Dictionary, t: float, view_rect: Rect2) -> int:
	var drawn := 0
	var later := _by_id(b.get("brawls", []))
	var now := Time.get_ticks_msec() / 1000.0
	var live := {}
	for brawl in a.get("brawls", []):
		live[brawl["id"]] = true
		var action = brawl.get("action")
		if typeof(action) == TYPE_DICTIONARY and action.get("kind", "") in ["strike", "dodge"]:
			var seen: Array = _brawl_punches.get(brawl["id"], [-1, 0.0])
			if int(action["seq"]) > int(seen[0]):
				_brawl_punches[brawl["id"]] = [int(action["seq"]), now]
		var punch: Array = _brawl_punches.get(brawl["id"], [-1, -10.0])
		var swing := clampf(1.0 - (now - float(punch[1])) / 0.35, 0.0, 1.0)
		var next_fighters: Array = later.get(brawl["id"], brawl).get("fighters", brawl["fighters"])
		for i in brawl["fighters"].size():
			var f: Dictionary = brawl["fighters"][i]
			if f.get("in_car", false):
				continue  # the player still at the wheel: the taxi is drawn, not a figure
			var p := StateBuffer.blend(f, next_fighters[i] if i < next_fighters.size() else f, t, origin)
			var c := Vector2(p.x, p.y)
			if not view_rect.has_point(c):
				continue
			var striking: bool = typeof(action) == TYPE_DICTIONARY and int(action.get("actor", -1)) == i
			_pedestrian(c, p.z, {
				"color": PLAYER_JACKET if f.get("kind", "") == "player" else BRAWL_JACKETS[i % BRAWL_JACKETS.size()],
				"animation_state": "fallen" if f.get("down", false) else "walking" if f.get("moving", false) else "standing",
				"activity": "" if f.get("down", false) else "brawl",
				"stick_swing": swing if striking else 0.0,
				"curse_timer": f.get("curse_timer", 0.0), "curse_text": f.get("curse_text", ""),
			}, now)
			_rage_face(c, p.z, float(f.get("rage", 0.0)), f.get("down", false))
			drawn += 1
	for id in _brawl_punches.keys():  # over: forget it
		if not live.has(id):
			_brawl_punches.erase(id)
	return drawn


## The server's rage on a fighter's face: a red flush that deepens with it,
## and anger marks once it is extreme (taxi_brawls.RAGE_EXTREME). Looks only.
func _rage_face(c: Vector2, heading: float, rage: float, down: bool) -> void:
	if rage < 0.1 or down:
		return
	var radius := maxf(_px(4.0), 0.45)
	var head := c + Vector2(cos(heading), -sin(heading)) * radius * 0.6
	_canvas.draw_circle(head, maxf(_px(1.0), radius * 0.35), _person_lit(Color(0.85, 0.1, 0.05, 0.6 * rage)))
	if rage >= 0.7:
		var mark := head + Vector2(radius * 0.55, -radius * 0.75)
		for i in 4:
			var d := Vector2.from_angle(PI * 0.25 + i * PI * 0.5) * radius * 0.22
			_canvas.draw_line(mark + d * 0.4, mark + d * 1.6, _person_lit(Color8(220, 20, 20)), maxf(_px(1.0), radius * 0.1))


## Relaxed beach poses and swimming strokes; the server decides land versus water.
func _beach_person(c: Vector2, h: Vector2, side: Vector2, radius: float, clothing: Color, swimming: bool, time: float) -> void:
	var skin := _person_lit(RS.PED_HEAD)
	if not swimming:
		_canvas.draw_set_transform(c, h.angle())
		_canvas.draw_rect(Rect2(Vector2(-1.9, -0.9) * radius, Vector2(3.8, 1.8) * radius), _person_lit(clothing.lightened(0.3)))
		_canvas.draw_rect(Rect2(Vector2(-1.9, -0.9) * radius, Vector2(3.8, 1.8) * radius), _person_lit(Color.WHITE), false, _px(1))
		_canvas.draw_set_transform(Vector2.ZERO)
		_canvas.draw_line(c - h * radius * 0.5, c + h * radius * 0.65, skin, radius * 0.7)
		for sign_side: float in [-1.0, 1.0]:
			_canvas.draw_line(c - h * radius * 0.45, c - h * radius * 1.5 + side * radius * 0.3 * sign_side, skin, radius * 0.22)
			_canvas.draw_line(c + h * radius * 0.4, c + side * radius * 0.85 * sign_side, skin, radius * 0.2)
		_rotated_ellipse(c - h * radius * 0.35, h, radius * 0.35, radius * 0.4, clothing)
	else:
		_swimmer(c, h, side, radius, clothing, time + _clock)
		return
	var head := c + h * radius * 0.95
	_canvas.draw_circle(head, radius * 0.43, _person_lit(RS.PED_HAIR))
	_canvas.draw_circle(head, radius * 0.32, skin)


func _swimmer(c: Vector2, h: Vector2, side: Vector2, radius: float, clothing: Color, time: float) -> void:
	var skin := _person_lit(RS.PED_HEAD)
	var submerged := Color(skin, 0.4)
	for sign_side: float in [-1.0, 1.0]:
		var wake := PackedVector2Array()
		for i in 7:
			var t := float(i) / 6.0
			wake.append(c - h * radius * (0.6 + t * 1.4) + side * radius * sign_side * (0.5 + t * 0.55))
		_canvas.draw_polyline(wake, _person_lit(Color(0.85, 0.95, 1.0, 0.35)), _px(0.8))
		var kick := sin(time * 7.0 + sign_side * PI * 0.5)
		_canvas.draw_line(c - h * radius * .65 + side * radius * .18 * sign_side,
			c - h * radius * (1.8 + kick * .15) + side * radius * .25 * sign_side, submerged, radius * .22)
	_rotated_ellipse(c - h * radius * .1, h, radius * .8, radius * .38, RS.PED_HEAD)
	_rotated_ellipse(c - h * radius * .65, h, radius * .35, radius * .4, clothing)
	for sign_side: float in [-1.0, 1.0]:
		var stroke := sin(time * 4.0 + sign_side * PI * 0.5)
		var shoulder := c + h * radius * .35 + side * radius * .3 * sign_side
		var elbow := shoulder + side * radius * .65 * sign_side + h * radius * stroke * .35
		var hand := elbow + h * radius * stroke * .9 - side * radius * .25 * sign_side
		_canvas.draw_polyline(PackedVector2Array([shoulder, elbow, hand]), skin, radius * .25)
	var head := c + h * radius * .9
	_canvas.draw_circle(head, radius * .4, _person_lit(RS.PED_HAIR))
	_canvas.draw_circle(head + h * radius * .06, radius * .3, skin)


## Golf clubs follow the server's club choice and swing progress.
func _golf_club(c: Vector2, h: Vector2, side: Vector2, radius: float, golf: Dictionary) -> void:
	var putting: bool = golf.get("club", "") == "putter"
	var swing: float = float(golf.get("swing", 0.0))
	var angle := (1.0 - swing) * (0.35 if putting else 1.5) if golf.get("phase", "") == "swing" else 0.0
	var hand := c + side * radius * 0.45
	var head := hand + h.rotated(angle) * (0.8 if putting else 1.05)
	if golf.get("phase", "") == "walk":
		hand = c + side * radius * 0.95
		head = hand + Vector2(0, 0.85)
	_canvas.draw_line(hand, head, _person_lit(Color8(195, 200, 205)), maxf(_px(1.2), 0.05))
	_canvas.draw_circle(hand, maxf(_px(1.4), radius * 0.18), _person_lit(RS.PED_HEAD))
	if putting:
		_canvas.draw_line(head - side * 0.16, head + side * 0.16, _person_lit(STICK_BLADE), maxf(_px(2.0), 0.09))
	else:
		_canvas.draw_circle(head, maxf(_px(2.0), 0.13 if golf.get("club", "") == "driver" else 0.08), _person_lit(STICK_BLADE))


## The ball and its ground shadow remain visible when the golfer is off screen.
func _golf_ball(row: Array) -> void:
	var ground: Vector2 = row[0]
	var pin: Vector2 = row[2]
	_lit_tint = vehicle_light(light_level * float(light_at.call(pin)), ambient)
	if view_rect.has_point(pin):
		_canvas.draw_circle(pin, maxf(_px(2.0), 0.11), _person_lit(STICK_BLADE))
		var top := pin - Vector2(0, 1.6)
		_canvas.draw_line(pin, top, _person_lit(Color.WHITE), maxf(_px(1.0), 0.04))
		_canvas.draw_set_transform(top)
		_canvas.draw_colored_polygon(PackedVector2Array([Vector2.ZERO, Vector2(0.65, 0.2), Vector2(0, 0.45)]), _person_lit(Color8(225, 45, 40)))
		_canvas.draw_set_transform(Vector2.ZERO)
	if row[3]:
		return
	var at := ground - Vector2(0, float(row[1]) * 0.35)
	if view_rect.has_point(ground) or view_rect.has_point(at):
		_lit_tint = vehicle_light(light_level * float(light_at.call(ground)), ambient)
		_canvas.draw_circle(ground, maxf(_px(1.8), 0.07), RS.PED_SHADOW)
		_canvas.draw_circle(at, maxf(_px(2.2), 0.045) + _px(0.6), _person_lit(STICK_BLADE))
		_canvas.draw_circle(at, maxf(_px(2.2), 0.045), _person_lit(SOCCER_BALL))


## A non-colliding owned dog and its leash, batched with its pedestrian.
func _dog(owner: Vector2, at: Vector2, heading: float, dog: Dictionary) -> void:
	var sizes := {"small": 0.28, "medium": 0.38, "large": 0.50}
	var radius: float = sizes.get(str(dog.get("size", "medium")), 0.38)
	var h := Vector2(cos(heading), -sin(heading))
	var side := Vector2(-h.y, h.x)
	var body := _rgb(dog.get("color", [120, 90, 60]))
	_canvas.draw_line(owner + side * 0.22, at - h * radius * 0.15, _person_lit(Color8(48, 38, 32)), maxf(_px(1.2), 0.06))
	_ellipse(at + Vector2(0, radius * 0.35), radius * 0.85, radius * 0.38, RS.PED_SHADOW)
	_ellipse(at, radius * 0.72, radius, body)
	var head := at + h * radius * (0.78 if dog.get("sniffing", false) else 1.02)
	_canvas.draw_circle(head, radius * 0.58, _person_lit(body.lightened(0.06)))
	var ear := PackedColorArray([_person_lit(body.darkened(0.25))])
	for s: float in [1.0, -1.0]:  # draw_primitive: a few-cm triangle needs no triangulation (which rejected it)
		_canvas.draw_primitive(PackedVector2Array([head + side * radius * 0.42 * s,
			head - h * radius * 0.48 + side * radius * 0.62 * s, head - h * radius * 0.22 + side * radius * 0.18 * s]), ear, PackedVector2Array())
	_canvas.draw_line(at - h * radius * 0.75, at - h * radius * 1.35 + side * radius * 0.35,
		_person_lit(body.darkened(0.12)), maxf(_px(1.5), radius * 0.24))


## An ice hockey player's stick: from the right hand forward to the blade on
## the ice; a hit (state stick_swing, seconds left) sweeps it through.
const STICK_SWING_S := 0.3  # ice_hockey.py STICK_SWING_S
const STICK_SHAFT := Color8(150, 110, 60)
const STICK_BLADE := Color8(25, 25, 28)
const GOALIE_PADS := Color8(236, 236, 230)
const SOCCER_BALL := Color8(250, 250, 250)


func _hockey_stick(c: Vector2, h: Vector2, side: Vector2, radius: float, swing: float, goalie := false) -> void:
	var hand := c + side * radius * 0.55 + h * radius * 0.2
	var reach := (h * 1.7 + side * 0.5).normalized() * radius * 2.4
	if swing > 0.0:  # the follow-through: swept across, back to rest as the swing ends
		reach = reach.rotated(-1.2 * swing / STICK_SWING_S)
	var blade_root := hand + reach
	_canvas.draw_line(hand, blade_root, _person_lit(STICK_SHAFT), maxf(_px(1.0), radius * 0.12))
	# A goalie's stick has the wide paddle and blade.
	_canvas.draw_line(blade_root, blade_root - side * radius * (0.8 if goalie else 0.55), _person_lit(STICK_BLADE), maxf(_px(1.5), radius * (0.3 if goalie else 0.18)))


## Pucks on the rinks (state "pucks"): small and black, where the
## simulation slid them (moved on toward the next state's spot).
func _pucks(a: Dictionary, b: Dictionary, t: float) -> void:
	if _canvas == self:
		_puck_frame = [a, b, t]
		return
	for key in ["pucks", "balls"]:  # hockey pucks black; soccer balls white, outlined
		var now: Array = a.get(key, [])
		var next: Array = b.get(key, [])
		for i in now.size():
			var p: Array = now[i]
			var q: Array = next[i] if next.size() == now.size() else p
			var at := MapMath.point(origin, lerpf(p[0], q[0], t), lerpf(p[1], q[1], t))
			_lit_tint = vehicle_light(light_level * float(light_at.call(at)), ambient)
			if key == "pucks":
				_canvas.draw_circle(at, maxf(_px(2.5), 0.12), _person_lit(STICK_BLADE))
			else:
				var radius := maxf(_px(3.0), 0.11)
				_canvas.draw_circle(at, radius + maxf(_px(0.7), 0.02), _person_lit(STICK_BLADE))
				_canvas.draw_circle(at, radius, _person_lit(SOCCER_BALL))


## A text bubble whose bottom centre is at `anchor`, drawn in screen
## pixels (constant size whatever the zoom).
func _bubble(anchor: Vector2, text: String, text_color: Color, border: Color, alpha := 1.0, font_size := 14, tail := false) -> void:
	if _canvas == self:  # text never dims: on _overlay
		_overlays.append(_bubble.bind(anchor, text, text_color, border, alpha, font_size, tail))
		return
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var box := Rect2(Vector2(-size.x / 2.0 - 4.0, -size.y - 4.0 - (8.0 if tail else 0.0)), size + Vector2(8.0, 4.0))
	_canvas.draw_set_transform(anchor, 0.0, Vector2.ONE / px_per_m)
	_canvas.draw_rect(box, Color(1, 1, 1, minf(240.0 / 255.0, alpha)))
	_canvas.draw_rect(box, Color(border, alpha), false, 1.0)
	if tail:
		_canvas.draw_colored_polygon(PackedVector2Array([Vector2(-7, -8), Vector2(7, -8), Vector2(0, 0)]), Color(1, 1, 1, alpha))
	_canvas.draw_string(_font, box.position + Vector2(4.0, size.y - 2.0), text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color(text_color, alpha))
	_canvas.draw_set_transform(Vector2.ZERO)


## A line bus's number on its roof: a dark box along the bus, turning
## with it (never upside down), about as tall as the bus is wide.
func _bus_number(c: Vector2, heading: float, text: String) -> void:
	if _canvas == self:  # text never dims: on _overlay
		_overlays.append(_bus_number.bind(c, heading, text))
		return
	var font_size := clampi(roundi(1.5 * px_per_m), 6, 48)
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var box := Rect2(Vector2(-size.x / 2.0 - 3.0, -size.y / 2.0), size + Vector2(6.0, 0.0))
	var angle := -heading if cos(heading) >= 0.0 else PI - heading
	_canvas.draw_set_transform(c, angle, Vector2.ONE / px_per_m)
	_canvas.draw_rect(box, Color8(20, 20, 20, 230))
	_canvas.draw_string(_font, Vector2(box.position.x + 3.0, _font.get_ascent(font_size) - size.y / 2.0), text,
		HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color8(255, 190, 60))
	_canvas.draw_set_transform(Vector2.ZERO)


## A label with a dark background (the target and customer tags).
func _tag(anchor: Vector2, text: String, text_color: Color, border = null, font_size := 14) -> void:
	if _canvas == self:  # text never dims: on _overlay
		_overlays.append(_tag.bind(anchor, text, text_color, border, font_size))
		return
	var size := _font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var box := Rect2(Vector2(-size.x / 2.0 - 4.0, -size.y / 2.0 - 2.0), size + Vector2(8.0, 4.0))
	_canvas.draw_set_transform(anchor, 0.0, Vector2.ONE / px_per_m)
	_canvas.draw_rect(box, Color8(20, 20, 20, 220))
	if border != null:
		_canvas.draw_rect(box, border, false, 1.0)
	_canvas.draw_string(_font, box.position + Vector2(4.0, size.y - 1.0), text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, text_color)
	_canvas.draw_set_transform(Vector2.ZERO)


## A person's colour in the light they stand in (_lit_tint, set per person).
func _person_lit(color: Color) -> Color:
	return Color(color.r * _lit_tint.r, color.g * _lit_tint.g, color.b * _lit_tint.b, color.a)


func _draw_people() -> void:
	_canvas = _people
	for row in _dog_rows:
		_lit_tint = vehicle_light(light_level * float(light_at.call(row[1])), ambient)
		_dog(row[0], row[1], row[2], row[3])
	for row in _people_rows:
		_lit_tint = vehicle_light(light_level * float(light_at.call(row[0])), ambient)
		_pedestrian(row[0], row[1], row[2], row[3])
	if not _puck_frame.is_empty():
		_pucks(_puck_frame[0], _puck_frame[1], _puck_frame[2])
	for row in _golf_rows:
		_golf_ball(row)
	for ball in _tennis_balls:
		var ground := Vector2(ball.x, ball.y)
		_lit_tint = vehicle_light(light_level * float(light_at.call(ground)), ambient)
		_canvas.draw_circle(ground, maxf(_px(1.5), .08), RS.PED_SHADOW)
		_canvas.draw_circle(ground - Vector2(0, ball.z * .7), maxf(_px(2), .09), _person_lit(Color8(220, 245, 65)))
	for ball in _beach_balls:
		var ground := Vector2(ball.x, ball.y)
		_lit_tint = vehicle_light(light_level * float(light_at.call(ground)), ambient)
		var at := ground - Vector2(0, ball.z * ball.w)
		_canvas.draw_circle(ground, maxf(_px(2), 0.12), RS.PED_SHADOW)
		_canvas.draw_circle(at, maxf(_px(3), 0.17), _person_lit(Color8(250, 215, 60)))
		_canvas.draw_arc(at, maxf(_px(2), 0.12), 0, PI, 8, _person_lit(Color8(230, 80, 55)), maxf(_px(1.2), 0.05))
	_lit_tint = Color.WHITE
	_canvas = self


func _rgb(values: Array) -> Color:
	return Color8(int(values[0]), int(values[1]), int(values[2]))


## The job target and the waiting customer; the off-screen arrow is screen UI (nav_overlay.gd).
## The navigation route: the server's route (state
## navigation.points) above the roads and pedestrians, under the target
## marker and the vehicles - dark edge, gold centre. Converted once per new route.
## Drawn on its own unshaded node, tinted half way from the night's
## ambient to daylight: dimmer at night, never lost in the dark.
func _route(state: Dictionary) -> void:
	_route_now = route_for(state)
	_route_node.queue_redraw()


func _draw_route() -> void:
	if _route_now.size() < 2:
		return
	var tint := route_tint(ambient)
	_route_node.draw_polyline(_route_now, RS.ROUTE_EDGE * tint, maxf(_px(5.0), 0.8))
	_route_node.draw_polyline(_route_now, RS.ROUTE * tint, maxf(_px(2.0), 0.45))


static func route_tint(ambient_color: Color) -> Color:
	return Color(ambient_color.lerp(Color.WHITE, ROUTE_NIGHT_VISIBILITY), 1.0)


## The route to draw this frame: none while N is off or there's no target.
func route_for(state: Dictionary) -> PackedVector2Array:
	if not show_route or current_target(state).is_empty():
		return PackedVector2Array()
	var source = state.get("navigation", {}).get("points") if state.get("navigation") is Dictionary else null
	if source != _route_source:  # a new route (or the first): convert once
		_route_source = source
		_route_points = route_points(source, origin)
	return _route_points


## The server's active rage shout ([text, alpha]: full, fading over the last
## 0.5 s), or [] - nothing for absent, malformed or expired state.
static func shout_for(state: Dictionary) -> Array:
	var shout = state.get("road_rage")
	if not shout is Dictionary or typeof(shout.get("text")) != TYPE_STRING or shout["text"] == "" \
			or not typeof(shout.get("timer")) in [TYPE_INT, TYPE_FLOAT] or not is_finite(shout["timer"]) or shout["timer"] <= 0.0:
		return []
	return [shout["text"], minf(1.0, shout["timer"] / 0.5)]


## World [[x, y], ...] -> layer points; anything malformed (or < 2 points) -> none.
static func route_points(source, world_origin: Vector2) -> PackedVector2Array:
	var points := PackedVector2Array()
	if typeof(source) != TYPE_ARRAY or source.size() < 2:
		return points
	for p in source:
		if typeof(p) != TYPE_ARRAY or p.size() < 2 or not typeof(p[0]) in [TYPE_INT, TYPE_FLOAT] or not typeof(p[1]) in [TYPE_INT, TYPE_FLOAT] \
				or not is_finite(p[0]) or not is_finite(p[1]):
			return PackedVector2Array()
		points.append(MapMath.point(world_origin, p[0], p[1]))
	return points


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
		_tag(at - Vector2(0, radius + _px(14.0)), "[%s] %s" % [T.text("pickup", language) if target["is_pickup"] else T.text("destination", language), target.get("address", "")],
			Color.WHITE, main_color)
	var passenger: Dictionary = state["taxi"]["current_passenger"]
	if target["is_pickup"] and not passenger.get("boarded", false) and passenger.has("ped"):
		for member in [passenger] + passenger.get("companions", []):
			if member.get("rail_booking", false):
				continue  # The booked lead has its own pedestrian; companions use the fare representation.
			var ped: Array = member["ped"]
			var c := MapMath.point(origin, ped[0], ped[1])
			var radius := maxf(_px(4.0), 0.5)
			draw_circle(c, radius + _px(2.0), RS.OUTLINE)
			draw_circle(c, radius, RS.CUSTOMER_COLOR)
			draw_circle(c + _forward(ped[2]) * radius * 0.9, maxf(_px(1.0), radius * 0.45), Color.WHITE)
			_tag(c - Vector2(0, radius + _px(12.0)), passenger_tag(member, language),
				Color8(255, 230, 80))


static func passenger_tag(member: Dictionary, lang: String) -> String:
	return "[%s] %s" % [T.text("to_taxi", lang) if member.get("is_walking_to_car", false) else T.text("pickup", lang), member.get("name", "")]


func _draw() -> void:
	if _frame.is_empty():
		return
	var started := Time.get_ticks_usec()
	var a: Dictionary = _frame["a"]
	var b: Dictionary = _frame["b"]
	var t: float = _frame["t"]
	var count := 0
	_lamp_polys.clear()
	_people_rows.clear()
	_dog_rows.clear()
	_golf_rows.clear()
	_tennis_balls.clear()
	_beach_balls.clear()
	_puck_frame = []
	_overlays.clear()
	_car_shapes.clear()
	_under_shapes.clear()
	_under_lamps.clear()
	glow_points.clear()
	glow_colors.clear()
	glow_triangles.clear()
	if not underground:
		for point in a.get("vomit_puddles", []):
			if point.size() >= 2:
				var at := MapMath.point(origin, point[0], point[1])
				if view_rect.has_point(at):
					_vomit_puddle(at, Vector2(point[0], point[1]))
		for print_point in a.get("vomit_footprints", []):
			if print_point.size() >= 3:
				var at := MapMath.point(origin, print_point[0], print_point[1])
				if view_rect.has_point(at):
					draw_set_transform(at, -float(print_point[2]), Vector2(maxf(_px(1.5), 0.14), maxf(_px(1.0), 0.06)))
					draw_circle(Vector2.ZERO, 1.0, Color8(95, 104, 55, 210))
					draw_set_transform(Vector2.ZERO)

	if not underground:
		var later_protests := _by_id(b.get("protests", []))
		for group in a.get("protests", []):
			var next_group: Dictionary = later_protests.get(group["id"], group)
			var seated: bool = group.get("state", "SITTING") in ["SITTING", "ALARMED"]
			for i in group.get("members", []).size():
				var at: Array = group["members"][i]
				var c := MapMath.point(origin, at[0], at[1])
				if next_group.get("members", []).size() == group["members"].size():
					var next_at: Array = next_group["members"][i]
					c = c.lerp(MapMath.point(origin, next_at[0], next_at[1]), t)
				if view_rect.has_point(c):
					_pedestrian(c, float(group["heading"]) + sin(i * 7.3) * 0.35, {
						"radius_m": 0.45, "color": [210, 100 + (i * 29) % 110, 50 + (i * 17) % 100],
						"animation_state": "sitting" if seated else "walking" if group["state"] in ["CLEARING", "RETURNING"] else "standing"
					}, float(a.get("sim_time", 0.0)))
					count += 1
			var banner_at: Array = group["members"][0]
			var banner := MapMath.point(origin, banner_at[0], banner_at[1])
			if view_rect.has_point(banner):
				_canvas.draw_rect(Rect2(banner + Vector2(-3.5, -3.0), Vector2(7, 1.3)), Color8(245, 213, 70))
				_canvas.draw_set_transform(banner + Vector2(-3.3, -2.0), 0.0, Vector2.ONE * 0.08)
				_canvas.draw_string(ThemeDB.fallback_font, Vector2.ZERO, "ILOKAPINA", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color8(30, 30, 30))
				_canvas.draw_set_transform(Vector2.ZERO)
	var later_peds := _by_id(b.get("pedestrians", []))
	for ped in ([] if underground else a.get("pedestrians", [])):  # below ground: the surface world isn't shown
		var next: Dictionary = later_peds.get(ped["id"], ped)
		var p := StateBuffer.blend(ped, next, t, origin)
		var c := Vector2(p.x, p.y)
		if ped.has("tennis_ball"):
			var ball: Array = ped["tennis_ball"]
			var later: Array = next.get("tennis_ball", ball)
			var at := MapMath.point(origin, lerpf(ball[0], later[0], t), lerpf(ball[1], later[1], t))
			if view_rect.has_point(at):
				_tennis_balls.append(Vector3(at.x, at.y, lerpf(ball[2], later[2], t)))
		if ped.has("beach_ball"):
			var ball: Array = ped["beach_ball"]
			var later: Array = next.get("beach_ball", ball)
			var at := MapMath.point(origin, lerpf(ball[0], later[0], t), lerpf(ball[1], later[1], t))
			if view_rect.has_point(at):
				var height_scale := 0.7 if ped.get("activity", "") == "beach_volleyball" else 0.35
				_beach_balls.append(Vector4(at.x, at.y, lerpf(ball[2], later[2], t), height_scale))
		var golf: Dictionary = ped.get("golf", {})
		if not golf.is_empty():
			var later_golf: Dictionary = next.get("golf", golf)
			var ball: Array = golf["ball"]
			var later_ball: Array = later_golf.get("ball", ball)
			var pin: Array = golf["pin"]
			_golf_rows.append([MapMath.point(origin, lerpf(ball[0], later_ball[0], t), lerpf(ball[1], later_ball[1], t)),
				lerpf(ball[2], later_ball[2], t), MapMath.point(origin, pin[0], pin[1]), golf.get("holed", false)])
		if not view_rect.has_point(c):
			continue
		var dog: Dictionary = ped.get("dog", {})
		if not dog.is_empty():
			var next_dog: Dictionary = next.get("dog", dog)
			var dog_at := MapMath.point(origin, lerpf(float(dog["x"]), float(next_dog.get("x", dog["x"])), t), lerpf(float(dog["y"]), float(next_dog.get("y", dog["y"])), t))
			var dog_heading := lerp_angle(float(dog.get("heading", 0.0)), float(next_dog.get("heading", dog.get("heading", 0.0))), t)
			_dog_rows.append([c, dog_at, dog_heading, dog])
			count += 1
		_pedestrian(c, p.z, ped, lerpf(ped.get("animation_time", 0.0), next.get("animation_time", 0.0), t))
		count += 1
	if not underground:
		_pucks(a, b, t)
	var later_npc_rows := _by_id(b.get("npcs", []))
	for npc in a.get("npcs", []):  # NPC drivers out of their car are drawn as pedestrians
		if underground or not npc.get("is_on_foot", false):
			continue
		var p := StateBuffer.blend(npc, later_npc_rows.get(npc["id"], npc), t, origin)
		var c := Vector2(p.x, p.y)
		if view_rect.has_point(c):
			_pedestrian(c, p.z, {"color": npc.get("color", [200, 200, 200])}, 0.0)
			count += 1
	if not underground:
		count += _brawls(a, b, t, view_rect)
	if a.get("on_foot", false) and not player_fighting(a):  # in a brawl the fighter figure is the player
		var walker := StateBuffer.blend(a["player_pedestrian"], b.get("player_pedestrian", a["player_pedestrian"]), t, origin)
		_pedestrian(Vector2(walker.x, walker.y), walker.z, {"color": [255, 217, 64], "animation_state": "standing"}, 0.0)
		count += 1

	_route(a)
	_target(a)

	var player: Dictionary = a["player"]
	var taxi := StateBuffer.blend(player, b.get("player", player), t, origin)
	var taxi_at := Vector2(taxi.x, taxi.y)
	var taxi_length: float = player.get("length_m", 4.4)
	var road: Dictionary = a.get("road", {}) if typeof(a.get("road")) == TYPE_DICTIONARY else {}
	var taxi_under: bool = not road.get("bridge", false) and covered.call(taxi_at, int(road.get("layer", 0)))
	if player.get("engine_on", false) and not taxi_under:
		_exhaust = lerpf(_exhaust, float(player.get("throttle", 0.0)), 0.15)  # eased: no flicker per snapshot
		_smoke(taxi_at, taxi.z, taxi_length, _clock, true, _exhaust)
	taxi_sign_on = taxi_sign_lit(a.get("taxi", {}))
	_vehicle(taxi_at, taxi.z, taxi_length, player.get("width_m", 1.8), RS.TAXI_BODY, "car", true,
		player.get("engine_on", false), player.get("braking", false), is_reversing(player.get("speed", 0.0)), "", 0.0, false, taxi_under)
	taxi_sign_on = false
	var smoke_timer: float = a.get("taxi", {}).get("taxi_smoke_timer", 0.0)
	if smoke_timer > 0.0:
		_smoke(taxi_at, taxi.z, taxi_length, 5.0 - smoke_timer)
	var shout := shout_for(a)
	if not shout.is_empty():  # the rage shout above the taxi, before the NPCs
		_bubble(taxi_at - Vector2(0.0, maxf(_px(22.0), 0.7 * taxi_length) + _px(6.0)), shout[0], RS.SHOUT, RS.SHOUT_BORDER, shout[1])
	count += 1

	var later_npcs := _by_id(b.get("npcs", []))
	ploughing = str(a.get("weather", {}).get("weather_type", "")) == "snow" or float(a.get("weather", {}).get("road_snow", 0.0)) > 0.1
	for npc in a.get("npcs", []):
		if underground or not drawn_as_vehicle(npc):
			continue
		var p := StateBuffer.blend(npc, later_npcs.get(npc["id"], npc), t, origin)
		var c := Vector2(p.x, p.y)
		if not view_rect.has_point(c):
			continue
		body_style = absi(hash(npc["id"]))  # its own body, every frame the same
		taxi_sign_on = not npc.get("taxi_fare", false)  # a competitor taxi: lit when free, off with a passenger aboard
		_vehicle(c, p.z, npc["length_m"], npc["width_m"], _rgb(npc["color"]), npc.get("vehicle_type", "car"),
			npc.get("is_taxi", false), npc.get("state", "") != "PARKED", npc.get("braking", false), is_reversing(npc.get("speed", 0.0)),
			npc.get("turn_signal", ""), npc.get("turn_signal_elapsed", 0.0), npc.get("fallen", false),
			int(npc.get("layer", 0)) <= 0 and covered.call(c, int(npc.get("layer", 0))))
		if npc.has("trailer"):  # a towed trailer: its own body, swinging on the hitch (server trailers.py)
			_trailer(npc["trailer"], later_npcs.get(npc["id"], npc).get("trailer", npc["trailer"]), t)
		if npc.get("bus_line") != null:  # a line bus: its number, like the destination display
			_bus_number(c, p.z, str(npc["bus_line"]))
		var crashed: float = npc.get("crashed_timer", 0.0)
		if crashed > 0.0:
			_smoke(c, p.z, npc["length_m"], crashed if is_finite(crashed) else _clock)
		var cursing: float = npc.get("curse_timer", 0.0)
		if cursing > 0.0:  # bumped by the taxi: the driver's curse, like a pedestrian's
			_bubble(c - Vector2(0, float(npc["length_m"]) * 0.5 + _px(6.0)), str(npc.get("curse_text", "@#*!%")),
				RS.CURSE_TEXT, RS.CURSE_BORDER, 1.0 if cursing >= 0.5 else cursing / 0.5)
		count += 1

	if a.get("taxi", {}).get("current_passenger") is Dictionary:
		var passenger: Dictionary = a["taxi"]["current_passenger"]
		if a["taxi"].get("state") == "DROPOFF" and passenger.get("nausea_warning_timer", 0.0) > 0.0:
			_bubble(taxi_at - Vector2(0, maxf(_px(34.0), 2.5)), T.text("nausea", language), RS.NAUSEA_TEXT, RS.NAUSEA_TEXT, 1.0, 16, true)

	_booked_arrow(a, b, t, later_peds)

	drawn_entities = count + _trains_drawn
	_people.queue_redraw()
	_overlay.queue_redraw()
	_cars.queue_redraw()
	_cars_under.queue_redraw()
	_lamps.queue_redraw()  # this frame's lamps and halos, collected above
	_glow.queue_redraw()
	interp_usec = Time.get_ticks_usec() - started
	preload("res://perf.gd").add("entities_draw", interp_usec)


## Trains, last (after the bridge rails),
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
## tint).
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


## The booked passenger's arrow: a downward arrow over
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


## One train vehicle: body in its profile
## colour, a white cab front on a locomotive, a white stripe along a
## restaurant car, a dark roof line.
func _train_car(c: Vector2, heading: float, length: float, profile: String, node: CanvasItem = self) -> void:
	var style: Array = RS.TRAIN_PROFILES.get(profile, RS.TRAIN_PROFILES["standard"])
	var f := _forward(heading)
	var r := _right(heading)
	var hl := length / 2.0
	var hw := (RS.TRAM_WIDTH_M if profile.begins_with("tram") else RS.TRAIN_WIDTH_M) / 2.0
	var body := _rect(c, f, r, hl, -hl, hw)
	if not drawable(body):  # a car of no length or a bad heading
		return
	node.draw_colored_polygon(body, style[0])
	if style[1] != null and profile == "locomotive":
		node.draw_colored_polygon(_rect(c, f, r, hl, hl - 3.0, hw), style[1])
	elif style[1] != null:
		node.draw_colored_polygon(_rect(c, f, r, hl - 1.0, -hl + 1.0, 0.5), style[1])
	var closed := body.duplicate()
	closed.append(body[0])
	node.draw_polyline(closed, RS.TRAIN_ROOF_LINE, _px(1.0))
