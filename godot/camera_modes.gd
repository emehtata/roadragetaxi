## Driving camera modes (docs/specs/third-person-camera.md): 1 third-person
## chase (the default), 2 top-down, 3 driver-eye. main.gd forwards the keys and
## shows the 3D view; this only picks the mode and places the chase camera.
## Rendering only: no physics, no collision shapes (Python stays authoritative).
extends RefCounted

enum Mode {THIRD, TOP, EYE}

const KEYS := {KEY_1: Mode.THIRD, KEY_2: Mode.TOP, KEY_3: Mode.EYE}
## A 4.5 m taxi fills ~1/4 of the width at 7.5 m with FOV 60, in the lower
## centre; 3.2 m up keeps ~40 m of road visible over its roof.
const CHASE_BACK_M := 7.5
const CHASE_UP_M := 3.2
const LOOK_AHEAD_M := 6.0
const LOOK_UP_M := 1.0
## On foot: a 1.75 m walker fills ~1/3 of the height at 3 m, FOV 60.
const WALK_BACK_M := 3.0
const WALK_UP_M := 1.8
const WALK_LOOK_AHEAD_M := 3.0
const WALK_LOOK_UP_M := 1.2
const FOV := 60.0
const HEADING_SMOOTH_S := 0.25
const CLEARANCE_M := 1.2  # above the ground under the camera
const DECK_GAP_M := 0.5  # below a bridge deck over the camera
## Mouse orbit (docs/specs/3rd-person-mouse.md): pitch raises (+) or lowers the
## eye around the look target; camera_reset eases back with RESET_SMOOTH_S.
const PITCH_MIN := -0.35
const PITCH_MAX := 1.2
const RESET_SMOOTH_S := 0.15
## Wheel zoom: the chase distance eases toward zoom_* x the base back distance.
const ZOOM_SMOOTH_S := 0.15

var mode := Mode.THIRD  # kept across leaving and re-entering the taxi
var _heading := INF
var orbit_yaw := 0.0  # offset from the held (or followed) heading
var orbit_pitch := 0.0
var _held := false  # looked away: the yaw stays put in world space
var _hold_yaw := INF  # the smoothed heading when the look began
var _resetting := false
var zoom_walk := 1.0  # target back-distance scale on foot
var zoom_car := 1.0  # and in the taxi
var walk_min_m := 1.5  # settings: chase_walk_min_m / max (keeps the eye out of the walker)
var walk_max_m := 8.0
var car_min_m := 4.0  # chase_car_min_m / max (out of the taxi body)
var car_max_m := 20.0
var walking := false  # zoom_step target: on foot (main sets it; _follow too)
var _zoom_cur := INF  # smoothed back distance (m), eased across enter/exit too


func select(m: Mode) -> void:
	mode = m
	_heading = INF


## Mouse motion (no button): orbit; the yaw is held in world space from now on.
func look(relative: Vector2, sensitivity: float) -> void:
	if not _held:
		_held = true
		_hold_yaw = _heading  # INF before the first frame: _follow takes it
	_resetting = false
	orbit_yaw = wrapf(orbit_yaw - relative.x * sensitivity, -PI, PI)
	orbit_pitch = clampf(orbit_pitch + relative.y * sensitivity, PITCH_MIN, PITCH_MAX)


## Wheel notches (+ closer) change the active mode's target, clamped to its limits.
func zoom_step(notches: float, sensitivity: float) -> void:
	if walking:
		zoom_walk = clampf(zoom_walk - notches * sensitivity, walk_min_m / WALK_BACK_M, walk_max_m / WALK_BACK_M)
	else:
		zoom_car = clampf(zoom_car - notches * sensitivity, car_min_m / CHASE_BACK_M, car_max_m / CHASE_BACK_M)


## Back behind the entity, eased in _follow (exp: frame-rate independent).
func reset_look() -> void:
	_resetting = true


## 1/2/3 select their mode (not a toggle); other keys: false.
func handle_key(event: InputEvent) -> bool:
	if not (event is InputEventKey and event.pressed and not event.echo and KEYS.has(event.keycode)):
		return false
	select(KEYS[event.keycode])
	return true


