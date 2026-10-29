## Presentation only: the server's holiday flags and static house-yard spots.
## Fixed caps, no particles/nodes per house, and no work on ordinary dates.
extends Node

const COLORS := [Color(1.0, 0.3, 0.2), Color(0.3, 0.8, 1.0), Color(1.0, 0.8, 0.2), Color(0.6, 1.0, 0.4)]
var map_layer: Node2D
var audio: Node  # AudioManager: the fireworks' whistles and bangs (main.gd sets it)
var yards := PackedVector2Array()
var sites := PackedVector2Array()  # firework launch points in the view
const SITE_CELL_M := 80.0
const RISE_S := 1.0
const BURST_S := 3.0
const CYCLE_S := 5.0  # rise, burst, then a short pause
const MAX_SITES := 12
const GHOST_CELL_M := 110.0
const MAX_GHOSTS := 24
var clock := 0.0
var _refresh := 0.0
var _halloween := false
var _fireworks := false
var _ghosts := false
var _christmas := false
var _window_decorations := false
const B3 := preload("res://buildings_3d.gd")
const WeatherLayer := preload("res://weather_layer.gd")
var _bonfires := false
var bonfire_layer: Node2D
var bonfires := PackedVector2Array()  # Midsummer bonfires in the view (chunk "bonfires")
const MAX_BONFIRES := 24
var decorations: Node2D
# Flagpoles in yards (chunk "flagpoles"), all year; the Finnish flag on them on
# flag days by the server's timetable (calendar "flags": "full" / "half" / "").
var flag_layer: Node2D
var poles := PackedVector2Array()
var _flags := ""
var _wind := Vector2.ZERO  # metres a second, layer coordinates (y down)
var _poles_refresh := 0.0
const MAX_POLES := 40
const POLE_M := 9.0
const FLAG_LENGTH_M := 2.0  # 18 : 11, the official proportions
const FLAG_HEIGHT_M := 2.0 * 11.0 / 18.0
const FLAG_BLUE := Color8(0, 47, 108)  # PMS 294 C
const FLAG_SEGMENTS := 9
var ghost_layer: Node2D
var elf_layer: Node2D
var bursts: Node2D
var ghosts := PackedVector2Array()
var elves := PackedVector2Array()


func setup(world: Node2D) -> void:
	map_layer = world
	decorations = Node2D.new()
	decorations.z_index = 6  # yard level, below roofs
	decorations.material = preload("res://emissive.tres")
	decorations.draw.connect(_draw_decorations)
	world.add_child(decorations)
	ghost_layer = Node2D.new()
	ghost_layer.z_index = 11  # supernatural scenery stays visible above roofs
	ghost_layer.material = preload("res://emissive.tres")
	ghost_layer.draw.connect(_draw_ghosts)
	world.add_child(ghost_layer)
	elf_layer = Node2D.new()
	elf_layer.z_index = 12  # brief peeks over the trees and roofs hiding them
	elf_layer.material = preload("res://emissive.tres")
	elf_layer.draw.connect(_draw_elves)
	world.add_child(elf_layer)
	flag_layer = Node2D.new()
	flag_layer.z_index = 6  # under the buildings' composite (7): their walls lean away from the view's centre, so a
	# building covers what stands behind it (seen from the camera) and leaves what stands in front of it
	flag_layer.draw.connect(_draw_flags)
	world.add_child(flag_layer)
	bonfire_layer = Node2D.new()
	bonfire_layer.z_index = 7  # ground level, above yard decorations, below roofs
	bonfire_layer.material = preload("res://emissive.tres")
	bonfire_layer.draw.connect(_draw_bonfires)
	world.add_child(bonfire_layer)
	bonfire_layer.hide()
	bursts = Node2D.new()
	bursts.z_index = 30  # sky above buildings, without illuminating roofs
	bursts.material = preload("res://emissive.tres")
	bursts.draw.connect(_draw_fireworks)
	world.add_child(bursts)
	decorations.hide()
	ghost_layer.hide()
	elf_layer.hide()
	bursts.hide()


