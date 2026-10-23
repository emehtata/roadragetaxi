## Client-side wildlife ambience. Animals are chunk-owned drawing records and
## never enter server state, physics, routing, collision, or the entity protocol.
class_name Wildlife
extends Node2D

const SPECIES := [&"squirrel", &"small_bird", &"pigeon", &"hare", &"fox", &"moose", &"roe_deer", &"crow"]
const VALID_STATES := [&"IDLE", &"WANDER", &"FEED", &"FLEE", &"FLY", &"CROSSING"]
const STEP_S := 0.1
const REACTION_M := 18.0

# Public layer properties follow the existing client-side configuration style.
var density := 48.0
var max_active := 128
var activity_distance_m := 900.0
var vehicle_reactions := true
var species_weights := {"squirrel": 1.0, "small_bird": 1.0, "pigeon": 1.0, "hare": 1.0,
	"fox": 1.0, "moose": 1.0, "roe_deer": 1.0, "crow": 1.0}

var animals: Array = []
var winter := 0.0  # the season's winter weight (main.gd, from the calendar): hares turn white, squirrels grey
var drawn_members := 0  # rendering regression check and F3/debug inspection
var _chunks: Dictionary = {}
var _next_id := 1
var _accumulator := 0.0


func _ready() -> void:
	z_index = 11


static func habitat(building_count: int, tree_count: int, forested: bool = false) -> String:
	# Canopy forests no longer need individual server trees to be rural habitat.
	if forested and building_count < 5:
		return "rural"
	if building_count >= 18 and tree_count < 24:
		return "urban"
	if building_count >= 5 or tree_count < 18:
		return "suburban"
	return "rural"


static func habitat_weights(kind: String) -> Dictionary:
	match kind:
		"urban": return {"squirrel": 3.0, "small_bird": 4.0, "pigeon": 4.0, "crow": 1.5}
		"suburban": return {"squirrel": 3.0, "small_bird": 4.0, "pigeon": 1.0, "crow": 1.5, "hare": 1.5, "fox": 0.35}
		_: return {"squirrel": 0.7, "small_bird": 3.0, "crow": 1.0, "hare": 2.0, "fox": 0.8, "moose": 0.6, "roe_deer": 1.0}


static func activity(species: String, game_time_seconds: float) -> float:
	var hour := fmod(game_time_seconds / 3600.0, 24.0)
	var dawn_dusk := maxf(exp(-pow((hour - 6.0) / 1.8, 2.0)), exp(-pow((hour - 19.0) / 1.8, 2.0)))
	var daylight := clampf(sin((hour - 6.0) * PI / 12.0), 0.0, 1.0)
	match species:
		"small_bird", "pigeon", "crow", "squirrel": return 0.15 + 0.75 * daylight + 0.1 * dawn_dusk
		"fox": return 0.25 + 0.55 * (1.0 - daylight) + 0.2 * dawn_dusk
		"moose", "roe_deer": return 0.45 + 0.55 * dawn_dusk
		_: return 0.45 + 0.35 * dawn_dusk


static func config_valid(weights: Dictionary) -> bool:
	return weights.size() == SPECIES.size() and SPECIES.all(func(species): return weights.get(species, -1.0) >= 0.0)


func clear() -> void:
	animals.clear()
	_chunks.clear()
	queue_redraw()


func remove_chunk(chunk_id: String) -> void:
	if not _chunks.has(chunk_id):
		return
	var ids: Array = _chunks[chunk_id]
	animals = animals.filter(func(animal): return not ids.has(animal["id"]))
	_chunks.erase(chunk_id)
	queue_redraw()


