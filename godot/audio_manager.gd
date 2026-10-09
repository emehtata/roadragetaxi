## All of the client's sound. Simulation events go in (`handle_event`) and
## presentation state drives the loops (`set_loop`); nothing else in the
## client plays audio. What an event sounds like is data: audio/audio_events.json
## maps events to groups of the game's own sound catalog, whose files are
## loaded from where the Python game keeps them (no copies).
##
## Buses: Master > Game (vehicle, trains, people...), Environment (ambience,
## weather), UI. Placed sounds are AudioStreamPlayer2D nodes heard from the
## camera, which also fades them with distance.
class_name AudioManager
extends Node

const CONFIG_PATH := "res://audio/audio_events.json"
const BUSES := ["Game", "Environment", "UI"]

var origin := Vector2.ZERO  # map origin (MapMath)
var player_at := Vector2.ZERO  # the taxi / walking player, world metres: where its own sounds come from
var played := 0  # one-shots started (performance / test readout)
var played_groups: Dictionary = {}  # group -> one-shots started
var loop_files: Dictionary = {}  # loop key -> the file it is (or was last) playing
var loop_starts: Dictionary = {}  # loop key -> times it (re)started: once per sounding stretch, not per state
var unhandled: Dictionary = {}  # event key -> times seen with no sound

var _config: Dictionary = {}
var _groups: Dictionary = {}  # catalog group id -> {"files": [absolute paths], "category": String}
var _streams: Dictionary = {}  # path -> AudioStream (loaded once)
var _loops: Dictionary = {}  # key -> AudioStreamPlayer
var _bus_of_category: Dictionary = {}
var _last_variation: Dictionary = {}  # group -> index last picked, so a random pick never repeats it back to back (as audio.py)
var _foot_at := Vector2.INF
var _foot_distance := 0.0
const FOOTSTEP_M := 0.8
# godot-final-07: one voice (driver/passenger speech) and one station loudspeaker.
const ANNOUNCEMENT_MAX_WAIT_MS := 20000  # station_announcer.py MAX_WAIT_S: a queued announcement older is dropped
var package_root: String = preload("res://paths.gd").package_root()  # the repo's or the release's
var speech_player := AudioStreamPlayer.new()
var announcer := AudioStreamPlayer2D.new()
var announcements: Array = []  # waiting: [queued at ms, clip paths, world position]
var _announcing: Array = []  # the clips still to play of the one on air


func _ready() -> void:
	for bus in BUSES:
		if AudioServer.get_bus_index(bus) == -1:
			AudioServer.add_bus()
			var index := AudioServer.bus_count - 1
			AudioServer.set_bus_name(index, bus)
			AudioServer.set_bus_send(index, "Master")
	load_config(CONFIG_PATH)
	speech_player.bus = "Game"
	add_child(speech_player)
	announcer.bus = "Game"
	announcer.attenuation = 1.0
	announcer.max_distance = _config.get("ranges_m", {}).get("railway.announcement", [60.0, 300.0])[1]
	announcer.finished.connect(_next_clip)  # the next clip the moment one ends: no polling gaps
	add_child(announcer)


func load_config(path: String) -> void:
	_config = JSON.parse_string(FileAccess.get_file_as_string(path))
	for bus in _config.get("buses", {}):
		for category in _config["buses"][bus]:
			_bus_of_category[category] = bus
	# The catalog sits in the Python package ("../src/theroadragetrip/..." from the repo's godot/).
	var catalog_path := package_root.path_join(str(_config["catalog"]).trim_prefix("../src/theroadragetrip/"))
	var catalog = JSON.parse_string(FileAccess.get_file_as_string(catalog_path))
	if typeof(catalog) != TYPE_DICTIONARY:
		push_warning("AudioManager: no sound catalog at %s - running silent" % catalog_path)
		return
	for group_id in catalog.get("groups", {}):
		var group: Dictionary = catalog["groups"][group_id]
		var files: Array = []
		for entry in group.get("files", []):
			if entry.get("status") == "generated":
				files.append(catalog_path.get_base_dir().path_join(entry["file"]))
		if not files.is_empty():
			_groups[group_id] = {"files": files, "category": group.get("category", "")}


## Volume of "Master", "Game", "Environment" or "UI", 0..1.
func set_bus_volume(bus: String, linear: float) -> void:
	var index := AudioServer.get_bus_index(bus)
	if index != -1:
		AudioServer.set_bus_volume_db(index, linear_to_db(clampf(linear, 0.0, 1.0)))


func bus_for(group_id: String) -> String:
	var category: String = _groups.get(group_id, {}).get("category", group_id.get_slice(".", 0))
	return _bus_of_category.get(category, "Game")


