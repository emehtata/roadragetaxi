## --audiotest [PATH]: a scripted, windowed run with the real audio driver.
## The Master bus is recorded (AudioEffectRecord: exactly what the mixer
## hands the audio driver), one WAV per phase into directory PATH (default
## user://audiotest), so tools/analyse_godot_audio.py can measure each phase
## on its own - one long recording drifted against the phase clock.
## It drives through the simulation like a player would; day/night and
## rain are forced locally as presentation overrides only.
extends Node

const PHASE_S := 3.0

var main: Node
var _phase := -1
var _phase_time := 0.0
var _events_seen := 0
var _log: Array = []
var out_path := "user://audiotest"
var _record := AudioEffectRecord.new()
var _report_extra := {}
var _door_before := 0
var _repeats_left := 0

# Each phase isolates what it checks: the other bus is muted.
var _phases := [
	"all_muted",          # Game and Environment at 0: silence (nothing bypasses the buses)
	"day_ambience",       # Environment only, day: city traffic bed
	"night_ambience",     # crossfade to the night bed
	"rain",               # rain on top of the night bed
	"enter_taxi",         # Game only from here, engine off: F -> the door-open sound alone
	"engine_start",       # E: engine start, then the engine loop
	"engine_idle",
	"engine_drive",       # throttle: pitch rises with speed
	"engine_brake",
	"engine_off",         # E: the engine loop must stop -> silence
	"train_movement",     # the train rumble loop, 40 m away
	"event_left",         # train_arrived 60 m left of the camera
	"event_right",        # ... and 60 m right
	"repeated_events",    # the same door event three times: three one-shots, all freed
	"exit_taxi",
	"master_muted",       # Master at 0, everything else on: silence
	"disconnect",         # the simulation goes away: every loop stops
]


func _process(delta: float) -> void:
	if main.entities.shown_state().is_empty() and _phase < _phases.find("disconnect"):
		return
	if _phase == _phases.find("disconnect") and _phase_time >= 0.6:
		# Before the client's 1 s reconnect (which rightly brings the sound back).
		_report_extra["loops_playing_after_disconnect"] = main.audio.loops_playing()
		_report_extra["one_shots_alive_after_disconnect"] = main.audio.one_shots_alive()
		_phase = _phases.size() - 1
		_next_phase()
		return
	if _repeats_left > 0 and _phase_time >= 0.8 * (3 - _repeats_left):
		_repeats_left -= 1
		main.audio.handle_event({"type": "sound", "group": "vehicle.door_open"})
	_phase_time += delta
	if _phase == -1 or _phase_time >= PHASE_S:
		_next_phase()
	_drive()


func _next_phase() -> void:
	_phase += 1
	_phase_time = 0.0
	if _phase >= _phases.size():
		_finish()
		return
	_save_recording()
	var name: String = _phases[_phase]
	var audio: AudioManager = main.audio
	if _phase == 0:
		DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(out_path))
		AudioServer.add_bus_effect(0, _record)  # Master
	_record.set_recording_active(true)
	var player: Vector2 = audio.player_at
	match name:
		"all_muted":
			main.override_night = 0.0
			main.override_rain = 0.0
			audio.set_bus_volume("Game", 0.0)
			audio.set_bus_volume("Environment", 0.0)
		"day_ambience":
			audio.set_bus_volume("Environment", 1.0)
		"night_ambience":
			main.override_night = 1.0
		"rain":
			main.override_rain = 0.6
		"enter_taxi":
			audio.set_bus_volume("Environment", 0.0)
			audio.set_bus_volume("Game", 1.0)
			main._engine_on = false
			_door_before = audio.played_groups.get("vehicle.door_open", 0)
			main.send({"interact": true})
		"engine_start":
			_report_extra["door_open_on_entry"] = audio.played_groups.get("vehicle.door_open", 0) - _door_before
			main._engine_on = true
		"engine_off":
			main._engine_on = false
		"train_movement":
			main.override_train_at = player + Vector2(40.0, 0.0)
		"event_left":
			main.override_train_at = Vector2.INF
			audio.handle_event({"type": "train_arrived", "at": [player.x - 60.0, player.y]})
		"event_right":
			audio.handle_event({"type": "train_arrived", "at": [player.x + 60.0, player.y]})
		"repeated_events":
			_door_before = audio.played_groups.get("vehicle.door_open", 0)
			_repeats_left = 3
		"exit_taxi":
			_report_extra["repeated_door_plays"] = audio.played_groups.get("vehicle.door_open", 0) - _door_before
			main.send({"interact": true})
		"master_muted":
			audio.set_bus_volume("Environment", 1.0)
			audio.set_bus_volume("Master", 0.0)
		"disconnect":
			audio.set_bus_volume("Master", 1.0)
			main.sim.drop_connection()
	var state: Dictionary = main.entities.shown_state()
	var entry := {"phase": name, "wall": Time.get_unix_time_from_system(),
		"on_foot": state.get("on_foot"), "engine_on": state.get("player", {}).get("engine_on"),
		"speed": snappedf(state.get("player", {}).get("speed", 0.0), 0.1),
		"file": ProjectSettings.globalize_path(out_path).path_join("%02d_%s.wav" % [_phase, name])}
	_log.append(entry)
	print("AUDIOTEST phase ", JSON.stringify(entry))


func _drive() -> void:
	var name: String = _phases[_phase] if _phase < _phases.size() else ""
	var controls := {"throttle": 1.0 if name == "engine_drive" else 0.0, "brake": 1.0 if name == "engine_brake" else 0.0,
		"steer_left": 0.0, "steer_right": 0.0, "forward": 0.0, "turn": 0.0, "sprint": false}
	if name != "enter_taxi" and name != "exit_taxi" or _phase_time > 0.1:
		main.send(controls)


## The phase that just ended, to its own file.
func _save_recording() -> void:
	if _log.is_empty() or not _record.is_recording_active():
		return
	_record.set_recording_active(false)
	var recording := _record.get_recording()
	if recording != null:
		recording.save_to_wav(_log[-1]["file"])


func _finish() -> void:
	_save_recording()
	var audio: AudioManager = main.audio

	audio.set_bus_volume("Master", 1.0)
	var report := {"phases": _log, "loop_starts": audio.loop_starts, "played_groups": audio.played_groups,
		"unhandled": audio.unhandled, "one_shots_alive": audio.one_shots_alive(),
		"engine_playing_at_end": audio.loop_playing("engine"),
		"events_presented": main.events_presented, "sounds_played": audio.played,
		"audio_driver": AudioServer.get_driver_name(), "mix_rate": AudioServer.get_mix_rate()}
	report.merge(_report_extra)
	print("AUDIOTEST report ", JSON.stringify(report))
	get_tree().quit()
