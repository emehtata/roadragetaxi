// rtx-scene-readiness step 6 (--outdoor-3d): a smoke puff, lit, its colour
// and fade per puff (buildings_3d.puff).
shader_type spatial;
render_mode blend_mix, depth_draw_never, cull_back;

instance uniform vec4 tint : source_color = vec4(0.6, 0.6, 0.6, 0.5);

void fragment() {
	ALBEDO = tint.rgb;
	ALPHA = tint.a;
	ROUGHNESS = 1.0;
}
