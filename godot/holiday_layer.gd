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
var decorations: Node2D
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
	var fireworks: bool = not underground and events.get("fireworks", false)
	var changed := halloween != _halloween or fireworks != _fireworks or ghost_season != _ghosts or christmas != _christmas
	_halloween = halloween
	_fireworks = fireworks
	_ghosts = ghost_season
	_christmas = christmas
	decorations.visible = halloween
	ghost_layer.visible = ghost_season
	elf_layer.visible = christmas
	bursts.visible = fireworks
	if not halloween and not fireworks and not ghost_season and not christmas:
		yards.clear()
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
		decorations.queue_redraw()
		ghost_layer.queue_redraw()
		elf_layer.queue_redraw()
	if ghost_season:
		_update_ghosts(delta, walkers)
		ghost_layer.queue_redraw()
	if christmas:
		elf_layer.queue_redraw()
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


func _draw_ghosts() -> void:
	for i in ghosts.size():
		var at := ghosts[i] + Vector2(sin(clock * 1.3 + i) * 1.2, sin(clock * 2.0 + i * 0.7) * 0.8)
		# Translucent ghosts drift toward nearby walkers; visual only, with no collision.
		ghost_layer.draw_circle(at + Vector2(0, -3.5), 2.5, Color(0.8, 0.9, 1.0, 0.58))
		ghost_layer.draw_rect(Rect2(at + Vector2(-2.5, -3.5), Vector2(5.0, 3.5)), Color(0.8, 0.9, 1.0, 0.58))
		for side: float in [-0.35, 0.35]:
			ghost_layer.draw_circle(at + Vector2(side * 2.0, -3.8), 0.3, Color(0.15, 0.2, 0.35, 0.9))


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
