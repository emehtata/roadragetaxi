shader_type spatial;
render_mode cull_back;

varying vec3 local_position;

void vertex() {
	local_position = VERTEX;
}

void fragment() {
	float part = round(UV2.x); // fabric 0, skin 1, hair 2, eyes 3, shoes 4, fur 5
	float grain = sin(local_position.x * 23.0) * sin(local_position.y * 31.0) * sin(local_position.z * 19.0);
	ALBEDO = pow(COLOR.rgb, vec3(2.2)) * (1.0 + grain * (part == 5.0 ? 0.055 : part == 0.0 ? 0.018 : 0.0));
	ROUGHNESS = part == 3.0 ? 0.42 : part == 1.0 ? 0.78 : part == 4.0 ? 0.86 : 0.94;
	SPECULAR = part == 3.0 ? 0.48 : part == 1.0 ? 0.28 : 0.18;
}
