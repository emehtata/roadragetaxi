## godot-final-06: the falling weather, puddle ripples and taxi splashes -
## render/weather.py's draw_rain, draw_puddles (ripples) and draw_splashes,
## and weather.py's particle pool and splash rule.
##
## Presentation only. The weather type, wetness, wind and the taxi come from
## the server's state; this owns:
## - the fixed pool of 220 screen-space particles (real-time motion)
## - the splash rings, at most 40
## - whether the taxi was in a puddle last frame
##
## It draws into three canvas items, one batched submission per primitive:
## - precipitation: screen space, in the Sky layer above the lightning flash
## - ripples: world space, with the puddles (z 5)
## - splashes: world space, above the vehicles (z 11)
extends Node

const PARTICLE_COUNT := 220
const FALL_FRACTION_PER_S := 0.9  # weather.py RAIN_FALL_FRACTION_PER_S
const DRIFT_FRACTION_PER_S := 0.05
const SPEED_VARIATION := Vector2(0.75, 1.3)
const MOTION := {"rain": Vector2(1.0, 1.0), "slush": Vector2(0.55, 1.35), "snow": Vector2(0.22, 1.8)}  # [fall, drift] factors
const STREAK_MIN_PX := 9.0
const STREAK_MAX_PX := 20.0
const RAIN_COLOR := Color8(196, 206, 222)
const SNOW_COLOR := Color8(242, 246, 250)
const SLUSH_COLOR := Color8(218, 226, 232)
const RIPPLE_CYCLE_S := 2.4
const RIPPLE_DURATION_S := 1.0
const RIPPLE_COLOR := Color8(190, 202, 218)
const RIPPLE_MAX_ALPHA := 70.0 / 255.0
const SPLASH_LIFETIME_S := 0.5
const SPLASH_MIN_SPEED_MPS := 1.0
const SPLASH_POOL_MAX := 40
const SPLASH_COLOR := Color8(215, 225, 238)
const SPLASH_MAX_RADIUS_M := 1.4
const SPLASH_MAX_ALPHA := 200.0 / 255.0
const RING_SEGMENTS := 16
const RS := preload("res://render_style.gd")

var particles := PackedFloat32Array()  # x, y (screen fractions), speed factor - per particle
var kind := ""  # "rain", "slush", "snow", or "" (nothing falling here)
var clock := 0.0  # real seconds, for the ripples
var splashes: Array = []  # [layer position, age s, strength]
var was_in_puddle := false
var draw_calls := 0  # submissions in the last drawn frame (precipitation + ripples + splashes)
var map_layer: Node2D
var precipitation: Control
var ripples: Node2D
var splash_node: Node2D
var _rng := RandomNumberGenerator.new()
var _ripple_points := PackedVector2Array()
var _ripple_colors := PackedColorArray()


func _init() -> void:
	_rng.seed = 22
	particles.resize(PARTICLE_COUNT * 3)
	for i in PARTICLE_COUNT:
		particles[i * 3] = _rng.randf()
		particles[i * 3 + 1] = _rng.randf()
		particles[i * 3 + 2] = _rng.randf_range(SPEED_VARIATION.x, SPEED_VARIATION.y)


## main.gd, once: where the three canvas items go.
func setup(sky: CanvasLayer, world: Node2D) -> void:
	map_layer = world
	precipitation = Control.new()
	precipitation.mouse_filter = Control.MOUSE_FILTER_IGNORE
	precipitation.set_anchors_preset(Control.PRESET_FULL_RECT)
	precipitation.visible = false
	precipitation.draw.connect(_draw_precipitation)
	sky.add_child(precipitation)  # after the lightning flash: rain is drawn over it, as Pygame
	ripples = Node2D.new()
	ripples.z_index = 5
	ripples.visible = false
	ripples.draw.connect(_draw_ripples)
	world.add_child(ripples)
	splash_node = Node2D.new()
	splash_node.z_index = 11
	splash_node.visible = false
	splash_node.draw.connect(_draw_splashes)
	world.add_child(splash_node)


static func falling(state: Dictionary) -> String:
	var weather = state.get("weather")
	var type = weather.get("weather_type") if weather is Dictionary else null
	return type if type in ["rain", "slush", "snow"] else ""