## What an event sounds like: [{"group", "file", "volume", "bus", "at"?,
## "range"?}]. Empty for an event with no sound (it's counted in `unhandled`).
func resolve(event: Dictionary) -> Array:
	var key: String = event.get("group", "") if event.get("type") == "sound" else event.get("type", "")
	var steps: Array = _config.get("events", {}).get(key, [{"group": key}])
	var actions: Array = []
	for step in steps:
		var group: Dictionary = _groups.get(step["group"], {})
		if group.is_empty():
			continue
		var files: Array = group["files"]
		var variation: int = step.get("variation", event.get("variation", _pick_variation(step["group"], files.size())))
		var action := {"group": step["group"], "file": files[clampi(variation, 0, files.size() - 1)],
			"volume": float(step.get("volume", 1.0)), "bus": bus_for(step["group"])}
		var at = event.get("at")
		if at == null and group["category"] in _config.get("player_categories", []):
			at = [player_at.x, player_at.y]
		if at != null:
			action["at"] = Vector2(at[0], at[1])
			action["range"] = _config.get("ranges_m", {}).get(step["group"], _config.get("player_range_m", [20.0, 300.0]))
		actions.append(action)
	if actions.is_empty():
		if not unhandled.has(key):
			print("audio: no sound for event '%s'" % key)
		unhandled[key] = unhandled.get(key, 0) + 1
	return actions


func _pick_variation(group_id: String, count: int) -> int:
	if count <= 1:
		return 0
	var pick := randi() % (count - 1)
	if pick >= _last_variation.get(group_id, -1) and _last_variation.has(group_id):
		pick += 1  # skip the last one: uniform over the others
	_last_variation[group_id] = pick
	return pick


## Every catalog file this client can play (validation and tests).
func all_files() -> Array:
	var files: Array = []
	for group in _groups.values():
		files.append_array(group["files"])
	return files


func load_file(path: String) -> AudioStream:
	return _stream(path)


## Present one simulation event (each arrives once - see StateBuffer).
func handle_event(event: Dictionary) -> void:
	for action in resolve(event):
		var stream := _stream(action["file"])
		if stream == null:
			continue
		var player: Node
		if action.has("at"):
			var placed := AudioStreamPlayer2D.new()
			placed.position = MapMath.point(origin, action["at"].x, action["at"].y)
			placed.max_distance = action["range"][1]
			placed.attenuation = 1.0
			placed.volume_db = linear_to_db(action["volume"])
			placed.bus = action["bus"]
			placed.stream = stream
			player = placed
		else:
			var flat := AudioStreamPlayer.new()
			flat.volume_db = linear_to_db(action["volume"])
			flat.bus = action["bus"]
			flat.stream = stream
			player = flat
		add_child(player)
		player.finished.connect(player.queue_free)
		player.play()
		played += 1
		played_groups[action["group"]] = played_groups.get(action["group"], 0) + 1


## Play local footsteps from actual interpolated movement, not key state.
func update_footsteps(on_foot: bool, at: Vector2) -> void:
	if not on_foot:
		_foot_at = Vector2.INF
		_foot_distance = 0.0
		return
	if _foot_at == Vector2.INF:
		_foot_at = at
		return
	var moved := _foot_at.distance_to(at)
	_foot_at = at
	if moved > 5.0:  # respawn/teleport, not walking
		_foot_distance = 0.0
		return
	_foot_distance += moved
	if _foot_distance >= FOOTSTEP_M:
		_foot_distance = fmod(_foot_distance, FOOTSTEP_M)
		handle_event({"type": "sound", "group": "pedestrian.footsteps"})


## A continuous sound named in the config's "loops": on at `volume` (0
## stops it), optionally pitched (engine revs). A loop marked "positional"
## sounds from `at` (world metres), moved there on every call. Started once
## and then only adjusted - never restarted per state.
func set_loop(key: String, volume: float, pitch: float = 1.0, at = null) -> void:
	var player: Node = _loops.get(key)
	if volume <= 0.001:
		if player != null and player.playing:
			player.stop()
		return
	var spec: Dictionary = _config.get("loops", {}).get(key, {})
	var group: Dictionary = _groups.get(spec.get("group", ""), {})
	if group.is_empty():
		return
	if player == null:
		if spec.get("positional", false):
			var placed := AudioStreamPlayer2D.new()
			placed.max_distance = _config.get("ranges_m", {}).get(spec["group"], [0.0, 200.0])[1]
			placed.attenuation = 1.0
			player = placed
		else:
			player = AudioStreamPlayer.new()
		player.bus = bus_for(spec["group"])
		add_child(player)
		_loops[key] = player
	if not player.playing:  # (re)starting: which variation
		var files: Array = group["files"]
		var variation = spec.get("variation", 0)
		var index: int = _pick_variation(spec["group"], files.size()) if variation is String else clampi(int(variation), 0, files.size() - 1)
		var stream := _stream(files[index]) as AudioStreamOggVorbis
		if stream == null:
			return
		stream.loop = true
		player.stream = stream
		loop_files[key] = files[index]
	player.volume_db = linear_to_db(volume)
	player.pitch_scale = pitch
	if at != null and player is AudioStreamPlayer2D:
		player.position = MapMath.point(origin, at.x, at.y)
	if not player.playing:
		player.play()
		loop_starts[key] = loop_starts.get(key, 0) + 1


