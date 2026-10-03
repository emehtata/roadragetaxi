## Client unit tests, no server needed:
##   godot --headless --path godot --script res://tests/run_tests.gd
## Exits 1 if any check fails.
extends SceneTree

const Hud := preload("res://hud.gd")
const MapLayer := preload("res://map_layer.gd")

var _failures := 0
var _checks := 0


func check(ok: bool, what: String) -> void:
	_checks += 1
	if not ok:
		_failures += 1
		printerr("FAIL: ", what)


func _state(x: float, heading: float = 0.0, events: Array = []) -> Dictionary:
	return {"player": {"x": x, "y": 0.0, "heading": heading}, "npcs": [], "events": events}


var _ran := false


func _process(_delta: float) -> bool:  # first frame: the tree is live, so nodes get _ready
	if _ran:
		return false
	_ran = true
	test_interpolation()
	test_audio()
	test_hud()
	test_map_chunks()
	test_commands_carry_the_player_id()
	print("%d checks, %d failed" % [_checks, _failures])
	quit(1 if _failures > 0 else 0)
	return false


func test_interpolation() -> void:
	var buffer := StateBuffer.new()
	buffer.delay = 0.1
	check(buffer.sample(0.0).is_empty(), "nothing received: an empty sample, no crash")
	# States 1/30 s apart, each arriving the moment it was made (local == server time).
	check(buffer.push(1, 1.0, _state(0.0), 1.0), "first state accepted")
	check(buffer.push(2, 1.0 + 1.0 / 30.0, _state(10.0), 1.0 + 1.0 / 30.0), "next state accepted")
	var halfway := buffer.sample(1.0 + 1.0 / 60.0 + 0.1)  # render time halfway between them
	check(is_equal_approx(StateBuffer.blend(halfway["a"]["player"], halfway["b"]["player"], halfway["t"]).x, 5.0), "two states interpolate")

	check(not buffer.push(2, 1.0 + 1.0 / 30.0, _state(99.0), 1.1), "a duplicate state is dropped")
	check(not buffer.push(1, 1.0, _state(99.0), 1.1), "an older state is dropped")
	check(buffer.size() == 2, "the buffer is unchanged by them")

	var late := buffer.sample(5.0)  # long after the newest state: hold it, don't extrapolate
	check(late["t"] == 0.0 and late["a"]["player"]["x"] == 10.0, "a missing state holds the newest one")
	check(buffer.underruns == 1, "and counts an underrun")

	# Heading across the +-pi seam turns the short way.
	var near_pi := 3.1
	var heading := lerp_angle(near_pi, -near_pi, 0.5)
	check(absf(absf(heading) - PI) < 0.01, "heading interpolation wraps (got %f)" % heading)
	var p := StateBuffer.blend({"x": 0.0, "y": 0.0, "heading": near_pi}, {"x": 0.0, "y": 0.0, "heading": -near_pi}, 0.5)
	check(absf(absf(p.z) - PI) < 0.01, "entity blend uses the short way round")

	# Events: handed out once, when the render time reaches their state.
	var events := StateBuffer.new()
	events.delay = 0.1
	events.push(1, 10.0, _state(0.0, 0.0, [{"type": "sound", "group": "vehicle.door_close"}]), 10.0)
	check(events.take_due_events(10.05).is_empty(), "an event waits for the picture to reach its state")
	check(events.take_due_events(10.2).size() == 1, "then it is due")
	check(events.take_due_events(10.3).is_empty(), "and only once")
	events.push(1, 10.0, _state(0.0, 0.0, [{"type": "sound", "group": "vehicle.door_close"}]), 10.4)
	check(events.take_due_events(11.0).is_empty(), "a re-sent state doesn't replay its events")