func update(delta: float, state: Dictionary, view: Rect2, underground: bool, walkers: Array[Vector2] = []) -> void:
	var calendar: Dictionary = state.get("calendar", {}) if state.get("calendar") is Dictionary else {}
	var events: Dictionary = calendar.get("holidays", {})
	var halloween: bool = not underground and events.get("halloween", false)
	var ghost_season: bool = not underground and events.get("halloween_ghosts", false)
	var christmas: bool = not underground and events.get("christmas", false)
	_update_flags(delta, calendar, state, view, underground)
	var decorated: bool = events.get("window_decorations", false)
	if decorated != _window_decorations:  # candle bridges and stars in the windows (building_snow.gdshader)
		_window_decorations = decorated
		B3._shared["material"].set_shader_parameter("decorations", 1.0 if decorated else 0.0)
	var fireworks: bool = not underground and events.get("fireworks", false)
	var midsummer: bool = not underground and events.get("midsummer_bonfires", false)
	var changed := halloween != _halloween or fireworks != _fireworks or ghost_season != _ghosts or christmas != _christmas or midsummer != _bonfires
	_bonfires = midsummer
	bonfire_layer.visible = midsummer
	_halloween = halloween
	_fireworks = fireworks
	_ghosts = ghost_season
	_christmas = christmas
	decorations.visible = halloween
	ghost_layer.visible = ghost_season
	elf_layer.visible = christmas
	bursts.visible = fireworks
	if not halloween and not fireworks and not ghost_season and not christmas and not midsummer:
		yards.clear()
		bonfires.clear()
		sites.clear()
		ghosts.clear()
		elves.clear()
		return
	clock += delta
	_refresh -= delta
	if changed or _refresh <= 0.0:
		_refresh = 0.5
		yards = map_layer.holiday_yards(view.grow(50.0)) if halloween else PackedVector2Array()
		sites = firework_sites(view.grow(40.0)) if fireworks else PackedVector2Array()
		if ghost_season and (ghosts.is_empty() or not view.has_point(ghosts[0])):
			ghosts = ghost_sites(view.grow(20.0))
		elves = map_layer.holiday_hiding_spots(view.grow(50.0)) if christmas else PackedVector2Array()
		bonfires = map_layer.holiday_yards(view.grow(20.0), MAX_BONFIRES, "bonfires") if midsummer else PackedVector2Array()
		decorations.queue_redraw()
		ghost_layer.queue_redraw()
		elf_layer.queue_redraw()
	if ghost_season:
		_update_ghosts(delta, walkers)
		ghost_layer.queue_redraw()
	if christmas:
		elf_layer.queue_redraw()
	if midsummer:
		bonfire_layer.queue_redraw()
	if fireworks:
		bursts.queue_redraw()
		if audio != null:
			for sound in firework_sounds(sites, clock - delta, clock):
				var at: Vector2 = sound[1]
				audio.handle_event({"type": "sound", "group": sound[0], "volume": 0.6,
					"at": [at.x + map_layer.origin.x, map_layer.origin.y - at.y]})


func _draw_decorations() -> void:
	for at in yards:
		# Jack-o'-lantern, stem and glowing eyes/mouth; a candle lantern beside it.
		decorations.draw_circle(at, 0.42, Color8(220, 98, 15))
		decorations.draw_line(at + Vector2(0, -0.3), at + Vector2(0.04, -0.55), Color8(80, 100, 35), 0.12)
		for side: float in [-1, 1]:
			decorations.draw_circle(at + Vector2(side * 0.15, -0.06), 0.07, Color(1, 0.9, 0.3))
		decorations.draw_arc(at, 0.23, 0.2, PI - 0.2, 8, Color(1, 0.9, 0.3), 0.08)
		var lantern := at + Vector2(0.9, 0.0)
		decorations.draw_circle(lantern, 0.6, Color(1, 0.6, 0.15, 0.12))
		decorations.draw_rect(Rect2(lantern - Vector2(0.19, 0.26), Vector2(0.38, 0.52)), Color8(35, 32, 28))
		decorations.draw_rect(Rect2(lantern - Vector2(0.12, 0.18), Vector2(0.24, 0.36)), Color(1, 0.8, 0.3))
		decorations.draw_arc(lantern + Vector2(0, -0.26), 0.13, PI, TAU, 8, Color8(45, 40, 30), 0.05)


func _update_flags(delta: float, calendar: Dictionary, state: Dictionary, view: Rect2, underground: bool) -> void:
	flag_layer.visible = not underground
	if underground:
		return
	_flags = str(calendar.get("flags", ""))
	var wind := WeatherLayer.wind_vector(state)
	_wind = Vector2(wind.x, -wind.y)
	_poles_refresh -= delta
	if _poles_refresh <= 0.0:
		_poles_refresh = 0.5
		poles = map_layer.holiday_yards(view.grow(20.0), MAX_POLES, "flagpoles")
	flag_layer.queue_redraw()