## Silence every loop (the simulation went away: nothing is running any more).
func stop_loops() -> void:
	for player in _loops.values():
		player.stop()


## One-shot players still alive (they free themselves when finished).
func one_shots_alive() -> int:
	return get_child_count() - _loops.size()


func loops_playing() -> int:
	return _loops.values().filter(func(p): return p.playing).size()


func loop_playing(key: String) -> bool:
	return _loops.has(key) and _loops[key].playing


## The recording of a server "speech" event, or "" for a malformed one: only
## sounds/<driver|passenger>_chatter/<f|m>_<fi|en>_<hex hash>.wav, never a path from the wire.
func speech_file(event: Dictionary) -> String:
	var speaker = event.get("speaker")
	var gender = event.get("gender")
	var language = event.get("language")
	var key = event.get("hash")
	if not speaker in ["driver", "passenger"] or not gender in ["f", "m"] or not language in ["fi", "en"] \
			or typeof(key) != TYPE_STRING or key.is_empty() or key.length() > 32 or not key.is_valid_hex_number():
		return ""
	return package_root.path_join("sounds/%s_chatter/%s_%s_%s.wav" % [speaker, gender, language, key])


## Plays a "speech" event on the one voice; false (and silent) if it's
## malformed, its recording is missing, or someone is already speaking.
func speak(event: Dictionary) -> bool:
	var path := speech_file(event)
	if path == "" or speech_player.playing or not FileAccess.file_exists(path):
		return false
	var stream := _stream(path)
	if stream == null:
		return false
	speech_player.stream = stream
	speech_player.play()
	played_groups["speech"] = played_groups.get("speech", 0) + 1
	return true


## A manifest clip under assets/railway_announcements, or "" (no traversal, no absolute paths).
func announcement_file(clip) -> String:
	if typeof(clip) != TYPE_STRING or clip.is_empty() or clip.begins_with("/") or ".." in clip or not clip.ends_with(".ogg"):
		return ""
	return package_root.path_join("assets/railway_announcements").path_join(clip)


## Queues a whole "station_announcement" (station_announcer.py): its clips
## play strictly in order on the one loudspeaker; one still waiting after 20 s is dropped.
func announce(event: Dictionary) -> bool:
	var clips = event.get("clips")
	var at = event.get("at")
	if not clips is Array or clips.is_empty() or not at is Array or at.size() != 2:
		return false
	var paths: Array = []
	for clip in clips:
		var path := announcement_file(clip)
		if path == "":
			return false
		paths.append(path)
	announcements.append([Time.get_ticks_msec(), paths, Vector2(float(at[0]), float(at[1]))])
	if not announcer.playing and _announcing.is_empty():
		_next_clip()
	return true


func _next_clip() -> void:
	while _announcing.is_empty() and not announcements.is_empty():
		var waiting: Array = announcements.pop_front()
		if Time.get_ticks_msec() - int(waiting[0]) <= ANNOUNCEMENT_MAX_WAIT_MS:  # older: stale, the train is long gone
			_announcing = waiting[1].duplicate()
			announcer.position = MapMath.point(origin, waiting[2].x, waiting[2].y)
	while not _announcing.is_empty():
		var stream := _stream(_announcing.pop_front())
		if stream != null:  # a missing clip is skipped, the rest still plays (as Pygame)
			announcer.stream = stream
			announcer.play()
			played_groups["announcement_clips"] = played_groups.get("announcement_clips", 0) + 1
			return


## The voice and the loudspeaker stop (the simulation went away).
func stop_voices() -> void:
	speech_player.stop()
	announcer.stop()
	announcements.clear()
	_announcing.clear()


func _stream(path: String) -> AudioStream:
	if not _streams.has(path):
		var stream: AudioStream = null
		if path.ends_with(".ogg"):
			stream = AudioStreamOggVorbis.load_from_file(path)
		elif path.ends_with(".wav"):  # the chatter recordings (PCM WAV), decoded once
			stream = AudioStreamWAV.load_from_file(path)
		if stream == null:
			push_warning("AudioManager: could not load %s" % path)
		_streams[path] = stream
	return _streams[path]
