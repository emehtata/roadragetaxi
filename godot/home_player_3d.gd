## Indoor presentation only; the Python map player remains at the front door.
extends CharacterBody3D

const DEFAULT_RADIUS := 0.30

@export var player_height := 1.75
@export var radius := DEFAULT_RADIUS
@export var eye_height := 1.60
@export var walking_speed := 3.5
@export var mouse_sensitivity := 0.002
var controls_enabled := false
var head: Node3D
var camera: Camera3D
var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity", 9.8)


func _ready() -> void:
	var capsule := CapsuleShape3D.new()
	capsule.radius = radius
	capsule.height = player_height
	var collision := CollisionShape3D.new()
	collision.shape = capsule
	collision.position.y = player_height / 2.0
	add_child(collision)
	head = Node3D.new()
	head.position.y = eye_height
	add_child(head)
	camera = Camera3D.new()
	camera.near = 0.05
	head.add_child(camera)
	camera.current = true


func look(relative: Vector2) -> void:
	rotation.y -= relative.x * mouse_sensitivity
	head.rotation.x = clampf(head.rotation.x - relative.y * mouse_sensitivity, deg_to_rad(-85), deg_to_rad(85))


func walk(direction: Vector2, delta: float) -> void:
	direction = direction.limit_length()
	var motion := basis * Vector3(direction.x, 0.0, direction.y)
	velocity.x = motion.x * walking_speed
	velocity.z = motion.z * walking_speed
	if not is_on_floor():
		velocity.y -= gravity * delta
	else:
		velocity.y = 0.0
	move_and_slide()


func _physics_process(delta: float) -> void:
	var direction := Input.get_vector("interior_left", "interior_right", "interior_forward", "interior_back") if controls_enabled else Vector2.ZERO
	walk(direction, delta)
