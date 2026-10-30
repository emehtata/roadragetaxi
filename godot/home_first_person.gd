## An isolated interior world over the map; freed on exit, never changes exterior cameras.
extends CanvasLayer

const Interior := preload("res://home_interior_3d.gd")
const Player := preload("res://home_player_3d.gd")
const Walk := preload("res://home_walk.gd")
const T := preload("res://i18n.gd")
const MAX_LOOK_SPEED := TAU * 2.0
var language := "en"
var is_home := false
var mouse_sensitivity := 0.002
var player: CharacterBody3D
var _container: SubViewportContainer
var _viewport: SubViewport
var _hint: Label
var _door := Vector2.ZERO
var _previous_mouse_mode := Input.MOUSE_MODE_VISIBLE
var _resume_capture := false
var _look_motion := Vector2.ZERO
var _discard_capture_motion := false
var _recenter_mouse := DisplayServer.get_name() == "X11"


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_PAUSABLE
	layer = 5
	visible = false


func enter(plan: Dictionary) -> bool:
	leave()
	var door := Walk.front_door(plan)
	if door.is_empty():
		return false
	var spawn := spawn_position(plan, Player.DEFAULT_RADIUS)
	if spawn == Vector2.INF:
		return false
	_previous_mouse_mode = Input.mouse_mode
	_door = door["middle"]
	_container = SubViewportContainer.new()
	_container.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_container.stretch = true
	_container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_container)
	_viewport = SubViewport.new()
	_viewport.own_world_3d = true
	_viewport.handle_input_locally = false
	_container.add_child(_viewport)
	var interior := Interior.new()
	_viewport.add_child(interior)
	if not interior.load_plan(plan):
		leave()
		return false
	# The front door is an E transition, not a route into the isolated world's void.
	var boundary := StaticBody3D.new()
	var barrier := CollisionShape3D.new()
	var box := BoxShape3D.new()
	var jambs: Array = []
	for entry in plan["doors"]:
		if int(entry["rooms"][0]) == -1:
			jambs = entry["points"]
			break
	var edge := Vector2(jambs[1][0] - jambs[0][0], jambs[1][1] - jambs[0][1])
	box.size = Vector3(edge.length() + interior.wall_thickness, interior.wall_height, interior.wall_thickness)
	barrier.shape = box
	var outside: Vector2 = _door - door["inward"] * interior.wall_thickness / 2.0
	boundary.position = Vector3(outside.x, interior.wall_height / 2.0, -outside.y)
	boundary.rotation.y = edge.angle()
	boundary.add_child(barrier)
	_viewport.add_child(boundary)
	player = Player.new()
	player.mouse_sensitivity = mouse_sensitivity
	_viewport.add_child(player)
	player.position = Vector3(spawn.x, 0.05, -spawn.y)
	player.look_at(player.position + Vector3(door["inward"].x, 0, -door["inward"].y))
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.background_mode = Environment.BG_COLOR
	environment.environment.background_color = Color("24303d")
	environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.environment.ambient_light_color = Color.WHITE
	environment.environment.ambient_light_energy = 0.75
	_viewport.add_child(environment)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-60, -30, 0)
	_viewport.add_child(light)
	_hint = Label.new()
	_hint.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	_hint.offset_top = -48
	_hint.offset_bottom = -12
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hint.add_theme_color_override("font_shadow_color", Color.BLACK)
	_hint.add_theme_constant_override("shadow_offset_x", 2)
	_hint.add_theme_constant_override("shadow_offset_y", 2)
	_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_container.add_child(_hint)
	visible = true
	capture_mouse()
	return true


func leave() -> void:
	if is_instance_valid(player):
		player.controls_enabled = false
	if is_instance_valid(_container):
		_container.free()
	_container = null
	_viewport = null
	player = null
	_hint = null
	if visible:
		Input.mouse_mode = _previous_mouse_mode
	visible = false
	_resume_capture = false


func _exit_tree() -> void:
	leave()


func at_exit() -> bool:
	return is_instance_valid(player) and Vector2(player.position.x, -player.position.z).distance_to(_door) <= Walk.EXIT_REACH_M


