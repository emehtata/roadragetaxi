## Run: godot --headless --path godot --script res://tests/vehicle_vertical.gd
## docs/specs/vehicle-airborne-physics.md criteria 1-6.
extends SceneTree

var failures := 0


func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		printerr("FAIL: ", message)


func _initialize() -> void:
	test_crest_airtime_at_speed()
	test_airtime_independent_of_frame_rate()
	test_no_airtime_low_speed()
	test_flat_unchanged()
	test_seam_no_bounce()
	test_bridge_ramp_no_bounce()
	test_deck_ramp_no_launch_below_40_mps()
	test_never_below_ground()
	test_layer_change_resets()
	print("vehicle_vertical: %d failures" % failures)
	quit(1 if failures else 0)


## Height along x: slope +0.15 for 10 m, -0.15 for 10 m, then flat.
func crest(x: float) -> float:
	return 0.15 * x if x < 10.0 else (1.5 - 0.15 * (x - 10.0) if x < 20.0 else 0.0)


## A 5 % grade easing to flat over 10 m (a bridge ramp's crest), then flat.
func ramp(x: float) -> float:
	return 0.05 * x if x < 10.0 else (0.5 + 0.05 * (x - 10.0) - 0.0025 * (x - 10.0) * (x - 10.0) if x < 20.0 else 0.75)


## Buildings3D.deck_base: a layer-1 deck climbs DECK_M over RAMP_M by smoothstep, then stays flat.
func deck(x: float) -> float:
	return 6.0 * smoothstep(0.0, 45.0, x)


## 0.04 m mesh seam steps every 7 m, up and down.
func seam(x: float) -> float:
	return 0.04 if int(x / 7.0) % 2 == 1 else 0.0


## Drive `ground` at `speed` and `fps`, the slope measured 1 m behind as entity_layer does;
## returns [airtime s, min(z - ground), max deviation from the ground while not airborne].
func drive(speed: float, ground: Callable, length: float, fps: float) -> Array:
	var v := VehicleVertical.new()
	var dt := 1.0 / fps
	var x := 0.0
	var air := 0.0
	var lowest := 1e9
	var off := 0.0
	v.track(0, Vector2.ZERO, ground.call(0.0))
	while x < length:
		x += speed * dt
		var g: float = ground.call(x)
		v.step(g, (g - float(ground.call(x - 1.0))), speed, dt)
		v.track(0, Vector2(x, 0.0), g)
		lowest = minf(lowest, v.z - g)
		if v.airborne:
			air += dt
		else:
			off = maxf(off, absf(v.z - g))
	return [air, lowest, off]


func test_crest_airtime_at_speed() -> void:
	var r := drive(25.0, crest, 80.0, 60.0)
	print("crest 25 m/s airtime ", r[0])
	check(r[0] >= 0.15, "crest at 25 m/s: airtime %.3f s >= 0.15" % r[0])


func test_airtime_independent_of_frame_rate() -> void:
	for speed in [13.0, 15.0, 18.0, 22.0, 25.0, 30.0]:
		var ref: float = drive(speed, crest, 90.0, 60.0)[0]
		check(ref > 0.1, "crest at %.0f m/s launches at 60 fps (%.3f s)" % [speed, ref])
		for fps in [30.0, 144.0, 240.0]:
			var air: float = drive(speed, crest, 90.0, fps)[0]
			check(absf(air - ref) <= 0.08 + 0.1 * ref, "crest at %.0f m/s: %.0f fps airtime %.3f s vs 60 fps %.3f s" % [speed, fps, air, ref])


func test_no_airtime_low_speed() -> void:
	for fps in [30.0, 60.0, 240.0]:
		check(drive(8.0, crest, 60.0, fps)[0] == 0.0, "crest at 8 m/s, %.0f fps: no airtime" % fps)
		check(drive(11.9, crest, 60.0, fps)[0] == 0.0, "crest just under LAUNCH_MIN_MPS, %.0f fps: no airtime" % fps)


func test_flat_unchanged() -> void:
	var grade := func(x: float) -> float: return 0.02 * x
	var flat := func(_x: float) -> float: return 0.0
	for fps in [30.0, 60.0, 144.0, 240.0]:
		var r := drive(14.0, grade, 200.0, fps)
		check(r[0] == 0.0 and r[2] < 0.001, "2 %% grade at 14 m/s, %.0f fps: body on the ground (dev %.4f)" % [fps, r[2]])
		r = drive(30.0, flat, 200.0, fps)
		check(r[0] == 0.0 and r[2] < 0.001, "flat at 30 m/s, %.0f fps: on the ground" % fps)


func test_seam_no_bounce() -> void:
	for fps in [30.0, 60.0, 144.0, 240.0]:
		for speed in [14.0, 30.0]:
			check(drive(speed, seam, 200.0, fps)[0] == 0.0, "0.04 m seam at %.0f m/s, %.0f fps: never airborne" % [speed, fps])


func test_bridge_ramp_no_bounce() -> void:
	for fps in [30.0, 60.0, 144.0, 240.0]:
		for speed in [14.0, 25.0, 33.0]:
			check(drive(speed, ramp, 100.0, fps)[0] == 0.0, "5 %% ramp easing over 10 m at %.0f m/s, %.0f fps: never airborne" % [speed, fps])


func test_deck_ramp_no_launch_below_40_mps() -> void:
	for fps in [30.0, 60.0, 144.0]:
		for speed in [26.0, 28.0, 30.0, 34.0, 38.0, 39.5]:
			var r := drive(speed, deck, 160.0, fps)
			check(r[0] == 0.0 and r[2] < 0.001, "bridge ramp (6 m over 45 m) at %.1f m/s, %.0f fps: no launch (%.3f s)" % [speed, fps, r[0]])


func test_never_below_ground() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var v := VehicleVertical.new()
	var ok := true
	var g := 0.0
	for i in 5000:
		g += rng.randf_range(-0.8, 0.8)
		v.step(g, rng.randf_range(-0.5, 0.5), rng.randf_range(0.0, 40.0), rng.randf_range(0.005, 0.1))
		ok = ok and v.z >= g - 0.001
	check(ok, "z >= ground - 0.001 for random input")


func test_layer_change_resets() -> void:
	var v := VehicleVertical.new()
	v.track(0, Vector2.ZERO, 0.0)
	v.z = 5.0
	v.vz = 3.0
	v.airborne = true
	v.track(1, Vector2(1, 0), 2.0)
	check(v.z == 2.0 and v.vz == 0.0 and not v.airborne, "layer change: z = ground, vz = 0")
	v.z = 5.0
	v.vz = 3.0
	v.airborne = true
	v.track(1, Vector2(50, 0), 0.0)
	check(v.z == 0.0 and v.vz == 0.0 and not v.airborne, "jump > 5 m: reset")
