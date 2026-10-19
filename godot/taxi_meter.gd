## The taximeter: the live fare on a red seven-segment display, unlit
## segments faintly visible like a real LED meter. Redraws only when the
## fare changes. hud.gd places it (a draggable "meter" panel).
extends Control

const DIGITS := 6  # 9999.99 €
const W := 18.0  # one digit
const H := 32.0
const T := 4.0  # segment thickness
const GAP := 6.0
const PAD := 8.0
const ON := Color8(255, 60, 40)
const OFF := Color8(70, 18, 14)
# Segments a..g as bits 0..6.
const MASKS := [0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F]

var cents := -1:
	set(value):
		if value != cents:
			cents = value
			queue_redraw()


func _init() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE  # hud_layout drags it
	size = Vector2(PAD * 2.0 + DIGITS * (W + GAP) + 14.0, H + PAD * 2.0 + 12.0)


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color8(12, 12, 14, 235))
	draw_rect(Rect2(Vector2.ZERO, size), Color8(190, 200, 205), false, 1.0)
	draw_string(get_theme_default_font(), Vector2(PAD, PAD + 8.0), "TAXI  €", HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color8(190, 200, 205))
	var text := readout(cents)
	var x := PAD
	var y := PAD + 12.0
	for ch in text:
		if ch == ".":  # the decimal point sits between digits
			draw_rect(Rect2(x - GAP / 2.0 - T / 2.0, y + H - T, T, T), ON)
			continue
		_digit(Vector2(x, y), MASKS[int(ch)] if ch != " " else 0)
		x += W + GAP


## What the digits show: blank-padded euros, e.g. "  12.50".
static func readout(fare_cents: int) -> String:
	return "%*.2f" % [DIGITS + 1, maxi(fare_cents, 0) / 100.0]


func _digit(o: Vector2, mask: int) -> void:
	var half := (H - T) / 2.0
	var rects := [
		Rect2(o.x + T, o.y, W - 2.0 * T, T),  # a
		Rect2(o.x + W - T, o.y + T, T, half - T),  # b
		Rect2(o.x + W - T, o.y + half + T, T, half - T),  # c
		Rect2(o.x + T, o.y + H - T, W - 2.0 * T, T),  # d
		Rect2(o.x, o.y + half + T, T, half - T),  # e
		Rect2(o.x, o.y + T, T, half - T),  # f
		Rect2(o.x + T, o.y + half, W - 2.0 * T, T),  # g
	]
	for i in 7:
		draw_rect(rects[i], ON if mask & (1 << i) else OFF)
