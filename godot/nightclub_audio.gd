## rrt-019-nightclub: dance music leaking out of the nightclubs nearby.
## The venues come with the map chunks (`nightclubs`: [x, y, weekly open
## intervals], server nightlife.py), so they load and unload with them; the
## time is the server's game clock. Three factors, kept apart and multiplied:
##
##   open(schedule, minute of week)   0..1, fading over FADE_MIN at opening / closing
##   gain(distance)                   1 at the door, smoothly to 0 at RANGE_M
##   cutoff(distance)                 the walls: muffled at the door, more so far off
##
## Muffling is a documented approximation, not acoustics: the music always
## comes through the venue's walls (players are outside), so a low-pass that
## closes with distance; no ray tests against other buildings.
## A fixed pool of PLAYERS (one low-pass bus each, made once) plays the
## loudest venues; a venue keeps its player while it stays among them, so the
## track never restarts on a chunk crossing, a volume change or the clock.
extends Node

const Paths := preload("res://paths.gd")
const PLAYERS := 3
const TRACKS := ["assets/music/nightclub/nightclub_dance_1.ogg", "assets/music/nightclub/nightclub_dance_2.ogg"]
const RANGE_M := 160.0  # inaudible from here (world metres: the server's EPSG:3067 metres)
const DOOR_M := 12.0  # full loudness this close
const LOUDNESS_DB := 2.0  # at the door, before the Environment bus (+6 dB over the original mix)
const CITY_AMBIENCE_MIN := 0.2  # leave a quiet city bed underneath nearby music
const CUTOFF_DOOR_HZ := 2600.0  # through the walls and doors, right outside
const CUTOFF_FAR_HZ := 280.0  # at RANGE_M: only the bass left
const FADE_MIN := 20.0  # game minutes: a venue opening or closing fades over this
const SMOOTH_S := 0.6  # volume and cutoff ease towards their targets this fast
const WEEK_MIN := 7 * 24 * 60

var _players: Array = []  # AudioStreamPlayer2D
var _club_of: Array = []  # each player's venue key ("x,y"), "" when free
var _cutoffs: Array = []  # each player's AudioEffectLowPassFilter
var _streams: Array = []


func _ready() -> void:
	for path in TRACKS:
		var stream := AudioStreamOggVorbis.load_from_file(Paths.package_path(path))
		if stream == null:
			push_warning("Nightclub music could not be loaded: %s" % path)
			continue
		stream.loop = true
		_streams.append(stream)
	for i in PLAYERS:
		var bus := "Nightclub%d" % i
		if AudioServer.get_bus_index(bus) == -1:
			AudioServer.add_bus()
			AudioServer.set_bus_name(AudioServer.bus_count - 1, bus)
			AudioServer.set_bus_send(AudioServer.bus_count - 1, "Environment")
			AudioServer.add_bus_effect(AudioServer.bus_count - 1, AudioEffectLowPassFilter.new())
		var index := AudioServer.get_bus_index(bus)
		_cutoffs.append(AudioServer.get_bus_effect(index, 0))
		var player := AudioStreamPlayer2D.new()
		player.bus = bus
		player.attenuation = 0.0  # the loudness is ours (gain); the 2D player only pans
		player.max_distance = 100000.0
		player.panning_strength = 0.6
		add_child(player)
		_players.append(player)
		_club_of.append("")


## How open a venue is at `minute` of the week (0 = Monday 00:00): 1 inside
## an interval, fading linearly over FADE_MIN after it opens and before it closes.
static func open_level(schedule: Array, minute: float) -> float:
	var level := 0.0
	for interval in schedule:
		var start: float = interval[0]
		var end: float = interval[1]
		for shift: float in [0.0, -WEEK_MIN, WEEK_MIN]:  # Sunday night into Monday wraps the week
			var m: float = minute + shift
			if m >= start and m <= end:
				level = maxf(level, minf(1.0, minf(m - start, end - m) / FADE_MIN))
	return level


