// rtx-scene-readiness step 3 (--outdoor-3d): roads, markings and water as lit
// surfaces. UV.x: 0 a road (dry to wet by the weather), 1 water (always glossy).
shader_type spatial;
render_mode cull_back;

uniform float wetness : hint_range(0.0, 1.0) = 0.0;  // weather.wetness (map_layer.set_wetness)

void fragment() {
	float water = UV.x;
	float wet = max(wetness, water);
	ALBEDO = pow(COLOR.rgb, vec3(2.2)) * mix(1.0, 0.6, wetness * (1.0 - water));  // sRGB vertex colours; wet asphalt darkens
	ROUGHNESS = mix(0.88, 0.12, wet);
	SPECULAR = mix(0.4, 0.6, wet);
}
