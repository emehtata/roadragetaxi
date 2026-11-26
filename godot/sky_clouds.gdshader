// sky-cloud-cover: Daylight.sky_color's gradient with value-noise clouds on a
// plane projected along EYEDIR.y (no raymarching, one pass). `coverage` is
// Daylight.cloud_coverage(cloud_cover); tests/run_tests.gd copies fbm() and the threshold.
shader_type sky;

uniform vec3 sky_top_color : source_color = vec3(0.385, 0.454, 0.55);
uniform vec3 sky_horizon_color : source_color = vec3(0.646, 0.656, 0.67);
uniform float coverage = 1.0;
uniform vec2 wind_offset = vec2(0.0);
uniform float energy = 1.0;
// sun-moon-in-sky: Buildings3D.set_sky_bodies; discs 2 deg wide (0.53 enlarged for readability)
uniform vec3 sun_dir = vec3(0.0, 1.0, 0.0);
uniform vec3 moon_dir = vec3(0.0, 1.0, 0.0);
uniform float moon_illumination = 0.0;
uniform float sun_visible = 0.0;
uniform float moon_visible = 0.0;
uniform sampler2D star_map_0 : filter_linear, repeat_enable;
uniform sampler2D star_map_1 : filter_linear, repeat_enable;
uniform mat3 map_to_stars = mat3(1.0);
uniform vec4 star_weights_0 = vec4(0.0);
uniform vec4 star_weights_1 = vec4(0.0);
uniform float star_visibility = 0.0;

const float DISC_COS = 0.99985;  // cos(1 deg): the discs' radius

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
		// the discs sit behind the clouds and vanish under overcast (cloud cover 0.9: coverage 0.125)
		float clear = (1.0 - density) * smoothstep(0.125, 0.25, coverage);
		float s = dot(EYEDIR, sun_dir);
		sky = sky * energy + vec3(1.0, 0.95, 0.8) * (smoothstep(DISC_COS - 0.00002, DISC_COS, s) * 2.0 + pow(max(s, 0.0), 400.0) * 0.3) * sun_visible * clear;
		// The catalog is a visual background; it need not rebuild/illuminate the radiance cubemap.
		if (!AT_CUBEMAP_PASS && star_visibility > 0.0) {
			vec3 equatorial = normalize(map_to_stars * EYEDIR);
			vec2 star_uv = vec2(atan(equatorial.y, equatorial.x) / (2.0 * PI), 0.5 - asin(clamp(equatorial.z, -1.0, 1.0)) / PI);
			float stars = dot(texture(star_map_0, star_uv), star_weights_0) + dot(texture(star_map_1, star_uv), star_weights_1);
			stars *= 1.0 - moon_visible * smoothstep(DISC_COS - 0.00002, DISC_COS, dot(EYEDIR, moon_dir));
			sky += vec3(stars * star_visibility * clear * smoothstep(0.0, 0.08, y));
		}
		float m = dot(EYEDIR, moon_dir);
		if (m > DISC_COS - 0.00002 && moon_visible > 0.0) {
			// lit side towards the sun; the terminator as a straight chord at the lit fraction
			vec3 side = normalize(sun_dir - moon_dir * dot(sun_dir, moon_dir) + vec3(1e-4, 0.0, 0.0));
			float u = dot(EYEDIR - moon_dir, side) / sqrt(1.0 - DISC_COS * DISC_COS);
			float lit = smoothstep(1.0 - 2.0 * moon_illumination - 0.05, 1.0 - 2.0 * moon_illumination + 0.05, u);
			vec3 moon = mix(sky + vec3(0.03), vec3(1.6, 1.58, 1.5), lit);
			sky = mix(sky, moon, smoothstep(DISC_COS - 0.00002, DISC_COS, m) * clear);
		}
		COLOR = mix(sky, cloud * energy, density);
	}
}
