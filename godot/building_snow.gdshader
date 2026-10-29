shader_type spatial;
render_mode unshaded, cull_back;

uniform vec4 ambient : source_color = vec4(1.0);
uniform float snow_cover : hint_range(0.0, 1.0) = 0.0;
uniform vec4 snow_color : source_color = vec4(0.84314, 0.87843, 0.90980, 1.0);
// Windows are drawn here, not as geometry (a city centre had 118k window quads
// and as many lit ones): each wall vertex carries UV2 = (metres along the wall,
// metres up) and CUSTOM0 = (wall length, storey height, windows per floor +
// 1000 x category, seed); roofs and gables carry no windows (0). Modelled on
// Oulu's Valkea talo: a window in every ~3 m bay of every floor, about half
// the storey tall; a shop's ground floor glazed nearly bay to bay (category
// 2); houses wider bays, every other floor. A share lit at night.
uniform vec4 window_color : source_color = vec4(0.22745, 0.31373, 0.36863, 1.0);  // buildings_25d.WINDOW
uniform vec4 storefront_color : source_color = vec4(0.32941, 0.41569, 0.47843, 1.0);  // .STOREFRONT
uniform vec4 lit_color : source_color = vec4(1.0, 0.87059, 0.55686, 1.0);  // buildings_3d.WINDOW_LIT_NIGHT
uniform float lit_level : hint_range(0.0, 1.0) = 0.0;  // Daylight.artificial: 0 by day, 1 at night
uniform vec3 lit_probability = vec3(0.12, 0.08, 0.03);  // other / house / storefront (buildings_25d.LIT_PROBABILITY)

varying flat vec4 wall;  // flat: interpolation noise in the seed, amplified by the hash, speckled the lit windows

void vertex() {
	wall = CUSTOM0;
}

// One window's own values, the same on every GPU: integer hashing (a sin()
// hash depends on each driver's sin precision). `key`: the building's seed
// (a whole-millimetre value), the floor and the column; `salt`: which value.
float window_hash(float key, float f, float w, uint salt) {
	uint h = uint(int(round(key * 1000.0))) * 747796405u + uint(int(f)) * 2891336453u + uint(int(w)) * 1181783497u + salt * 3266489917u;
	h ^= h >> 16u;
	h *= 2246822519u;
	h ^= h >> 13u;
	h *= 3266489917u;
	h ^= h >> 16u;
	return float(h & 16777215u) / 16777216.0;
}

// The curtains' fabric, by a window's own value: white, beige, rust, blue-grey, green.
vec3 fabric(float pick) {
	return pick < 0.35 ? vec3(0.88, 0.87, 0.83) : pick < 0.6 ? vec3(0.80, 0.72, 0.58)
		: pick < 0.75 ? vec3(0.62, 0.30, 0.22) : pick < 0.9 ? vec3(0.42, 0.50, 0.60) : vec3(0.40, 0.52, 0.38);
}

// A lit room's light by a window's own value: mostly warm incandescent
// (~2700 K), some neutral (~4000 K), a few cool LED (~5500 K).
vec3 room_light(float pick) {
	vec3 warm = vec3(1.0, 0.80, 0.48);
	vec3 neutral = vec3(1.0, 0.92, 0.76);
	vec3 cool = vec3(0.86, 0.92, 1.0);
	return pick < 0.6 ? mix(warm, neutral, pick / 0.6 * 0.5) : pick < 0.9 ? mix(warm, neutral, 0.5 + (pick - 0.6) / 0.3 * 0.5) : cool;
}

void fragment() {
	// UV.x marks only roof triangles; walls, gables, doors and windows stay bare.
	vec3 color = mix(COLOR.rgb, snow_color.rgb * UV.y, UV.x * snow_cover) * ambient.rgb;
	float count = mod(wall.z, 1000.0);
	if (count >= 1.0 && wall.y > 0.0) {
		float category = floor(wall.z / 1000.0 + 0.001);
		bool house = abs(category - 1.0) < 0.5;
		float storey = wall.y;
		float f = floor(UV2.y / storey);
		bool storefront = abs(category - 2.0) < 0.5 && f < 0.5;
		bool skipped = house && mod(f, 2.0) > 0.5;
		float bay = wall.x / count;
		float w = clamp(floor(UV2.x / bay), 0.0, count - 1.0);
		float across = UV2.x - (w + 0.5) * bay;  // from the bay's centre
		float up = UV2.y - storey * f;  // within the floor
		float half_width = storefront ? bay * 0.425 : bay * 0.225;
		float bottom = storefront ? 0.3 : storey * 0.25;
		float top = storefront ? storey * 0.75 : storey * 0.75;
		if (!skipped && abs(across) <= half_width && up >= bottom && up <= top) {
			vec2 local = vec2(across / half_width, (up - bottom) / (top - bottom));  // -1..1 across, 0..1 up
			vec3 glass = (storefront ? storefront_color.rgb : window_color.rgb) * ambient.rgb;
			// Curtains on about a third of homes' and offices' windows (not shops): side panels
			// drawn open, a half-lowered blind or a thin sheer over the whole window.
			float curtain = 0.0;
			float style = window_hash(wall.w, f, w, 2u);
			if (!storefront && window_hash(wall.w, f, w, 1u) < 0.35) {
				curtain = style < 0.45 ? (abs(local.x) > 0.6 ? 1.0 : 0.0)
					: style < 0.8 ? (local.y > 0.55 ? 1.0 : 0.0)
					: 0.45;
			}
			vec3 cloth = fabric(window_hash(wall.w, f, w, 3u));
			glass = mix(glass, cloth * 0.75 * ambient.rgb, curtain);
			float chance = storefront ? lit_probability.z : house ? lit_probability.y : lit_probability.x;
			if (window_hash(wall.w, f, w, 0u) < chance) {
				vec3 light = room_light(window_hash(wall.w, f, w, 4u)) * (0.78 + 0.27 * window_hash(wall.w, f, w, 5u));
				vec3 shown = mix(light, light * cloth * 0.8, curtain);  // through the fabric: dimmer, its tint
				glass = mix(glass, shown, lit_level);
			}
			color = glass;
		}
	}
	ALBEDO = color;
}