static func gain(distance_m: float) -> float:
	if distance_m >= RANGE_M:
		return 0.0
	var t := clampf((distance_m - DOOR_M) / (RANGE_M - DOOR_M), 0.0, 1.0)
	return (1.0 - t) * (1.0 - t) * (1.0 - t * 0.5)  # steep near the door, a long quiet tail, 0 at the edge


static func cutoff_hz(distance_m: float) -> float:
	var t := clampf((distance_m - DOOR_M) / (RANGE_M - DOOR_M), 0.0, 1.0)
	return CUTOFF_DOOR_HZ * pow(CUTOFF_FAR_HZ / CUTOFF_DOOR_HZ, t)  # even steps per octave


## Minute of the week from the server's calendar date and game time.
static func week_minute(date: String, game_time_seconds: float) -> float:
	var day: int = Time.get_datetime_dict_from_datetime_string(date + "T00:00:00", true).get("weekday", 1)
	return float(((day + 6) % 7) * 24 * 60) + fmod(game_time_seconds, 86400.0) / 60.0


## Once per state frame: `clubs` the loaded chunks' venues, `listener` and
## the venues in world metres.
func update(clubs: Array, listener: Vector2, minute: float, origin: Vector2, delta: float) -> void:
	var wanted := {}  # key -> [loudness, distance, position]
	for club in clubs:
		var at := Vector2(club[0], club[1])
		var distance := at.distance_to(listener)
		if distance >= RANGE_M:
			continue
		var loudness := gain(distance) * open_level(club[2], minute)
		if loudness > 0.0005:
			wanted["%s,%s" % [club[0], club[1]]] = [loudness, distance, at]
	var keys := wanted.keys()
	keys.sort_custom(func(a, b): return wanted[a][0] > wanted[b][0])
	keys = keys.slice(0, PLAYERS)
	var blend := 1.0 - exp(-delta / SMOOTH_S)
	for i in _players.size():  # players keep their venue; a venue no longer wanted fades out
		if _club_of[i] != "" and not keys.has(_club_of[i]):
			_fade(i, 0.0, CUTOFF_FAR_HZ, blend)
	for key in keys:
		var i := _club_of.find(key)
		if i == -1:
			i = _club_of.find("")
			if i == -1 or _streams.is_empty():
				continue
			_club_of[i] = key
			var player: AudioStreamPlayer2D = _players[i]
			player.stream = _streams[hash(key) % _streams.size()]
			player.volume_db = -80.0
			_cutoffs[i].cutoff_hz = cutoff_hz(wanted[key][1])
			player.play(randf() * 200.0)  # not every club at the same bar
		_players[i].position = MapMath.point(origin, wanted[key][2].x, wanted[key][2].y)
		_fade(i, wanted[key][0], cutoff_hz(wanted[key][1]), blend)


func _fade(i: int, loudness: float, cutoff: float, blend: float) -> void:
	var player: AudioStreamPlayer2D = _players[i]
	var linear := db_to_linear(player.volume_db) / db_to_linear(LOUDNESS_DB)
	linear += (loudness - linear) * blend
	_cutoffs[i].cutoff_hz += (cutoff - _cutoffs[i].cutoff_hz) * blend
	if loudness == 0.0 and linear < 0.002:
		player.stop()
		_club_of[i] = ""
		return
	player.volume_db = linear_to_db(maxf(linear, 0.00001)) + LOUDNESS_DB


func playing_count() -> int:
	return _players.filter(func(p): return p.playing).size()


## Follow the loudest actual player, including its opening/closing and distance fades.
func city_ambience_gain() -> float:
	var strongest := 0.0
	for i in _players.size():
		if _club_of[i] != "" and _players[i].playing:
			strongest = maxf(strongest, db_to_linear(_players[i].volume_db - LOUDNESS_DB))
	return lerpf(1.0, CITY_AMBIENCE_MIN, clampf(strongest, 0.0, 1.0))
