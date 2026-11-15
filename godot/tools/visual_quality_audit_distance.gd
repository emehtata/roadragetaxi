## Audit-only perspective distances, production chase pose, and indoor player cameras.
extends 'res://tools/visual_quality_audit.gd'
const Modes := preload('res://camera_modes.gd')
class AuditHost extends Node:
	var _visual_test := true
	var _screenshot_path := ''

func run() -> void:
	var args := OS.get_cmdline_user_args()
	var fixture=JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	B3.use_shaded()
	viewport=SubViewport.new(); viewport.size=Vector2i(640,480); viewport.own_world_3d=true
	viewport.render_target_update_mode=SubViewport.UPDATE_ALWAYS; root.add_child(viewport)
	camera=Camera3D.new(); camera.fov=Modes.FOV; camera.near=.05; camera.far=2000; viewport.add_child(camera); camera.current=true
	environment=Environment.new(); environment.background_mode=Environment.BG_COLOR; environment.background_color=Color('303b46')
	environment.ambient_light_source=Environment.AMBIENT_SOURCE_COLOR; environment.ambient_light_color=Color.WHITE; environment.ambient_light_energy=.65; camera.environment=environment
	sun=DirectionalLight3D.new(); sun.rotation_degrees=Vector3(-45,25,0); sun.shadow_enabled=true; viewport.add_child(sun)
	for row: Dictionary in fixture['assets']:
		if not row.has('mode') or row['mode']=='uninspected': continue
		var body:=build(row); viewport.add_child(body); await process_frame
		var box:=bounds(body); var centre:=box.get_center(); var span:=maxf(box.size.x,maxf(box.size.y,box.size.z))
		for distance in ['close','normal','far']:
			var factor:=1.7 if distance=='close' else 4.0 if distance=='normal' else 14.0
			var metres:=maxf(3.0,span*factor)
			# The real chase helper supplies the gameplay FOV/pose; at is behind the inspected target.
			camera.transform=Modes.chase_pose(Vector2(centre.x-metres,centre.z),0,0,0,INF,0, maxf(3.2,centre.y+metres*.2),metres,centre.y)
			camera.look_at(centre)
			B3._shared['road'].set_shader_parameter('surface_pixels_per_m',480.0/(metres*.9))
			for i in 4: await process_frame
			await RenderingServer.frame_post_draw
			var filename:='%s_distance_%s.png' % [row['id'],distance]
			assert(camera.is_position_in_frustum(centre),'target centre not in perspective view')
			assert(viewport.get_texture().get_image().save_png(args[1].path_join(filename))==OK)
			results.append({'asset':row['id'],'file':filename,'angle':distance,'condition':'day perspective distance','distance_m':camera.position.distance_to(centre),'fov':camera.fov,'camera_position':[camera.position.x,camera.position.y,camera.position.z],'camera_method':'CameraModes.chase_pose + target aim','ready':true,'target_confirmed':true,'resolution':[640,480],'lod_scope':'fixed production mesh; no runtime server LOD transition implied'})
		body.free()
		print('AUDIT distance ',row['id'])
	viewport.free()
	# Instantiate the actual indoor view/controller. No replacement gameplay camera is introduced.
	root.size=Vector2i(640,480)
	var host:=AuditHost.new(); root.add_child(host)
	var plans=JSON.parse_string(FileAccess.get_file_as_string('res://tests/data/home_plans.json'))
	var indoor:=preload('res://home_first_person.gd').new(); host.add_child(indoor); indoor._recenter_mouse=false
	for row: Dictionary in fixture['assets']:
		if row['mode']!='interior': continue
		var plan: Dictionary=plans[int(row['index'])]
		assert(indoor.enter(plan),'actual interior enter failed')
		indoor.player.controls_enabled=false
		for i in 15: await physics_frame
		assert(indoor.player.is_on_floor(),'indoor player did not settle on floor')
		var heading: float=indoor.player.rotation.y
		for direction in ['entry_forward','entry_left','entry_back','entry_right']:
			var turn: float=['entry_forward','entry_left','entry_back','entry_right'].find(direction)*PI/2.0
			indoor.player.rotation.y=heading+turn
			for i in 4: await process_frame
			await RenderingServer.frame_post_draw
			var filename:='%s_indoor_%s.png' % [row['id'],direction]
			assert(root.get_texture().get_image().save_png(args[1].path_join(filename))==OK)
			results.append({'asset':row['id'],'file':filename,'angle':direction,'condition':'actual HomeFirstPerson / HomePlayer3D at entry','ready':true,'target_confirmed':true,'on_floor':true,'camera_height':indoor.player.eye_height,'camera_position':[indoor.player.camera.global_position.x,indoor.player.camera.global_position.y,indoor.player.camera.global_position.z],'resolution':[640,480]})
		indoor.leave(); print('AUDIT indoor ',row['id'])
	host.free()
	var file:=FileAccess.open(args[1].path_join('distance-results.json'),FileAccess.WRITE)
	file.store_string(JSON.stringify({'captures':results,'renderer':RenderingServer.get_current_rendering_method(),'adapter':RenderingServer.get_video_adapter_name()},'\t')); file.close(); quit()
