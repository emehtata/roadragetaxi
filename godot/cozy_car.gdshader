shader_type spatial;
render_mode cull_disabled;
uniform sampler2D base_color : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D metallic_roughness : filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_texture : hint_normal, filter_linear_mipmap, repeat_enable;
uniform vec3 source_paint : source_color;
uniform vec2 lamp_z;
uniform vec2 front_lamp_height;
uniform vec2 rear_lamp_height;
instance uniform vec4 body_paint : source_color = vec4(1.0);
instance uniform int lamp_bits = 0;
varying vec3 source_position;
void vertex() { source_position = VERTEX; }
void fragment() {
	vec3 tex = texture(base_color, UV).rgb;
	vec3 chroma = tex - vec3(min(tex.r, min(tex.g, tex.b)));
	vec3 paint_chroma = source_paint - vec3(min(source_paint.r, min(source_paint.g, source_paint.b)));
	float match_paint = (length(chroma) > 0.04 && dot(normalize(chroma), normalize(paint_chroma)) > 0.985) ? 1.0 : 0.0;
	float shade = clamp(dot(tex, vec3(0.3333)) / max(dot(source_paint, vec3(0.3333)), 0.01), 0.35, 1.35);
	ALBEDO = mix(tex, body_paint.rgb * shade, match_paint);
	vec4 mr = texture(metallic_roughness, UV);
	METALLIC = mr.b;
	ROUGHNESS = mr.g;
	NORMAL_MAP = texture(normal_texture, UV).rgb;
	bool front = source_position.z > lamp_z.x && source_position.y > front_lamp_height.x && source_position.y < front_lamp_height.y;
	bool rear = source_position.z < lamp_z.y && source_position.y > rear_lamp_height.x && source_position.y < rear_lamp_height.y;
	vec3 srgb = pow(max(tex,vec3(0.0)),vec3(1.0/2.2));
	bool yellow_lens = srgb.r > srgb.b * 1.7 && srgb.g > srgb.b * 1.45 && srgb.r > 0.5;
	bool red_lens = srgb.r > srgb.g * 1.8 && srgb.r > srgb.b * 1.7 && srgb.r > 0.4;
	if ((front && yellow_lens) || (rear && red_lens)) ALBEDO = tex;
	if (front && yellow_lens && (lamp_bits & 1) != 0) EMISSION = vec3(1.0, 0.94, 0.75) * 2.0;
	if (rear && red_lens && (lamp_bits & 3) != 0) EMISSION = vec3(1.0, 0.03, 0.01) * (((lamp_bits & 2) != 0) ? 3.0 : 0.7);
}