## Where a point `h` metres up the pole shows: leaning out from the view's
## centre as the buildings' walls do (B3.lift_point), but at least as far as
## seen from about 60 degrees - straight from above a pole was a dot and its
## flag a line.
const MIN_LEAN := 0.35


static func _lean(at: Vector2) -> Vector2:
	var out := at - B3.view_centre
	return out.normalized() if out.length() > 1.0 else Vector2.DOWN


static func _up(at: Vector2, h: float) -> Vector2:
	var lifted := B3.lift_point(at, h)
	return lifted if lifted.distance_to(at) >= h * MIN_LEAN else at + _lean(at) * h * MIN_LEAN


func _draw_flags() -> void:
	for at in poles:
		var top := _up(at, POLE_M)
		flag_layer.draw_line(at, top, Color8(225, 228, 230), 0.22)
		flag_layer.draw_circle(top, 0.16, Color8(200, 170, 60))  # the gilded knob
		if _flags != "":
			_draw_flag(at, POLE_M - 0.25 if _flags == "full" else POLE_M * 0.5 + FLAG_HEIGHT_M * 0.5)


## The flag from the hoist at `top` metres: streaming downwind as far as the
## wind holds it out (hanging down in a calm), waving in travelling waves.
func _draw_flag(at: Vector2, top: float) -> void:
	var speed := _wind.length()
	var downwind := _wind / speed if speed > 0.05 else Vector2.RIGHT
	var across := Vector2(-downwind.y, downwind.x)
	var face := across if across.y >= 0.0 else -across
	var held := clampf(speed / 6.0, 0.12, 1.0)  # 6 m/s and more: straight out
	var seed := absf(at.x * 0.37 + at.y * 0.11)
	var frequency := 1.2 + speed * 0.35
	var corners: Array = []  # per segment edge: [upper, lower] on screen
	for i in FLAG_SEGMENTS + 1:
		var u := float(i) / FLAG_SEGMENTS
		var wave := sin(u * 5.0 - clock * frequency * TAU * 0.5 + seed) * 0.18 * u * (0.4 + held)
		var sag := u * FLAG_LENGTH_M * sqrt(1.0 - held * held)  # what the wind does not hold out hangs down
		var hoist := _up(at, top - sag)
		var fly := downwind * (u * FLAG_LENGTH_M * held) + across * wave
		# Its face, not its edge: the height shown across the wind (on the screen's lower
		# side), whichever way the camera looks - edge-on it was a line of a few pixels.
		corners.append([hoist + fly, hoist + fly + face * FLAG_HEIGHT_M * 0.8])
	for i in FLAG_SEGMENTS:
		var u0 := float(i) / FLAG_SEGMENTS
		var u1 := float(i + 1) / FLAG_SEGMENTS
		var shade := 0.9 + 0.1 * sin(u0 * 5.0 - clock * frequency * TAU * 0.5 + seed + 0.8)  # the folds catch the light
		_flag_quad(corners[i], corners[i + 1], 0.0, 1.0, Color(shade, shade, shade))
		if u1 > 5.0 / 18.0 and u0 < 8.0 / 18.0:  # the cross's upright: 5/18 to 8/18 of the length
			var a := clampf((5.0 / 18.0 - u0) / (u1 - u0), 0.0, 1.0)
			var b := clampf((8.0 / 18.0 - u0) / (u1 - u0), 0.0, 1.0)
			_flag_quad(_lerp_edge(corners[i], corners[i + 1], a), _lerp_edge(corners[i], corners[i + 1], b), 0.0, 1.0, FLAG_BLUE * shade)
		_flag_quad(corners[i], corners[i + 1], 4.0 / 11.0, 7.0 / 11.0, FLAG_BLUE * shade)  # its arm: 4/11 to 7/11 down


static func _lerp_edge(e0: Array, e1: Array, t: float) -> Array:
	return [e0[0].lerp(e1[0], t), e0[1].lerp(e1[1], t)]


## The band from `v0` to `v1` (0 the top edge, 1 the bottom) between two edges.
func _flag_quad(e0: Array, e1: Array, v0: float, v1: float, color: Color) -> void:
	var points := PackedVector2Array([e0[0].lerp(e0[1], v0), e1[0].lerp(e1[1], v0), e1[0].lerp(e1[1], v1), e0[0].lerp(e0[1], v1)])
	flag_layer.draw_colored_polygon(points, color)


