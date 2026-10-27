## rrt-019-amikset: some NPC cars have aftermarket stereos booming
## bass-heavy electro pop. Client-side only: the simulation knows nothing.
##
## Which cars: an eligible car (vehicle_type "car", not a taxi or police)
## has one when the hash of its vehicle id falls under share(the game clock)
## - more on Friday and Saturday nights, few on weekday days. Decided once
## when the car is first seen and kept while it exists, so streaming or the
## clock crossing an hour never rerolls it.
##
## How it sounds: the nightclub music's levels and pool
## (nightclub_audio.gd): gain by distance, a low-pass that closes with it
## (through the car body: bright up close, only the bass far off), at most
## PLAYERS sources from the cars' interpolated positions (EntityLayer.npc_cars).
extends Node

const NightclubAudio := preload("res://nightclub_audio.gd")
const Paths := preload("res://paths.gd")
const PLAYERS := 3
const TRACK_DIR := "assets/music/cars"  # every .ogg in it is a track (NightclubAudio.tracks_in)
const RANGE_M := 120.0  # inaudible from here (world metres)
const NEAR_M := 6.0  # full loudness this close
const CUTOFF_NEAR_HZ := 9000.0  # windows down: synths and percussion still there
const CUTOFF_FAR_HZ := 250.0  # far off: only the 808s
# Share of eligible cars with a stereo (estimates): Fri/Sat nights, other evenings, otherwise
const SHARE_WEEKEND_NIGHT := 0.20
const SHARE_EVENING := 0.10
const SHARE_DAY := 0.05
const FORGET_S := 10.0  # a car unseen this long is forgotten (despawned)

var _players: Array = []
var _car_of: Array = []  # each player's vehicle id, -1 when free
var _cutoffs: Array = []
var _streams: Array = []
var _stereo := {}  # vehicle id -> [has a stereo, last seen (s)]
var _clock := 0.0


func _ready() -> void:
	for path in NightclubAudio.tracks_in(TRACK_DIR):
		var stream := AudioStreamOggVorbis.load_from_file(Paths.package_path(path))
		if stream == null:
			push_warning("Car music could not be loaded: %s" % path)
			continue
		stream.loop = true
		_streams.append(stream)
	for i in PLAYERS:
		var bus := "CarMusic%d" % i
		if AudioServer.get_bus_index(bus) == -1:
			AudioServer.add_bus()
			AudioServer.set_bus_name(AudioServer.bus_count - 1, bus)
			AudioServer.set_bus_send(AudioServer.bus_count - 1, "Environment")
			AudioServer.add_bus_effect(AudioServer.bus_count - 1, AudioEffectLowPassFilter.new())
		_cutoffs.append(AudioServer.get_bus_effect(AudioServer.get_bus_index(bus), 0))
		var player := AudioStreamPlayer2D.new()
		player.bus = bus
		player.attenuation = 0.0  # the loudness is ours (gain); the 2D player only pans
		player.max_distance = 100000.0
		player.panning_strength = 0.6
		add_child(player)
		_players.append(player)
		_car_of.append(-1)


## Share of eligible cars with a stereo at `minute` of the week (0 = Monday 00:00).
static func share(minute: float) -> float:
	var day := int(minute / 1440.0) % 7
	var hour := fmod(minute, 1440.0) / 60.0
	var night_of := day if hour >= 18.0 else (day + 6) % 7  # 00-05 belongs to the night before
	if hour >= 18.0 or hour < 5.0:
		return SHARE_WEEKEND_NIGHT if night_of in [4, 5] else SHARE_EVENING  # Friday, Saturday nights
	return SHARE_DAY


static func eligible(npc: Dictionary) -> bool:
	return npc.get("vehicle_type", "") == "car" and not npc.get("is_taxi", false) and not npc.get("is_police", false)


