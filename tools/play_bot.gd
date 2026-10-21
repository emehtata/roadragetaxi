## Play-test bot: the real Godot client (startup.tscn --skip-menu) played by key
## events from the shown state - F/E to board and start, P+1 to take a fare,
## arrows to follow the navigation route, R when stuck 40 s.
##
##     make play-bot [BOT_MINUTES=10] [BOT_OUT=/tmp/rrt-play-bot]
##
## Prints "BOT {json}" lines (state changes, notices, stuck, position jumps,
## 30 s status) and saves screenshots every 60 s and when stuck to BOT_OUT.
## Diagnostic only; the server decides everything as for a player.
extends SceneTree

var out := ""
var minutes := 10.0
var game = null
var t0 := 0.0
var held := {}
var last_state := ""
var prog := Vector3.ZERO  # time, x, y of the last real progress
var reverse_until := 0.0
var last_pos := Vector2.INF
var next_shot := 20.0
var next_status := 0.0
var next_phone := 0.0
var fares := 0
var last_notice := ""
var slow_frames := 0
var last_err := 0.0


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	out = args[args.find("--bot-out") + 1] if "--bot-out" in args else "/tmp/rrt-play-bot"
	minutes = float(args[args.find("--bot-minutes") + 1]) if "--bot-minutes" in args else 10.0
	DirAccess.make_dir_recursive_absolute(out)
	var shell = load("res://startup.tscn").instantiate()
	root.add_child(shell)
	call_deferred("_find_game", shell)


func _find_game(shell) -> void:
	game = shell.get("_game")
	t0 = Time.get_ticks_msec() / 1000.0


func ev(kind: String, data := {}) -> void:
	data["t"] = snappedf(now(), 0.1)
	data["kind"] = kind
	print("BOT " + JSON.stringify(data))


func now() -> float:
	return Time.get_ticks_msec() / 1000.0 - t0


func key(code: Key, down: bool) -> void:
	if held.get(code, false) == down:
		return
	held[code] = down
	var e := InputEventKey.new()
	e.keycode = code
	e.physical_keycode = code
	e.pressed = down
	Input.parse_input_event(e)


func tap(code: Key) -> void:
	key(code, true)
	key(code, false)


func shot(name: String) -> void:
	var path := out.path_join("%s_%04d.png" % [name, int(now())])
	root.get_viewport().get_texture().get_image().save_png(path)
	ev("screenshot", {"path": path})