func test_audio() -> void:
	var audio := AudioManager.new()
	root.add_child(audio)  # _ready loads the config and the game's catalog
	var door := audio.resolve({"type": "sound", "group": "vehicle.door_close"})
	check(door.size() == 1 and door[0]["file"].ends_with(".ogg") and FileAccess.file_exists(door[0]["file"]), "a sound event resolves to an existing file")
	check(door[0].has("at"), "the taxi's own sounds come from the taxi")
	var arrived := audio.resolve({"type": "train_arrived", "at": [100.0, 200.0], "station": "Oulu"})
	check(arrived.size() == 2 and arrived[0]["group"] == "railway.train_brakes" and arrived[0]["at"] == Vector2(100, 200), "train_arrived maps to brakes + doors, placed")
	check(arrived[0]["range"][1] == 150.0, "with the game's hearing range")
	check(audio.bus_for("ui.accept") == "UI" and audio.bus_for("weather.rain") == "Environment", "categories map to buses")
	check(audio.bus_for("ambient.city_day") == "Environment", "the day bed is environment")
	var opened := audio.resolve({"type": "sound", "group": "vehicle.door_open"})
	check(opened.size() == 1 and opened[0]["file"].ends_with(".ogg") and FileAccess.file_exists(opened[0]["file"]), "getting in: the door-open sound exists as OGG")
	check(audio.resolve({"type": "something_new"}).is_empty() and audio.unhandled.get("something_new") == 1, "an unknown event is noted, not played")
	audio.handle_event({"type": "something_new"})  # no crash
	var unloadable: Array = []
	for path in audio.all_files():
		var stream := audio.load_file(path)
		if stream == null or stream.get_length() <= 0.0:
			unloadable.append(path)
	check(audio.all_files().size() >= 120 and unloadable.is_empty(), "Godot loads every catalog sound (%d files; failed: %s)" % [audio.all_files().size(), unloadable])
	var picks: Array = []
	for i in 30:
		picks.append(audio.resolve({"type": "sound", "group": "vehicle.door_open"})[0]["file"])
	var repeats := 0
	for i in range(1, picks.size()):
		repeats += int(picks[i] == picks[i - 1])
	var distinct := {}
	for pick in picks:
		distinct[pick] = true
	check(repeats == 0 and distinct.size() == 3, "door-open variations: all used, never the same twice in a row")
	var before := audio.played
	audio.handle_event({"type": "sound", "group": "vehicle.door_close"})
	check(audio.played == before + 1, "one event plays one sound")
	var beds: Array = []
	for day in 3:  # day, night (loop stopped), day ...
		audio.set_loop("city_day", 0.5)
		audio.set_loop("city_day", 0.4)  # an update, not a restart
		beds.append(audio.loop_files["city_day"])
		audio.set_loop("city_day", 0.0)
	check(audio.loop_starts["city_day"] == 3 and beds[0] != beds[1] and beds[2] == beds[0], "the day bed alternates its two variations on each restart")
	audio.set_loop("engine", 0.5, 1.2)
	check(audio.loop_playing("engine"), "a loop starts")
	audio.set_loop("engine", 0.0)
	check(not audio.loop_playing("engine"), "and stops at volume 0")
	audio.set_bus_volume("Game", 0.5)
	check(is_equal_approx(AudioServer.get_bus_volume_db(AudioServer.get_bus_index("Game")), linear_to_db(0.5)), "bus volume")
	audio.free()


func test_hud() -> void:
	var text := Hud.values({
		"on_foot": false, "game_time_seconds": 18.0 * 3600.0 + 5.0 * 60.0,
		"player": {"speed": 13.9, "engine_on": true},
		"weather": {"weather_type": "rain", "wetness": 0.4},
		"taxi": {"balance_cents": 12345, "state": "DROPOFF", "completed_fares": 2, "notification_msg": "Fare paid", "notification_timer": 2.0,
			"current_passenger": {"name": "Aino", "pickup": {"address": "Kauppurienkatu 1"}, "dropoff": {"address": "Rautatientori"}}},
	})
	check(text["money"] == "123.45 €", "money (%s)" % text["money"])
	check(text["speed"] == "50 km/h", "speed (%s)" % text["speed"])
	check(text["clock"] == "18:05", "clock (%s)" % text["clock"])
	check(text["weather"] == "Rain, road 40% wet", "weather (%s)" % text["weather"])
	check(text["fare"] == "Drive Aino to Rautatientori", "fare (%s)" % text["fare"])
	check(text["notice"] == "Fare paid", "notice")
	var empty := Hud.values({})
	check(empty["money"] == "– €" and empty["clock"] == "--:--" and empty["speed"] == "on foot", "missing fields show placeholders")
	check(Hud.values({"taxi": {"current_passenger": null}})["fare"].begins_with("No fare"), "no passenger")


func test_map_chunks() -> void:
	var map := MapLayer.new()
	root.add_child(map)
	var chunk := {"chunk_id": "1_2", "roads": [{"points": [[0, 0], [10, 0]], "half_width_m": 3.0, "drivable": true}], "railways": [], "waters": [], "buildings": []}
	check(map.add_chunk(chunk), "a chunk loads")
	check(not map.add_chunk(chunk) and map.chunk_count() == 1, "the same chunk isn't loaded twice")
	check(map.add_chunk({"chunk_id": "1_3"}) and map.chunk_count() == 2, "a new area's chunk is added")
	check(map.remove_chunk("1_2") and not map.has_chunk("1_2") and map.chunk_count() == 1, "a distant chunk is removed")
	check(not map.remove_chunk("9_9"), "removing an unknown chunk is harmless")
	map.free()


func test_commands_carry_the_player_id() -> void:
	var line := SimClient.command_line({"throttle": 1.0}, 7, "local_player")
	var message: Dictionary = JSON.parse_string(line)
	check(line.ends_with("\n") and message["type"] == "command" and message["player_id"] == "local_player" and message["seq"] == 7, "commands carry the player id")
