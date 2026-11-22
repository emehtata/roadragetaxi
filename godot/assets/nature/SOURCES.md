# Cozy Nature mapped vegetation

Grab3D [Cozy Nature](https://grab3d.com/kits/cozy-nature/), CC0 1.0. Full legal text is `CC0-1.0.txt`; each model has its unchanged original manifest (`*.source.json`), notice (`*.LICENSE.txt`), download URL/hash and measured source information (`*.json`). Retrieved 2026-11-22. Finnish, English and German credits display the selected models.

| Existing kind | Source | Triangles |
|---|---|---:|
| spruce | Spruce Tree | 14,248 |
| pine | Pine Tree | 8,032 |
| birch | Birch Tree | 22,914 |
| shrub | Bush | 11,570 |

No Light variants are offered in the manifests. Keep all authored triangles and child transforms. Ground-centre the combined bounds; use one uniform scale bounded by existing crown diameter and total height, with deterministic position-derived yaw. Materials retain UVs, tangents and textures; only green foliage texels receive the existing seasonal instance colour, leaving bark/flowers intact. No new nature placements are generated.

Dense polygon forests retain their existing near/far primitive MultiMeshes: these source trees contain 8,032–22,914 triangles each versus hundreds for the near primitives. Mapped individual/tree-row trees and shrubs use the GLBs. Leafless birch retains the existing seasonal fallback because bark and foliage share one inseparable body mesh. Felled trees retain their verified horizontal trunk/crown geometry: a uniformly laid whole source crown lifts the trunk clear of the ground; preserving the existing source stem/crown contact envelope would require deformation. The Fallen Log candidate is 2.0314m long, 0.4292m high and 0.4957m wide, with an authored branch stub/moss. A uniform fit to existing trunk length would exceed the pine/birch trunk diameter; reducing it to the trunk diameter shortens the trunk and breaks crown contact. It is not shipped.

The Boulder Rock Set candidate has one inseparable mesh containing three rocks (10,112 triangles; about 3.42 ×1.14 ×1.50m), unsuitable for an existing single mapped boulder. No rock asset is shipped. Hedges remain continuous map-line geometry rather than repeated disconnected bushes.
