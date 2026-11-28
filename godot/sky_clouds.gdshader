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
// solar-eclipse-sky: the radii (radians) share one display scale; the Moon's one path covers the Sun when they overlap
uniform float sun_radius = 0.0174533;
uniform float moon_radius = 0.0174533;
uniform float eclipse_obscuration = 0.0;
uniform float eclipse_energy = 0.0;
uniform vec3 sun_dir = vec3(0.0, 1.0, 0.0);
uniform vec3 moon_dir = vec3(0.0, 1.0, 0.0);
uniform vec3 moon_north = vec3(0.0, 0.0, 1.0);
uniform float moon_illumination = 0.0;
uniform float sun_visible = 0.0;
uniform float moon_visible = 0.0;
uniform sampler2D moon_texture : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D star_map_0 : filter_linear, repeat_enable;
uniform sampler2D star_map_1 : filter_linear, repeat_enable;
uniform mat3 map_to_stars = mat3(1.0);
uniform vec4 star_weights_0 = vec4(0.0);
uniform vec4 star_weights_1 = vec4(0.0);
uniform float star_visibility = 0.0;
// planet-sky: Mercury..Uranus (PlanetSky): xyz unit direction, w display level (0 hides); one pixel-sized gaussian each
uniform vec4 planet_dir[6];
uniform vec3 planet_color[6];
uniform float planet_visible = 0.0;

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
	float pixel = max(length(dFdx(EYEDIR)), length(dFdy(EYEDIR)));  // radians per pixel: a point stays one pixel wide at any FOV or resolution
	vec3 sky = mix(sky_horizon_color, sky_top_color, smoothstep(0.0, 0.5, y));
	float sun_cos = cos(sun_radius);
	float moon_cos = cos(moon_radius);
	float sky_energy = eclipse_obscuration > 0.0 ? max(energy, eclipse_energy * eclipse_obscuration) : energy;
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
		float m = dot(EYEDIR, moon_dir);
		float moon_mask = smoothstep(moon_cos - 0.00002, moon_cos, m) * moon_visible;
		vec3 sky_no_sun = sky * sky_energy;  // the Moon is the top layer: it shows this, never the Sun behind it
		float sun_disc = smoothstep(sun_cos - 0.00002, sun_cos, s) * 2.0;
		float sun_glow = pow(max(s, 0.0), 400.0) * 0.3 * (1.0 - eclipse_obscuration);  // the covered share of the glow is gone
		sky = sky_no_sun + vec3(1.0, 0.95, 0.8) * (sun_disc + sun_glow) * sun_visible * clear;
		if (eclipse_obscuration >= 0.9999) {  // totality: a corona fades out over two Moon radii
			float ring = acos(clamp(m, -1.0, 1.0)) / moon_radius;
			sky += vec3(0.9, 0.92, 1.0) * pow(clamp(2.0 - ring, 0.0, 1.0), 3.0) * (1.0 - moon_mask) * sun_visible * clear;
		}
		// The catalog is a visual background; it need not rebuild/illuminate the radiance cubemap.
		if (!AT_CUBEMAP_PASS && star_visibility > 0.0) {
			vec3 equatorial = normalize(map_to_stars * EYEDIR);
			vec2 star_uv = vec2(atan(equatorial.y, equatorial.x) / (2.0 * PI), 0.5 - asin(clamp(equatorial.z, -1.0, 1.0)) / PI);
			float stars = dot(texture(star_map_0, star_uv), star_weights_0) + dot(texture(star_map_1, star_uv), star_weights_1);
			// layer order, back to front, in every frame: stars and planets < Sun < Moon
			stars *= (1.0 - sun_visible * smoothstep(sun_cos - 0.00002, sun_cos, s)) * (1.0 - moon_visible * smoothstep(moon_cos - 0.00002, moon_cos, m));
			sky += vec3(stars * star_visibility * clear * smoothstep(0.0, 0.08, y));
		}
		// Planets are unresolved points behind the clouds and the Sun/Moon discs, never below the horizon; no light is added to the world.
		if (!AT_CUBEMAP_PASS && planet_visible > 0.0) {
			vec3 planets = vec3(0.0);
			for (int i = 0; i < 6; i++) {
				vec3 off = cross(EYEDIR, planet_dir[i].xyz);
				float sigma = 0.8 * pixel;
				planets += planet_color[i] * planet_dir[i].w * exp(-0.5 * dot(off, off) / (sigma * sigma)) * step(0.0, dot(EYEDIR, planet_dir[i].xyz));
			}
			planets *= (1.0 - sun_visible * smoothstep(sun_cos - 0.00002, sun_cos, s)) * (1.0 - moon_visible * smoothstep(moon_cos - 0.00002, moon_cos, m));
			sky += planets * clear;
		}
		if (m > moon_cos - 0.00002 && moon_visible > 0.0) {
			// A visible hemisphere lit from the projected Sun: only quarter phases have a straight terminator.
			vec3 projected_sun = sun_dir - moon_dir * dot(sun_dir, moon_dir);
			vec3 fallback = abs(moon_dir.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
			vec3 side = length(projected_sun) > 0.00001 ? normalize(projected_sun) : normalize(cross(moon_dir, fallback));
			vec3 up = cross(moon_dir, side);
			vec2 p = vec2(dot(EYEDIR, side), dot(EYEDIR, up)) / sin(moon_radius);
			float z = sqrt(max(0.0, 1.0 - dot(p, p)));
			float phase_cos = 2.0 * clamp(moon_illumination, 0.0, 1.0) - 1.0;
			float incidence = p.x * sqrt(max(0.0, 1.0 - phase_cos * phase_cos)) + z * phase_cos;
			float lit = smoothstep(-0.005, 0.005, incidence);
			lit *= smoothstep(0.0005, 0.005, moon_illumination);  // a new Moon has no lit rim: at the limb z is 0 and the edge band would light up
			vec3 map_up = moon_north - moon_dir * dot(moon_north, moon_dir);
			if (length(map_up) < 0.00001) {
				vec3 fallback_up = abs(moon_dir.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
				map_up = fallback_up - moon_dir * dot(fallback_up, moon_dir);
			}
			map_up = normalize(map_up);
			// Equirectangular positive-east longitude appears to the observer's right.
			vec3 map_right = normalize(cross(moon_dir, map_up));
			vec3 surface_normal = normalize(moon_dir * z + side * p.x + up * p.y);
			float longitude = atan(dot(surface_normal, map_right), dot(surface_normal, moon_dir));
			float latitude = asin(clamp(dot(surface_normal, map_up), -1.0, 1.0));
			vec2 moon_uv = vec2(longitude / (2.0 * PI) + 0.5, 0.5 - latitude / PI);
			float albedo = texture(moon_texture, moon_uv).r;
			// Keep the lit albedo below display clipping so maria survive Forward+ tonemapping.
			vec3 moon = mix(sky_no_sun + vec3(0.03), vec3(0.95, 0.94, 0.9) * clamp(0.25 + 1.1 * albedo, 0.25, 0.85), lit);
			sky = mix(sky, moon, moon_mask * clear);  // layer order, back to front: stars and planets < Sun < Moon
		}
		COLOR = mix(sky, cloud * sky_energy, density);
	}
}
