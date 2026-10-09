## Movable HUD panels (main()'s hud_layout / hud_dragging, more panels):
## each panel is drawn at its default rectangle plus the offset the player
## dragged it by, always kept whole on screen; U (or F2) resets them all.
## The offsets are saved to user://hud_layout.cfg.
extends RefCounted

const PATH := "user://hud_layout.cfg"

var offsets := {}  # panel name -> Vector2 from its default position
var rects := {}  # panel name -> Rect2 where it was drawn last
var _dragging := ""
var _store := ConfigFile.new()


func _init(load_saved := true) -> void:
	if load_saved and _store.load(PATH) == OK:
		for name in _store.get_section_keys("offsets") if _store.has_section("offsets") else []:
			var value = _store.get_value("offsets", name)
			if value is Vector2:
				offsets[name] = value


## Where a panel goes this frame: its default rectangle moved by its offset,
## pushed back inside `screen` (the offset follows, so a panel dragged
## against an edge comes straight back when dragged the other way).
func place(name: String, default_rect: Rect2, screen: Vector2) -> Rect2:
	var rect := clamp_rect(Rect2(default_rect.position + offsets.get(name, Vector2.ZERO), default_rect.size), screen)
	if offsets.has(name):
		offsets[name] = rect.position - default_rect.position
	rects[name] = rect
	return rect


static func clamp_rect(rect: Rect2, screen: Vector2) -> Rect2:
	var top_left := Vector2(clampf(rect.position.x, 0.0, maxf(0.0, screen.x - rect.size.x)),
		clampf(rect.position.y, 0.0, maxf(0.0, screen.y - rect.size.y)))
	return Rect2(top_left, rect.size)


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
			_dragging = panel_at(event.position)
			return _dragging != ""
		if _dragging != "":
			_dragging = ""
			save()
			return true
	elif event is InputEventMouseMotion and _dragging != "":
		offsets[_dragging] = offsets.get(_dragging, Vector2.ZERO) + event.relative
		return true
	return false


func reset() -> void:
	offsets.clear()
	_dragging = ""
	save()


func save() -> void:
	_store.clear()
	for name in offsets:
		_store.set_value("offsets", name, offsets[name])
	_store.save(PATH)
