shader_type spatial;
uniform sampler2D base_color : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D metallic_roughness : filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_texture : hint_normal, filter_linear_mipmap, repeat_enable;
varying vec3 foliage_colour;
void vertex() { foliage_colour = pow(COLOR.rgb, vec3(2.2)); }
void fragment() {
	vec3 tex = texture(base_color, UV).rgb;
	bool foliage = tex.g > tex.r * 1.05 && tex.g > tex.b * 1.05;
	float shade = clamp(dot(tex, vec3(0.3333)) / 0.45, 0.35, 1.4);
	ALBEDO = foliage ? foliage_colour * shade : tex;
	vec4 mr = texture(metallic_roughness, UV);
	METALLIC = mr.b;
	ROUGHNESS = mr.g;
	NORMAL_MAP = texture(normal_texture, UV).rgb;
}
