// rtx-scene-readiness step 2 (--outdoor-3d): shaded car bodies. UV2.x is the
// part's material (buildings_3d.car_arrays): 0 paint, 1 rubber, 2 glass, 3 a lit lamp,
// 4 metallic car paint (four-wheelers' bodywork).
shader_type spatial;
render_mode cull_back;

// Metallic paint's sheen from the top-down camera: the boxy roofs and bonnets
// light as if domed - their normals lean out from the vehicle's centre by
// this much per metre - so the sun and the street lamps glint on the side of
// the body facing them, as on a real curved panel (flat, they mirror only
// the plain sky and look darker than plain paint).
const float DOME_PER_M = 0.22;

varying vec3 local_position;  // model space: the vehicle's centre at the origin, +x forward
varying vec3 local_normal;

void vertex() {
	local_position = VERTEX;
	local_normal = NORMAL;
}

void fragment() {
	float part = round(UV2.x);
	ALBEDO = pow(COLOR.rgb, vec3(2.2));  // sRGB vertex colours, lit in linear space
	ROUGHNESS = part == 1.0 ? 0.92 : part == 2.0 ? 0.06 : part == 4.0 ? 0.3 : 0.32;
	METALLIC = part == 2.0 ? 0.55 : part == 4.0 ? 0.25 : 0.0;
	SPECULAR = part == 1.0 ? 0.2 : 0.5;
	if (part == 4.0) {  // metallic paint: flakes under a glossy clear coat
		CLEARCOAT = 1.0;
		CLEARCOAT_ROUGHNESS = 0.12;
		if (local_normal.y > 0.7) {
			vec2 lean = clamp(local_position.xz * DOME_PER_M, vec2(-0.4), vec2(0.4));  // a bus's 12 m roof: the ends no steeper than a car's
			vec3 domed = normalize(vec3(lean.x, 1.0, lean.y));
			NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(domed, 0.0)).xyz);
		}
	}
	EMISSION = part == 3.0 ? COLOR.rgb * 2.0 : vec3(0.0);
}
