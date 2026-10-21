## Movable, resizable HUD panels:
## each panel is drawn at its default rectangle plus the offset the player
## dragged it by, at the scale the player resized it to (dragging its
## bottom-right corner), always kept whole on screen; U (or F2) resets them
## all. The offsets and scales are saved to user://hud_layout.cfg.
extends RefCounted

const PATH := "user://hud_layout.cfg"

var offsets := {}  # panel name -> Vector2 from its default position
var scales := {}  # panel name -> its size factor (1: default)
var rects := {}  # panel name -> Rect2 where it was drawn last: dragging it moves it
var bounds := {}  # panel name -> its whole drawn Rect2: the bottom-right corner resizes it
var _dragging := ""
var _resizing := ""
var _resize_width := 0.0  # the resized panel's width as the mouse would have it
var _resize_base := 1.0  # its unscaled width, taken when the resize began

const MIN_SCALE := 0.6
const MAX_SCALE := 2.0
const GRIP := 16.0  # px: the corner square that resizes instead of moves
var _store := ConfigFile.new()
var _persist := true  # false: never reads or writes the player's saved layout (tests, defaults)


func _init(load_saved := true) -> void:
	_persist = load_saved
	if load_saved and _store.load(PATH) == OK:
		for name in _store.get_section_keys("offsets") if _store.has_section("offsets") else []:
			var value = _store.get_value("offsets", name)
			if value is Vector2:
				offsets[name] = value
		for name in _store.get_section_keys("scales") if _store.has_section("scales") else []:
			var value = _store.get_value("scales", name)
			if value is float:
				scales[name] = clampf(value, MIN_SCALE, MAX_SCALE)


func scale_of(name: String) -> float:
	return scales.get(name, 1.0)


## Where a panel goes this frame: its default rectangle moved by its offset,
## pushed back inside `screen` (the offset follows, so a panel dragged
## against an edge comes straight back when dragged the other way).
## `default_rect.size` is the unscaled size; the result is scaled.
func place(name: String, default_rect: Rect2, screen: Vector2) -> Rect2:
	var rect := clamp_rect(Rect2(default_rect.position + offsets.get(name, Vector2.ZERO), default_rect.size * scale_of(name)), screen)
	if offsets.has(name):
		offsets[name] = rect.position - default_rect.position
	rects[name] = rect
	bounds[name] = rect
	return rect


static func clamp_rect(rect: Rect2, screen: Vector2) -> Rect2:
	var top_left := Vector2(clampf(rect.position.x, 0.0, maxf(0.0, screen.x - rect.size.x)),
		clampf(rect.position.y, 0.0, maxf(0.0, screen.y - rect.size.y)))
	return Rect2(top_left, rect.size)


func grip_at(point: Vector2) -> String:
	for name in bounds:
		var rect: Rect2 = bounds[name]
		if Rect2(rect.end - Vector2(GRIP, GRIP), Vector2(GRIP, GRIP)).has_point(point):
			return name
	return ""


func panel_at(point: Vector2) -> String:
	for name in rects:
		if rects[name].has_point(point):
			return name
	return ""


## Mouse: press on a panel picks it up, motion moves it, release drops it
## (and saves). True when the event was a panel's.
func handle(event: InputEvent) -> bool:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			_resizing = grip_at(event.position)
			if _resizing != "":
				_resize_width = bounds[_resizing].size.x
				_resize_base = maxf(1.0, _resize_width / scale_of(_resizing))
				return true
			_dragging = panel_at(event.position)
			return _dragging != ""
		if _dragging != "" or _resizing != "":
			_dragging = ""
			_resizing = ""
			save()
			return true
	elif event is InputEventMouseMotion and _resizing != "":
		# Uniform: the width follows the mouse, the height keeps the aspect.
		_resize_width += event.relative.x
		scales[_resizing] = clampf(_resize_width / _resize_base, MIN_SCALE, MAX_SCALE)
		return true
	elif event is InputEventMouseMotion and _dragging != "":
		offsets[_dragging] = offsets.get(_dragging, Vector2.ZERO) + event.relative
		return true
	return false


func reset() -> void:
	offsets.clear()
	scales.clear()
	_dragging = ""
	_resizing = ""
	save()


func save() -> void:
	if not _persist:
		return
	_store.clear()
	for name in offsets:
		_store.set_value("offsets", name, offsets[name])
	for name in scales:
		_store.set_value("scales", name, scales[name])
	_store.save(PATH)