func replace_chunk(message: Dictionary, origin: Vector2) -> void:
	var chunk_id := str(message.get("chunk_id", ""))
	if _chunks.has(chunk_id):
		return  # a streamed refresh keeps the same animals and their movement
	if density <= 0.0 or animals.size() >= max_active:
		_chunks[chunk_id] = []
		return
	var bounds: Array = message.get("bounds", [])
	if bounds.size() != 4:
		return
	var a := MapMath.point(origin, float(bounds[0]), float(bounds[1]))
	var b := MapMath.point(origin, float(bounds[2]), float(bounds[3]))
	var rect := Rect2(Vector2(minf(a.x, b.x), minf(a.y, b.y)), (b - a).abs())
	var forested: bool = message.get("landuse", []).any(func(area): return area.size() > 3 and str(area[3]) in ["forest", "wood"])
	var kind := habitat(message.get("buildings", []).size(), message.get("trees", []).size(), forested)
	var weights := habitat_weights(kind)
	for species in weights.keys():
		weights[species] *= float(species_weights.get(species, 1.0))
	var wanted := mini(max_active - animals.size(), maxi(0, roundi(density * rect.get_area() / 250000.0)))
	var rng := RandomNumberGenerator.new()
	rng.seed = hash(chunk_id)
	var trees: Array = message.get("trees", [])
	var ids: Array = []
	for index in wanted:
		var species := _weighted_species(weights, rng.randf())
		var animal := _animal(_next_id, species, rect, rng)
		if species != "pigeon" and not trees.is_empty():
			var tree: Array = trees[index % trees.size()]
			var tree_at := MapMath.point(origin, float(tree[0]), float(tree[1]))
			var near_tree := tree_at + Vector2.from_angle(rng.randf_range(-PI, PI)) * rng.randf_range(2.0, 14.0)
			animal["position"] = Vector2(clampf(near_tree.x, rect.position.x, rect.end.x), clampf(near_tree.y, rect.position.y, rect.end.y))
		animals.append(animal)
		ids.append(_next_id)
		_next_id += 1
	_chunks[chunk_id] = ids
	queue_redraw()


static func _weighted_species(weights: Dictionary, roll: float) -> String:
	var total := 0.0
	for weight in weights.values(): total += float(weight)
	var at := roll * total
	for species in weights:
		at -= float(weights[species])
		if at <= 0.0: return species
	return weights.keys()[-1]


static func _animal(id: int, species: String, bounds: Rect2, rng: RandomNumberGenerator) -> Dictionary:
	var at := Vector2(rng.randf_range(bounds.position.x, bounds.end.x), rng.randf_range(bounds.position.y, bounds.end.y))
	return {"id": id, "species": species, "position": at, "bounds": bounds,
		"heading": rng.randf_range(-PI, PI), "state": "IDLE", "timer": rng.randf_range(0.4, 2.5), "cycle": 0}


func update(delta: float, game_time_seconds: float, view_centre: Vector2, vehicles: Array = []) -> void:
	_accumulator += minf(delta, 0.5)
	while _accumulator >= STEP_S:
		_step(STEP_S, game_time_seconds, view_centre, vehicles)
		_accumulator -= STEP_S
	queue_redraw()


func _step(dt: float, game_time_seconds: float, view_centre: Vector2, vehicles: Array) -> void:
	for animal in animals:
		if animal["position"].distance_squared_to(view_centre) > activity_distance_m * activity_distance_m: continue
		animal["timer"] -= dt
		var threat := _nearest_vehicle(animal["position"], vehicles) if vehicle_reactions else Vector2.INF
		if threat != Vector2.INF and threat.distance_to(animal["position"]) < REACTION_M:
			animal["state"] = "FLY" if animal["species"] in ["small_bird", "pigeon", "crow"] else "FLEE"
			animal["heading"] = (animal["position"] - threat).angle()
			animal["timer"] = 1.5
		elif animal["timer"] <= 0.0:
			_transition(animal, activity(animal["species"], game_time_seconds))
		var speed := _speed(animal["species"], animal["state"])
		if speed > 0.0:
			var next: Vector2 = animal["position"] + Vector2.from_angle(animal["heading"]) * speed * dt
			if animal["bounds"].has_point(next): animal["position"] = next
			else: animal["heading"] += PI


static func _nearest_vehicle(at: Vector2, vehicles: Array) -> Vector2:
	var nearest := Vector2.INF
	var best := INF
	for position in vehicles:
		var distance := at.distance_squared_to(position)
		if distance < best:
			best = distance
			nearest = position
	return nearest


static func _transition(animal: Dictionary, active: float) -> void:
	animal["cycle"] += 1
	var phase := absf(sin(float(animal["id"] * 37 + animal["cycle"] * 101)))
	if phase > active:
		animal["state"] = "IDLE"
		animal["timer"] = 1.0 + phase * 3.0
		return
	var species: String = animal["species"]
	if species in ["small_bird", "pigeon", "crow"] and phase < 0.18: animal["state"] = "FLY"
	elif species in ["small_bird", "pigeon", "crow", "squirrel"] and phase < 0.45: animal["state"] = "FEED"
	else: animal["state"] = "WANDER"
	animal["heading"] = fmod(float(animal["id"] * 2 + animal["cycle"] * 3), TAU) - PI
	animal["timer"] = 0.8 + phase * 2.0


