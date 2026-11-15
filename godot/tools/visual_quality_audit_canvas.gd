## Audit-only supplemental canvas inspection through production draw methods.
extends SceneTree
const Chunk := preload("res://map_chunk.gd")
const Detail := preload("res://chunk_detail.gd")
const Holiday := preload("res://holiday_layer.gd")
var records: Array = []

func _initialize() -> void:
	create_timer(180).timeout.connect(func(): quit(1))
	call_deferred("run")

func draw_map(node: Node2D, chunk: Node2D, kind: String) -> void:
	match kind:
		"stop sign", "yield sign", "speed camera": Detail.draw_signs(chunk,node,null)
		"parking bay markings": Detail.draw_parking(chunk,node)
		"bus stop sign": Detail._draw_stop_sign(node,Vector2.ZERO)
		"volleyball court": Detail.draw_volleyball_courts(chunk,node)
		"tennis court": Detail.draw_tennis_courts(chunk,node)
		"soccer pitch": Detail.draw_soccer_markings(chunk,node)
		"ice hockey rink": Detail.draw_rink_markings(chunk,node)
		"wetland reeds": Detail.draw_wetland_ground(node,[[Vector2.ZERO,2.0,0],[Vector2(3,2),1.0,1],[Vector2(-2,-2),1.0,2]],0.0)
		"canopy feet": Detail.draw_canopy_feet(chunk,node)
		"track markings": Detail.draw_tracks(chunk,node,"railways")
		"ice floe": chunk._draw_ice_floe(node,{"at":Vector2.ZERO,"angle":0.4,"rx":3.0,"ry":1.8,"color":Color8(210,230,240)})

func run() -> void:
	var args := OS.get_cmdline_user_args()
	var fixture = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	root.size = Vector2i(800,600)
	RenderingServer.set_default_clear_color(Color("26343e"))
	Chunk.buildings_3d = false; Chunk.outdoor_3d = false
	var supported := ["stop sign","yield sign","speed camera","parking bay markings","bus stop sign","volleyball court","tennis court","soccer pitch","ice hockey rink","wetland reeds","canopy feet","track markings","ice floe","flags","bonfire","ghost","fireworks","Halloween lanterns"]
	var plans = JSON.parse_string(FileAccess.get_file_as_string("res://tests/data/home_plans.json"))
	for row: Dictionary in fixture["assets"]:
		var kind: String = row["name"]
		if kind not in supported and row["category"] != "Interior furniture" and kind != "electronic sign": continue
		var group := Node2D.new(); root.add_child(group)
		var chunk := Chunk.new()
		chunk._origin = Vector2.ZERO
		chunk._season = [1.0,0.0,0.0,0.0] if kind == "ice hockey rink" else [0.0,0.0,1.0,0.0]
		chunk._data = {"signs":[[0,0,"stop" if kind == "stop sign" else "yield",0]],"speed_cameras":[[1,0,0,0]],"parking":[[[-3,-5],[3,-5],[3,5],[-3,5]]],"volleyball_courts":[[0,0,0,9,4.5]],"tennis_courts":[[0,0,0,12,5.5]],"soccer_pitches":[[0,0,0,12,8]],"rinks":[[0,0,0,12,6]],"canopies":[[[-4,-3],[4,-3],[4,3],[-4,3]]],"railways":[[[-8,0],[8,0]]]}
		var node := Node2D.new(); group.add_child(node)
		var camera := Camera2D.new(); group.add_child(camera); camera.make_current()
		var helper: Node
		if row["category"] == "Interior furniture":
			var interior := preload("res://home_interior.gd").new()
			group.add_child(interior)
			var selected: Dictionary = plans[0].duplicate(true)
			for plan: Dictionary in plans:
				var items: Array = plan.get("furniture",[]).filter(func(item): return item["kind"] == kind)
				if not items.is_empty():
					selected = plan.duplicate(true); selected["furniture"] = items; break
			assert(not selected.get("furniture",[]).is_empty())
			interior.show_plan(selected)
		elif kind == "electronic sign":
			var sign := preload("res://electronic_signs.gd").new(); group.add_child(sign)
			sign.position = Vector2(180,180); sign.size = Vector2(440,160)
			sign.show_state([{"speed_limit_kmh":60,"text":["[tie_4] Oulu"],"id":"audit-1"},{"code":"142","text":["Roadworks"],"id":"audit-2"}],"en")
		elif kind in ["flags","bonfire","ghost","fireworks","Halloween lanterns"]:
			var holiday := Holiday.new(); helper = holiday; group.add_child(holiday)
			holiday.clock = 2.1; holiday.poles = PackedVector2Array([Vector2.ZERO]); holiday._flags = "full"; holiday._wind=Vector2(3,2)
			holiday.flag_layer=node; holiday.bonfire_layer=node; holiday.ghost_layer=node; holiday.bursts=node; holiday.decorations=node
			holiday.bonfires=PackedVector2Array([Vector2(0,3)]); holiday.ghosts=PackedVector2Array([Vector2.ZERO]); holiday.sites=PackedVector2Array([Vector2(0,18)]); holiday.yards=PackedVector2Array([Vector2.ZERO])
			node.draw.connect(holiday._draw_flags if kind == "flags" else holiday._draw_bonfires if kind == "bonfire" else holiday._draw_ghosts if kind == "ghost" else holiday._draw_fireworks if kind == "fireworks" else holiday._draw_decorations)
		else:
			node.draw.connect(draw_map.bind(node,chunk,kind))
		for distance in ["normal","close"]:
			var ppm := 12.0 if distance == "normal" else 18.0
			if kind in ["ghost","Halloween lanterns","bus stop sign","ice floe"]: ppm *= 3.0
			camera.zoom = Vector2.ONE*ppm
			if row["category"] == "Interior furniture" or kind == "electronic sign": camera.zoom=Vector2.ONE; camera.position=Vector2(400,300)
			chunk._px_per_m=ppm; node.queue_redraw()
			for i in 5: await process_frame
			await RenderingServer.frame_post_draw
			var filename := "%s_canvas_%s.png" % [row["id"],distance]
			var shot := root.get_texture().get_image()
			# A successful file save alone must not turn an empty canvas into evidence.
			var changed := 0
			var bg := shot.get_pixel(0,0)
			for x in range(0,800,4):
				for y in range(0,600,4):
					if absf(shot.get_pixel(x,y).r-bg.r)+absf(shot.get_pixel(x,y).g-bg.g)+absf(shot.get_pixel(x,y).b-bg.b) > 0.05: changed += 1
			if changed <= 5:
				records.append({"asset":row["id"],"angle":distance,"ready":false,"reason":"empty supplemental canvas"})
				continue
			assert(shot.save_png(args[1].path_join(filename)) == OK)
			records.append({"asset":row["id"],"file":filename,"angle":distance,"condition":"canvas fixed palette","ready":true,"nonbackground_samples":changed,"pixels_per_m":ppm})
		chunk._wet.free(); chunk._puddles.free()
		chunk.free(); group.free()
		print("AUDIT canvas ",row["id"]," ",kind)
	var file := FileAccess.open(args[1].path_join("canvas-results.json"),FileAccess.WRITE)
	file.store_string(JSON.stringify({"captures":records},"\t")); file.close()
	quit()
