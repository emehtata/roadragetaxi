## Deferred layout and actual GUI clicks in the shared compact phone.
## godot --headless --path godot --script res://tests/phone_apps.gd
extends SceneTree


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(1280, 720)
	root.add_child(viewport)
	var phone := Phone.new()
	viewport.add_child(phone)
	phone.set_connected(true)
	phone.open()
	var offers: Array = []
	for i in 3:
		offers.append({"id": "offer-%d" % i, "kind": "offer", "status": "AVAILABLE", "name": "Aino", "pickup": "Kirkkokatu", "dropoff": "Rautatientori"})
	phone.show_phone({"busy": false, "items": offers})
	await process_frame
	await process_frame
	assert(phone.size == Phone.DEVICE_SIZE, "fare picker must not stretch the device")
	var card: Button = phone._rows.get_child(1)
	var click := InputEventMouseButton.new()
	click.position = card.get_global_rect().get_center()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	assert(phone.layout.panel_at(click.position) == "", "dragging must not intercept cards")
	viewport.push_input(click)
	click = click.duplicate()
	click.pressed = false
	viewport.push_input(click)
	assert(phone.selected_id == "offer-1", "compact offer cards must be clickable")
	var requests: Array = []
	phone.request.connect(func(action, item_id, request_id): requests.append([action, item_id, request_id]))
	click = click.duplicate()
	click.position = phone._accept.get_global_rect().get_center()
	click.pressed = true
	viewport.push_input(click)
	click = click.duplicate()
	click.pressed = false
	viewport.push_input(click)
	assert(requests == [["accept", "offer-1", 1]], "compact accept button sends the selected offer")
	phone.handle_result({"request_id": 1, "action": "accept", "ok": true})
	assert(phone.is_open, "accepting a fare keeps the shared phone open")
	var position := phone.position
	phone.show_phone({"busy": true, "items": []})
	await process_frame
	await process_frame
	assert(phone.size == Phone.DEVICE_SIZE and phone.position == position, "navigation keeps the same device size and position")
	assert(phone.navigation.visible and not phone._offers.visible)
	phone.show_phone({"busy": false, "items": offers})
	await process_frame
	await process_frame
	assert(phone.size == Phone.DEVICE_SIZE and phone.position == position, "returning to offers keeps device geometry")
	assert(phone._offers.visible and not phone.navigation.visible)
	viewport.free()
	print("Shared phone layout and GUI clicks passed")
	quit()
