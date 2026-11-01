// rtx-scene-readiness step 3 (--outdoor-3d): roads, markings, water and
// puddles as lit surfaces (buildings_3d._ground).
// UV.x: 0 road, 1 open water (always glossy), 2 a puddle.
// UV.y: the road's surface pattern family (surface.gdshader's, 0 none).
// UV2.x: a puddle's distance from its centre (1 at the rim); UV2.y: 1 on a
// drivable road (it takes the road snow). COLOR.a: a puddle's reveal wetness.
shader_type spatial;
render_mode cull_back;

uniform float wetness : hint_range(0.0, 1.0) = 0.0;  // weather.wetness (map_layer.set_wetness)
uniform float wind = 0.3;  // step 6: open water's waves, 0 calm .. 1 rough (main.gd, as the 2D water's)
// The chunk's road snow per 10 m world cell, ploughed ones cleared (map_chunk._road_snow_3d): one
// texel a cell; cell_map (a, b, cells across, cells down): the texel of layer point p is
// (p.x / 10 + a, -p.y / 10 + b) / (cells across, down) - world y runs up, layer y down.
uniform sampler2D snow_cells : filter_nearest, repeat_disable, hint_default_black;
uniform vec4 cell_map = vec4(0.0, 0.0, 1.0, 1.0);
uniform vec4 puddle_color : source_color = vec4(0.3608, 0.4235, 0.5020, 1.0);  // render_style.PUDDLE_COLOR
uniform vec4 snow_color : source_color = vec4(0.9020, 0.9255, 0.9412, 1.0);  // Color8(230, 236, 240), the 2D road snow

varying vec3 world;