func capture_mouse() -> void:
	if visible and not get_tree().paused and not player.controls_enabled:
		_look_motion = Vector2.ZERO
		_discard_capture_motion = true
		if _recenter_mouse:
			# Bypass X11 raw deltas, which can be incorrect for absolute pointing devices.
			Input.mouse_mode = Input.MOUSE_MODE_CONFINED_HIDDEN
			DisplayServer.warp_mouse(Vector2(DisplayServer.window_get_size()) / 2.0)
		else:
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		player.controls_enabled = true


func release_mouse() -> void:
	_look_motion = Vector2.ZERO
	if is_instance_valid(player):
		player.controls_enabled = false
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func set_paused(paused: bool) -> void:
	if not visible:
		return
	if paused:
		_resume_capture = player.controls_enabled
		release_mouse()
	elif _resume_capture:
		capture_mouse()
		_resume_capture = false


func _notification(what: int) -> void:
	if what in [NOTIFICATION_APPLICATION_FOCUS_OUT, NOTIFICATION_WM_WINDOW_FOCUS_OUT] and visible:
		_resume_capture = false
		release_mouse()


## Called once from main's input path; exterior HUD, driving and phone never see these events.
func handle_input(event: InputEvent) -> bool:
	if not visible:
		return false
	if event is InputEventMouseMotion:
		var motion: Vector2 = event.screen_relative
		if player.controls_enabled and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED and motion.is_finite() and not motion.is_zero_approx():
			if _discard_capture_motion:
				_discard_capture_motion = false  # X11 capture can deliver a cursor-recentering delta.
			else:
				_look_motion += motion
		return true
	if event is InputEventMouseButton:
		if event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			capture_mouse()
		return true
	if event is InputEventKey:
		return not event.keycode in [KEY_E, KEY_H, KEY_F12, KEY_ESCAPE]
	return false


func _process(delta: float) -> void:
	if not visible:
		return
	if player.controls_enabled:
		if _recenter_mouse:
			var center := Vector2(DisplayServer.window_get_size()) / 2.0
			_look_motion = Vector2(DisplayServer.mouse_get_position() - DisplayServer.window_get_position()) - center
			DisplayServer.warp_mouse(center)
		# Bound capture/warp bursts per rendered frame; never retain excess motion as a backlog.
		var limit: float = MAX_LOOK_SPEED * minf(delta, 0.05) / player.mouse_sensitivity
		player.look(_look_motion.limit_length(limit))
	_look_motion = Vector2.ZERO
	_hint.text = T.text("home_first_person_hint", language)
	if at_exit():
		_hint.text += " · " + T.text("house_leave_prompt", language)
	if not is_home:
		_hint.text += " · " + T.text("home_choose_hint", language)
	if not player.controls_enabled:
		_hint.text += " · " + T.text("home_mouse_resume", language)


## The preferred doorstep first, then inward offsets and room labels; source plans are connected.
static func spawn_position(plan: Dictionary, radius: float) -> Vector2:
	var door := Walk.front_door(plan)
	if door.is_empty():
		return Vector2.INF
	var candidates: Array[Vector2] = []
	for distance in [Walk.SPAWN_IN_M, 0.65, 0.85, 1.1]:
		candidates.append(door["middle"] + door["inward"] * distance)
	for room in plan.get("rooms", []):
		candidates.append(Vector2(room["label_at"][0], room["label_at"][1]))
	var outline := Interior._points(plan["footprint"])
	var reach := radius + 0.12 / 2.0 + 0.02
	for candidate in candidates:
		if not Geometry2D.is_point_in_polygon(candidate, outline):
			continue
		var on_floor := false
		for room in plan.get("rooms", []):
			if Geometry2D.is_point_in_polygon(candidate, Interior._points(room["points"])):
				on_floor = true
		if not on_floor:
			continue
		var clear := true
		for i in outline.size():
			if Geometry2D.get_closest_point_to_segment(candidate, outline[i], outline[(i + 1) % outline.size()]).distance_to(candidate) < radius + 0.02:
				clear = false
		for line in plan.get("walls", []):
			for i in range(line.size() - 1):
				var a := Vector2(line[i][0], line[i][1])
				var b := Vector2(line[i + 1][0], line[i + 1][1])
				if Geometry2D.get_closest_point_to_segment(candidate, a, b).distance_to(candidate) < reach:
					clear = false
		if clear:
			return candidate
	return Vector2.INF
