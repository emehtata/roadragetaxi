// rrt-018-shadows: the ground of the shadow view. White in the sun, darker in
// the buildings' shadows; the view is multiplied over the map, so white
// changes nothing. ATTENUATION is the sun's shadow term (1 lit, 0 shadow).
shader_type spatial;
render_mode cull_disabled, specular_disabled, ambient_light_disabled;

uniform float darkness : hint_range(0.0, 1.0) = 0.45;

void fragment() {
	ALBEDO = vec3(1.0);
}

void light() {
	DIFFUSE_LIGHT = vec3(1.0 - darkness * (1.0 - ATTENUATION));
}
