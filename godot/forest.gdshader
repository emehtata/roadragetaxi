// Dense visual canopy: no per-tree nodes, network records or collision objects.
shader_type canvas_item;

uniform sampler2D canopy_mask : filter_linear, repeat_disable;
uniform sampler2D crown_mask : filter_nearest, repeat_disable;  // the same mask, read once per crown at its centre
uniform vec4 mask_rect;
varying vec2 world;

vec2 hash2(vec2 p) {
	return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453);
}

void vertex() {
	world = (MODEL_MATRIX * vec4(VERTEX, 0.0, 1.0)).xy;
}

void fragment() {
	// Other landuse polygons share this material and retain their own fill.
	// UV.x: 1 + kind * 2 + winter (kind 0 forest, 1 scrub, 2 wetland); UV.y: autumn.
	if (UV.x > 0.5) {
		float kind = floor((UV.x - 1.0) * 0.5);
		float winter = clamp(UV.x - 1.0 - 2.0 * kind, 0.0, 1.0);
		float autumn = UV.y;
		bool forest = kind < 0.5;
		bool scrub = kind > 0.5 && kind < 1.5;
		// Each kind its own mask channel: a crown is drawn only where its centre is its own kind.
		vec4 channel = forest ? vec4(1.0, 0.0, 0.0, 0.0) : (scrub ? vec4(0.0, 1.0, 0.0, 0.0) : vec4(0.0, 0.0, 1.0, 0.0));
		float cell_m = forest ? 4.2 : (scrub ? 3.0 : 5.5);  // dense crowns; bushes; a bog's scattered stunted pines
		float presence = forest ? 1.0 : (scrub ? 0.62 : 0.3);
		vec2 grid = world / cell_m;
		vec2 cell = floor(grid);
		vec3 color = COLOR.rgb * 0.65;
		float highest = -1.0;
		float coverage = 0.0;
		vec2 neighbour = mix(vec2(-1.0), vec2(1.0), step(vec2(0.5), fract(grid)));
		float pixel_size = max(length(dFdx(world)), length(dFdy(world)));
		// Fade crowns below a few pixels instead of aliasing at map zoom.
		float detail = 1.0 - smoothstep(1.2, 3.0, pixel_size);
		float aa = max(0.08, pixel_size * 0.6);
		if (detail > 0.0) {
			for (int y = 0; y < 2; y++) {
				for (int x = 0; x < 2; x++) {
					vec2 key = cell + vec2(float(x), float(y)) * neighbour;
					vec2 seed = hash2(key);
					if (fract(seed.x * 41.3 + seed.y * 3.1) > presence) {
						continue;  // scrub and bog: open ground between the bushes and pines
					}
					vec2 center = key + vec2(0.2) + seed * 0.6;
					vec2 offset = (grid - center) * cell_m;
					float species = fract(seed.x * 17.0 + seed.y * 7.0);
					float radius = forest ? 2.5 + seed.y * 0.8 : (scrub ? 1.3 + seed.y * 0.8 : 0.8 + seed.y * 0.6);
					float angle = atan(offset.y, offset.x + 0.0001);
					float lobes = forest ? (species < 0.45 ? 5.0 : (species < 0.8 ? 9.0 : 7.0)) : (scrub ? 3.0 : 9.0);
					// Bushes: a few broad lumps rather than a crown's many small ones.
					float ragged = scrub ? 0.14 : 0.08;
					float edge = radius * (1.0 - ragged + ragged * sin(angle * lobes + seed.x * 6.28)
						+ (scrub ? 0.07 * sin(angle * 5.0 + seed.y * 6.28) : 0.0));
					float distance = length(offset);
					float height = (1.0 - distance / edge) * (2.0 + seed.x);
					// Whole crowns or none: the mask is read at the crown's centre, so a road,
					// building or clearing edge never slices one (it overhangs instead) - and only
					// for a crown covering this pixel on top (one or two reads, not four).
					if (height > highest && distance < edge + aa
							&& dot(texture(crown_mask, (center * cell_m - mask_rect.xy) / mask_rect.zw), channel) >= 0.5) {
						highest = height;
						vec3 crown;
						if (forest) {
							crown = species < 0.45 ? vec3(0.25, 0.34, 0.13) : (species < 0.8 ? vec3(0.08, 0.24, 0.12) : vec3(0.24, 0.42, 0.17));
							if (species >= 0.8) {
								crown = mix(crown, vec3(0.67, 0.51, 0.13), autumn);
							}
						} else if (scrub) {  // willow, juniper and young birch: lighter, yellower, greyer
							crown = species < 0.4 ? vec3(0.36, 0.45, 0.17) : (species < 0.75 ? vec3(0.30, 0.40, 0.16) : vec3(0.42, 0.48, 0.33));
							if (species >= 0.4 && species < 0.75) {
								crown = mix(crown, vec3(0.70, 0.45, 0.15), autumn);
							}
						} else {  // bog pines, dark and small, the odd dwarf birch
							crown = species < 0.75 ? vec3(0.13, 0.24, 0.12) : vec3(0.33, 0.40, 0.20);
							if (species >= 0.75) {
								crown = mix(crown, vec3(0.72, 0.42, 0.16), autumn);
							}
						}
						float relief = forest ? 0.24 : 0.14;  // low bushes shade flatter
						float light = 0.72 + relief * (1.0 - distance / edge) - dot(offset / radius, vec2(0.11, 0.14));
						crown *= light * (0.88 + seed.x * 0.24);
						float snow = winter * (0.5 + 0.4 * max(0.0, 1.0 - distance / edge));
						crown = mix(crown, vec3(0.82, 0.88, 0.88), snow);
						coverage = 1.0 - smoothstep(edge - aa, edge + aa, distance);
						color = crown;
					}
				}
			}
		}
		COLOR.rgb = mix(COLOR.rgb * 0.85, color, detail);
		// The flat fill of distant zooms keeps the per-pixel mask (dense forest only:
		// scrub and bog show their own ground); crowns carry their own.
		float flat_fill = detail < 1.0 && forest ? dot(texture(canopy_mask, (world - mask_rect.xy) / mask_rect.zw), channel) : 0.0;
		COLOR.a *= mix(flat_fill, coverage, detail);
	} else {
		COLOR.a = 0.0;
	}
}
