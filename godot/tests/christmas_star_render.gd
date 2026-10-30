## Render the production star function: columns grow in size, rows cool in colour.
extends SceneTree
func _initialize() -> void:
	call_deferred("run")
func run() -> void:
	root.size = Vector2i(640, 640)
	var source := FileAccess.get_file_as_string("res://building_snow.gdshader")
	var start := source.find("vec3 star_light(")
	var stop := source.find("// Independence Day:", start)
	assert(start >= 0 and stop > start)
	var shader := Shader.new()
	shader.code = "shader_type canvas_item; render_mode unshaded;\n" + source.substr(start, stop - start) + """
void fragment() {
	vec2 cell = floor(UV * 4.0);
	vec2 local = fract(UV * 4.0);
	vec2 p = vec2((local.x - 0.5) * 1.6, (1.0 - local.y) * 1.4);
	vec4 star = decoration(p, vec2(0.8, 1.4), 0.1, 1.0, cell.x / 3.0, cell.y / 3.0, 1.0);
	COLOR = vec4(mix(vec3(0.03, 0.05, 0.07), star.rgb, star.a), 1.0);
}
"""
	var panel := ColorRect.new()
	panel.size = Vector2(640, 640)
	var material := ShaderMaterial.new()
	material.shader = shader
	panel.material = material
	root.add_child(panel)
	for i in 4:
		await process_frame
	await RenderingServer.frame_post_draw
	var first := root.get_texture().get_image()
	first.save_png("/tmp/christmas-star-variations.png")
	var areas := []
	for column in 4:
		var area := 0
		for x in range(column * 160, (column + 1) * 160):
			for y in 160:
				if first.get_pixel(x, y).r > 0.2:
					area += 1
		areas.append(area)
	assert(areas[0] > 0 and areas[0] < areas[1] and areas[1] < areas[2] and areas[2] < areas[3], "star sizes must differ")
	var warm := first.get_pixel(80, 51)
	var cool := first.get_pixel(80, 531)
	assert(warm.r > warm.b * 2 and cool.b > cool.r, "amber and cool stars must have distinct colour temperatures")
	for i in 3:
		await process_frame
	await RenderingServer.frame_post_draw
	assert(first.get_data() == root.get_texture().get_image().get_data(), "star appearance must remain stable between frames")
	print("CHRISTMAS STARS: size areas=", areas, "; amber-to-cool colours and frame stability passed")
	panel.free()
	quit()
