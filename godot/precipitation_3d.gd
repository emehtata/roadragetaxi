## Rain and snow as world-space particles that fall from EMIT_HEIGHT_M to the
## ground or a roof (docs/specs/precipitation-falling.md). All per-drop work is
## on the GPU (the process shader below); GDScript only moves the emitter with
## the camera and sets uniforms.
class_name Precipitation3D
extends Node3D

const Perf := preload("res://perf.gd")
const MAX_PARTICLES := 8000
const EMIT_HEIGHT_M := 30.0
const STREAK_S := 0.35  # rain streak length = velocity * this (spec 0.05 s: too short to read from the top-down camera)
const NEAR_SPEEDUP := 0.3  # near layer 1.3x faster than far
const BASE_SPEED := {"rain": 6.5, "slush": 2.61, "snow": 1.0}  # far layer, m/s; slush 3 m/s at mid layer
const WIND_FACTOR := {"rain": 0.5, "slush": 0.5, "snow": 0.9}
const SIZE_M := {"rain": 0.035, "slush": 0.035, "snow": 0.12}  # far layer; near is 2x
const COLLISION_STEP_M := 50.0

const PROCESS_SHADER := """
shader_type particles;
uniform vec2 extent;
uniform float emit_height;
uniform float base_speed;
uniform float speedup;
uniform vec2 wind;
uniform float size_m;
uniform float streak_s;
uniform float sway;

float rnd(inout uint s) {
	s = s * 747796405u + 2891336453u;
	uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
	return float((w >> 22u) ^ w) / 4294967295.0;
}

vec3 fall(float layer) {
	return vec3(wind.x, -base_speed * (1.0 + speedup * layer), wind.y);
}

void start() {
	uint s = NUMBER * 9781u + RANDOM_SEED * 6271u + INDEX;
	float layer = rnd(s);
	CUSTOM = vec4(layer, rnd(s) * 6.2832, 0.5 + rnd(s), 0.0);  // layer, sway phase, sway Hz, age
	vec3 v = fall(layer);
	// Spawn upwind so that the drop lands inside the box under the camera.
	vec2 land = vec2(rnd(s) * 2.0 - 1.0, rnd(s) * 2.0 - 1.0) * extent;
	vec2 offset = -v.xz * (emit_height / -v.y);
	vec3 origin = EMISSION_TRANSFORM[3].xyz;
	VELOCITY = v;
	float width = size_m * (1.0 + layer);
	TRANSFORM = mat4(vec4(width, 0.0, 0.0, 0.0),
		vec4(streak_s > 0.0 ? v * streak_s : vec3(0.0, width, 0.0), 0.0),
		vec4(0.0, 0.0, width, 0.0),
		vec4(origin.x + land.x + offset.x, emit_height, origin.z + land.y + offset.y, 1.0));
}

void process() {
	CUSTOM.w += DELTA;
	vec3 v = fall(CUSTOM.x);
	if (sway > 0.0) {  // snow: sideways sin(age, phase), 0.2-0.5 m
		float amplitude = 0.2 + 0.3 * fract(CUSTOM.y * 7.0);
		float w = 6.2832 * CUSTOM.z;
		v.x += amplitude * w * cos(w * CUSTOM.w + CUSTOM.y);
	}
	VELOCITY = v;
	if (COLLIDED || TRANSFORM[3].y <= 0.0) {
		ACTIVE = false;
	}
}
"""

var particles: GPUParticles3D
var collision: GPUParticlesCollisionHeightField3D
var _kind := ""
var _intensity := -1.0
var _process_material: ShaderMaterial
var _draw_materials := {}


static func drop_count(_kind_name: String, intensity: float) -> int:
	return clampi(int(MAX_PARTICLES * intensity), 0, MAX_PARTICLES)