void vertex() {
	world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

float grain_hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

// surface.gdshader's pattern families (map_style.SURFACE_TEXTURES): a shade
// to multiply the colour by (1 + shade), faded out where a metre is under
// 12 pixels, as the 2D map does.
float pattern(int family, vec2 metres, float pixels_per_m) {
	float detail = smoothstep(12.0, 24.0, pixels_per_m);
	if (family <= 0 || detail <= 0.0) {
		return 0.0;
	}
	float shade = 0.0;
	if (family == 2 || family == 3 || family == 4 || family == 6 || family == 7 || family == 8) {
		vec2 cell_size = family == 2 ? vec2(0.24, 0.12) : vec2(0.28, 0.22);
		if (family == 6) cell_size = vec2(3.0, 4.0);
		if (family == 7) cell_size = vec2(0.16, 2.0);
		if (family == 8) cell_size = vec2(0.35);
		vec2 grid = metres / cell_size;
		if (family == 2 || family == 3) grid.x += mod(floor(grid.y), 2.0) * 0.5;
		if (family == 4) grid.x += grain_hash(vec2(floor(grid.y), 1.0));
		vec2 edge = min(fract(grid), 1.0 - fract(grid)) * cell_size;
		float gap = min(edge.x, edge.y);
		float aa = 0.6 / pixels_per_m;
		float seam = 1.0 - smoothstep(0.008 - aa, 0.008 + aa, gap);
		shade = (grain_hash(floor(grid)) - 0.5) * 0.09 - seam * 0.16;
		if (family == 4) {
			float rounded = length((fract(grid) - 0.5) * 2.0);
			shade -= smoothstep(0.78, 1.05, rounded) * 0.12;
		}
		if (family == 8) shade -= (1.0 - smoothstep(0.15, 0.3, length(fract(grid) - 0.5))) * 0.18;
	} else {
		float size = family == 1 ? 0.07 : 0.12;
		vec2 grid = metres / size;
		vec2 blend = smoothstep(vec2(0.0), vec2(1.0), fract(grid));
		vec2 cell = floor(grid);
		float grain = mix(mix(grain_hash(cell), grain_hash(cell + vec2(1,0)), blend.x),
			mix(grain_hash(cell + vec2(0,1)), grain_hash(cell + vec2(1,1)), blend.x), blend.y);
		shade = (grain - 0.5) * (family == 1 ? 0.09 : 0.18);
		if (family == 9) shade += sin((metres.x + metres.y) * 45.0) * 0.025;
	}
	return shade * detail;
}

// Raindrop rings on a puddle: a drop per 0.7 m cell, each ring expanding over
// its own 1.2 s; the slope of the rings, in world xz.
vec2 ripple_slope(vec2 p, float time) {
	vec2 cell = floor(p / 0.7);
	vec2 slope = vec2(0.0);
	for (int dx = -1; dx <= 1; dx++) {
		for (int dy = -1; dy <= 1; dy++) {
			vec2 c = cell + vec2(float(dx), float(dy));
			vec2 drop = (c + vec2(grain_hash(c), grain_hash(c + 7.1))) * 0.7;
			float age = fract(time / 1.2 + grain_hash(c + 3.7));
			vec2 away = p - drop;
			float d = length(away);
			float ring = sin((d - age * 0.6) * 40.0) * (1.0 - age) * exp(-d * 5.0);
			slope += (d > 0.001 ? away / d : vec2(0.0)) * ring;
		}
	}
	return slope;
}

void fragment() {
	int kind = int(round(UV.x));
	vec3 albedo = pow(COLOR.rgb, vec3(2.2));  // sRGB vertex colours, lit in linear space
	if (kind == 2) {  // a puddle: grows from its rim as the road gets wetter (render_style.puddle_strength)
		float reveal = COLOR.a;
		float strength = clamp((wetness - reveal) / max(1.0 - reveal, 0.001), 0.0, 1.0);
		if (strength <= 0.0 || UV2.x > 0.4 + 0.6 * strength) {
			discard;
		}
		vec2 slope = ripple_slope(world.xz, TIME) * 0.35 * wetness;
		NORMAL = normalize(NORMAL - (VIEW_MATRIX * vec4(slope.x, 0.0, slope.y, 0.0)).xyz);
		ALBEDO = puddle_color.rgb * 0.5;
		ROUGHNESS = 0.03;
		SPECULAR = 0.6;
	} else {
		float water = kind == 1 ? 1.0 : 0.0;
		if (kind == 1) {  // step 6: wind waves on open water - a few travelling swells, their slopes as the normal
			vec2 p = world.xz;
			vec2 slope = vec2(cos(dot(p, vec2(0.9, 0.4)) - TIME * 1.3), cos(dot(p, vec2(-0.3, 1.1)) - TIME * 1.1)) * 0.5
				+ vec2(cos(dot(p, vec2(2.3, -1.7)) - TIME * 2.1), cos(dot(p, vec2(1.9, 2.6)) - TIME * 2.4)) * 0.2;
			slope *= 0.08 + 0.25 * clamp(wind, 0.0, 1.0);
			NORMAL = normalize(NORMAL - (VIEW_MATRIX * vec4(slope.x, 0.0, slope.y, 0.0)).xyz);
		}
		float pixels_per_m = 1.0 / max(max(length(dFdx(world.xz)), length(dFdy(world.xz))), 0.0001);
		vec2 cell_uv = (vec2(world.x * 0.1, -world.z * 0.1) + cell_map.xy) / cell_map.zw;
		float snow = clamp(texture(snow_cells, cell_uv).r, 0.0, 1.0) * UV2.y;
		albedo *= 1.0 + pattern(int(round(UV.y)), world.xz, pixels_per_m) * (1.0 - snow);
		albedo *= mix(1.0, 0.6, wetness * (1.0 - water) * (1.0 - snow));  // wet asphalt darkens
		ALBEDO = mix(albedo, snow_color.rgb, snow);
		ROUGHNESS = mix(mix(0.88, 0.12, max(wetness, water)), 0.7, snow);
		SPECULAR = mix(0.4, 0.6, max(wetness, water));
	}
}
