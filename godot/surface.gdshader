// Pattern families match map_style.SURFACE_TEXTURES. UV.x is negative family; UV.y is snow cover.
shader_type canvas_item;
varying vec2 metres;

float grain_hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void vertex() {
	// Chunk geometry already uses the map's shared metre coordinates.
	metres = VERTEX;
}

void fragment() {
	float pixels_per_m = 1.0 / max(max(length(dFdx(metres)), length(dFdy(metres))), 0.0001);
	float detail = smoothstep(12.0, 24.0, pixels_per_m) * (1.0 - clamp(UV.y, 0.0, 1.0));
	if (UV.x < -0.5 && detail > 0.0) {
		int family = int(round(-UV.x));
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
		COLOR.rgb *= 1.0 + shade * detail;
	}
}
