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

var map_layer: Node2D  # MapLayer: the loaded chunks and their labels
var _font: Font
var _key := []  # what the last drawing was for: [view cell, zoom, chunks]
var _transform := Transform2D()


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_font = ThemeDB.fallback_font


## main.gd, each frame: redraw when the view has moved 16 px, or the zoom
## or the chunks changed.
func update_view(canvas: Transform2D, chunk_count: int, hidden: bool) -> void:
	var key := [Vector2i((canvas.origin / 16.0).floor()), snappedf(canvas.x.x, 0.0001), chunk_count, hidden]
	if key == _key:
		return
	_key = key
	_transform = canvas
	visible = not hidden
	queue_redraw()


## The labels to show for a view: [[screen position, text, category], ...]
## in Pygame's order and rules. `candidates` are [x, y, text, category] in
## layer coordinates.
static func declutter(candidates: Array, canvas: Transform2D, screen: Vector2, font: Font) -> Array:
	var px_per_m := canvas.x.x
	var by_category := [[], [], [], [], []]
	for label in candidates:
		by_category[clampi(int(label[3]), 0, 4)].append(label)
	var placed: Array = []
	var rects: Array = []
	var seen := {}
	for category in 5:
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
			var size := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, STYLES[category][3]) + Vector2(10, 6)
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
	var candidates: Array = []
	for chunk in map_layer._chunks.values():
		for label in chunk._data.get("labels", []):
			candidates.append([MapMath.point(map_layer.origin, label[0], label[1]).x, MapMath.point(map_layer.origin, label[0], label[1]).y, label[2], label[3]])
	for label in declutter(candidates, _transform, size, _font):
		var style: Array = STYLES[label[2]]
		var box: Rect2 = label[0]
		draw_rect(box, style[1])
		if style[2] != null:
			draw_rect(box, style[2], false, 1.0)
		draw_string(_font, box.position + Vector2(5, 3 + _font.get_ascent(style[3])), label[1], HORIZONTAL_ALIGNMENT_LEFT, -1, style[3], style[0])