static func _speed(species: String, state: String) -> float:
	if state in ["IDLE", "FEED"]: return 0.0
	if state in ["FLEE", "FLY"]: return 7.0 if species in ["small_bird", "pigeon", "crow"] else 5.0
	return {"squirrel": 1.6, "small_bird": 0.5, "pigeon": 0.55, "hare": 1.8,
		"fox": 1.5, "moose": 1.0, "roe_deer": 1.2, "crow": 0.65}.get(species, 1.0)


func _draw() -> void:
	drawn_members = 0
	for animal in animals: _draw_animal(animal)


func _draw_animal(animal: Dictionary) -> void:
	var at: Vector2 = animal["position"]
	var direction := Vector2.from_angle(animal["heading"])
	var species: String = animal["species"]
	var scale_m: float = {"small_bird": 0.65, "pigeon": 0.72, "crow": 0.8, "squirrel": 0.3, "hare": 0.42,
		"fox": 0.65, "roe_deer": 0.85, "moose": 1.15}.get(species, 0.4)
	var color: Color = {"small_bird": Color8(54, 49, 42), "pigeon": Color8(92, 99, 108), "crow": Color8(42, 43, 45), "squirrel": Color8(144, 79, 38),
		"hare": Color8(142, 126, 101), "fox": Color8(194, 91, 38), "roe_deer": Color8(151, 104, 62), "moose": Color8(91, 67, 48)}.get(species, Color.GRAY)
	color = winter_coat(species, color, winter)
	var members := 5 if species == "small_bird" else (3 if species == "pigeon" else 1)
	drawn_members += members
	var flying: bool = animal["state"] == "FLY"
	var seconds := Time.get_ticks_msec() / 1000.0
	for member in members:
		var offset := Vector2.ZERO if member == 0 else Vector2.from_angle(float(animal["id"] * 2 + member * 2)) * (1.5 + member * 0.8)
		if flying:  # each member flaps on its own beat
			_draw_flying(at + offset, direction, scale_m, color, species, seconds + float(animal["id"] * 7 + member * 3) * 0.13)
		else:
			_draw_body(at + offset, direction, scale_m, color, species, int(animal["id"]))


## A bird in flight from above: two swept
## wings (arm and hand) that beat - wider when spread, narrower and swept
## back on the upstroke - a slim body, head and fan tail. Quads and
## triangles only, drawn as is: no polygon triangulation to fail.
const FLIGHT := {  # span (x scale), flaps per second, wing chord (x scale)
	"small_bird": [1.7, 4.5, 0.42],
	"pigeon": [2.0, 3.2, 0.40],
	"crow": [2.3, 2.2, 0.55],
}


func _draw_flying(at: Vector2, direction: Vector2, scale_m: float, color: Color, species: String, seconds: float) -> void:
	var shape: Array = FLIGHT.get(species, FLIGHT["pigeon"])
	var beat := sin(seconds * TAU * float(shape[1]))  # +1 wings level and spread, -1 raised (seen shorter from above)
	var spread := 0.62 + 0.38 * (beat * 0.5 + 0.5)
	var sweep := (1.0 - spread) * 0.9  # tips swept back as the wing rises
	var span: float = scale_m * float(shape[0]) * spread
	var chord: float = scale_m * float(shape[2])
	var side := direction.orthogonal()
	var feather := color.lightened(0.18)
	_draw_wings(at, direction, side, span, chord, sweep * scale_m, color, feather)
	var body := PackedVector2Array([at + direction * scale_m * 0.6, at + side * scale_m * 0.24,
		at - direction * scale_m * 0.6, at - side * scale_m * 0.24])
	draw_primitive(body, PackedColorArray([color.darkened(0.08)]), PackedVector2Array())
	var tail := at - direction * scale_m * 0.5
	draw_primitive(PackedVector2Array([tail, tail - direction * scale_m * 0.5 + side * scale_m * 0.26,
		tail - direction * scale_m * 0.5 - side * scale_m * 0.26]), PackedColorArray([color]), PackedVector2Array())
	draw_circle(at + direction * scale_m * 0.62, scale_m * 0.19, color.lightened(0.05))
	if species == "crow" or species == "pigeon":  # the bill
		var bill := at + direction * scale_m * 0.78
		draw_line(bill, bill + direction * scale_m * 0.18, Color8(30, 30, 28) if species == "crow" else Color8(200, 170, 120), scale_m * 0.08)


