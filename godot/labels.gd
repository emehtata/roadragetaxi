## Map labels (render/labels.py draw_labels), one screen-space overlay over
## the world and under the HUD. The server sends each chunk's candidates
## ([x, y, text, category]); this declutters per view as Pygame does: by
## priority (districts, waters, areas, buildings, roads), each name once,
## no overlaps, at most 35, buildings from 0.45 px/m and roads from
## 0.35 px/m. Redrawn when the view moves 16 px, the zoom or the loaded
## chunks change - not per frame.
extends Control

const MAX_LABELS := 35
const STYLES := [  # [text colour, background, border or null, font size] per category
	[Color8(255, 230, 120), Color8(30, 25, 10, 220), Color8(200, 170, 70), 15],  # district
	[Color8(160, 225, 255), Color8(10, 30, 50, 210), null, 15],  # water
	[Color8(190, 255, 190), Color8(15, 45, 15, 210), null, 15],  # named area
	[Color8(255, 225, 135), Color8(45, 30, 12, 220), Color8(205, 150, 55), 16],  # building
	[Color8(255, 255, 255), Color8(25, 25, 25, 210), null, 15],  # road
]
const MIN_PX_PER_M := [0.0, 0.0, 0.0, 0.45, 0.35]

const MODE_NAMES := ["OFF", "STREETS", "ALL"]
var mode := 0  # L cycles main()'s label_mode: 0 none (Pygame's start), 1 street names, 2 everything
var map_layer: Node2D  # MapLayer: the loaded chunks and their labels
var _font: Font
var _key := []  # what the last drawing was for: [view cell, zoom, chunks]
var _transform := Transform2D()


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_font = ThemeDB.fallback_font


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_L:
		mode = (mode + 1) % 3
		_key = []  # redraw now


## main.gd, each frame: redraw when the view has moved 16 px, or the zoom
## or the chunks changed.
func update_view(canvas: Transform2D, chunk_count: int, hidden: bool) -> void:
	var key := [Vector2i((canvas.origin / 16.0).floor()), snappedf(canvas.x.x, 0.0001), chunk_count, hidden, mode]
	if key == _key:
		return
	_key = key
	_transform = canvas
	visible = not hidden and mode > 0
	queue_redraw()


static var _sizes := {}  # [text, font size] -> pixel size (godot-18: measured once, not every redraw)


static func text_size(font: Font, text: String, font_size: int) -> Vector2:
	var key := "%d|%s" % [font_size, text]
	if not _sizes.has(key):
		_sizes[key] = font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	return _sizes[key]


## The labels to show for a view: [[screen position, text, category], ...]
## in Pygame's order and rules. `candidates` are [x, y, text, category] in
## layer coordinates.
static func declutter(candidates: Array, canvas: Transform2D, screen: Vector2, font: Font, label_mode := 2) -> Array:
	var px_per_m := canvas.x.x
	var by_category := [[], [], [], [], []]
	for label in candidates:
		by_category[clampi(int(label[3]), 0, 4)].append(label)
	var placed: Array = []
	var rects: Array = []
	var seen := {}
	for category in 5:
		if label_mode <= 0 or label_mode == 1 and category != 4:  # render/labels.py: mode 1 draws only road names
			continue
		if px_per_m < MIN_PX_PER_M[category]:
			continue
		for label in by_category[category]:
			if placed.size() >= MAX_LABELS:
				return placed
			var text: String = label[2]
			if seen.has(text):
				continue
			var at: Vector2 = canvas * Vector2(label[0], label[1])
			if at.x < 10.0 or at.x > screen.x - 10.0 or at.y < 80.0 or at.y > screen.y - 20.0:
				continue
			var size := text_size(font, text, STYLES[category][3]) + Vector2(10, 6)
			var box := Rect2(at - size / 2.0, size)
			if rects.any(func(r): return r.intersects(box)):
				continue
			rects.append(box)
			seen[text] = true
			placed.append([box, text, category])
	return placed


func _draw() -> void:
	if map_layer == null:
		return
	var started := Time.get_ticks_usec()
	# godot-18: only the chunks under the view, their label positions converted once per chunk.
	var view := _transform.affine_inverse() * Rect2(Vector2.ZERO, size)
	var candidates: Array = []
	for chunk in map_layer._chunks.values():
		if chunk._bounds_rect.size == Vector2.ZERO or chunk._bounds_rect.intersects(view):
			candidates.append_array(chunk.label_candidates())
	for label in declutter(candidates, _transform, size, _font, mode):
		var style: Array = STYLES[label[2]]
		var box: Rect2 = label[0]
		draw_rect(box, style[1])
		if style[2] != null:
			draw_rect(box, style[2], false, 1.0)
		draw_string(_font, box.position + Vector2(5, 3 + _font.get_ascent(style[3])), label[1], HORIZONTAL_ALIGNMENT_LEFT, -1, style[3], style[0])
	preload("res://perf.gd").add("labels_draw", Time.get_ticks_usec() - started)
