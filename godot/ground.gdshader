// rtx-scene-readiness step 3 (--outdoor-3d): the open ground, landuse,
// parking, islands and curbs, lit; snow-covered with the winter weight as the
// 2D map's ground (map_layer._draw_ground) - set_snow, no chunk rebuilt.
shader_type spatial;
render_mode cull_back;

uniform float snow_cover : hint_range(0.0, 1.0) = 0.0;
uniform vec4 snow_color : source_color = vec4(0.9020, 0.9255, 0.9412, 1.0);  // Color8(230, 236, 240)

void fragment() {
	ALBEDO = mix(pow(COLOR.rgb, vec3(2.2)), snow_color.rgb, clamp(snow_cover, 0.0, 1.0));  // sRGB vertex colours
	ROUGHNESS = 0.95;
}
