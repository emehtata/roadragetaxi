## Lightweight frame-time and section accounting (godot-18). Scripts add
## the time a section took (Perf.add("labels_draw", usec)); main.gd feeds
## frame times. F3 shows a summary; --bench prints the whole report as JSON.
## Costs a couple of integer additions per section when nobody looks.
extends RefCounted

static var sections := {}  # name -> [count, total usec, max usec]
static var frames := PackedFloat32Array()  # frame times, ms (bench: all; else the last 600)
static var keep_all := false
static var counters := {}  # name -> value (gauges: chunks, buildings, windows...)


static func add(name: String, usec: int) -> void:
	var s: Array = sections.get(name, [0, 0, 0])
	s[0] += 1
	s[1] += usec
	s[2] = maxi(s[2], usec)
	sections[name] = s


static func frame(ms: float) -> void:
	frames.append(ms)
	if not keep_all and frames.size() > 600:
		frames = frames.slice(frames.size() - 600)


static func reset() -> void:
	sections.clear()
	frames.clear()


## Frame-time distribution: average, percentiles, worst; lows as FPS.
static func summary(times: PackedFloat32Array = frames) -> Dictionary:
	if times.is_empty():
		return {}
	var sorted := times.duplicate()
	sorted.sort()
	var n := sorted.size()
	var total := 0.0
	for t in sorted:
		total += t
	var pct := func(p: float) -> float: return sorted[clampi(int(ceil(p * n)) - 1, 0, n - 1)]
	# "1% low": the average FPS of the slowest 1 % of frames.
	var low := func(fraction: float) -> float:
		var k := maxi(1, int(n * fraction))
		var worst := 0.0
		for i in k:
			worst += sorted[n - 1 - i]
		return 1000.0 / (worst / k)
	return {"frames": n, "avg_ms": total / n, "avg_fps": 1000.0 / (total / n), "p50_ms": pct.call(0.5), "p95_ms": pct.call(0.95), "p99_ms": pct.call(0.99),
		"worst_ms": sorted[n - 1], "low_1pct_fps": low.call(0.01), "low_01pct_fps": low.call(0.001),
		"over_33ms": times.size() - Array(times).filter(func(t): return t <= 33.3).size(),
		"over_66ms": times.size() - Array(times).filter(func(t): return t <= 66.7).size()}


static func report() -> Dictionary:
	var out := {"frames": summary(), "sections": {}, "counters": counters.duplicate()}
	for name in sections:
		var s: Array = sections[name]
		out["sections"][name] = {"count": s[0], "avg_ms": s[1] / 1000.0 / maxi(1, s[0]), "max_ms": s[2] / 1000.0, "total_ms": s[1] / 1000.0}
	return out
