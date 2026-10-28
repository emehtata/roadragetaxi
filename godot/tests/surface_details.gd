## Real map renderer: zoom fade, material variation, pan anchoring, chunk seams and snow.
## Run with a display: godot --path godot --script res://tests/surface_details.gd
extends SceneTree
const MapLayer := preload('res://map_layer.gd')
const Chunk := preload('res://map_chunk.gd')
const CASES := [
	['asphalt', Color8(70,70,70), 1], ['concrete', Color8(166,163,154), 6],
	['paving stones', Color8(157,149,136), 2], ['sett', Color8(126,129,126), 3],
	['cobblestone', Color8(112,117,111), 4], ['gravel', Color8(137,129,112), 5],
	['wood', Color8(112,83,55), 7], ['grass paver', Color8(105,128,90), 8]]
var map: Node2D
var labels: Node2D
var ppm := 9.0

func _initialize() -> void:
	create_timer(30).timeout.connect(func(): quit(1))
	call_deferred('run')

func message() -> Dictionary:
	var roads := []
	var areas := []
	for i in CASES.size():
		var x := (i % 2) * 22.0
		var y := 26.0 - floorf(i / 2.0) * 6.0
		var color: Color = CASES[i][1]
		var rgb := [color.r8,color.g8,color.b8]
		roads.append({'points':[[x+2,y],[x+14,y]],'half_width_m':1.5,'drivable':true,
			'color':rgb,'surface_texture':CASES[i][2]})
		areas.append([rgb,0,[[x+15,y-1.5],[x+19,y-1.5],[x+19,y+1.5],[x+15,y+1.5]],'',CASES[i][2]])
	return {'chunk_id':'all','bounds':[0,0,44,32],'roads':roads,'landuse':areas}

func capture() -> Image:
	for i in 4:
		await process_frame
	await RenderingServer.frame_post_draw
	return root.get_texture().get_image()

func at(i: int, x: float, y: float) -> Vector2i:
	return Vector2i(Vector2(20,70) + Vector2((i%2)*22+x, 30-(26-floorf(i/2.0)*6+y)) * ppm)

func variation(image: Image, index: int, area := false) -> float:
	var low := 1.0
	var high := 0.0
	var start := at(index,16 if area else 4,1)
	for x in range(int(ppm*(2 if area else 8))):
		for y in range(mini(20,int(ppm*0.8))):
			var c := image.get_pixel(start.x+x,start.y+y)
			low = minf(low,c.r)
			high = maxf(high,c.r)
	return high-low

func run() -> void:
	var batch := Chunk.Strokes.new()
	batch.polyline(PackedVector2Array([Vector2.ZERO,Vector2(2,0)]),Color.WHITE,1)
	assert(batch.uvs.is_empty())
	batch.polyline(PackedVector2Array([Vector2(2,0),Vector2(4,0)]),Color.WHITE,1,Vector2(-3,0))
	batch.multiline(PackedVector2Array([Vector2(4,0),Vector2(5,0)]),Color.WHITE,1,Vector2(-3,1))
	batch.polygon(PackedVector2Array([Vector2(0,0),Vector2(0,1),Vector2(1,1)]),Color.WHITE)
	assert(batch.uvs.size()==batch.points.size() and batch.uvs[0]==Vector2.ZERO
		and batch.uvs[4]==Vector2(-3,0) and batch.uvs[8]==Vector2(-3,1) and batch.uvs[-1]==Vector2.ZERO)
	if DisplayServer.get_name()=='headless':
		print('SURFACE_DETAILS: batched UV checks passed; render checks require a display')
		quit(0)
		return
	root.size=Vector2i(1280,900)
	map=MapLayer.new()
	map.position=Vector2(20,70)
	root.add_child(map)
	map.set_origin(Vector2(0,30))
	map.add_chunk(message())
	labels=Node2D.new()
	labels.z_index=100
	root.add_child(labels)
	labels.draw.connect(func():
		labels.draw_string(ThemeDB.fallback_font,Vector2(20,35),'Surface review · %d pixels/metre · road and pedestrian area' % ppm,HORIZONTAL_ALIGNMENT_LEFT,-1,24,Color.WHITE)
		for i in CASES.size():
			labels.draw_string(ThemeDB.fallback_font,Vector2(at(i,2,2.2)),CASES[i][0],HORIZONTAL_ALIGNMENT_LEFT,-1,16,Color.WHITE))
	for scale in [9.0,27.0]:
		ppm=scale
		map.scale=Vector2.ONE*ppm
		map.set_px_per_m(ppm)
		labels.queue_redraw()
		var image := await capture()
		for i in CASES.size():
			for area in [false,true]:
				var delta := variation(image,i,area)
				assert(delta < 0.004 if ppm==9 else delta>0.004, '%s zoom=%s area=%s variation=%s' % [CASES[i][0],ppm,area,delta])
		image.save_png('/tmp/rrt-surface-%d.png' % ppm)
	var original := await capture()
	map.position+=Vector2(13,7)
	var shifted := await capture()
	for i in CASES.size():
		var sample := at(i,5,0)
		assert(original.get_pixelv(sample).is_equal_approx(shifted.get_pixelv(sample+Vector2i(13,7))))
	map.position-=Vector2(13,7)
	map.remove_chunk('all')
	for bounds in [[0,0,10,32],[10,0,44,32]]:
		var part := message()
		part['bounds']=bounds
		part['chunk_id']=str(bounds[0])
		map.add_chunk(part)
	var split := await capture()
	for i in [0,2,4,6]:
		for x in range(-15,16):
			var sample := at(i,10,0)+Vector2i(x,0)
			var a := original.get_pixelv(sample)
			var b := split.get_pixelv(sample)
			assert(absf(a.r-b.r)+absf(a.g-b.g)+absf(a.b-b.b)<0.012,'pattern continues across chunks')
	map.set_wetness(1.0)
	var wet := await capture()
	wet.save_png('/tmp/rrt-surface-wet.png')
	assert(wet.get_pixelv(at(1,5,0)).r < original.get_pixelv(at(1,5,0)).r,'wet concrete darkens')
	map.set_wetness(0.0)
	map.set_road_snow(3.0,[],true)
	var snowy := await capture()
	for i in CASES.size():
		assert(variation(snowy,i)<0.004,'snow hides texture')
	snowy.save_png('/tmp/rrt-surface-snow.png')
	map.free()
	labels.free()
	print('SURFACE_DETAILS: zoom fade, material variation, pan anchoring, seams, wetness and snow passed')
	quit(0)
