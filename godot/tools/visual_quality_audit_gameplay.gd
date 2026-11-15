## Existing named gameplay scenarios with additional audit-only map-idle readiness.
extends SceneTree
class StrictVisual extends 'res://visual_test.gd':
	var context_samples:Array=[]
	var context_clock:=0.0
	var returning:=false
	var return_at:=-1
	func revisit_controls() -> void:
		if context_samples.size()<2:return
		var player:Dictionary=main.entities.shown_state().get('player',{})
		var point:=Vector2(float(player.get('x',0)),float(player.get('y',0)))
		if not returning:
			var dropped:=false
			for id in context_samples[0].chunk_ids:
				if not main.map_layer._chunks.has(id):dropped=true
			if not dropped:return
			returning=true;return_at=context_samples.size()-2
			print('audit: naturally evicted chunks; reversing along recorded driver path')
			if check().is_empty():main.get_viewport().get_texture().get_image().save_png(out_dir.path_join('screenshot_turn.png'))
		while return_at>=0 and point.distance_to(Vector2(context_samples[return_at].position[0],context_samples[return_at].position[1]))<12.0:
			return_at-=1
		var speed:=float(player.get('speed',0))
		var steer:=0.0
		if return_at>=0:
			var target:=Vector2(context_samples[return_at].position[0],context_samples[return_at].position[1])
			var error:=angle_difference(float(player.get('heading',0)),(target-point).angle()+PI)
			steer=-clampf(error*2.0,-1.0,1.0) if speed<0 else 0.0
		main.send({'throttle':1.0 if return_at<0 and speed< -0.2 else 0.0,'brake':1.0 if return_at>=0 else 0.0,'steer_left':maxf(steer,0.0),'steer_right':maxf(-steer,0.0),'forward':0.0,'turn':0.0,'sprint':false})
	func map_sample() -> Dictionary:
		var player:Dictionary=main.entities.shown_state().get('player',{})
		var at:=Vector2(float(player.get('x',0)),float(player.get('y',0)))
		var roads:Array=[]
		for chunk in main.map_layer._chunks.values():
			for road in chunk._data.get('roads',[]):
				var points:PackedVector2Array=chunk._points(road['points'])
				var local:=MapMath.point(chunk._origin,at.x,at.y)
				for i in range(points.size()-1):
					if Geometry2D.get_closest_point_to_segment(local,points[i],points[i+1]).distance_to(local)<8.0:
						roads.append({'color':road.get('color',[]),'surface_texture':road.get('surface_texture',0),'rank':road.get('rank',0),'layer':road.get('layer',0),'drivable':road.get('drivable',false),'half_width_m':road.get('half_width_m',0),'points':road['points']})
						break
		return {'position':[at.x,at.y],'chunk_ids':main.map_layer._chunks.keys(),'roads_at_player':roads}
	func _process(delta:float) -> void:
		super._process(delta)
		if scenario.get('audit_context',false) and _measuring:
			context_clock-=delta
			if context_samples.is_empty() or context_clock<=0:
				context_samples.append(map_sample());context_clock=1.0
				if context_samples.size()==1:main.get_viewport().get_texture().get_image().save_png(out_dir.path_join('screenshot_start.png'))
			if scenario.get('audit_chunk_revisit',false):revisit_controls()
	func forest_view() -> Dictionary:
		var result:={'near_in_frustum':0,'far_in_frustum':0,'outside_frustum':0,'minimum_m':INF,'maximum_m':0.0,'chunks':0,'range_basis':'camera distance to batch AABB centre','near_active_batches':0,'far_active_batches':0}
		var layer=main.map_layer.buildings_3d
		if not is_instance_valid(layer):return result
		var camera:Camera3D=layer._camera
		for chunk in main.map_layer._chunks.values():
			var forest=chunk._dynamic_3d.get('forest')
			if not is_instance_valid(forest):continue
			result.chunks+=1
			for batch:MultiMeshInstance3D in forest.get_children():
				var batch_distance:=camera.global_position.distance_to(batch.global_transform*batch.get_aabb().get_center())
				if batch_distance<batch.visibility_range_begin or (batch.visibility_range_end>0 and batch_distance>=batch.visibility_range_end):continue
				result['far_active_batches' if batch.visibility_range_begin>0 else 'near_active_batches']+=1
				for i in batch.multimesh.instance_count:
					var point:Vector3=batch.global_transform*batch.multimesh.get_instance_transform(i).origin
					var distance:=camera.global_position.distance_to(point)
					if camera.is_position_in_frustum(point):
						result['far_in_frustum' if batch.visibility_range_begin>0 else 'near_in_frustum']+=1
						result.minimum_m=minf(result.minimum_m,distance);result.maximum_m=maxf(result.maximum_m,distance)
					else:result.outside_frustum+=1
		return result
	func check() -> Array:
		var missing:=super.check()
		var state: Dictionary=main.entities.shown_state()
		if state.get('map_loading','')!='': missing.append('audit: server map loading still active')
		if main.hud._map_sign.visible: missing.append('audit: map-loading banner still visible')
		if main._start_sign!=null: missing.append('audit: startup sign still covering the inspected view')
		if scenario.get('audit_forest',false):
			var forest:=forest_view()
			if forest.near_in_frustum==0 or forest.far_in_frustum==0:missing.append('audit: real-map forest near/far geometry not both in camera frustum')
		if scenario.get('audit_live_weather',false):
			var layer=main.map_layer.buildings_3d
			if not is_instance_valid(layer) or not is_instance_valid(layer._precip) or not layer._precip.visible or not layer._precip.particles.emitting or layer._precip.particles.amount<1000:
				missing.append('audit: live world-space precipitation not emitting')
		return missing
	func _write(result: Dictionary) -> void:
		if scenario.get('audit_forest',false):result['audit_forest']=forest_view()
		if scenario.get('audit_road_metadata',false):result['audit_road_metadata']=map_sample()
		if scenario.get('audit_context',false) and not context_samples.is_empty():
			context_samples.append(map_sample())
			var first:Dictionary=context_samples[0];var last:Dictionary=context_samples[-1]
			var added:Array=[];var removed:Array=[];var reloaded:Array=[]
			var prior:Array=first.chunk_ids
			for sample in context_samples:
				for id in sample.chunk_ids:
					if not id in prior:
						if not id in added:added.append(id)
						if id in removed and not id in reloaded:reloaded.append(id)
				for id in prior:
					if not id in sample.chunk_ids and not id in removed:removed.append(id)
				prior=sample.chunk_ids
			result['audit_context']={'samples':context_samples.size(),'travel_m':Vector2(first.position[0],first.position[1]).distance_to(Vector2(last.position[0],last.position[1])),'added_chunk_ids':added,'removed_chunk_ids':removed,'reloaded_chunk_ids':reloaded,'returning':returning,'return_waypoint':return_at,'timeline':context_samples}
		if scenario.get('audit_live_weather',false) and result.get('status')=='passed':
			var missing:=check()
			var first:=Image.load_from_file(out_dir.path_join('screenshot.png'))
			var second:=Image.load_from_file(out_dir.path_join('screenshot_2.png'))
			var different: bool=not first.is_empty() and not second.is_empty() and first.get_data()!=second.get_data()
			if not different:missing.append('audit: temporal weather frames are missing or identical')
			var layer=main.map_layer.buildings_3d
			result['audit_temporal']={'interval_s':scenario.get('second_shot_s',0),'frames_differ':different,'second_frame_readiness':missing,'precip_kind':layer.precip_kind,'particle_count':layer._precip.particles.amount,'emitting':layer._precip.particles.emitting,'speed_scale':layer._precip.particles.speed_scale}
			if not missing.is_empty():result['status']='failed';result['errors']=missing
		super._write(result)
func _initialize() -> void:
	create_timer(290).timeout.connect(func():quit(1))
	call_deferred('run')
func run() -> void:
	var args:=OS.get_cmdline_user_args(); var at:=args.find('--audit-scenario'); assert(at>=0)
	var scenario: Dictionary=JSON.parse_string(FileAccess.get_file_as_string(args[at+1]))
	var game:=preload('res://main.tscn').instantiate()
	game._entered_taxi=true; game._engine_on=true  # Same automation setup as main.gd --visual-test.
	root.add_child(game)
	var test:=StrictVisual.new(); test.main=game; test.scenario=scenario; test.out_dir=args[at+1].get_base_dir()
	game._visual_test=test; game.add_child(test)
