## Binoculars in outdoor first person (docs/specs/binoculars-fps-moon.md): O raises
## them at 2x, wheel and +/- step 2/4/6/8x. Only the existing Camera3D's vertical FOV
## narrows (optical_fov); the eye, the aim and every scene object stay as they are.
## This holds the state, the FOV maths and the overlay; main.gd routes input and
## buildings_3d.gd applies optical_fov after the normal camera pose.
extends RefCounted

const ACTION := "binoculars_toggle"
const STEPS := [2.0, 4.0, 6.0, 8.0]
const EASE_S := 0.2  # 1x to 8x at the most; the change is eased in log magnification (no overshoot, frame-rate independent)
const DRIVER_YAW_LIMIT := deg_to_rad(135.0)  # camera-only aim from the taxi's seat
const DRIVER_PITCH_LIMIT := deg_to_rad(80.0)
const KEYS_IN := [KEY_EQUAL, KEY_PLUS, KEY_KP_ADD]
const KEYS_OUT := [KEY_MINUS, KEY_KP_SUBTRACT]

var active := false
var step := 0
var base_fov := 0.0  # the ordinary FPS FOV (degrees), captured when raised
var yaw := 0.0  # driver-eye aim relative to the taxi (rad, counter-clockwise +)
var pitch := 0.0
var _ln := 0.0  # ln of the magnification shown now
var overlay: Control
var _vignette: TextureRect
var _label: Label
var _hint: Label


static func register_action() -> void:
	if not InputMap.has_action(ACTION):
		InputMap.add_action(ACTION)
		var key := InputEventKey.new()
		key.keycode = KEY_O
		InputMap.action_add_event(ACTION, key)


## The vertical FOV (degrees) that magnifies the view `magnification` times.
static func fov_for(base_deg: float, magnification: float) -> float:
	return rad_to_deg(2.0 * atan(tan(deg_to_rad(base_deg) / 2.0) / magnification))


## +1 / -1: a wheel notch or +/- key that steps the magnification, else 0.
static func zoom_direction(event: InputEvent) -> int:
	if event is InputEventMouseButton and event.pressed:
		return 1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else (-1 if event.button_index == MOUSE_BUTTON_WHEEL_DOWN else 0)
	if event is InputEventKey and event.pressed and not event.echo:
		return 1 if event.keycode in KEYS_IN else (-1 if event.keycode in KEYS_OUT else 0)
	return 0


func magnification() -> float:
	return STEPS[step]


func shown_magnification() -> float:
	return exp(_ln)


func raise(fov: float) -> void:
	active = true
	step = 0
	base_fov = fov  # the aim (yaw, pitch) stays as it is: raising never moves the view


func lower() -> void:
	active = false  # the FOV eases back; optical_fov() is 0 once it is exact


## Every exit path but O: at once, 2x again next time.
func reset() -> void:
	active = false
	step = 0
	_ln = 0.0
	yaw = 0.0
	pitch = 0.0
	_refresh()


func zoom(direction: int) -> void:
	step = clampi(step + direction, 0, STEPS.size() - 1)


func update(delta: float) -> void:
	_ln = move_toward(_ln, log(magnification()) if active else 0.0, delta * log(STEPS[-1]) / EASE_S)
	_refresh()


## The FOV to apply to the camera, or 0.0: the ordinary one stands.
func optical_fov() -> float:
	return fov_for(base_fov, exp(_ln)) if _ln > 0.0 else 0.0


## Mouse look scales by this: the same pixel turns the view a smaller angle at 8x.
func sensitivity_scale() -> float:
	return exp(-_ln)


## Camera-only driver-eye aim (the taxi is not steered).
func look(relative: Vector2, sensitivity: float) -> void:
	var scaled := sensitivity * sensitivity_scale()
	yaw = clampf(yaw - relative.x * scaled, -DRIVER_YAW_LIMIT, DRIVER_YAW_LIMIT)
	pitch = clampf(pitch - relative.y * scaled, -DRIVER_PITCH_LIMIT, DRIVER_PITCH_LIMIT)


## Vignette, magnification and hint, built once under `parent`.
func build_overlay(parent: Node) -> void:
	overlay = Control.new()
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	overlay.visible = false
	var gradient := Gradient.new()
	gradient.offsets = PackedFloat32Array([0.6, 1.0])  # clear well past the centre, dark only at the rim
	gradient.colors = PackedColorArray([Color(0, 0, 0, 0), Color(0, 0, 0, 0.7)])
	var texture := GradientTexture2D.new()
	texture.gradient = gradient
	texture.fill = GradientTexture2D.FILL_RADIAL
	texture.fill_from = Vector2(0.5, 0.5)
	texture.fill_to = Vector2(1.0, 0.5)
	texture.width = 256
	texture.height = 256
	_vignette = TextureRect.new()
	_vignette.texture = texture
	_vignette.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_vignette.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_vignette.stretch_mode = TextureRect.STRETCH_SCALE
	_vignette.mouse_filter = Control.MOUSE_FILTER_IGNORE
	overlay.add_child(_vignette)
	_label = _corner_label(22, 8.0)  # top left, the hint under it: clear of the HUD's bottom notices and the top-right panels
	_hint = _corner_label(13, 40.0)
	parent.add_child(overlay)


func _corner_label(size: int, top: float) -> Label:
	var label := Label.new()
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_outline_color", Color.BLACK)
	label.add_theme_constant_override("outline_size", 4)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.position = Vector2(8.0, top)
	overlay.add_child(label)
	return label


func set_hint(text: String) -> void:
	_hint.text = text


func _refresh() -> void:
	if overlay != null:
		overlay.visible = active or _ln > 0.0
		_label.text = "%d×" % int(magnification())
