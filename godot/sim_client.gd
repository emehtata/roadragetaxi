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
			connection_changed.emit(false)
		_retry_in -= delta
		if _retry_in <= 0.0:
			_retry_in = 1.0
			_peer = StreamPeerTCP.new()
			_peer.connect_to_host(host, port)


func _drain_lines() -> void:
	var start := 0
	while true:
		var newline := _buffer.find(10, start)
		if newline < 0:
			break
		var started := Time.get_ticks_usec()
		var message = JSON.parse_string(_buffer.slice(start, newline).get_string_from_utf8())
		parse_usec = Time.get_ticks_usec() - started
		start = newline + 1
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
				chunk_unloaded.emit(message["chunk_id"])
	if start > 0:
		_buffer = _buffer.slice(start)


## A player command: the simulation validates and applies it.
func send_command(command: Dictionary) -> void:
	if not connected:
		return
	_seq += 1
	_peer.put_data(command_line(command, _seq, player_id).to_utf8_buffer())


static func command_line(command: Dictionary, seq: int, player: String) -> String:
	return JSON.stringify({"type": "command", "version": PROTOCOL_VERSION, "seq": seq, "player_id": player, "command": command}) + "\n"
