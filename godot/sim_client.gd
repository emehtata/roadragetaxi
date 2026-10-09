## Connection to the Python simulation server: loopback TCP, one JSON
## message per line (src/theroadragetrip/protocol.py). Receives the one-off
## "world" header, map "chunk"/"chunk_unload" messages and every tick's
## "state"; sends "command" messages on behalf of `player_id`.
## Reconnects every second while the server is not there.
class_name SimClient
extends Node

signal world_received(message: Dictionary)
signal state_received(message: Dictionary)
signal chunk_received(message: Dictionary)
signal chunk_unloaded(chunk_id: String)
signal connection_changed(connected: bool)

const PROTOCOL_VERSION := 1

var host := "127.0.0.1"
var port := 8765
var player_id := "local_player"  # the world message says which player this client is
var connected := false
var parse_usec := 0  # time spent decoding the last message (performance readout)

var _peer := StreamPeerTCP.new()
var _buffer := PackedByteArray()
var _retry_in := 0.0
var _seq := 0
var _last_command: Dictionary = {}
var paused := false  # the phone or the pause menu is open: the simulation waits (main()'s dt = 0)
var _parsing := {}  # chunk_id -> worker task parsing it (godot-18: a big chunk took up to ~18 ms on the main thread)
var _cancelled := {}  # chunk ids unloaded while still being parsed
const CHUNK_PREFIX := "{\"type\":\"chunk\","  # protocol.encode: compact JSON, "type" first


func _process(delta: float) -> void:
	_peer.poll()
	var status := _peer.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTED:
		if not connected:
			connected = true
			connection_changed.emit(true)
		var available := _peer.get_available_bytes()
		if available > 0:
			var result := _peer.get_data(available)
			if result[0] == OK:
				_buffer.append_array(result[1])
				_drain_lines()
	elif status == StreamPeerTCP.STATUS_NONE or status == StreamPeerTCP.STATUS_ERROR:
		if connected:
			connected = false
			_buffer.clear()
			for chunk_id in _parsing:  # chunks still being parsed belong to the lost connection
				_cancelled[chunk_id] = true
			connection_changed.emit(false)
		_retry_in -= delta
		if _retry_in <= 0.0:
			_retry_in = 1.0
			_peer = StreamPeerTCP.new()
			_peer.connect_to_host(host, port)


func _parse_chunk(line: String) -> void:
	var at := line.find("\"chunk_id\":\"") + 12
	var chunk_id := line.substr(at, line.find("\"", at) - at)
	_cancelled.erase(chunk_id)
	_parsing[chunk_id] = WorkerThreadPool.add_task(func():
		var started := Time.get_ticks_usec()
		var message = JSON.parse_string(line)
		_chunk_parsed.call_deferred(chunk_id, message, Time.get_ticks_usec() - started))


func _chunk_parsed(chunk_id: String, message, usec: int) -> void:
	if _parsing.has(chunk_id):
		WorkerThreadPool.wait_for_task_completion(_parsing[chunk_id])
		_parsing.erase(chunk_id)
	preload("res://perf.gd").add("parse_chunk", usec)
	if _cancelled.has(chunk_id):
		_cancelled.erase(chunk_id)
		return
	if typeof(message) != TYPE_DICTIONARY or message.get("version") != PROTOCOL_VERSION:
		push_warning("Ignoring malformed chunk from the simulation")
		return
	chunk_received.emit(message)


func _drain_lines() -> void:
	var start := 0
	while true:
		var newline := _buffer.find(10, start)
		if newline < 0:
			break
		var started := Time.get_ticks_usec()
		var line := _buffer.slice(start, newline).get_string_from_utf8()
		if line.begins_with(CHUNK_PREFIX):  # parsed on a worker thread, delivered when done
			_parse_chunk(line)
			start = newline + 1
			continue
		var message = JSON.parse_string(line)
		parse_usec = Time.get_ticks_usec() - started
		start = newline + 1
		if typeof(message) == TYPE_DICTIONARY:
			preload("res://perf.gd").add("parse_" + str(message.get("type", "?")), parse_usec)
		if typeof(message) != TYPE_DICTIONARY or message.get("version") != PROTOCOL_VERSION:
			push_warning("Ignoring malformed message from the simulation")
			continue
		match message.get("type"):
			"world":
				world_received.emit(message)
			"state":
				state_received.emit(message)
			"chunk":
				chunk_received.emit(message)
			"chunk_unload":
				if _parsing.has(message["chunk_id"]):
					_cancelled[message["chunk_id"]] = true  # never shown: drop it when its parse is done
				chunk_unloaded.emit(message["chunk_id"])
	if start > 0:
		_buffer = _buffer.slice(start)


## Hang up (tests): the client notices on the next frame, like a lost
## server, and reconnects a second later.
func drop_connection() -> void:
	_peer.disconnect_from_host()


## A player command: the simulation validates and applies it.
func send_command(command: Dictionary) -> void:
	_last_command = command
	if not connected:
		return
	_seq += 1
	_peer.put_data(command_line(command, _seq, player_id, {}, "", paused).to_utf8_buffer())


## A phone answer, riding on a command with the current controls (the
## simulation applies it once). False without a connection.
func send_phone(action: String, item_id: String, request_id: int) -> bool:
	if not connected:
		return false
	_seq += 1
	var phone := {"action": action, "item_id": item_id, "request_id": request_id}
	_peer.put_data(command_line(_last_command, _seq, player_id, phone, "", paused).to_utf8_buffer())
	return true


## F12: the server writes Pygame's debug JSON (its world) at `path`.
func send_debug_snapshot(path: String) -> bool:
	if not connected:
		return false
	_seq += 1
	_peer.put_data(command_line(_last_command, _seq, player_id, {}, path, paused).to_utf8_buffer())
	return true


static func command_line(command: Dictionary, seq: int, player: String, phone: Dictionary = {}, debug_snapshot := "", paused := false) -> String:
	var message := {"type": "command", "version": PROTOCOL_VERSION, "seq": seq, "player_id": player, "command": command}
	if not phone.is_empty():
		message["phone"] = phone
	if debug_snapshot != "":
		message["debug_snapshot"] = debug_snapshot
	if paused:
		message["paused"] = true
	return JSON.stringify(message) + "\n"
