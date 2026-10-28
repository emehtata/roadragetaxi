## Where the place-bound ambience loops sound from (main.gd _feature_loops):
## the nearest playground, campfire spot, beer garden and building site in
## the listener's chunk and its eight neighbours, from the chunk data the
## map already has. World metres (as audio positions are). Sampled twice a
## second by the caller; presentation only.
extends RefCounted

const CHUNK_M := 500.0
const REACH_M := 250.0  # farther than any of their loops' ranges
const KINDS := {
	"playground": ["swing", "slide", "sandpit", "spring_rider", "climbing_frame", "seesaw"],
	"campfire": ["firepit", "tent", "camper_van", "caravan", "caravan_with_car"],
	"biergarten": ["biergarten"],
}


## {"playground", "campfire", "biergarten", "construction"} -> the nearest
## site's world position within REACH_M, or null.
static func nearest(chunks: Dictionary, origin: Vector2, at: Vector2) -> Dictionary:
	var best := {"playground": null, "campfire": null, "biergarten": null, "construction": null}
	var distance := {"playground": REACH_M, "campfire": REACH_M, "biergarten": REACH_M, "construction": REACH_M}
	var cell := Vector2i(floori(at.x / CHUNK_M), floori(at.y / CHUNK_M))
	for x in range(-1, 2):
		for y in range(-1, 2):
			var chunk = chunks.get("%d_%d" % [cell.x + x, cell.y + y])
			if chunk == null:
				continue
			for row in chunk._data.get("scenery_objects", []):
				var point := Vector2(float(row[0]), float(row[1]))
				for key in KINDS:
					if str(row[2]) in KINDS[key] and point.distance_to(at) < distance[key]:
						distance[key] = point.distance_to(at)
						best[key] = point
			for ring in chunk._data.get("construction_fences", []):  # layer metres once MapChunk._compact ran, else world [x, y]
				if ring.size() == 0:
					continue
				var middle := Vector2.ZERO
				for p in ring:
					middle += p if p is Vector2 else Vector2(float(p[0]), float(p[1]))
				middle /= ring.size()
				var point := Vector2(middle.x + origin.x, origin.y - middle.y) if ring is PackedVector2Array else middle
				if point.distance_to(at) < distance["construction"]:
					distance["construction"] = point.distance_to(at)
					best["construction"] = point
	return best
