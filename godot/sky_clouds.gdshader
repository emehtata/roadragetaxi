// sky-cloud-cover: Daylight.sky_color's gradient with value-noise clouds on a
// plane projected along EYEDIR.y (no raymarching, one pass). `coverage` is
// Daylight.cloud_coverage(cloud_cover); tests/run_tests.gd copies fbm() and the threshold.
shader_type sky;

uniform vec3 sky_top_color : source_color = vec3(0.385, 0.454, 0.55);
uniform vec3 sky_horizon_color : source_color = vec3(0.646, 0.656, 0.67);
uniform float coverage = 1.0;
uniform vec2 wind_offset = vec2(0.0);
uniform float energy = 1.0;

const vec3 GROUND = vec3(0.2, 0.169, 0.133);

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = p - i;
	vec2 u = f * f * (3.0 - 2.0 * f);
	float a = hash(i);
	float b = hash(i + vec2(1.0, 0.0));
	float c = hash(i + vec2(0.0, 1.0));
	float d = hash(i + vec2(1.0, 1.0));
	return a + (b - a) * u.x + (c - a) * u.y + (a - b - c + d) * u.x * u.y;
}

float fbm(vec2 p) {
	return 0.5 * noise(p) + 0.3 * noise(p * 2.03) + 0.2 * noise(p * 4.01);
}

void sky() {
	float y = EYEDIR.y;
	vec3 sky = mix(sky_horizon_color, sky_top_color, smoothstep(0.0, 0.5, y));
	if (y <= 0.0) {
		COLOR = mix(sky_horizon_color, GROUND, smoothstep(0.0, 0.1, -y)) * energy;
	} else {
		vec2 uv = EYEDIR.xz / max(y, 0.06) * 0.6 + wind_offset;
		float n = fbm(uv);
		float density = smoothstep(coverage, coverage + 0.08, n) * smoothstep(0.0, 0.08, y);
		float thickness = smoothstep(coverage, coverage + 0.35, n);
		// lit tops (a little higher noise up-sun) brighter, thick undersides darker; tinted by the sky
		float sun = LIGHT0_ENABLED ? max(dot(EYEDIR, LIGHT0_DIRECTION), 0.0) : 0.0;
		float lit = clamp(n - fbm(uv - LIGHT0_DIRECTION.xz * 0.15), 0.0, 1.0) * 4.0;
		vec3 base = sky_horizon_color * 1.1;
		vec3 cloud = base * mix(1.0, 0.6, thickness) + base * (lit + pow(sun, 6.0) * (1.0 - thickness)) * 0.25;
		COLOR = mix(sky, cloud, density) * energy;
	}
}
