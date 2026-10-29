shader_type spatial;
render_mode unshaded, cull_back;

uniform vec4 ambient : source_color = vec4(1.0);
uniform float snow_cover : hint_range(0.0, 1.0) = 0.0;
uniform vec4 snow_color : source_color = vec4(0.84314, 0.87843, 0.90980, 1.0);
// Windows are drawn here, not as geometry (a city centre had 118k window quads
// and as many lit ones): each wall vertex carries UV2 = (metres along the wall,
// metres up) and CUSTOM0 = (wall length, storey height, windows per floor +
// 1000 x category + 10000 x (shop state + 1), seed); roofs and gables carry no windows (0). Modelled on
// Oulu's Valkea talo: a window in every ~3 m bay of every floor, about half
// the storey tall; a shop's ground floor glazed nearly bay to bay (category
// 2); houses wider bays, every other floor. A share lit at night.
uniform vec4 window_color : source_color = vec4(0.22745, 0.31373, 0.36863, 1.0);  // buildings_25d.WINDOW
uniform vec4 storefront_color : source_color = vec4(0.32941, 0.41569, 0.47843, 1.0);  // .STOREFRONT
uniform vec4 lit_color : source_color = vec4(1.0, 0.87059, 0.55686, 1.0);  // buildings_3d.WINDOW_LIT_NIGHT
uniform float lit_level : hint_range(0.0, 1.0) = 0.0;  // Daylight.artificial: 0 by day, 1 at night
uniform float independence_candles = 0.0;  // 1 on 6 December 18-24 (holiday_events.independence_candles)
uniform float decorations = 0.0;  // 1 from the first Advent to Epiphany (holiday_events.window_decorations)
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

// A star lamp's own light: amber incandescent through warm white to cool LED.
vec3 star_light(float pick) {
	return pick < 0.7 ? mix(vec3(1.0, 0.58, 0.25), vec3(1.0, 0.88, 0.65), pick / 0.7)
		: mix(vec3(1.0, 0.88, 0.65), vec3(0.78, 0.88, 1.0), (pick - 0.7) / 0.3);
}

// A Finnish window's Christmas: an Advent candle bridge (kynttelikkö, seven
// candles in a triangle on the sill) or a paper star lamp (joulutähti) in
// the top of the window. `p`: metres from the window's bottom centre; `size`:
// its half width and height. The glow's strength (0 none) and colour.
vec4 decoration(vec2 p, vec2 size, float kind, float tint, float size_pick, float temperature, float night) {
	if (kind < 0.4) {  // a star, red or white
		vec2 c = p - vec2(0.0, size.y * 0.68);
		float r = min(size.x * 0.75, size.y * 0.3) * mix(0.55, 1.0, size_pick);
		float a = atan(c.y, c.x) - radians(90.0);
		float half_sector = radians(36.0);
		float sector = abs(mod(a + half_sector, half_sector * 2.0) - half_sector);
		// Ray intersection with a straight edge between an outer tip and inner corner.
		vec2 corner = vec2(cos(half_sector), sin(half_sector)) * 0.45;
		float edge = r * corner.y / (corner.y * cos(sector) + (1.0 - corner.x) * sin(sector));
		if (length(c) <= edge) {
			vec3 paper = tint < 0.6 ? vec3(0.85, 0.12, 0.08) : vec3(0.95, 0.93, 0.86);
			return vec4(mix(paper * 0.8, paper * star_light(temperature) * 1.2, night), 1.0);
		}
		return vec4(0.0);
	}
	// The candle bridge: a stepped triangle of seven candles, a bulb on each.
	float span = size.x * 0.85;
	float tall = min(size.y * 0.5, span * 0.9);
	float slot = span * 2.0 / 7.0;
	float i = clamp(floor((p.x + span) / slot), 0.0, 6.0);
	float step_up = 1.0 - abs(i - 3.0) / 3.0;  // the middle candle highest
	float candle_top = tall * (0.45 + 0.4 * step_up);
	float x = p.x + span - (i + 0.5) * slot;
	if (abs(p.x) <= span && p.y >= 0.0 && p.y <= tall * 0.12) {
		return vec4(vec3(0.92, 0.9, 0.85) * mix(0.8, 0.5, night), 1.0);  // the white wooden base
	}
	if (abs(x) <= slot * 0.18 && p.y > tall * 0.12 && p.y <= candle_top) {
		return vec4(vec3(0.92, 0.9, 0.85) * mix(0.8, 0.45, night), 1.0);  // a candle
	}
	if (length(vec2(x, (p.y - candle_top - slot * 0.3) * 0.8)) <= slot * 0.32) {
		return vec4(mix(vec3(0.75, 0.68, 0.45), vec3(1.25, 1.05, 0.6), night), 1.0);  // its bulb, glowing at night
	}
	return vec4(0.0);
}

