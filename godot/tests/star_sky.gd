extends SceneTree

var failures := 0

func check(ok: bool, what: String) -> void:
	if not ok:
		failures += 1
		push_error(what)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var sky = load("res://star_sky.gd")
	check(sky != null,"catalog sky helper exists")
	if sky == null:
		quit(1); return
	var stars: Array = sky.stars()
	check(stars.size()==5092,"full pinned eligible SAO subset is cached")
	check(is_same(stars,sky.stars()),"catalog resource is shared across updates")
	check(sky.limiting_magnitude(-20,0,0,0)==6.0,"dark rural sky reaches magnitude six")
	check(sky.limiting_magnitude(-20,1,0,0)<sky.limiting_magnitude(-20,0,0,0),"pollution hides faint stars first")
	check(sky.limiting_magnitude(-20,0,60,1)<6,"bright high moon reduces the limiting magnitude")
	check(sky.night_visibility(10)==0 and sky.night_visibility(-20)==1,"day/night star fade")
	check(sky.band_weight(6,6)>0 and sky.band_weight(6,3)==0 and sky.band_weight(1,3)>0,"faint and bright atlas bands are independently attenuated")
	check(sky.STARS_0.get_width()==4096 and sky.STARS_0.get_height()==2048,"source sky atlas dimensions")
	var faint_image: Image=sky.STARS_1.get_image()
	var faint_source_seen:=false
	for row: Array in stars:
		if float(row[3])<5.9: continue
		var direction: Vector3=sky.direction(row)
		var x:=int(fposmod(atan2(direction.y,direction.x),TAU)/TAU*4096.0)%4096
		var y:=mini(2047,int((.5-asin(direction.z)/PI)*2048.0))
		if faint_image.get_pixel(x,y).b>.03: faint_source_seen=true
	check(faint_source_seen,"lossless imported data preserves magnitude-six RGB despite zero alpha")
	var shader := FileAccess.get_file_as_string("res://sky_clouds.gdshader")
	check("star_map_0" in shader and "map_to_stars" in shader and "AT_CUBEMAP_PASS" in shader,"actual sky shader samples oriented catalog behind clouds without radiance stars")
	var B3=load("res://buildings_3d.gd")
	var old_opaque: bool=B3.opaque
	B3.opaque=true
	var layer=B3.new()
	root.add_child(layer)
	var state: Dictionary={"supported":true,"basis":[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],"utc":"2026-01-01T00:00:00Z"}
	layer.set_catalog_stars(state,0.0,-20.0,-10.0,0.0)
	var material: ShaderMaterial=layer._camera.environment.sky.sky_material
	var source=material.get_shader_parameter("star_map_0")
	var children: int=layer.get_child_count()
	layer.set_catalog_stars(state,0.0,-20.0,-10.0,0.0)
	check(is_same(source,material.get_shader_parameter("star_map_0")),"unchanged sky inputs reuse the atlas")
	state=state.duplicate(true)
	state.utc="2026-02-01T12:00:00Z"
	layer.set_catalog_stars(state,1.0,20.0,50.0,1.0)
	check(layer.star_state.utc==state.utc and layer.star_visibility==0,"time jumps replace cached state and hide daytime stars")
	check(is_same(source,material.get_shader_parameter("star_map_0")) and layer.get_child_count()==children,"time/pollution updates create no per-star resources or nodes")
	layer.free()
	B3.opaque=old_opaque
	print("STAR_SKY failures=",failures)
	quit(1 if failures else 0)
