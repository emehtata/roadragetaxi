// Rain: a streak quad along the drop's velocity (the process shader puts
// velocity * 0.35 s in the Y basis and the width in X), facing the camera.
shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_disabled, skip_vertex_transform;

varying float layer;

void vertex() {
	layer = INSTANCE_CUSTOM.x;
	vec3 centre = MODEL_MATRIX[3].xyz;
	vec3 axis = MODEL_MATRIX[1].xyz;
	float width = length(MODEL_MATRIX[0].xyz);
	vec3 to_camera = normalize(INV_VIEW_MATRIX[3].xyz - centre);
	vec3 side = cross(axis, to_camera);
	side = length(side) > 1e-4 ? normalize(side) : INV_VIEW_MATRIX[0].xyz;  // seen end-on: a dot
	vec3 world = centre + side * width * VERTEX.x * 2.0 + axis * VERTEX.y;
	VERTEX = (VIEW_MATRIX * vec4(world, 1.0)).xyz;
	NORMAL = vec3(0.0, 0.0, 1.0);
}

void fragment() {
	float across = 1.0 - abs(UV.x * 2.0 - 1.0);
	ALBEDO = vec3(0.85, 0.9, 1.0);
	ALPHA = across * (0.45 + 0.45 * layer) * smoothstep(0.0, 0.3, UV.y);  // far drops dimmer, a faded tail
}
