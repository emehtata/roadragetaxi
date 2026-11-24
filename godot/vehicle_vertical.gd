## docs/specs/vehicle-airborne-physics.md: visual-only vertical state of the vehicle the player drives.
## On the ground it follows `ground`; over a crest fast enough it flies a ballistic arc and lands with a bump.
## The take-off test is a ballistic "ghost" that keeps falling under gravity from the surface's own vertical
## speed, so it depends on the road's shape and the speed, not on the frame time. The ghost lives only
## GHOST_MAX_S: the gap must open that fast, so a short sharp crest launches the car but a long gentle
## convex top (a bridge ramp's, even at 40 m/s) never does.
class_name VehicleVertical
extends RefCounted

const GRAVITY := 9.81
const LAUNCH_MIN_MPS := 12.0
const LAUNCH_GAP_M := 0.15  # the ghost this far above the road: take off (a 0.04 m seam or a gentle ramp never does)
const GHOST_MAX_S := 0.08  # the ghost must clear LAUNCH_GAP_M within this long of leaving the road
const POP_EASE_S := 0.08  # the take-off height jump is eased in over this long
const BUMP_DECAY_S := 0.25
const RESET_JUMP_M := 5.0

var z := 0.0
var vz := 0.0
var airborne := false
var land_bump := 0.0  # 1 at a hard landing, decays to 0
var _layer := 0
var _slope := 0.0  # last frame's ground slope: the rise the body was following
var _ghost_z := 0.0
var _ghost_vz := 0.0
var _ghost_age := 0.0
var _pop := 0.0  # take-off height jump still to ease in, and the time left
var _pop_left := 0.0
var _at := Vector2.INF


## The first call, a layer change or a jump over RESET_JUMP_M (teleport, respawn) puts the body back on the ground.
func track(layer: int, at: Vector2, ground: float) -> void:
	if _at == Vector2.INF or layer != _layer or at.distance_to(_at) > RESET_JUMP_M:
		_land(ground)
		land_bump = 0.0
		_slope = 0.0
	_layer = layer
	_at = at


## Body height for this frame; `ground_slope` is the road's rise per metre along the heading (measured behind the body).
func step(ground: float, ground_slope: float, speed: float, dt: float) -> float:
	land_bump = maxf(0.0, land_bump - dt / BUMP_DECAY_S)
	var rise := _slope
	_slope = ground_slope
	if not airborne:
		_ghost_vz -= GRAVITY * dt
		_ghost_z += _ghost_vz * dt
		_ghost_age += dt
		if _ghost_z <= ground or absf(speed) < LAUNCH_MIN_MPS or _ghost_age > GHOST_MAX_S:  # on the road (or too slow to open the gap): the ghost rides along its vertical speed
			_ghost_z = ground
			_ghost_vz = speed * rise
			_ghost_age = 0.0
		if _ghost_z <= ground + LAUNCH_GAP_M:
			z = ground
			return z
		airborne = true
		z = _ghost_z
		vz = _ghost_vz
		_pop = z - ground
		_pop_left = POP_EASE_S
	else:
		vz -= GRAVITY * dt
		z += vz * dt
		_pop_left = maxf(0.0, _pop_left - dt)
	if z <= ground:
		land_bump = clampf(-vz / 8.0, 0.0, 1.0)
		_land(ground)
		return z
	return maxf(ground, z - _pop * _pop_left / POP_EASE_S)  # airborne: the jump at take-off eased in


func _land(ground: float) -> void:
	z = ground
	vz = 0.0
	_ghost_z = ground
	_ghost_vz = 0.0
	_ghost_age = 0.0
	_pop_left = 0.0
	airborne = false