## A stable 0..1 draw per vehicle id: the same car always draws the same.
static func draw(vehicle_id) -> float:
	return float((int(vehicle_id) * 2654435761) & 0xFFFFFFFF) / 4294967296.0  # Knuth's multiplicative hash


static func gain(distance_m: float) -> float:
	if distance_m >= RANGE_M:
		return 0.0
	var t := clampf((distance_m - NEAR_M) / (RANGE_M - NEAR_M), 0.0, 1.0)
	return (1.0 - t) * (1.0 - t) * (1.0 - t * 0.5)


static func cutoff_hz(distance_m: float) -> float:
	var t := clampf((distance_m - NEAR_M) / (RANGE_M - NEAR_M), 0.0, 1.0)
	return CUTOFF_NEAR_HZ * pow(CUTOFF_FAR_HZ / CUTOFF_NEAR_HZ, t)


## Once per frame: `cars` from EntityLayer.npc_cars(), `listener` in layer
## coordinates (metres), the game's minute of the week.
func update(cars: Array, listener: Vector2, minute: float, delta: float) -> void:
	_clock += delta
	var wanted := {}  # id -> [loudness, distance, position]
	for car in cars:
		var id = car[0]
		var known = _stereo.get(id)
		if known == null:
			known = [eligible(car[2]) and draw(id) < share(minute), 0.0]
			_stereo[id] = known
		known[1] = _clock
		if not known[0]:
			continue
		var distance: float = car[1].distance_to(listener)
		if distance < RANGE_M:
			wanted[id] = [gain(distance), distance, car[1]]
	for id in _stereo.keys():  # despawned: forget (and its player fades out below)
		if _clock - _stereo[id][1] > FORGET_S:
			_stereo.erase(id)
	var ids := wanted.keys()
	ids.sort_custom(func(a, b): return wanted[a][0] > wanted[b][0])
	ids = ids.slice(0, PLAYERS)
	var blend := 1.0 - exp(-delta / NightclubAudio.SMOOTH_S)
	for i in _players.size():
		if _car_of[i] != -1 and not ids.has(_car_of[i]):
			_fade(i, 0.0, CUTOFF_FAR_HZ, blend)
	for id in ids:
		var i := _car_of.find(id)
		if i == -1:
			i = _car_of.find(-1)
			if i == -1 or _streams.is_empty():
				continue
			_car_of[i] = id
			var player: AudioStreamPlayer2D = _players[i]
			player.stream = _streams[hash(str(id)) % _streams.size()]
			player.volume_db = -80.0
			_cutoffs[i].cutoff_hz = cutoff_hz(wanted[id][1])
			player.play(randf() * 60.0)
		_players[i].position = wanted[id][2]
		_fade(i, wanted[id][0], cutoff_hz(wanted[id][1]), blend)


func _fade(i: int, loudness: float, cutoff: float, blend: float) -> void:
	var player: AudioStreamPlayer2D = _players[i]
	var linear := db_to_linear(player.volume_db) / db_to_linear(NightclubAudio.LOUDNESS_DB)
	linear += (loudness - linear) * blend
	_cutoffs[i].cutoff_hz += (cutoff - _cutoffs[i].cutoff_hz) * blend
	if loudness == 0.0 and linear < 0.002:
		player.stop()
		_car_of[i] = -1
		return
	player.volume_db = linear_to_db(maxf(linear, 0.00001)) + NightclubAudio.LOUDNESS_DB


func playing_count() -> int:
	return _players.filter(func(p): return p.playing).size()


## Like the nightclubs: loud music nearby turns the city ambience down.
func city_ambience_gain() -> float:
	var strongest := 0.0
	for i in _players.size():
		if _car_of[i] != -1 and _players[i].playing:
			strongest = maxf(strongest, db_to_linear(_players[i].volume_db - NightclubAudio.LOUDNESS_DB))
	return lerpf(1.0, NightclubAudio.CITY_AMBIENCE_MIN, clampf(strongest, 0.0, 1.0))
