# Forest canopy and mapped trees

The server creates tree objects only from OSM `natural=tree` nodes. Genus,
species and leaf-type tags still choose the existing pine, spruce or birch
appearance. A mapped tree belongs to one scenery area; a standalone mapped
tree is kept as a point scenery so it is streamed; the client knocks it
over when the taxi touches it (client-side only, forgotten when its chunk
reloads). Forests, parks and gardens never receive invented server
tree positions. Tile merges do not plant additional trees.

Mapped `forest`, `wood` and `scrub` polygons carry a dense canopy in the Godot client.
The canopy shader draws overlapping, position-seeded pine, spruce and
birch crowns without creating individual tree nodes, collision shapes or
network records. Crowns render at z13 above cars and tyre tracks. A one-metre visibility mask
baked once per chunk preserves landuse clearings and cuts out roads, railways,
water, parking and buildings. The mask is read once per crown, at its centre:
a crown is drawn whole or not at all, so edges never slice one, and crowns
by a road or clearing overhang it slightly. The canopy layer draws the forest
outline 3.5 m larger so the outermost crowns are whole too (the mask still
keeps crowns to the forest); the flat fill of distant zooms keeps the
per-pixel mask. Transparent gaps between crowns reveal the ground. Adjacent chunks use the same coordinate-based pattern.
Autumn colours affect birches, winter adds snow, and tiny crowns fade into a
simple forest fill at distant map zooms.

These extra canopy trees are visual coverage. Only individually mapped OSM
trees can be knocked over by the taxi. Existing
road-overlap cleanup still applies to mapped tree positions. Wildlife habitat
uses forest tags even when no individual trees were surveyed there.

World cache format 54 invalidates older cached procedural trees. The next load
rebuilds the world cache from OSM source data; game saves are unchanged.

Validation covers unmapped areas staying empty on the server, standalone OSM
trees, species, unique ownership, collision lookup, chunk streaming and fixed
client node counts. Render inspection includes summer, autumn, winter, roads
and an open clearing. The performance workflow uses a shared shader and
distance-dependent detail, following the Godot performance skill's batching
and level-of-detail suggestions.

Before adding the overhead mask, a 1200 x 800 software-rendered test scene used four draw calls and nineteen
nodes with either the dense canopy or a flat fill. Over ninety measured frames,
the canopy averaged 8.1 ms per frame versus 4.5 ms flat on Mesa llvmpipe. This
measures the test scene, not release performance on a hardware GPU. A render of
one forest polygon and the same polygon split into two chunks differed by at
most one colour-channel step from floating-point rasterization.
