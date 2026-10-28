## A slippy map of OpenStreetMap tiles for picking the gig's exact start:
## drag or arrow keys pan, the wheel or +/- zoom, a click sets the pin.
## Tiles are cached under user://tiles (the OSM tile policy asks for it).
extends Control

signal picked(latitude: float, longitude: float)

const TILE := 256
const TILE_URL := "https://tile.openstreetmap.org/%d/%d/%d.png"
const MIN_ZOOM := 5
const MAX_ZOOM := 18
const MAX_REQUESTS := 4  # in flight at once (the tile policy: few connections)

var zoom := 13
var center := Vector2.ZERO  # the view centre, in tile pixels at `zoom`
var pin := Vector2.INF  # the picked point as (latitude, longitude); INF: none yet
var _tiles := {}  # "z/x/y" -> Texture2D, or null while it loads
var _queue: Array[String] = []
var _requests := 0
var _failed := {}  # "z/x/y" -> [failures, retry at (msec)]: a failed tile is asked again later, not never
const RETRY_LIMIT := 5
const RETRY_FIRST_MS := 1000  # then doubling
var _warned := 0
var _dragged := false


static func to_pixels(latitude: float, longitude: float, z: int) -> Vector2:
	var n := float(TILE << z)
	var lat := deg_to_rad(clampf(latitude, -85.0, 85.0))
	return Vector2((longitude + 180.0) / 360.0 * n, (1.0 - log(tan(lat) + 1.0 / cos(lat)) / PI) / 2.0 * n)


static func to_latlon(pixels: Vector2, z: int) -> Vector2:
	var n := float(TILE << z)
	return Vector2(rad_to_deg(atan(sinh(PI * (1.0 - 2.0 * pixels.y / n)))), pixels.x / n * 360.0 - 180.0)


func _init() -> void:
	clip_contents = true
	focus_mode = Control.FOCUS_ALL
	custom_minimum_size = Vector2(720, 440)


func show_point(latitude: float, longitude: float) -> void:
	center = to_pixels(latitude, longitude, zoom)
	queue_redraw()


func _zoom_at(step: int, at: Vector2) -> void:
	var new_zoom := clampi(zoom + step, MIN_ZOOM, MAX_ZOOM)
	if new_zoom == zoom:
		return
	var anchor := center + at - size / 2.0  # the point under the cursor stays put
	var scale := pow(2.0, new_zoom - zoom)
	center = anchor * scale - (at - size / 2.0)
	zoom = new_zoom
	queue_redraw()


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		match event.button_index:
			MOUSE_BUTTON_WHEEL_UP:
				_zoom_at(1, event.position)
			MOUSE_BUTTON_WHEEL_DOWN:
				_zoom_at(-1, event.position)
			MOUSE_BUTTON_LEFT:
				_dragged = false
				grab_focus()
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and not _dragged:
		_pick(to_latlon(center + event.position - size / 2.0, zoom))  # a click, not the end of a drag
	elif event is InputEventMouseMotion and event.button_mask & MOUSE_BUTTON_MASK_LEFT:
		_dragged = _dragged or event.relative.length() > 1.0
		center -= event.relative
		queue_redraw()
	elif event is InputEventKey and event.pressed:
		var pan := {KEY_LEFT: Vector2.LEFT, KEY_RIGHT: Vector2.RIGHT, KEY_UP: Vector2.UP, KEY_DOWN: Vector2.DOWN}
		if event.keycode in pan:
			center += pan[event.keycode] * 96.0
			queue_redraw()
		elif event.keycode in [KEY_EQUAL, KEY_KP_ADD]:
			_zoom_at(1, size / 2.0)
		elif event.keycode in [KEY_MINUS, KEY_KP_SUBTRACT]:
			_zoom_at(-1, size / 2.0)
		elif event.keycode == KEY_SPACE:  # keyboard/controller: the pin at the view centre
			_pick(to_latlon(center, zoom))
		else:
			return
		accept_event()