func _draw_wings(at: Vector2, direction: Vector2, side: Vector2, span: float, chord: float, sweep: float,
		arm_color: Color, hand_color: Color) -> void:
	for sign: float in [-1.0, 1.0]:
		var out: Vector2 = side * sign
		# From above a bird's wing is an M: the arm angles forward from the
		# body, the hand sweeps back to its tip; broad at the root.
		var root_front: Vector2 = at + direction * chord * 0.5
		var root_back: Vector2 = at - direction * chord * 0.75
		var elbow: Vector2 = at + out * span * 0.42 + direction * chord * (0.35 - sweep * 0.3)
		var elbow_front: Vector2 = elbow + direction * chord * 0.3
		var elbow_back: Vector2 = elbow - direction * chord * 0.75
		var tip: Vector2 = at + out * span - direction * (chord * 0.55 + sweep)
		draw_primitive(PackedVector2Array([root_front, elbow_front, elbow_back, root_back]),
			PackedColorArray([arm_color]), PackedVector2Array())
		draw_primitive(PackedVector2Array([elbow_front, tip, elbow_back]),
			PackedColorArray([hand_color]), PackedVector2Array())


## A Finnish winter coat, blended in with the season (moulting through
## autumn and spring): the mountain hare turns white, the red squirrel grey.
static func winter_coat(species: String, color: Color, winter_weight: float) -> Color:
	match species:
		"hare": return color.lerp(Color8(238, 238, 234), clampf(winter_weight, 0.0, 1.0))
		"squirrel": return color.lerp(Color8(120, 118, 116), clampf(winter_weight, 0.0, 1.0))
	return color


