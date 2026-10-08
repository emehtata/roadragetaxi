## Headlights (render/vehicles.py draw_headlight_beams), godot-lights-01: the
## world's darkness is now main.gd's CanvasModulate (Daylight.ambient_color,
## by solar altitude) - no tint polygon at all. This draws every vehicle's
## beams in one triangle batch on top: additive and unshaded (the ambient
## multiply doesn't touch it), brightest at the lamps, fading to nothing at
## the beam's end, scaled by how much artificial light shows
## (Daylight.artificial). Beams light whatever they fall on, buildings
## included (no per-frame polygon booleans).
extends Node2D

const BEAM := Color(0.27, 0.26, 0.22)  # near the lamps: a neutral, slightly warm white, added

var level := 0.0  # Daylight.artificial: 0 by day .. 1 at night
var view := Rect2()
var beams := Node2D.new()
var beam_points := PackedVector2Array()  # reused every frame
var beam_colors := PackedColorArray()
var beam_triangles := PackedInt32Array()


func _ready() -> void:
	z_index = 20
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	add.light_mode = CanvasItemMaterial.LIGHT_MODE_UNSHADED  # light, not lit: the ambient multiply leaves it be
	beams.material = add
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
		var near := Color(BEAM * level, 1.0)
		var far := Color(0, 0, 0, 1.0)
		for polygon in beam_polygons:
			if polygon.size() == 4:
				quad(polygon, near, far, beam_points, beam_colors, beam_triangles)
	visible = not beam_triangles.is_empty()
	if visible:
		beams.queue_redraw()


## A beam quad [lamp, near, far side, tip]: bright at the lamp end, black
## (adds nothing) at the far end - a soft-ended cone with no texture.
static func quad(polygon: PackedVector2Array, near: Color, far: Color, points: PackedVector2Array,
		colors: PackedColorArray, triangles: PackedInt32Array) -> void:
	var base := points.size()
	points.append_array(polygon)
	colors.append_array(PackedColorArray([near, near, far, far]))
	triangles.append_array(PackedInt32Array([base, base + 1, base + 2, base, base + 2, base + 3]))


func _draw_beams() -> void:
	RenderingServer.canvas_item_add_triangle_array(beams.get_canvas_item(), beam_triangles, beam_points, beam_colors)
