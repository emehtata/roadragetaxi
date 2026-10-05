## The night (render/hud.py draw_day_night_overlay, render/vehicles.py
## draw_headlight_beams): a dark-blue tint over the world, under the UI, with
## the headlight beams cut out of it so they show the scene as in daylight -
## Pygame restores its pre-tint copy inside the beam mask. Buildings are no
## part of a beam (Pygame masks them out): the beam polygons arrive already
## clipped, and a building wholly inside a beam is tinted again here.
##
## godot-18: drawn directly as polygons - the view minus the beams, at the
## tint's own alpha - not as a CanvasGroup with the beams subtracted from a
## full-screen tint: on a software renderer (llvmpipe) the group's
## screen-sized copy and composite cost ~20 ms a frame at night.
##
## In the world at z 20: above the map and entities (and the fuel boards),
## below the street lights (z 21) Pygame adds after it. Redrawn when the
## view, the tint or the beams change: at night, every frame a vehicle
## moves; by day, never.
extends Node2D

const TINT := Color8(10, 18, 48)

var alpha := 0.0  # 0..1, main.gd: Main.night_alpha(darkness, visible roads)
var view := Rect2()  # the visible world area in layer coordinates
var _beams: Array = []  # PackedVector2Array: lit area (already clear of buildings)
var _retint: Array = []  # PackedVector2Array: buildings wholly inside a beam


func _ready() -> void:
	z_index = 20


## This frame's tint and beams; redraws only on a change.
func show_night(new_alpha: float, new_view: Rect2, beams: Array, retint: Array) -> void:
	if is_equal_approx(new_alpha, alpha) and new_view == view and beams == _beams and retint == _retint:
		return
	alpha = new_alpha
	view = new_view
	_beams = beams
	_retint = retint
	visible = alpha > 0.0
	queue_redraw()


func _draw() -> void:
	var color := Color(TINT, alpha)
	for piece in tint_pieces(view, _beams):
		if piece.size() >= 3 and not Geometry2D.triangulate_polygon(piece).is_empty():
			draw_colored_polygon(piece, color)
	for polygon in _retint:  # buildings inside a beam: tinted after all (their area was cut out with the beam)
		draw_colored_polygon(polygon, color)


## The view rectangle minus the beams, as polygons without holes (Godot
## draws no polygon with a hole): a piece a beam lies wholly inside is
## first split in two through the beam, so the cut reaches its edge.
static func tint_pieces(rect: Rect2, beams: Array) -> Array:
	var pieces: Array = [PackedVector2Array([rect.position, Vector2(rect.end.x, rect.position.y), rect.end, Vector2(rect.position.x, rect.end.y)])]
	for beam in beams:
		var box := _bounds(beam)
		var next: Array = []
		for piece in pieces:
			if not _bounds(piece).intersects(box):
				next.append(piece)
				continue
			next.append_array(_subtract(piece, beam, box, 2))
		pieces = next
	return pieces


static func _subtract(piece: PackedVector2Array, beam: PackedVector2Array, box: Rect2, splits: int) -> Array:
	var parts := Geometry2D.clip_polygons(piece, beam)
	if not has_hole(parts):
		return parts
	if splits == 0:
		return [piece]  # can't cut it cleanly: leave it tinted (never seen in practice)
	var x := box.get_center().x
	var out: Array = []
	var far := 1e6
	for half in [PackedVector2Array([Vector2(-far, -far), Vector2(x, -far), Vector2(x, far), Vector2(-far, far)]),
			PackedVector2Array([Vector2(x, -far), Vector2(far, -far), Vector2(far, far), Vector2(x, far)])]:
		for side in Geometry2D.intersect_polygons(piece, half):
			out.append_array(_subtract(side, beam, box, splits - 1))
	return out


## Whether a clipping result holds a hole: Godot returns outer polygons in
## one orientation and holes in the other, whatever the inputs' winding -
## so a hole shows as mixed orientations (comparing with the input's own
## winding, as before, took every piece for a hole when the input wound
## the other way).
static func has_hole(parts: Array) -> bool:
	for part in parts:
		if Geometry2D.is_polygon_clockwise(part) != Geometry2D.is_polygon_clockwise(parts[0]):
			return true
	return false


static func _bounds(polygon: PackedVector2Array) -> Rect2:
	var box := Rect2(polygon[0], Vector2.ZERO)
	for point in polygon:
		box = box.expand(point)
	return box


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
				if has_hole(parts):  # the building is inside this piece: keep it, tint the building again
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
