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

float unit_hash(float seed) {  // buildings_25d.unit
	float f = sin(seed * 12.9898) * 43758.5453;
	return f - floor(f);
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
		float across = abs(UV2.x - (w + 0.5) * bay);  // from the bay's centre
		float up = UV2.y - storey * f;  // within the floor
		bool inside = storefront
			? across <= bay * 0.425 && up >= 0.3 && up <= storey * 0.75  // shop glazing, a band above
			: across <= bay * 0.225 && abs(up - storey * 0.5) <= storey * 0.25;
		if (!skipped && inside) {
			vec3 glass = (storefront ? storefront_color.rgb : window_color.rgb) * ambient.rgb;
			float chance = storefront ? lit_probability.z : house ? lit_probability.y : lit_probability.x;
			if (unit_hash(wall.w + f * 3.71 + w * 1.37) < chance) {
				float shade = 0.82 + 0.18 * unit_hash(wall.w * 0.61803 + f + w);  // warm, each a little brighter or dimmer
				glass = mix(glass, lit_color.rgb * shade, lit_level);
			}
			color = glass;
		}
	}
	ALBEDO = color;
}
