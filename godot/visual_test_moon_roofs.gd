## Pixel and final-mesh evidence for the reported Oulu Moon and mapped car shelters.
extends RefCounted

const Buildings3D := preload("res://buildings_3d.gd")

static func moon(main: Node, request: Dictionary) -> Dictionary:
	var layer = main.map_layer.buildings_3d
	if layer == null: return {"missing": ["waiting for lunar sky renderer"]}
	var material: ShaderMaterial = layer._camera.environment.sky.sky_material
	var phase: float = material.get_shader_parameter("moon_illumination")
	var range_: Array = request.get("illumination", [0, 1])
	if phase < range_[0] or phase > range_[1]: return {"missing": ["wrong lunar phase %.3f" % phase]}
	var camera: Camera3D = layer._camera
	var direction: Vector3 = material.get_shader_parameter("moon_dir")
	var at := camera.global_position + direction * camera.far * 0.5
	if not camera.is_position_in_frustum(at): return {"missing": ["Moon outside camera view"]}
	var center := camera.unproject_position(at)
	var sun: Vector3 = material.get_shader_parameter("sun_dir")
	var side := (sun - direction * sun.dot(direction)).normalized()
	var up := direction.cross(side)
	var radius := sqrt(1.0 - 0.99985 * 0.99985)
	var image: Image = layer._view.get_texture().get_image()
	var bright := 0
	var count := 0
	var wrong := 0
	var diagnostic := 0
	var phase_cos := 2.0 * phase - 1.0
	var surface_samples := 0
	var surface_min := 1.0
	var surface_max := 0.0
	var clipped := 0
	for y in range(maxi(0, int(center.y)-60), mini(image.get_height(), int(center.y)+61)):
		for x in range(maxi(0, int(center.x)-60), mini(image.get_width(), int(center.x)+61)):
			var ray := camera.project_ray_normal(Vector2(x+.5,y+.5))
			var p := Vector2(ray.dot(side),ray.dot(up))/radius
			if p.length_squared() > .92: continue
			var incidence := p.x * sqrt(1.0-phase_cos*phase_cos)+sqrt(1.0-p.length_squared())*phase_cos
			var value := image.get_pixel(x,y).r
			var lit := value > .45
			if p.length_squared() < .36 and incidence > .25:
				surface_samples += 1
				surface_min = minf(surface_min, value)
				surface_max = maxf(surface_max, value)
				clipped += int(value > .98)
			count += 1
			bright += int(lit)
			if absf(incidence) > .05: wrong += int(lit != (incidence > 0))
			if p.x > -phase_cos+.03 and incidence < -.02 and not lit: diagnostic += 1
	var fraction := float(bright)/maxi(count,1)
	var missing := []
	if count < 100: missing.append("Moon has too few rendered samples")
	if absf(fraction-phase) > float(request.get("max_area_error",.08)) or float(wrong)/maxi(count,1) > .08:
		missing.append("rendered Moon does not follow spherical phase mask")
	if diagnostic < 2: missing.append("curved gibbous terminator lacks dark pixels inside a straight chord")
	var contrast := surface_max - surface_min if surface_samples > 0 else 0.0
	var clipped_fraction := float(clipped) / maxi(surface_samples,1)
	if request.get("surface_texture", false):
		if surface_samples < 100 or contrast < .1: missing.append("Moon lit interior lacks surface texture contrast")
		if clipped_fraction > .05: missing.append("Moon lit interior clips to white")
	return {"missing":missing,"illumination":phase,"lit_fraction":fraction,"samples":count,"mask_mismatches":wrong,"curved_limb_samples":diagnostic,"surface_samples":surface_samples,"surface_contrast":contrast,"surface_clipped_fraction":clipped_fraction}

static func roofs(main: Node, targets: Array) -> Dictionary:
	var missing := []
	var found := []
	for target: Dictionary in targets:
		var owners := []
		for chunk in main.map_layer._chunks.values():
			for index in chunk._data.get("canopies",[]).size():
				var points: PackedVector2Array = chunk._data.canopies[index]
				if points.size() != target.points.size(): continue
				var matched := true
				for i in points.size():
					if points[i].distance_to(MapMath.point(main.entities.origin,target.points[i][0],target.points[i][1])) > .1: matched=false
				if not matched: continue
				owners.append(chunk)
				var height: float = chunk._data.canopy_heights[index]
				var roofs_seen := 0
				var feet_seen := 0
				var tops_seen := 0
				for local: Vector2 in points.slice(0,points.size()-1):
					var ground: float = Buildings3D.ground_height(chunk.ground_heights,local)
					var roof_seen := false
					var foot_seen := false
					var top_seen := false
					for node in chunk.meshes_3d:
						if not node is MeshInstance3D or node.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY: continue
						for surface in node.mesh.get_surface_count():
							for vertex: Vector3 in node.mesh.surface_get_arrays(surface)[Mesh.ARRAY_VERTEX]:
								var p: Vector3 = node.global_transform * vertex
								if Vector2(p.x,p.z).distance_to(local) > .18: continue
								var h := p.y-ground
								if node.material_override == Buildings3D._shared.glass and absf(h-height)<.15: roof_seen=true
								if node.material_override == Buildings3D._shared.ground:
									if absf(h)<.15: foot_seen=true
									if absf(h-height)<.15: top_seen=true
					roofs_seen += int(roof_seen)
					feet_seen += int(foot_seen)
					tops_seen += int(top_seen)
				found.append({"osm_way":target.osm_way,"height":height,"roof_corners":roofs_seen,"post_feet":feet_seen,"post_tops":tops_seen,"points":target.points})
				if height != 2.5 or roofs_seen<4 or feet_seen<4 or tops_seen<4: missing.append("target roof %s height %.1f corners roof/foot/top=%d/%d/%d" % [target.osm_way,height,roofs_seen,feet_seen,tops_seen])
		if owners.size()!=1: missing.append("target roof %s must have one loaded owner" % target.osm_way)
	return {"missing":missing,"targets":found}
