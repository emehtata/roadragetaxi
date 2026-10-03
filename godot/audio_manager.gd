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


func _ready() -> void:
	for bus in BUSES:
		if AudioServer.get_bus_index(bus) == -1:
			AudioServer.add_bus()
			var index := AudioServer.bus_count - 1
			AudioServer.set_bus_name(index, bus)
			AudioServer.set_bus_send(index, "Master")
	load_config(CONFIG_PATH)


func load_config(path: String) -> void:
	_config = JSON.parse_string(FileAccess.get_file_as_string(path))
	for bus in _config.get("buses", {}):
		for category in _config["buses"][bus]:
			_bus_of_category[category] = bus
	var catalog_path := ProjectSettings.globalize_path("res://").path_join(_config["catalog"]).simplify_path()
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
		var variation: int = step.get("variation", _pick_variation(step["group"], files.size()))
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


func _stream(path: String) -> AudioStream:
	if not _streams.has(path):
		var stream: AudioStream = AudioStreamOggVorbis.load_from_file(path) if path.ends_with(".ogg") else null
		if stream == null:
			push_warning("AudioManager: could not load %s" % path)
		_streams[path] = stream
	return _streams[path]
