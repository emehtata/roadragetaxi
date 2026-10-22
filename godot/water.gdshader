// Lakes and rivers (map_chunk.gd _draw): slow wave shading, crossing glints
// and drifting sparkles over the season colour. Only blue pixels move, so
// ice, spring floes and field markings in the same draw list stay still.
// Coordinates are world space, so the pattern continues across chunks.
shader_type canvas_item;

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
	float water = clamp((COLOR.b - COLOR.r) * 4.0, 0.0, 1.0);
	if (water > 0.0) {
		float t = mod(TIME, 1000.0);
		float a = noise(world * 0.18 + vec2(t * 0.25, t * 0.08));
		float b = noise(world * 0.23 - vec2(t * 0.06, t * 0.21));
		float swell = noise(world * 0.035 + vec2(t * 0.03, 0.0));
		float glint = smoothstep(0.07, 0.0, abs(a - b));
		vec2 cell = world * 0.8;
		float dot_ = smoothstep(0.3, 0.0, length(fract(cell) - 0.5));
		float sparkle = step(0.99, hash(floor(cell) + floor(t * 2.0))) * dot_ * a;
		vec3 c = COLOR.rgb * (0.86 + 0.22 * swell + 0.1 * (a - 0.5));
		c += vec3(0.75, 0.88, 1.0) * (glint * 0.12 + sparkle * 0.5);
		COLOR.rgb = mix(COLOR.rgb, c, water);
	}
}
