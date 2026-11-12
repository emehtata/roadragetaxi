// Snow: a round soft flake, billboarded, spinning slowly (the sway is in the
// process shader: the flake's path, not its quad).
shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_disabled, skip_vertex_transform;

varying float layer;
varying float spin;

void vertex() {
	layer = INSTANCE_CUSTOM.x;
	spin = INSTANCE_CUSTOM.y + TIME * (0.5 + INSTANCE_CUSTOM.z);
	float size = length(MODEL_MATRIX[0].xyz);
	vec3 centre = (VIEW_MATRIX * vec4(MODEL_MATRIX[3].xyz, 1.0)).xyz;
	VERTEX = centre + vec3(VERTEX.xy * size * 2.0, 0.0);
	NORMAL = vec3(0.0, 0.0, 1.0);
}

void fragment() {
	vec2 p = UV * 2.0 - 1.0;
	p = mat2(vec2(cos(spin), sin(spin)), vec2(-sin(spin), cos(spin))) * p;
	float r = length(p * vec2(1.0, 1.15));  // slightly oval, so the spin shows
	ALBEDO = vec3(0.96, 0.97, 1.0);
	ALPHA = (1.0 - smoothstep(0.4, 1.0, r)) * (0.45 + 0.5 * layer);
}