func _draw_bonfires() -> void:
	# Juhannuskokko: a log stack about 5 m across under 4-6 m flames, lighting the shore around it.
	for at in bonfires:
		var seed := absf(at.x * 0.37 + at.y * 0.11)
		var flicker := 0.85 + 0.15 * sin(clock * 9.0 + seed) * sin(clock * 5.3 + seed * 2.0)
		for ring in 8:  # the glow fades outwards in steps too fine to show
			bonfire_layer.draw_circle(at, (22.0 - ring * 2.4) * flicker, Color(1.0, 0.55 + ring * 0.015, 0.18, 0.045))
		for stick in 7:
			var direction := Vector2.from_angle(TAU * stick / 7.0 + seed)
			bonfire_layer.draw_line(at + direction * 0.4, at + direction * 2.6, Color8(70, 45, 28), 0.6)
		for tongue in 5:
			var sway := sin(clock * 6.0 + tongue * 1.7 + seed) * 0.35
			var base := at + Vector2((tongue - 2) * 0.7, 0.5)
			var height := (4.0 + 1.2 * sin(clock * 7.0 + tongue + seed)) * flicker * (1.0 - absf(tongue - 2) * 0.18)
			var tip := base + Vector2(sway, -height)
			bonfire_layer.draw_colored_polygon(PackedVector2Array([base + Vector2(-0.8, 0), tip, base + Vector2(0.8, 0)]), Color(1.0, 0.45, 0.1, 0.9))
			bonfire_layer.draw_colored_polygon(PackedVector2Array([base + Vector2(-0.35, 0), base.lerp(tip, 0.65), base + Vector2(0.35, 0)]), Color(1.0, 0.85, 0.35, 0.95))
		for spark in 4:
			var rise := fposmod(clock * 0.8 + spark * 0.25 + seed, 1.0)
			bonfire_layer.draw_circle(at + Vector2(sin(seed + spark * 2.0 + clock) * 1.8, -5.0 - rise * 7.0), 0.18, Color(1.0, 0.7, 0.3, 1.0 - rise))


func _draw_ghosts() -> void:
	for i in ghosts.size():
		var at := ghosts[i] + Vector2(sin(clock * 1.3 + i) * 1.2, sin(clock * 2.0 + i * 0.7) * 0.8)
		# Overhead shroud at pedestrian scale, with its crown above trailing cloth.
		ghost_layer.draw_set_transform(at, clock * 0.35 + i * 2.4)
		ghost_layer.draw_circle(Vector2(-0.1, 0), 0.85, Color(0.65, 0.85, 1.0, 0.07))
		ghost_layer.draw_colored_polygon(ghost_outline(clock * 2.0 + i), Color(0.8, 0.9, 1.0, 0.5))
		ghost_layer.draw_circle(Vector2(0.22, 0), 0.28, Color(0.9, 0.96, 1.0, 0.65))
	ghost_layer.draw_set_transform(Vector2.ZERO)


static func ghost_outline(phase: float) -> PackedVector2Array:
	var flutter := sin(phase) * 0.12
	return PackedVector2Array([
		Vector2(0.7, 0), Vector2(0.64, -0.28), Vector2(0.43, -0.46),
		Vector2(0.05, -0.55), Vector2(-0.35, -0.5), Vector2(-0.72, -0.42),
		Vector2(-1.05, -0.6 + flutter), Vector2(-0.89, -0.22),
		Vector2(-1.35, -0.12 + flutter), Vector2(-1.05, 0.08),
		Vector2(-1.24, 0.35 + flutter), Vector2(-0.75, 0.25),
		Vector2(-0.92, 0.6 + flutter), Vector2(-0.38, 0.47),
		Vector2(0.07, 0.55), Vector2(0.43, 0.46), Vector2(0.64, 0.28),
	])


func _draw_elves() -> void:
	for at in elves:
		var seed := hash(Vector2i(roundi(at.x), roundi(at.y)))
		var period := 3.0 + posmod(seed, 7000) / 1000.0
		var phase := fposmod(clock + posmod(seed / 7, 10000) / 1000.0, period)
		if phase > 0.16:
			continue
		var peek := at + Vector2(0, -1.0)
		elf_layer.draw_circle(peek, 1.0, Color8(241, 190, 123))
		elf_layer.draw_rect(Rect2(peek + Vector2(-0.85, 0.8), Vector2(1.7, 2.0)), Color8(35, 132, 68))
		elf_layer.draw_colored_polygon(PackedVector2Array([peek + Vector2(-1.1, -0.45), peek + Vector2(0.7, -2.1), peek + Vector2(1.2, -0.4)]), Color8(190, 40, 39))
		elf_layer.draw_circle(peek + Vector2(0.3, 0), 0.12, Color8(35, 30, 28))


