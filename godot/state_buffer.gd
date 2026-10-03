## Received simulation states on the server's timeline, and the pair to
## draw between at any moment.
##
## Rendering runs `delay` seconds behind the newest state, so the state
## after the render time has normally already arrived. Movement is then
## blended between two known states instead of snapping to whatever came in
## last. Only interpolation: past the newest state the picture holds still
## (no prediction; Python stays authoritative).
##
## Why 0.1 s by default: states come every 1/30 s (33 ms). Interpolating
## needs one interval of headroom, and two more absorb arrival jitter (a
## late or bunched state). Set it with --interp-delay-ms.
class_name StateBuffer
extends RefCounted

const MAX_STATES := 16
const LATE_FOLLOW := 0.5
const EARLY_FOLLOW := 0.05
const CLOCK_SNAP_S := 0.25  # a jump bigger than this (server restart, long stall) resets the clock

var delay := 0.1
var underruns := 0  # frames the render time was past the newest state
# Diagnostics (selftest report): an underrun episode is a run of such
# frames; the longest wait between two arriving states says whether one was
# late (a server tick spike or a stalled client frame), not just slow frames.
var underrun_episodes := 0
var longest_underrun_s := 0.0
var max_arrival_gap_s := 0.0
var _underrun_since := -1.0
var _last_arrival := -1.0

var _states: Array = []  # [{"tick", "time", "state"}], oldest first
var _events: Array = []  # [{"time", "events"}] not yet presented
var _offset := 0.0  # server time minus local time, smoothed
var _has_clock := false


## Zero the diagnostics (measure a steady stretch, not the connect burst).
func reset_diagnostics() -> void:
	underruns = 0
	underrun_episodes = 0
	longest_underrun_s = 0.0
	max_arrival_gap_s = 0.0
	_underrun_since = -1.0


func clear() -> void:
	_last_arrival = -1.0
	_states.clear()
	_events.clear()
	_has_clock = false


func size() -> int:
	return _states.size()


## Add a state that arrived at `local_now` (seconds). Returns false for a
## duplicate or out-of-order tick, which is dropped untouched.
func push(tick: int, server_time: float, state: Dictionary, local_now: float) -> bool:
	if not _states.is_empty() and tick <= _states[-1]["tick"]:
		return false
	if _last_arrival >= 0.0:
		max_arrival_gap_s = maxf(max_arrival_gap_s, local_now - _last_arrival)
	_last_arrival = local_now
	_states.append({"tick": tick, "time": server_time, "state": state})
	if _states.size() > MAX_STATES:
		_states.pop_front()
	var events: Array = state.get("events", [])
	if not events.is_empty():
		_events.append({"time": server_time, "events": events})
	# Server-local clock offset, smoothed so arrival jitter doesn't shake the
	# render time - but asymmetrically: a state later than expected pulls
	# the offset back fast, an early one only slowly. server_time is
	# simulated time, and a server tick that runs late is never caught up,
	# so the server clock falls behind for good; following that slowly let
	# the render time overtake the newest state for a frame or two
	# (godot-05 underrun investigation).
	var sample := server_time - local_now
	if not _has_clock or absf(sample - _offset) > CLOCK_SNAP_S:
		_offset = sample
		_has_clock = true
	else:
		_offset += (sample - _offset) * (LATE_FOLLOW if sample < _offset else EARLY_FOLLOW)
	return true


func render_time(local_now: float) -> float:
	return local_now + _offset - delay


## The two states around the render time: {"a", "b", "t"}, with discrete
## values taken from "a" and positions blended by "t" in [0, 1]. Empty when
## nothing has arrived.
func sample(local_now: float) -> Dictionary:
	if _states.is_empty():
		return {}
	var at := render_time(local_now)
	if at < _states[-1]["time"]:
		_underrun_since = -1.0
	if at >= _states[-1]["time"]:
		if _states.size() > 1 and at > _states[-1]["time"]:
			underruns += 1
			if _underrun_since < 0.0:
				_underrun_since = local_now
				underrun_episodes += 1
			longest_underrun_s = maxf(longest_underrun_s, local_now - _underrun_since)
		return {"a": _states[-1]["state"], "b": _states[-1]["state"], "t": 0.0}
	if at <= _states[0]["time"]:
		return {"a": _states[0]["state"], "b": _states[0]["state"], "t": 0.0}
	for i in range(_states.size() - 1, 0, -1):
		var earlier: Dictionary = _states[i - 1]
		if earlier["time"] <= at:
			var later: Dictionary = _states[i]
			var span: float = later["time"] - earlier["time"]
			return {"a": earlier["state"], "b": later["state"], "t": clampf((at - earlier["time"]) / span, 0.0, 1.0)}
	return {"a": _states[0]["state"], "b": _states[0]["state"], "t": 0.0}


## Events whose state the render time has reached, each handed out once,
## so sounds line up with what's on screen.
func take_due_events(local_now: float) -> Array:
	var at := render_time(local_now)
	var due: Array = []
	while not _events.is_empty() and _events[0]["time"] <= at:
		due.append_array(_events.pop_front()["events"])
	return due


static func blend(a: Dictionary, b: Dictionary, t: float) -> Vector3:
	## x, y and heading (shortest way round) of one entity: z is the heading.
	return Vector3(lerpf(a["x"], b["x"], t), lerpf(a["y"], b["y"], t), lerp_angle(a.get("heading", 0.0), b.get("heading", 0.0), t))