## `wind_mps` is in 3D ground axes (x east, y = world z, south): buildings_3d's sky_wind.
static func fall_velocity(kind: String, layer: float, wind_mps: Vector2) -> Vector3:
	var speed: float = BASE_SPEED.get(kind, 6.5) * (1.0 + NEAR_SPEEDUP * layer)
	var drift: Vector2 = wind_mps * float(WIND_FACTOR.get(kind, 0.5))
	return Vector3(drift.x, -speed, drift.y)


func _init() -> void:
	visible = false
	particles = GPUParticles3D.new()
	particles.emitting = false
	particles.local_coords = false
	particles.amount = 1
	particles.collision_base_size = 0.0
	particles.visibility_aabb = AABB(Vector3(-1000, -10, -1000), Vector3(2000, EMIT_HEIGHT_M + 20.0, 2000))
	particles.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_process_material = ShaderMaterial.new()
	_process_material.shader = Shader.new()
	_process_material.shader.code = PROCESS_SHADER
	_process_material.set_shader_parameter("emit_height", EMIT_HEIGHT_M)
	_process_material.set_shader_parameter("speedup", NEAR_SPEEDUP)
	particles.process_material = _process_material
	particles.draw_pass_1 = QuadMesh.new()
	for kind in ["rain", "snow"]:
		var material := ShaderMaterial.new()
		material.shader = load("res://precip_%s.gdshader" % kind)
		_draw_materials[kind] = material
	add_child(particles)
	collision = GPUParticlesCollisionHeightField3D.new()  # roofs (and the ground mesh) stop the drops
	collision.resolution = GPUParticlesCollisionHeightField3D.RESOLUTION_512
	collision.update_mode = GPUParticlesCollisionHeightField3D.UPDATE_MODE_WHEN_MOVED
	add_child(collision)


func set_weather(kind: String, intensity: float, wind_mps: Vector2) -> void:
	visible = kind != ""
	particles.emitting = visible
	if not visible:
		_kind = ""
		return
	_process_material.set_shader_parameter("wind", wind_mps * float(WIND_FACTOR.get(kind, 0.5)))
	if kind == _kind and is_equal_approx(intensity, _intensity):
		return
	_kind = kind
	_intensity = intensity
	var speed: float = BASE_SPEED.get(kind, 6.5)
	particles.amount = maxi(1, drop_count(kind, intensity))
	particles.lifetime = EMIT_HEIGHT_M / speed + 1.0
	particles.preprocess = particles.lifetime  # the sky is full at once, not after a fall
	particles.draw_pass_1.material = _draw_materials["snow" if kind == "snow" else "rain"]
	_process_material.set_shader_parameter("base_speed", speed)
	_process_material.set_shader_parameter("size_m", SIZE_M.get(kind, 0.05))
	_process_material.set_shader_parameter("streak_s", 0.0 if kind == "snow" else STREAK_S)
	_process_material.set_shader_parameter("sway", 1.0 if kind == "snow" else 0.0)


## Follow the camera: the emitter box covers its view, the collision box snaps to a grid.
func _process(_delta: float) -> void:
	if not visible:
		return
	var started := Time.get_ticks_usec()
	var camera := get_viewport().get_camera_3d()
	if camera != null:
		var at := camera.global_position
		var extent := maxf(at.y, 40.0) * tan(deg_to_rad(camera.fov) * 0.5) * 1.8 + 10.0
		particles.global_position = Vector3(at.x, 0.0, at.z)
		_process_material.set_shader_parameter("extent", Vector2(extent, extent))
		var step := COLLISION_STEP_M
		var span := ceilf(extent * 2.0 / step + 2.0) * step
		if collision.size.x != span:  # re-rendered only when moved or resized
			collision.size = Vector3(span, EMIT_HEIGHT_M * 2.0 + 20.0, span)
		collision.global_position = Vector3(snappedf(at.x, step), 0.0, snappedf(at.z, step))
	Perf.add("precipitation_3d", Time.get_ticks_usec() - started)
