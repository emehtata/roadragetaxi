## Headlights, godot-lights-01: the
## world's darkness is now main.gd's CanvasModulate (Daylight.ambient_color,
## by solar altitude) - no tint polygon at all. This draws every vehicle's
## beams in one triangle batch on top: additive and unshaded (the ambient
## multiply doesn't touch it), brightest at the lamps, fading to nothing at
## the beam's end, scaled by how much artificial light shows
## (Daylight.artificial). Beams light whatever they fall on, buildings
## included (no per-frame polygon booleans).
extends Node2D

const BEAM := Color(0.34, 0.33, 0.28)  # the beams' warm glow at the lamps (the shader's glow)

var level := 0.0  # Daylight.artificial: 0 by day .. 1 at night
var view := Rect2()
var beams := Node2D.new()
var beam_points := PackedVector2Array()  # reused every frame
var beam_colors := PackedColorArray()
var beam_triangles := PackedInt32Array()


## The beams brighten what is under them: the screen behind a beam times
## (1 + gain x the beam's strength), so the road, its markings and the verge
## show their own colours in the light. An added tint only greyed everything
## evenly - in the dark the road was hard to see. A little warm glow on top.
const BEAM_SHADER := """
shader_type canvas_item;
render_mode unshaded, blend_add;
uniform sampler2D screen_texture : hint_screen_texture, filter_linear;
uniform float gain = 3.0;
uniform vec3 glow = vec3(0.34, 0.33, 0.28);
void fragment() {
	float strength = COLOR.r;
	vec3 under = texture(screen_texture, SCREEN_UV).rgb;
	COLOR = vec4((under * gain + glow * 0.3) * strength, 1.0);
}
"""
var ambient := Color.WHITE  # the world's ambient multiply (main.gd): darker night, more gain


func _ready() -> void:
	z_index = 20
	var shader := Shader.new()
	shader.code = BEAM_SHADER
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("glow", Vector3(BEAM.r, BEAM.g, BEAM.b))
	beams.material = material
	beams.draw.connect(_draw_beams)
	add_child(beams)


## This frame's beams: entity_layer.gd beam_polygons (per lamp a quad
## [lamp, near, far side, tip] and a round cap; the caps are left out).
func show_lights(new_level: float, new_view: Rect2, beam_polygons: Array) -> void:
	level = new_level
	view = new_view
	beam_points.clear()
	beam_colors.clear()
	beam_triangles.clear()
	if level > 0.01:
		(beams.material as ShaderMaterial).set_shader_parameter("gain", beam_gain(ambient))
		var near := Color(level, level, level, 1.0)  # the beam's strength (the shader's COLOR.r)
		var far := Color(0, 0, 0, 1.0)
		for polygon in beam_polygons:
			if polygon.size() == 4:
				quad(polygon, near, far, beam_points, beam_colors, beam_triangles)
	visible = not beam_triangles.is_empty()
	if visible:
		beams.queue_redraw()


## How much a full-strength beam brightens what is under it: back to about
## daylight against the night's ambient multiply (its luminance), at most 6x.
static func beam_gain(ambient_color: Color) -> float:
	return clampf(1.0 / maxf(ambient_color.get_luminance(), 0.05) - 1.0, 0.0, 6.0)


## A beam quad [lamp, near, far side, tip]: bright at the lamp end, black
## (adds nothing) at the far end - a soft-ended cone with no texture.
static func quad(polygon: PackedVector2Array, near: Color, far: Color, points: PackedVector2Array,
		colors: PackedColorArray, triangles: PackedInt32Array) -> void:
	var base := points.size()
	points.append_array(polygon)
	colors.append_array(PackedColorArray([near, near, far, far]))
	triangles.append_array(PackedInt32Array([base, base + 1, base + 2, base, base + 2, base + 3]))


func _draw_beams() -> void:
	if beam_triangles.is_empty():  # queued, then the beams went before the draw
		return
	RenderingServer.canvas_item_add_triangle_array(beams.get_canvas_item(), beam_triangles, beam_points, beam_colors)