## Each frame, after the camera is placed: `taxi` is the drawn (interpolated)
## taxi in layer coordinates.
func update(delta: float, state: Dictionary, taxi: Vector2, underground: bool) -> void:
	var started := Time.get_ticks_usec()
	kind = "" if underground else falling(state)  # render: no rain or sky underground
	clock += delta
	advance_particles(delta)
	if precipitation != null:
		precipitation.visible = kind != ""
		if kind != "":
			precipitation.queue_redraw()
	var wetness := float(state.get("weather", {}).get("wetness", 0.0)) if state.get("weather") is Dictionary else 0.0
	if ripples != null:
		ripples.visible = kind != "" and wetness > 0.0  # ambient ripples only while it falls
		if ripples.visible:
			ripples.queue_redraw()
	var player: Dictionary = state.get("player", {}) if state.get("player") is Dictionary else {}
	var speed := absf(float(player.get("speed", 0.0)))
	var probe := maxf(float(player.get("length_m", 4.4)), float(player.get("width_m", 1.8))) * 0.5
	var in_puddle: bool = not underground and not state.get("on_foot", true) and speed >= SPLASH_MIN_SPEED_MPS \
		and puddle_at(taxi, probe, wetness) != null
	if in_puddle and not was_in_puddle:
		spawn_splash(taxi, minf(1.0, speed * 3.6 / 60.0))
	was_in_puddle = in_puddle
	age_splashes(delta)
	if splash_node != null:
		splash_node.visible = not splashes.is_empty()
		if splash_node.visible:
			splash_node.queue_redraw()
	Perf.add("weather", Time.get_ticks_usec() - started)


const Perf := preload("res://perf.gd")


## weather.py update: fall and drift in real time, by the type's factors;
## off the bottom -> back at the top at a new x; off the right -> wrap.
func advance_particles(delta: float) -> void:
	if kind == "" or delta <= 0.0:
		return
	var motion: Vector2 = MOTION[kind]
	for i in PARTICLE_COUNT:
		var factor := particles[i * 3 + 2]
		var x := particles[i * 3] + DRIFT_FRACTION_PER_S * motion.y * factor * delta
		var y := particles[i * 3 + 1] + FALL_FRACTION_PER_S * motion.x * factor * delta
		if y > 1.0:
			y -= 1.0
			x = _rng.randf()
		elif x > 1.0:
			x -= 1.0
		particles[i * 3] = x
		particles[i * 3 + 1] = y


func _draw_precipitation() -> void:
	var started := Time.get_ticks_usec()
	draw_calls = 0
	var size := precipitation.size
	var streaks := PackedVector2Array()
	var small := PackedVector2Array()
	var large := PackedVector2Array()
	var direction := Vector2(DRIFT_FRACTION_PER_S * size.x, FALL_FRACTION_PER_S * size.y).normalized()
	for i in PARTICLE_COUNT:
		var at := Vector2(particles[i * 3] * size.x, particles[i * 3 + 1] * size.y)
		var factor := particles[i * 3 + 2]
		if kind == "rain":
			var length := STREAK_MIN_PX + (STREAK_MAX_PX - STREAK_MIN_PX) * (factor - SPEED_VARIATION.x) / (SPEED_VARIATION.y - SPEED_VARIATION.x)
			streaks.append_array([at - direction * length, at])
			continue
		var radius := 1.0 if factor < (1.0 if kind == "snow" else 1.1) else 2.0
		(small if radius == 1.0 else large).append_array([at - Vector2(radius, 0), at + Vector2(radius, 0)])  # a 2r square: a flake at this size
		if kind == "slush":
			streaks.append_array([at - Vector2(0, radius + 2.0), at + Vector2(0, radius + 1.0)])
	var flake: Color = SNOW_COLOR if kind == "snow" else SLUSH_COLOR
	for batch in [[small, flake, 2.0], [large, flake, 4.0], [streaks, RAIN_COLOR, 1.0]]:
		if not batch[0].is_empty():
			precipitation.draw_multiline(batch[0], batch[1], batch[2])
			draw_calls += 1
	Perf.add("weather_draw_precipitation", Time.get_ticks_usec() - started)


