shader_type spatial;
render_mode unshaded, cull_back;

uniform vec4 ambient : source_color = vec4(1.0);
uniform float snow_cover : hint_range(0.0, 1.0) = 0.0;
uniform vec4 snow_color : source_color = vec4(0.84314, 0.87843, 0.90980, 1.0);

void fragment() {
	// UV.x marks only roof triangles; walls, gables, doors and windows stay bare.
	ALBEDO = mix(COLOR.rgb, snow_color.rgb * UV.y, UV.x * snow_cover) * ambient.rgb;
}
