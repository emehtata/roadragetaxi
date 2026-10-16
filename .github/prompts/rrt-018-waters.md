# Fix OSM Coastline and Water Polygon Generation

## Objective

Fix the coastal water rendering problem in Road Rage Taxi, where sea water sometimes extends inland across land areas.

Work on the current release branch and inspect the actual implementation before editing. The primary implementation is expected to be in `src/theroadragetrip/osm/build.py`, particularly `_sea_polygons()`, but verify all relevant data-loading, geometry-building, and Godot rendering paths.

This task is specifically about correct OSM water geometry, not a visual workaround.

## Constraints

- Do not investigate or fix the separate PBF gameplay stuttering issue.
- Do not introduce a binary map-data architecture.
- Do not change traffic simulation, NPC behavior, or unrelated gameplay.
- Preserve the existing online-map and PBF workflows.
- Preserve inland lakes, rivers, canals, reservoirs, islands, and existing water styling.
- Preserve the current server/client architecture.
- Avoid arbitrary geometry buffers, coastline offsets, or rendering masks that merely hide the underlying defect.
- Do not silently discard invalid coastline segments or invent long closing edges that can flood land.
- Git pushes are permitted. Do not create or push Git tags.

## 1. Audit the current geometry pipeline

Inspect:

- How OSM `natural=coastline` ways are collected.
- How coastline nodes are converted to projected coordinates.
- How the fetched bounding box and any expanded fetch bounds are handled.
- How `_sea_polygons()` partitions and classifies the map region.
- How `Water` polygons are constructed and passed to Godot.
- How `natural=water`, `waterway=riverbank`, `natural=bay`, `natural=strait`, reservoirs, and multipolygon relations are handled.
- How polygon holes, islands, invalid geometries, and polygons extending beyond the fetched region are handled.

Determine whether the observed defect is caused by incorrect polygon classification, incomplete coastline coverage, incorrect closure at the fetch boundary, relation processing, overlapping water features, or a later rendering-stage issue.

Do not assume that every water-rendering defect originates in `_sea_polygons()`.

## 2. Correct sea polygon construction

OSM `natural=coastline` is directional linework: land is on the left and sea is on the right when following the way direction.

Replace or improve the current classification algorithm if necessary. In particular, do not classify an entire polygon face solely from the nearest arbitrary coastline segment to the face's representative point.

Use robust planar geometry operations, preferably the Shapely functionality already available in the project.

A suitable approach may include:

1. Clip relevant coastline geometry to the map region while retaining enough context to classify boundaries correctly.
2. Node intersecting linework where required.
3. Combine coastline segments with the relevant map-region boundary.
4. Polygonize the resulting planar linework into candidate faces.
5. Classify faces using coastline direction and their actual boundary relationships.
6. Preserve islands and exclude land faces from the sea geometry.
7. Clip final sea polygons to the intended map bounds.
8. Validate the resulting polygons before constructing `Water` objects.

Treat this as an implementation strategy, not a requirement to use an unsuitable operation blindly. Select the algorithm that correctly handles the actual input geometry and document why it works.

Important edge cases:

- A straight coastline crossing the bounding box.
- A coastline with several bends.
- A bay or inlet.
- A peninsula.
- One or more islands surrounded by sea.
- Multiple nearby islands and narrow channels.
- Coastline segments entering and leaving the bounding box.
- A coastline ending at or near the bounding-box boundary.
- Disconnected or malformed coastline fragments.
- A bounding box entirely inland with no coastline.
- A bounding box entirely offshore.
- A region where the coastline is missing or insufficient to classify sea safely.

Do not infer that all unclassified space is sea. If the data cannot establish a safe classification, fail conservatively and emit useful diagnostics.

## 3. Handle incomplete OSM data safely

OSM coastline data is linework, not a ready-made set of sea polygons. Large-scale coastline processing can also encounter broken or disconnected geometry.

The implementation must distinguish:

- Valid coastline geometry.
- Segments clipped by the requested map bounds.
- Genuine coastline gaps or dangling segments.
- Invalid rings or self-intersections.
- Areas whose sea/land classification is ambiguous.

Use available boundary context when classifying faces. Do not connect arbitrary dangling endpoints across land or use a large geometric buffer as a substitute for topology.

Where appropriate, use Shapely polygonization diagnostics to detect dangling edges, cut edges, and invalid rings.

If the existing map-fetching workflow needs additional coastline context for correct classification, investigate the smallest compatible change. Do not expand data fetching without measuring the effect or solving a demonstrated correctness issue.

## 4. Preserve other water features

Sea polygon generation must remain separate from the normal processing of inland water features.

Verify that:

- `natural=water` areas continue to render.
- Water multipolygon relations preserve their intended geometry.
- Lakes and reservoirs are not reclassified as sea.
- River areas and legacy `waterway=riverbank` features continue to work.
- Islands are not filled by the surrounding sea.
- Existing water kinds and gameplay semantics remain intact.
- No new water polygons extend outside the map's intended bounds.
- Overlapping or duplicate polygons do not introduce unexpected inland flooding.

Do not make a closed way mandatory for every valid water feature; relation members may collectively form the area.

## 5. Add geometry-focused regression tests

Extend the existing tests, including `tests/test_build_waters_relation.py` if appropriate.

Use small deterministic geometries and projected coordinates. Test both the polygon geometry and the final `Water` objects returned by the map builder.

At minimum, verify:

1. A straight coastline produces sea on the correct side.
2. A bent coastline correctly separates land and sea.
3. An island inside the sea remains land.
4. Multiple islands do not become filled with sea.
5. A bay or inlet does not cause sea to extend across its surrounding land.
6. A peninsula does not create a wrongly classified land face.
7. Coastline segments crossing the fetch boundary produce correct geometry within the bounds.
8. A missing or disconnected coastline does not cause the entire map region to be classified as sea.
9. A fully inland region does not acquire a sea polygon.
10. An offshore region is handled correctly when the available geometry supports that conclusion.
11. Inland lakes and reservoirs remain unaffected.
12. Water multipolygon relations retain their existing behavior.
13. Invalid geometry is handled deterministically and produces diagnostics rather than silently generating a huge polygon.
14. All resulting sea polygons are valid and contained within the intended bounds.

Use geometric assertions such as area, containment, intersection, and representative points. Avoid tests that depend on rendering screenshots alone.

For a coastal test, explicitly check known land points and known sea points against the generated sea polygons.

## 6. Diagnose real map cases

Use existing fixtures or add a reproducible coastal fixture representative of a complex Finnish coastline with islands and bays.

If the actual failing map data is available in the repository or test environment, reproduce the issue and add it as a regression test.

Do not claim that a real-world coastline case is fixed unless it has been tested against that geometry.

## 7. Validate and deliver

- Run the focused water and OSM geometry tests.
- Run the broader relevant map-building regression suite.
- Verify existing inland water tests.
- Run the project's supported linting, formatting, and type checks.
- Check that the fix does not alter unrelated map features.
- Do not attempt to solve the deferred PBF stuttering problem.
- Document the root cause, the chosen geometry algorithm, its limitations, and the tests run.
- Commit the changes in a coherent commit and push the working branch if permitted.
- Do not create or push Git tags.

In the final report, distinguish the confirmed root cause from hypotheses, list the files changed, report the tests run, and identify any remaining cases where missing OSM coastline data prevents reliable classification.

Do not mark the task complete merely because the existing straight-coastline test passes.