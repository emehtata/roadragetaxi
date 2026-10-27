## Run with isolated settings: XDG_DATA_HOME=$(mktemp -d) godot --path godot --script res://tests/settings_keyboard.gd
extends SceneTree

class MenuShell:
	extends "res://startup.gd"
	var launched := {}
	func _start(mode: String, _skip_pbf_offer := false) -> void:
		launched = {"mode": mode, "time": _start_time.duplicate()}

var shell: Control
var checks := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok:
		printerr("FAIL: ", message)
		quit(1)
		assert(ok, message)

func key(code: Key, shift := false) -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = code
		if code == KEY_A:
			event.unicode = 97
		event.pressed = pressed
		event.shift_pressed = shift
		Input.parse_input_event(event)
		await process_frame

func show_menu(category: String) -> void:
	shell.call("_" + category + "_menu")
	await process_frame
	await process_frame

func test_calendar() -> void:
	shell._language = "en"
	var today := Time.get_date_dict_from_system()
	var resume := Time.get_date_dict_from_unix_time(int(Time.get_unix_time_from_datetime_dict(today)) - 40 * 86400)
	resume.day = 15
	resume.hour = 8
	resume.minute = 30
	shell._settings.set_value("gig", "left_at", resume)
	shell._settings.set_value("gig", "start_now", false)
	await show_menu("time")
	check(shell._start_time.day == 15 and shell._start_time.hour == 8 and shell._start_time.minute == 30, "time: resumes the saved date and time")
	var calendar = shell._body.get_child(2)
	calendar.grab_focus()
	await key(KEY_LEFT)
	check(shell._start_time.day == calendar.value.day and not shell._settings.get_value("gig", "start_now"), "calendar: arrows update chosen start date")
	var previous_stamp: int = calendar._stamp(calendar.value)
	await key(KEY_UP)
	check(calendar._stamp(calendar.value) == previous_stamp - 7 * 86400, "calendar: Up moves one week")
	await key(KEY_DOWN)
	check(calendar._stamp(calendar.value) == previous_stamp, "calendar: Down moves one week")
	await key(KEY_PAGEUP)
	check(calendar._stamp(calendar.value) < previous_stamp, "calendar: PageUp changes month")
	await key(KEY_PAGEDOWN)
	check(calendar._stamp(calendar.value) == previous_stamp, "calendar: PageDown returns to month")
	await key(KEY_TAB)
	var hours = root.gui_get_focus_owner()
	check(hours is LineEdit, "calendar: Tab leaves grid for hour")
	hours.text = "7"
	await key(KEY_ENTER)
	check(shell._start_time.hour == 7, "time: typed hour applies with Enter")
	await key(KEY_TAB)
	var minutes = root.gui_get_focus_owner()
	check(minutes is LineEdit and minutes != hours, "time: Tab reaches minute")
	minutes.text = "15"
	await key(KEY_ENTER)
	check(shell._start_time.minute == 15, "time: typed minute applies with Enter")
	await key(KEY_TAB)
	await key(KEY_TAB)
	await key(KEY_ENTER)
	check(shell.launched.mode == "gig_driver" and shell.launched.time.hour == 7 and shell.launched.time.minute == 15 and shell.launched.time.day == calendar.value.day, "time: Start receives selected date and typed time")
	await key(KEY_TAB, true)
	await key(KEY_ENTER)
	check(shell._settings.get_value("gig", "start_now") and calendar.value.day == Time.get_date_dict_from_system().day, "time: keyboard Now restores current date")
	calendar.previous.grab_focus()
	await key(KEY_ENTER)
	calendar.next.grab_focus()
	await key(KEY_ENTER)
	check(calendar.next.disabled and root.gui_get_focus_owner() == calendar, "calendar: month navigation retains focus at the date limit")
	var visited := []
	for i in 8:
		visited.append(root.gui_get_focus_owner())
		await key(KEY_TAB)
	check(calendar in visited and hours in visited and minutes in visited, "time: Tab traverses calendar and time controls")
	for language in ["en", "fi", "de"]:
		shell._language = language
		await show_menu("time")
		calendar = shell._body.get_child(2)
		calendar.grab_focus()
		if DisplayServer.get_name() != "headless":
			await RenderingServer.frame_post_draw
			root.get_texture().get_image().save_png("/tmp/calendar-%s.png" % language)
	await key(KEY_ESCAPE)
	check(shell._back_action == Callable(shell, "_main_menu"), "time: Escape returns to city menu")


