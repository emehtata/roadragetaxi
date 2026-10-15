## Presentation only: the server's holiday flags and static house-yard spots.
## Fixed caps, no particles/nodes per house, and no work on ordinary dates.
extends Node

const COLORS := [Color(1.0, 0.3, 0.2), Color(0.3, 0.8, 1.0), Color(1.0, 0.8, 0.2), Color(0.6, 1.0, 0.4)]
var map_layer: Node2D
var yards := PackedVector2Array()
var sites := PackedVector2Array()  # firework launch points in the view
const SITE_CELL_M := 80.0
const RISE_S := 1.0
const BURST_S := 3.0
const CYCLE_S := 5.0  # rise, burst, then a short pause
const MAX_SITES := 12
var clock := 0.0
var _refresh := 0.0
var _halloween := false
var _fireworks := false
var decorations: Node2D
var bursts: Node2D


func setup(world: Node2D) -> void:
	map_layer = world
	decorations = Node2D.new()
	decorations.z_index = 6  # yard level, below roofs
	decorations.material = preload("res://emissive.tres")
	decorations.draw.connect(_draw_decorations)
	world.add_child(decorations)
	bursts = Node2D.new()
	bursts.z_index = 30  # sky above buildings, without illuminating roofs
	bursts.material = preload("res://emissive.tres")
	bursts.draw.connect(_draw_fireworks)
	world.add_child(bursts)
	decorations.hide()
	bursts.hide()


func update(delta: float, state: Dictionary, view: Rect2, underground: bool) -> void:
	var calendar: Dictionary = state.get("calendar", {}) if state.get("calendar") is Dictionary else {}
	var events: Dictionary = calendar.get("holidays", {})
	var halloween: bool = not underground and events.get("halloween", false)
	var fireworks: bool = not underground and events.get("fireworks", false)
	var changed := halloween != _halloween or fireworks != _fireworks
	_halloween = halloween
	_fireworks = fireworks
	decorations.visible = halloween
	bursts.visible = fireworks
	if not halloween and not fireworks:
		yards.clear()
		sites.clear()
		return
	clock += delta
	_refresh -= delta
	if changed or _refresh <= 0.0:
		_refresh = 0.5
		yards = map_layer.holiday_yards(view.grow(50.0)) if halloween else PackedVector2Array()
		sites = firework_sites(view.grow(40.0)) if fireworks else PackedVector2Array()
		decorations.queue_redraw()
	if fireworks:
		bursts.queue_redraw()


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