func _process(delta: float) -> bool:
	if game == null:
		return false
	var t := now()
	if t > minutes * 60.0:
		ev("end", {"fares": fares, "slow_frames": slow_frames})
		shot("end")
		return true
	if delta > 0.1 and t > 30.0:
		slow_frames += 1
		if delta > 0.3:
			ev("slow_frame", {"ms": int(delta * 1000)})
	var s: Dictionary = game.entities.shown_state()
	if s.is_empty() or not s.has("player"):
		return false
	var p: Dictionary = s["player"]
	var pos := Vector2(p["x"], p["y"])
	var heading: float = p["heading"]
	var speed: float = p["speed"]
	var taxi: Dictionary = s.get("taxi", {})
	var phone: Dictionary = s.get("phone", {})
	var pts: Array = s.get("navigation", {}).get("points", [])
	var state: String = str(taxi.get("state", ""))

	if last_pos != Vector2.INF and pos.distance_to(last_pos) > 15.0:
		ev("position_jump", {"m": snappedf(pos.distance_to(last_pos), 0.1), "x": int(pos.x), "y": int(pos.y)})
	last_pos = pos
	var notice := str(taxi.get("notification_msg", ""))
	if notice != last_notice and notice != "":
		ev("notice", {"msg": notice})
	last_notice = notice
	if state != last_state:
		ev("state", {"state": state, "score": taxi.get("total_score"), "completed": taxi.get("completed_fares")})
		if last_state == "DROPOFF":
			fares += 1
		last_state = state
	if t >= next_shot:
		next_shot = t + 60.0
		shot("play")
	if t >= next_status:
		next_status = t + 30.0
		ev("status", {"x": int(pos.x), "y": int(pos.y), "speed": snappedf(speed, 0.1), "state": state,
			"route_pts": pts.size(), "fps": Engine.get_frames_per_second(), "fares": fares,
			"busy": phone.get("busy"), "items": phone.get("items", []).size(), "loading": s.get("map_loading", "")})

	# phone: open it and take the first row
	if not phone.get("busy", true) and phone.get("items", []).size() > 0 and t >= next_phone:
		next_phone = t + 3.0
		if not game.phone.is_open:
			tap(KEY_P)
		tap(KEY_1)
		ev("accept_try", {"items": phone["items"].size()})
	elif phone.get("busy", false) and game.phone.is_open and t >= next_phone:
		next_phone = t + 3.0
		tap(KEY_P)  # close: the navigation phone must not hide the map

	var up := false
	var down := false
	var left := false
	var right := false
	var target_dist := 1e9
	if pts.size() > 0:
		var last = pts[pts.size() - 1]
		target_dist = pos.distance_to(Vector2(last[0], last[1]))
	if s.get("on_foot", false):
		var me: Dictionary = s.get("player_pedestrian", {})
		var mp := Vector2(me.get("x", pos.x), me.get("y", pos.y))
		var err := wrapf(mp.angle_to_point(pos) - float(me.get("heading", 0.0)), -PI, PI)
		left = err > 0.2
		right = err < -0.2
		up = absf(err) < 0.8 and mp.distance_to(pos) > 2.5
		if int(t * 2.0) % 2 == 0:
			tap(KEY_F)
		prog = Vector3(t, pos.x, pos.y)
	elif not p.get("engine_on", true):
		if int(t * 2.0) % 4 == 0:
			tap(KEY_E)
		prog = Vector3(t, pos.x, pos.y)
	elif state == "WALKING" or (pts.size() > 0 and target_dist < 15.0):
		down = speed > 0.3
		if absf(speed) < 0.5 and int(t * 2.0) % 4 == 0:
			tap(KEY_F)
	elif t < reverse_until:
		down = true
		left = last_err < 0.0  # reversing: steer away to swing the nose towards the route
		right = not left
	elif pts.size() > 1:
		var best := 0
		var best_d := INF
		for i in pts.size() - 1:
			var d := pos.distance_squared_to(Vector2(pts[i][0], pts[i][1]))
			if d < best_d:
				best_d = d
				best = i
		var look := 12.0 + absf(speed) * 0.6
		var acc := 0.0
		var aim := Vector2(pts[pts.size() - 1][0], pts[pts.size() - 1][1])
		for i in range(best, pts.size() - 1):
			var a := Vector2(pts[i][0], pts[i][1])
			var b := Vector2(pts[i + 1][0], pts[i + 1][1])
			acc += a.distance_to(b)
			if acc >= look:
				aim = b
				break
		var err := wrapf(atan2(aim.y - pos.y, aim.x - pos.x) - heading, -PI, PI)
		last_err = err
		left = err > 0.06
		right = err < -0.06
		var want := maxf(4.0, 14.0 * (1.0 - minf(1.0, absf(err) / 1.2)))
		if target_dist < 60.0:
			want = minf(want, 6.0)
		up = speed < want
		down = speed > want + 3.0
	else:
		down = speed > 0.3

	if pos.distance_to(Vector2(prog.y, prog.z)) > 5.0:
		prog = Vector3(t, pos.x, pos.y)
	elif up and t - prog.x > 8.0 and t >= reverse_until:
		ev("stuck", {"x": int(pos.x), "y": int(pos.y), "s": int(t - prog.x), "state": state})
		shot("stuck")
		if t - prog.x > 40.0:
			tap(KEY_R)
			ev("respawn", {})
			prog = Vector3(t, pos.x, pos.y)
		else:
			reverse_until = t + 4.0
	key(KEY_UP, up)
	key(KEY_DOWN, down)
	key(KEY_LEFT, left)
	key(KEY_RIGHT, right)
	return false