func _update_ghosts(delta: float, walkers: Array[Vector2]) -> void:
	for i in ghosts.size():
		if walkers.is_empty():
			continue
		var target := walkers[0]
		for walker in walkers:
			if ghosts[i].distance_squared_to(walker) < ghosts[i].distance_squared_to(target):
				target = walker
		var angle := clock * 0.7 + i * TAU / maxi(1, ghosts.size())
		var haunt_spot := target + Vector2.from_angle(angle) * 5.0
		ghosts[i] = ghosts[i].move_toward(haunt_spot, delta * 3.0)


static func ghost_sites(view: Rect2) -> PackedVector2Array:
	var result := PackedVector2Array()
	for cx in range(floori(view.position.x / GHOST_CELL_M), floori(view.end.x / GHOST_CELL_M) + 1):
		for cy in range(floori(view.position.y / GHOST_CELL_M), floori(view.end.y / GHOST_CELL_M) + 1):
			var h := hash(Vector2i(cx, cy))
			if posmod(h, 4) != 0:
				continue
			var at := Vector2(cx + (posmod(h / 1000, 1000)) / 1000.0, cy + posmod(h, 1000) / 1000.0) * GHOST_CELL_M
			if view.has_point(at):
				result.append(at)
				if result.size() >= MAX_GHOSTS:
					return result
	return result


## Launch points over the whole town, not only house yards (the centre has
## none): about one SITE_CELL_M cell in three, at a fixed spot in its cell,
## so they stay put as the view moves. At most MAX_SITES.
static func firework_sites(view: Rect2) -> PackedVector2Array:
	var result := PackedVector2Array()
	for cx in range(floori(view.position.x / SITE_CELL_M), floori(view.end.x / SITE_CELL_M) + 1):
		for cy in range(floori(view.position.y / SITE_CELL_M), floori(view.end.y / SITE_CELL_M) + 1):
			var h := hash(Vector2i(cx, cy))
			if h % 3 != 0:
				continue
			var at := Vector2(cx + (h % 1000) / 1000.0, cy + (h / 1000 % 1000) / 1000.0) * SITE_CELL_M
			if view.has_point(at):
				result.append(at)
				if result.size() >= MAX_SITES:
					return result
	return result


## The sounds due between `before` and `now` (clock seconds): a rocket's
## whistle at launch, its bang at the burst, high where it bursts. [[group, at]]
static func firework_sounds(points: PackedVector2Array, before: float, now: float) -> Array:
	var due: Array = []
	for at in points:
		var offset := absf(at.x * 0.17 + at.y * 0.31)
		for event: Array in [[0.0, "holiday.firework_launch", at], [RISE_S, "holiday.firework_burst", at - Vector2(0, 30)]]:
			var mark: float = event[0]
			if floorf((now + offset - mark) / CYCLE_S) > floorf((before + offset - mark) / CYCLE_S):
				due.append([event[1], event[2]])
	return due


func _draw_fireworks() -> void:
	# Widths at least 2 screen pixels: in metres they vanished when zoomed out.
	var px := 1.0 / maxf(0.01, bursts.get_viewport().get_canvas_transform().get_scale().x)
	for i in sites.size():
		var at := sites[i]
		var phase := fposmod(clock + absf(at.x * 0.17 + at.y * 0.31), CYCLE_S)
		var color: Color = COLORS[i % COLORS.size()]
		var top := at - Vector2(0, 30)
		if phase < RISE_S:
			var rocket := at.lerp(top, phase / RISE_S)
			bursts.draw_line(rocket, rocket + Vector2(0, 2.0), Color(1, 0.8, 0.4), maxf(0.3, 2.0 * px))
		elif phase < RISE_S + BURST_S:
			var age := phase - RISE_S
			color.a = 1.0 - age / BURST_S
			bursts.draw_circle(top, maxf(1.5, 4.0 * px) * (1.0 - age / BURST_S), Color(1, 1, 0.9, color.a))  # the flash
			for ray in 24:
				var direction := Vector2.from_angle(TAU * ray / 24.0 + i)
				var gravity := Vector2(0, age * age * 1.4)
				var end := top + direction * age * 7.0 + gravity
				bursts.draw_line(end - direction * 1.5, end, color, maxf(0.35, 2.0 * px))