func run() -> void:
	shell = MenuShell.new()
	root.add_child(shell)
	await process_frame
	shell._settings = ConfigFile.new()
	shell._language = "en"
	for category in ["settings", "general", "gameplay", "graphics", "audio", "maps", "pbf"]:
		await show_menu(category)
		var controls: Array[Control] = []
		for node in shell._body.find_children("*", "Control", true, false):
			if node.focus_mode == Control.FOCUS_ALL and node.is_visible_in_tree() and not (node is BaseButton and node.disabled):
				controls.append(node)
		var visited := []
		for i in controls.size():
			visited.append(root.gui_get_focus_owner())
			await key(KEY_TAB)
		check(controls.all(func(c): return c in visited), category + ": Tab reaches every visible enabled control")
		check(root.gui_get_focus_owner() == visited[0], category + ": Tab wraps")
		await key(KEY_TAB, true)
		check(root.gui_get_focus_owner() == visited[-1], category + ": Shift+Tab reverses")
		for control in controls:
			if control is Button and control.text == "?":
				control.grab_focus()
				var help = control.get_parent().get_parent().get_child(1)
				await key(KEY_ENTER)
				check(help.visible, category + ": Enter opens help")
				await key(KEY_SPACE)
				check(not help.visible, category + ": Space closes help")
		await key(KEY_ESCAPE)
		check(not shell._back_action.is_valid() if category == "settings" else shell._back_action == Callable(shell, "_settings_menu" if category == "pbf" else "_main_menu"), category + ": Escape returns to parent")
	await show_menu("settings")
	await key(KEY_ENTER)
	check(shell._focusables[0] is OptionButton, "Enter opens General")
	await key(KEY_ENTER)
	await key(KEY_DOWN)
	await key(KEY_ENTER)
	await process_frame
	check(shell._language == "fi", "keyboard changes language")
	await show_menu("gameplay")
	for toggle in shell._focusables:
		if toggle is CheckButton:
			toggle.grab_focus()
			var before: bool = toggle.button_pressed
			await key(KEY_SPACE)
			check(toggle.button_pressed != before, "Space changes gameplay: " + toggle.text)
	await show_menu("graphics")
	for control in shell._focusables:
		if control is CheckButton and not control.disabled:
			control.grab_focus()
			var old: bool = control.button_pressed
			await key(KEY_SPACE)
			check(control.button_pressed != old, "Space changes graphics: " + control.text)
	await show_menu("audio")
	for slider in shell._focusables:
		if slider is HSlider:
			slider.grab_focus()
			slider.value = 0.5
			await key(KEY_RIGHT)
			check(slider.value > 0.5, "Right adjusts " + slider.get_parent().get_child(0).text)
			await key(KEY_LEFT)
			check(is_equal_approx(slider.value, 0.5), "Left adjusts volume")
	await show_menu("maps")
	await key(KEY_ENTER)
	await key(KEY_DOWN)
	await key(KEY_ENTER)
	var path = shell._focusables[1]
	check(path.is_visible_in_tree(), "keyboard selects local map source")
	await key(KEY_TAB)
	await key(KEY_TAB)
	check(root.gui_get_focus_owner() == path, "Tab reaches revealed PBF path")
	path.clear()
	await key(KEY_A)
	check(path.text == "a", "keyboard edits PBF path")
	# The in-game Escape branch must follow Back before accessing game internals.
	shell._game = Node.new()
	await show_menu("audio")
	await key(KEY_ESCAPE)
	check(shell._back_action == Callable(shell, "_pause_menu"), "in-game Escape returns to settings categories")
	shell._game.free()
	shell._game = null
	await test_calendar()
	await show_menu("gameplay")
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("/tmp/settings-keyboard.png")
	print("SETTINGS KEYBOARD: %d checks passed" % checks)
	shell.free()
	quit()
