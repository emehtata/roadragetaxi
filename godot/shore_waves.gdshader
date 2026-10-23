// Contours are cached at chunk load; positive time moves crests toward distance zero.
shader_type canvas_item;

void fragment() {
	float distance = COLOR.r * 6.0;
	float crest = pow(0.5 + 0.5 * sin(distance * 2.094395 + TIME * 1.5), 6.0);
	float envelope = smoothstep(0.0, 0.8, distance) * (1.0 - smoothstep(3.5, 6.0, distance));
	COLOR = vec4(vec3(0.72, 0.78, 0.75), COLOR.a * crest * envelope * 0.24);
}