## render/weather.py draw_puddles' ripple: each visible puddle, every 2.4 s,
## a ring growing from 0.25 to 1.1 of its radius over 1 s, fading.
static func ripple(spot: Dictionary, wetness: float, now: float) -> Array:
	var strength := RS.puddle_strength(wetness, spot["reveal"])
	if strength <= 0.0:
		return []
	var cycle := fmod(now + float(spot.get("phase", 0.0)) * RIPPLE_CYCLE_S, RIPPLE_CYCLE_S)
	if cycle >= RIPPLE_DURATION_S:
		return []
	var progress := cycle / RIPPLE_DURATION_S
	var radius: float = spot["radius"] * (0.4 + 0.6 * strength) * (0.25 + 0.85 * progress)
	return [radius, RIPPLE_MAX_ALPHA * (1.0 - progress) * strength]


func _draw_ripples() -> void:
	var started := Time.get_ticks_usec()
	_ripple_points.clear()
	_ripple_colors.clear()
	var view := _view()
	for chunk in map_layer._chunks.values():
		if not chunk._bounds_rect.intersects(view):
			continue
		for spot in chunk._puddle_spots:
			if not view.has_point(spot["at"]):
				continue
			var ring := ripple(spot, chunk._wetness, clock)
			if not ring.is_empty():
				_ring(spot["at"], ring[0], Color(RIPPLE_COLOR, ring[1]))
	if not _ripple_points.is_empty():
		ripples.draw_multiline_colors(_ripple_points, _ripple_colors)
		draw_calls += 1
	Perf.add("weather_draw_ripples", Time.get_ticks_usec() - started)


## The puddle the taxi is in (weather.py find_puddle_overlap on Godot's own
## spots): only the loaded chunks around it, only puddles showing at this
## wetness. Null if none.
func puddle_at(at: Vector2, probe: float, wetness: float):
	if map_layer == null or wetness <= 0.0:
		return null
	for chunk in map_layer._chunks.values():
		if chunk._bounds_rect.size != Vector2.ZERO and not chunk._bounds_rect.grow(probe + RS.PUDDLE_MAX_RADIUS_M).has_point(at):
			continue
		for spot in chunk._puddle_spots:
			if wetness > spot["reveal"] and at.distance_to(spot["at"]) <= spot["radius"] + probe:
				return spot
	return null


func spawn_splash(at: Vector2, strength: float) -> void:
	splashes.append([at, 0.0, clampf(strength, 0.0, 1.0)])
	if splashes.size() > SPLASH_POOL_MAX:
		splashes = splashes.slice(splashes.size() - SPLASH_POOL_MAX)


func age_splashes(delta: float) -> void:
	for splash in splashes:
		splash[1] += delta
	splashes = splashes.filter(func(s): return s[1] < SPLASH_LIFETIME_S)


## render/weather.py draw_splashes: [radius m, alpha] of a splash ring.
static func splash_ring(splash: Array) -> Array:
	var progress := minf(1.0, splash[1] / SPLASH_LIFETIME_S)
	return [0.25 + progress * SPLASH_MAX_RADIUS_M * splash[2], SPLASH_MAX_ALPHA * (1.0 - progress) * (0.5 + 0.5 * splash[2])]


func _draw_splashes() -> void:
	_ripple_points.clear()
	_ripple_colors.clear()
	for splash in splashes:
		var ring := splash_ring(splash)
		if ring[1] > 0.0:
			_ring(splash[0], ring[0], Color(SPLASH_COLOR, ring[1]))
	if not _ripple_points.is_empty():
		splash_node.draw_multiline_colors(_ripple_points, _ripple_colors)
		draw_calls += 1


func _ring(at: Vector2, radius: float, color: Color) -> void:
	for i in RING_SEGMENTS:
		_ripple_points.append(at + Vector2.from_angle(TAU * i / RING_SEGMENTS) * radius)
		_ripple_points.append(at + Vector2.from_angle(TAU * (i + 1) / RING_SEGMENTS) * radius)
		_ripple_colors.append(color)


## The camera's view in layer coordinates (+ 30 m), for the ripple culling.
func _view() -> Rect2:
	var viewport := ripples.get_viewport()
	var canvas := viewport.get_canvas_transform()
	return (canvas.affine_inverse() * Rect2(Vector2.ZERO, viewport.get_visible_rect().size)).grow(30.0)