func _pick(point: Vector2) -> void:
	pin = point
	queue_redraw()
	picked.emit(point.x, point.y)


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color8(170, 211, 223))
	var origin := center - size / 2.0
	var count := 1 << zoom
	var wanted: Array[String] = []
	for ty in range(floori(origin.y / TILE), floori((origin.y + size.y) / TILE) + 1):
		if ty < 0 or ty >= count:
			continue
		for tx in range(floori(origin.x / TILE), floori((origin.x + size.x) / TILE) + 1):
			var key := "%d/%d/%d" % [zoom, posmod(tx, count), ty]
			var texture: Texture2D = _tiles.get(key)
			if texture != null:
				draw_texture(texture, Vector2(tx, ty) * TILE - origin)
			elif not _tiles.has(key) and (not _failed.has(key) or Time.get_ticks_msec() >= _failed[key][1]):
				wanted.append(key)
	_queue = wanted  # tiles scrolled out of view are no longer fetched
	_fetch()
	if pin != Vector2.INF:
		var at := to_pixels(pin.x, pin.y, zoom) - origin
		draw_circle(at, 9.0, Color.BLACK)
		draw_circle(at, 7.0, Color8(255, 205, 26))
	var font := get_theme_default_font()
	var credit := "© OpenStreetMap contributors"  # required by the tile licence
	var width := font.get_string_size(credit, HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x
	draw_rect(Rect2(size - Vector2(width + 8.0, 18.0), Vector2(width + 8.0, 18.0)), Color(1, 1, 1, 0.75))
	draw_string(font, size - Vector2(width + 4.0, 5.0), credit, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color.BLACK)


## A tile's answer: cached and shown, or asked again later (a few times,
## further apart: offline, no hammering).
func _tile_loaded(key: String, path: String, result: int, code: int, body: PackedByteArray) -> void:
	var image := Image.new()
	if result == HTTPRequest.RESULT_SUCCESS and code == 200 and image.load_png_from_buffer(body) == OK:
		_tiles[key] = ImageTexture.create_from_image(image)
		_failed.erase(key)
		DirAccess.make_dir_recursive_absolute(path.get_base_dir())
		image.save_png(path)
	else:
		_tiles.erase(key)
		var failures: int = _failed.get(key, [0, 0])[0] + 1
		_failed[key] = [failures, Time.get_ticks_msec() + RETRY_FIRST_MS * (1 << (failures - 1)) if failures < RETRY_LIMIT else 1 << 62]
		if _warned < 3:
			_warned += 1
			push_warning("Map tile %s failed: result %d, HTTP %d" % [key, result, code])
	queue_redraw()


func _process(_delta: float) -> void:
	if not _failed.is_empty() and Engine.get_process_frames() % 30 == 0:
		queue_redraw()  # a failed tile's retry time may have come


func _fetch() -> void:
	while _requests < MAX_REQUESTS and not _queue.is_empty():
		var key: String = _queue.pop_back()
		_tiles[key] = null
		var path := "user://tiles/%s.png" % key
		if FileAccess.file_exists(path):
			var cached := Image.load_from_file(path)
			if cached != null and not cached.is_empty():
				_tiles[key] = ImageTexture.create_from_image(cached)
				queue_redraw()
				continue
			DirAccess.remove_absolute(path)  # a damaged cache file: fetched again, not blank for good
		var parts := key.split("/")
		var request := HTTPRequest.new()
		add_child(request)
		_requests += 1
		request.request_completed.connect(func(result: int, code: int, _headers, body: PackedByteArray):
			request.queue_free()
			_requests -= 1
			_tile_loaded(key, path, result, code, body))
		var agent := "RoadRageTrip/%s (Godot)" % ProjectSettings.get_setting("application/config/version")
		if request.request(TILE_URL % [int(parts[0]), int(parts[1]), int(parts[2])], ["User-Agent: " + agent]) != OK:
			request.queue_free()  # refused at once: no completion signal will come to free the slot
			_requests -= 1
			_tile_loaded(key, path, HTTPRequest.RESULT_CANT_CONNECT, 0, PackedByteArray())
