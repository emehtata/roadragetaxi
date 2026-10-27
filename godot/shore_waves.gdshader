// True shore contours are cached by the server. Crests move toward distance zero.
shader_type canvas_item;

uniform vec2 wind = vec2(2.0, 0.0);
varying vec2 world;

void vertex() {
	world = (MODEL_MATRIX * vec4(VERTEX, 0.0, 1.0)).xy;
}

void fragment() {
	float distance = COLOR.r * 6.0;
	float speed = length(wind);
	float strength = clamp(speed / 10.0, 0.0, 1.0);
	float variation = sin(world.x * 0.12 + sin(world.y * 0.15)) * sin(world.y * 0.09 - TIME * 0.15);
	float crest = pow(0.5 + 0.5 * sin(distance * 1.65 + TIME * 1.2 + variation), 4.0);
	float envelope = smoothstep(0.0, 0.7, distance) * (1.0 - smoothstep(3.0, 6.0, distance));
	float shallows = pow(1.0 - distance / 6.0, 1.5) * (0.06 + 0.02 * variation);
	float waves = crest * envelope * strength * (0.07 + 0.04 * variation);
	COLOR = vec4(vec3(0.65, 0.70, 0.66), COLOR.a * (shallows + waves));
}