## An animal on the ground, from above: its own silhouette per species
## (scale_m: about half its body length). No shadows: they would not follow the sun as buildings' do. Circles,
## quads and triangles only, drawn as is - no polygon triangulation to fail.
func _draw_body(at: Vector2, direction: Vector2, scale_m: float, color: Color, species: String, id: int) -> void:
	if direction.length_squared() < 1e-6:
		direction = Vector2.RIGHT  # standing still: any facing, never a collapsed body
	var d := direction.normalized() * scale_m  # along the body, one scale_m long
	var s := direction.normalized().orthogonal() * scale_m
	var light := color.lightened(0.15)
	var dark := color.darkened(0.25)
	match species:
		"fox":
			_quad(at - d * 0.45 + s * 0.1, at - d * 0.45 - s * 0.1, at - d * 1.15 - s * 0.17, at - d * 1.15 + s * 0.17, color)
			draw_circle(at - d * 1.2, scale_m * 0.15, Color8(240, 235, 225))  # the white tail tip
			_capsule(at + d * 0.35, at - d * 0.45, scale_m * 0.22, color)
			draw_circle(at + d * 0.6, scale_m * 0.2, light)
			_tri(at + d * 0.98, at + d * 0.7 + s * 0.12, at + d * 0.7 - s * 0.12, light)  # snout
			for side: float in [-1.0, 1.0]:  # pointed ears, black backs
				_tri(at + d * 0.58 + s * 0.12 * side, at + d * 0.48 + s * 0.3 * side, at + d * 0.68 + s * 0.24 * side, dark)
		"hare":
			_capsule(at + d * 0.2, at - d * 0.35, scale_m * 0.3, color)
			draw_circle(at - d * 0.62, scale_m * 0.13, Color8(235, 232, 225))  # the white scut
			draw_circle(at + d * 0.48, scale_m * 0.2, light)
			for side: float in [-1.0, 1.0]:  # long ears raised back in a V over the shoulders, dark tips
				var tip := at - d * 0.12 + s * 0.46 * side  # past the body's outline: visible against the ground
				_quad(at + d * 0.48 + s * 0.05 * side, at + d * 0.5 + s * 0.17 * side, tip + d * 0.07, tip - d * 0.05,
					color.darkened(0.3) if color.v < 0.8 else color.darkened(0.08))  # (white in winter; the tips stay black)
				_tri(tip + d * 0.07, tip - d * 0.05, tip - d * 0.16 + s * 0.06 * side, Color8(30, 26, 22))
		"squirrel":
			for k in 5:  # the big bushy tail: up from the back and curling over to one side
				var curl := float(k) / 4.0
				draw_circle(at - d * (0.45 + 0.45 * sin(curl * 2.2)) + s * (0.55 * (1.0 - cos(curl * 2.4))),
					scale_m * (0.2 + 0.08 * sin(curl * PI)), light if k % 2 else color.lightened(0.05))
			_capsule(at + d * 0.2, at - d * 0.3, scale_m * 0.22, color)
			draw_circle(at + d * 0.45, scale_m * 0.18, light)
			for side: float in [-1.0, 1.0]:
				_tri(at + d * 0.5 + s * 0.1 * side, at + d * 0.42 + s * 0.22 * side, at + d * 0.58 + s * 0.16 * side, dark)
		"roe_deer":
			_capsule(at + d * 0.4, at - d * 0.45, scale_m * 0.27, color)
			draw_circle(at - d * 0.58, scale_m * 0.15, Color8(238, 228, 205))  # the pale rump patch
			_capsule(at + d * 0.55, at + d * 0.78, scale_m * 0.13, color.lightened(0.05))  # neck and head
			_tri(at + d * 1.0, at + d * 0.82 + s * 0.08, at + d * 0.82 - s * 0.08, dark)  # muzzle
			for side: float in [-1.0, 1.0]:
				_tri(at + d * 0.74 + s * 0.08 * side, at + d * 0.64 + s * 0.26 * side, at + d * 0.8 + s * 0.2 * side, color.darkened(0.1))
		"moose":
			_capsule(at + d * 0.35, at - d * 0.5, scale_m * 0.32, color)
			draw_circle(at + d * 0.22, scale_m * 0.24, dark)  # the shoulder hump
			_capsule(at + d * 0.62, at + d * 0.98, scale_m * 0.14, color.darkened(0.1))  # long head
			draw_circle(at + d * 1.02, scale_m * 0.15, dark)  # the broad muzzle
			if id % 2 == 0:  # a bull: pale palmate antlers
				var antler := Color8(205, 190, 160)
				for side: float in [-1.0, 1.0]:  # broad palms out to the sides and back from the head
					var base := at + d * 0.62 + s * 0.1 * side
					_quad(base, base + d * 0.12 + s * 0.42 * side, base - d * 0.12 + s * 0.62 * side, base - d * 0.2 + s * 0.2 * side, antler)
					for tine in 3:  # the tines along the palm's front edge
						var on := base + d * (0.1 - tine * 0.1) + s * (0.42 + tine * 0.09) * side
						_tri(on, on + d * 0.04 + s * 0.12 * side, on - d * 0.05 + s * 0.06 * side, antler)
		_:  # a bird on the ground: round body, folded wings, head and bill, tail
			_tri(at - d * 0.4, at - d * 0.95 + s * 0.2, at - d * 0.95 - s * 0.2, dark)  # tail
			_capsule(at + d * 0.15, at - d * 0.3, scale_m * 0.3, color)
			for side: float in [-1.0, 1.0]:  # folded wings along the back
				_quad(at + d * 0.15 + s * 0.12 * side, at + d * 0.2 + s * 0.27 * side,
					at - d * 0.55 + s * 0.16 * side, at - d * 0.5 + s * 0.04 * side, light)
			if species == "pigeon":
				draw_circle(at + d * 0.35, scale_m * 0.2, Color8(96, 128, 116))  # the green-purple neck sheen
			draw_circle(at + d * 0.5, scale_m * 0.2, color.lightened(0.05))
			_tri(at + d * 0.85, at + d * 0.62 + s * 0.06, at + d * 0.62 - s * 0.06,
				Color8(40, 40, 38) if species == "crow" else Color8(205, 175, 120))  # the bill


## A rounded body from `back` to `front`.
func _capsule(front: Vector2, back: Vector2, radius: float, color: Color) -> void:
	var across := (front - back).normalized().orthogonal() * radius
	draw_circle(front, radius, color)
	draw_circle(back, radius, color)
	_quad(front + across, front - across, back - across, back + across, color)


func _quad(a: Vector2, b: Vector2, c: Vector2, e: Vector2, color: Color) -> void:
	draw_primitive(PackedVector2Array([a, b, c, e]), PackedColorArray([color]), PackedVector2Array())


func _tri(a: Vector2, b: Vector2, c: Vector2, color: Color) -> void:
	draw_primitive(PackedVector2Array([a, b, c]), PackedColorArray([color]), PackedVector2Array())
