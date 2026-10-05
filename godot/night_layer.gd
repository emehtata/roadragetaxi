## The night (render/hud.py draw_day_night_overlay, render/vehicles.py
## draw_headlight_beams): a dark-blue tint over the world, under the UI, with
## the headlight beams cut out of it so they show the scene as in daylight -
## Pygame restores its pre-tint copy inside the beam mask. Buildings are no
## part of a beam (Pygame masks them out): the beam polygons arrive already
## clipped, and a building wholly inside a beam is tinted again here.
##
## One CanvasGroup in the world at z 20: above the map and entities (and the
## fuel boards, z 11), below the street lights (z 21) Pygame adds after it.
## Redrawn when the view, the tint or the beams change: at night, every frame
## a vehicle moves; by day, never.
extends CanvasGroup

const TINT := Color8(10, 18, 48)
# The group's buffer keeps colour but, in the compatibility renderer, only a
# few alpha levels (0.451 came back 0.333): the tint is painted opaque inside
# and this shader gives it its alpha - wherever the buffer holds the tint
# colour, i.e. everywhere but the cleared beams.
const SHADER := """shader_type canvas_item;
uniform float tint_alpha;
uniform sampler2D screen_texture : hint_screen_texture, repeat_disable, filter_nearest;
void fragment() {
	vec4 c = textureLod(screen_texture, SCREEN_UV, 0.0);
	COLOR = vec4(c.rgb, c.b > 0.02 ? tint_alpha : 0.0);
}"""

var alpha := 0.0  # 0..1, main.gd: Main.night_alpha(darkness, visible roads)
var view := Rect2()  # the visible world area in layer coordinates
var _beams: Array = []  # PackedVector2Array: lit area (already clear of buildings)
var _retint: Array = []  # PackedVector2Array: buildings wholly inside a beam
var _tint: Node2D  # children made in _ready; the tint is a child: the group doesn't render its own draws
var _holes: Node2D
var _roofs: Node2D


func _ready() -> void:
	z_index = 20
	var shader := Shader.new()
	shader.code = SHADER
	material = ShaderMaterial.new()
	material.shader = shader
	_tint = Node2D.new()
	_holes = Node2D.new()
	_roofs = Node2D.new()
	_tint.draw.connect(func(): _tint.draw_rect(view, TINT))
	add_child(_tint)
	var subtract := CanvasItemMaterial.new()
	subtract.blend_mode = CanvasItemMaterial.BLEND_MODE_SUB  # white clears the tint, colour and alpha
	_holes.material = subtract
	_holes.draw.connect(_draw_holes)
	add_child(_holes)
	_roofs.draw.connect(_draw_roofs)
	add_child(_roofs)


## This frame's tint and beams; redraws only on a change.
func show_night(new_alpha: float, new_view: Rect2, beams: Array, retint: Array) -> void:
	if is_equal_approx(new_alpha, alpha) and new_view == view and beams == _beams and retint == _retint:
		return
	alpha = new_alpha
	view = new_view
	_beams = beams
	_retint = retint
	visible = alpha > 0.0
	if _tint == null:
		return
	material.set_shader_parameter("tint_alpha", alpha)
	_tint.queue_redraw()
	_holes.queue_redraw()
	_roofs.queue_redraw()


func _draw_holes() -> void:
	for polygon in _beams:
		_holes.draw_colored_polygon(polygon, Color.WHITE)


func _draw_roofs() -> void:
	for polygon in _retint:
		_roofs.draw_colored_polygon(polygon, TINT)


## The beam polygons minus `buildings` ([Rect2, outline], Geometry2D, no
## holes): pieces of the beams to light, and the buildings lying wholly
## inside one (to tint again over the cleared beam). Each beam is only
## clipped by the buildings its bounding box meets. [lit pieces, retint]
static func clip_beams(beams: Array, buildings: Array) -> Array:
	var lit: Array = []
	var retint: Array = []
	for beam in beams:
		var pieces: Array = [beam]
		var box := Rect2(beam[0], Vector2.ZERO)
		for point in beam:
			box = box.expand(point)
		for entry in buildings:
			if not entry[0].intersects(box):
				continue
			var building: PackedVector2Array = entry[1]
			var next: Array = []
			for piece in pieces:
				var parts := Geometry2D.clip_polygons(piece, building)
				var has_hole := false
				for part in parts:
					if Geometry2D.is_polygon_clockwise(part) != Geometry2D.is_polygon_clockwise(piece):
						has_hole = true
				if has_hole:  # the building is inside this piece: keep it, tint the building again
					next.append(piece)
					if not retint.has(building):
						retint.append(building)
				else:
					next.append_array(parts)
			pieces = next
		for piece in pieces:  # clipping can leave slivers that don't triangulate: nothing to light there
			if piece.size() >= 3 and not Geometry2D.triangulate_polygon(piece).is_empty():
				lit.append(piece)
	return [lit, retint]
