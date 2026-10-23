// Lakes and rivers (map_chunk.gd _draw): slow wave shading and sky reflection.
// Ice and spring floes in the same draw list stay still.
// Coordinates are world space, so the pattern continues across chunks.
shader_type canvas_item;

uniform vec4 sky_color : source_color = vec4(0.40, 0.62, 0.83, 1.0);

uniform vec2 wind = vec2(2.0, 0.0); // canvas metres per second

varying vec2 world;

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
		mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}

void vertex() {
	world = (MODEL_MATRIX * vec4(VERTEX, 0.0, 1.0)).xy;
}

void fragment() {
	float water = 1.0 - smoothstep(0.45, 0.7, dot(COLOR.rgb, vec3(0.3, 0.59, 0.11)));
	if (water > 0.0) {
		float t = mod(TIME, 1000.0);
		float speed = length(wind);
		float strength = clamp(speed / 12.0, 0.0, 1.0);
		vec2 direction = wind / max(speed, 0.001);
		float swell = noise(world * 0.035 - direction * t * 0.18);
		float ripple = sin(dot(world, direction) * 0.8 - t * 1.2
			+ noise(world * 0.12) * 3.0) * smoothstep(0.2, 0.8, noise(world * 0.08 - direction * t * 0.08));
		vec3 reflected = mix(COLOR.rgb, sky_color.rgb, 0.53 + strength * 0.08 * (swell - 0.5));
		vec3 c = reflected * (0.98 + strength * (0.20 * (swell - 0.5) + 0.08 * ripple));
		COLOR.rgb = mix(COLOR.rgb, c, water);
	}
}