// Independence Day: two white candles side by side in the middle of the
// sill, their flames glowing. `p`: metres from the window's bottom centre;
// `size`: its half width and height. Colour and coverage (0 none).
vec4 independence_candle(vec2 p, vec2 size) {
	float thick = max(0.05, size.x * 0.07);
	float x = abs(p.x) - thick * 1.7;  // from a candle's axis: the pair a hand's width apart
	float tall = min(size.y * 0.32, 0.3);
	if (abs(x) <= thick && p.y >= 0.0 && p.y <= tall) {
		return vec4(0.93, 0.92, 0.88, 1.0);  // the candle
	}
	vec2 flame = vec2(x / (thick * 1.1), (p.y - tall - thick * 1.4) / (thick * 2.0));
	if (length(flame) <= 1.0) {
		return vec4(1.35, 1.0, 0.45, 1.0);  // its flame
	}
	if (length(flame) <= 2.6) {
		return vec4(1.0, 0.75, 0.35, 0.35 * (2.6 - length(flame)) / 1.6);  // its glow on the glass
	}
	return vec4(0.0);
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
		float category = mod(floor(wall.z / 1000.0 + 0.001), 10.0);
		float shop_state = floor(wall.z / 10000.0) - 1.0;  // unknown / closed / open, from the server
		bool house = abs(category - 1.0) < 0.5;
		bool retail_hall = abs(category - 4.0) < 0.5;
		float storey = wall.y;
		float f = floor(UV2.y / storey);
		bool storefront = (abs(category - 2.0) < 0.5 || retail_hall) && f < 0.5;
		bool skipped = (house && mod(f, 2.0) > 0.5) || (retail_hall && f > 0.5);
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
			if (storefront && shop_state >= 0.0) {
				chance = shop_state;  // all shop windows open, none closed; upper apartments stay independent
			}
			if (window_hash(wall.w, f, w, 0u) < chance) {
				bool shop_open = storefront && shop_state > 0.5;
				vec3 light = shop_open ? vec3(0.95, 0.95, 0.87) : room_light(window_hash(wall.w, f, w, 4u)) * (0.78 + 0.27 * window_hash(wall.w, f, w, 5u));
				vec3 shown = mix(light, light * cloth * 0.8, curtain);  // through the fabric: dimmer, its tint
				glass = mix(glass, shown, shop_open ? 1.0 : lit_level);
			}
			if (decorations > 0.5 && window_hash(wall.w, f, w, 6u) < (storefront ? 0.4 : 0.25)) {
				vec4 deco = decoration(vec2(across, up - bottom), vec2(half_width, top - bottom),
					window_hash(wall.w, f, w, 7u), window_hash(wall.w, f, w, 8u),
					window_hash(wall.w, f, w, 10u), window_hash(wall.w, f, w, 11u), lit_level);
				glass = mix(glass, deco.rgb * mix(ambient.rgb, vec3(1.0), lit_level), deco.a);  // its own light at night
			}
			if (independence_candles > 0.5 && window_hash(wall.w, f, w, 9u) < (storefront ? 0.2 : 0.7)) {
				vec4 candle = independence_candle(vec2(across, up - bottom), vec2(half_width, top - bottom));
				glass = mix(glass, candle.rgb, candle.a);  // their own light: no ambient dimming
			}
			color = glass;
		}
	}
	ALBEDO = color;
}
