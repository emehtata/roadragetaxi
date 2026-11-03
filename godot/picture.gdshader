// The graphics settings' brightness and contrast over the game world (main.gd
// _apply_graphics: drawn over the Sky layer, under the HUD).
shader_type canvas_item;

uniform sampler2D screen : hint_screen_texture, filter_nearest;
uniform float brightness = 1.0;
uniform float contrast = 1.0;

void fragment() {
	vec3 c = texture(screen, SCREEN_UV).rgb;
	c = pow(c, vec3(1.0 / brightness));  // brightness as gamma, as games do: darks lift, whites stay white
	COLOR = vec4(clamp((c - 0.5) * contrast + 0.5, 0.0, 1.0), 1.0);
}
