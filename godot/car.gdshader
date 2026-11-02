// rtx-scene-readiness step 2 (--outdoor-3d): shaded car bodies. UV2.x is the
// part's material (buildings_3d.car_arrays): 0 paint, 1 rubber, 2 glass, 3 a lit lamp,
// 4 bare galvanised steel (lamp and signal posts).
shader_type spatial;
render_mode cull_back;

void fragment() {
	float part = round(UV2.x);
	ALBEDO = pow(COLOR.rgb, vec3(2.2));  // sRGB vertex colours, lit in linear space
	ROUGHNESS = part == 1.0 ? 0.92 : part == 2.0 ? 0.06 : part == 4.0 ? 0.45 : 0.32;
	METALLIC = part == 2.0 ? 0.55 : part == 4.0 ? 0.85 : 0.0;
	SPECULAR = part == 1.0 ? 0.2 : 0.5;
	EMISSION = part == 3.0 ? COLOR.rgb * 2.0 : vec3(0.0);
}
