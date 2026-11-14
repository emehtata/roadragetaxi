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
const FOV := 60.0
const HEADING_SMOOTH_S := 0.25
const CLEARANCE_M := 1.2  # above the ground under the camera
const DECK_GAP_M := 0.5  # below a bridge deck over the camera

var mode := Mode.THIRD  # kept across leaving and re-entering the taxi
var _heading := INF


func select(m: Mode) -> void:
	mode = m
	_heading = INF


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
static func chase_pose(at: Vector2, heading: float, ground: float, cam_ground: float, deck := INF) -> Transform3D:
	var forward := Vector3(cos(heading), 0.0, -sin(heading))
	var eye := Vector3(at.x, ground + CHASE_UP_M, at.y) - forward * CHASE_BACK_M
	eye.y = maxf(minf(eye.y, deck - DECK_GAP_M), cam_ground + CLEARANCE_M)
	var target := Vector3(at.x, ground + LOOK_UP_M, at.y) + forward * LOOK_AHEAD_M
	return Transform3D(Basis.looking_at(target - eye, Vector3.UP), eye)


## The chase camera for the taxi `body` (entity_layer.player_body: the same
## interpolated sample as the car model). height: map_layer.deck_height;
## covered: map_layer.covered.
func chase(body: Dictionary, delta: float, height: Callable, covered: Callable) -> Transform3D:
	var heading := smooth_heading(float(body["heading"]), delta)
	var at: Vector2 = body["position"]
	var layer := int(body.get("layer", 0))
	var cam: Vector2 = at - Vector2(cos(heading), -sin(heading)) * CHASE_BACK_M
	var deck: float = float(height.call(cam, layer + 1)) if layer <= 0 and covered.call(cam, layer) else INF
	return chase_pose(at, heading, float(height.call(at, layer)), float(height.call(cam, layer)), deck)