## Only the heading lags (exponentially, HEADING_SMOOTH_S); a jump over 90 deg
## (respawn, first frame) snaps.
func smooth_heading(target: float, delta: float) -> float:
	if _heading == INF or absf(angle_difference(_heading, target)) > PI / 2.0:
		_heading = target
	else:
		_heading = wrapf(_heading + angle_difference(_heading, target) * (1.0 - exp(-delta / HEADING_SMOOTH_S)), -PI, PI)
	return _heading


## Behind and above `at` (2D map metres; heading as Buildings3D: forward is
## (cos, 0, -sin)), aimed ahead of it, upright. Never below `cam_ground` +
## CLEARANCE_M, and under `deck` (a bridge over the camera) when it can.
static func chase_pose(at: Vector2, heading: float, ground: float, cam_ground: float, deck := INF,
		back := CHASE_BACK_M, up := CHASE_UP_M, ahead := LOOK_AHEAD_M, look_up := LOOK_UP_M, pitch := 0.0) -> Transform3D:
	var forward := Vector3(cos(heading), 0.0, -sin(heading))
	var eye := Vector3(at.x, ground + up, at.y) - forward * back
	if pitch != 0.0:  # swing the eye up or down around the look target
		var target0 := Vector3(at.x, ground + look_up, at.y) + forward * ahead
		var offset := eye - target0
		var elevation := clampf(atan2(offset.y, back + ahead) + pitch, -1.4, 1.4)
		eye = target0 + (-forward * cos(elevation) + Vector3.UP * sin(elevation)) * offset.length()
	eye.y = maxf(minf(eye.y, deck - DECK_GAP_M), cam_ground + CLEARANCE_M)
	var target := Vector3(at.x, ground + look_up, at.y) + forward * ahead
	return Transform3D(Basis.looking_at(target - eye, Vector3.UP), eye)


## The chase camera for the taxi `body` (entity_layer.player_body: the same
## interpolated sample as the car model). height: map_layer.deck_height;
## covered: map_layer.covered.
func chase(body: Dictionary, delta: float, height: Callable, covered: Callable) -> Transform3D:
	return _follow(body["position"], float(body["heading"]), delta, height, covered, int(body.get("layer", 0)), CHASE_BACK_M, CHASE_UP_M, LOOK_AHEAD_M, LOOK_UP_M)


## The chase camera behind the walking player (at: entity_layer.player_position,
## heading: the figure's facing).
func walk_chase(at: Vector2, heading: float, delta: float, height: Callable, covered: Callable, layer := 0) -> Transform3D:
	return _follow(at, heading, delta, height, covered, layer, WALK_BACK_M, WALK_UP_M, WALK_LOOK_AHEAD_M, WALK_LOOK_UP_M)


func _follow(at: Vector2, target_heading: float, delta: float, height: Callable, covered: Callable, layer: int,
		back: float, up: float, ahead: float, look_up: float) -> Transform3D:
	var heading := smooth_heading(target_heading, delta)
	walking = back == WALK_BACK_M
	var goal := back * (zoom_walk if walking else zoom_car)
	_zoom_cur = goal if _zoom_cur == INF else lerpf(goal, _zoom_cur, exp(-delta / ZOOM_SMOOTH_S))
	up *= _zoom_cur / back
	back = _zoom_cur
	if _held and _hold_yaw == INF:
		_hold_yaw = heading
	if _resetting:
		if _held:  # from the held world yaw to an offset behind the entity, then ease it out
			orbit_yaw = angle_difference(heading, _hold_yaw + orbit_yaw)
			_held = false
		var keep := exp(-delta / RESET_SMOOTH_S)
		orbit_yaw *= keep
		orbit_pitch *= keep
		if absf(orbit_yaw) < 1e-3 and absf(orbit_pitch) < 1e-3:
			orbit_yaw = 0.0
			orbit_pitch = 0.0
			_resetting = false
	var yaw := (_hold_yaw if _held else heading) + orbit_yaw
	var cam: Vector2 = at - Vector2(cos(yaw), -sin(yaw)) * back
	var deck: float = float(height.call(cam, layer + 1)) if layer <= 0 and covered.call(cam, layer) else INF
	return chase_pose(at, yaw, float(height.call(at, layer)), float(height.call(cam, layer)), deck, back, up, ahead, look_up, orbit_pitch)
