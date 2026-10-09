# Godot-16: Complete the Remaining Static World (Phase 6b)

Continue the Godot migration from the current repository state.

`godot-15` is complete and pushed. Do not create or push a Git tag. You may create commits and push them to the remote.

The previous phase completed the main static scenery layer. Before navigation, finish the remaining **static-world rendering and map presentation** that can be migrated without introducing navigation or physics.

This is deliberately a broad but still bounded phase: the objective is to make the Godot world visually complete enough that navigation can later be built on top of a stable representation of the world.

## Current architecture

Preserve these principles:

* The server is authoritative.
* Godot has no physics.
* Godot does not perform gameplay collision.
* Godot renders authoritative server/map state.
* Static objects belong to deterministic map chunks.
* Dynamic state is sent separately where appropriate.
* Do not introduce a second simulation of anything already owned by the server.

The current Godot baseline is approximately:

* 145 FPS
* 0 backward rendering steps
* taxi exactly centred
* ~78.7 MiB static memory

Do not sacrifice this baseline unnecessarily.

## First: inspect before implementing

Inspect the current implementation and Pygame rendering for all remaining parity items.

In particular inspect:

* roads
* road colours
* road markings
* curbs
* crossings
* speed bumps
* signs
* speed cameras
* bus stops
* landuse
* parking areas
* traffic islands
* labels
* buildings
* canopies
* bridges
* underground map levels
* tire tracks
* existing fuel-station rendering

Determine for each item:

1. Is it authoritative server/map data?
2. Does it already exist in the current protocol?
3. Should it be static chunk data?
4. Can it be deterministically derived by Godot?
5. Does it require additional server data?
6. Is it genuinely dependent on future navigation?

Do not simply reproduce Pygame's architecture. Reproduce the visual result using the existing Godot architecture.

---

# 1. Landuse

Implement the remaining landuse rendering that is visible in Pygame.

Examples may include:

* parks
* forests
* residential/commercial/industrial areas
* other meaningful landuse regions

Use the existing map data where possible.

Avoid sending unnecessarily detailed polygon data if the Godot client can derive the same visual representation from data it already receives.

Do not turn landuse into collision geometry.

---

# 2. Parking areas and traffic islands

Implement visible:

* parking areas
* parking surfaces
* traffic islands
* medians
* other equivalent static road-adjacent areas

Preserve their geometry and visual relationship with roads.

Do not add collision shapes.

Do not implement parking-garage navigation in this phase.

The existing underground parking-garage architecture remains a later gameplay/navigation concern.

---

# 3. Curbs and road edges

Implement the visual curb/road-edge treatment that is currently missing.

Inspect Pygame carefully for:

* curb widths
* curb colours
* raised/lowered appearance
* transitions at intersections
* transitions around traffic islands
* transitions around parking areas

The goal is visual parity, not physical collision.

Avoid creating thousands of individual scene nodes if batched drawing can represent the same result.

---

# 4. Crossings and speed bumps

Implement the remaining road markings/features:

* pedestrian crossings
* other crossings represented by Pygame
* speed bumps

Match:

* placement
* orientation
* width
* spacing
* colours
* relationship to the road

Do not make speed bumps affect vehicle movement. The server remains authoritative for all gameplay collision/simulation.

---

# 5. Traffic signs, speed cameras and bus stops

Implement the static visual representation of:

* traffic signs
* speed cameras
* bus stops

Where an object has a gameplay effect on the server, Godot should only display the authoritative object/state.

Do not implement client-side:

* speed-camera logic
* traffic enforcement
* bus scheduling
* passenger navigation
* collision

If these objects already exist in server state but are not currently sent to Godot, add the minimum required protocol representation.

Use deterministic chunk ownership.

---

# 6. Labels

Implement map/world labels that are visible in Pygame and still missing from Godot.

Inspect the existing label system carefully.

Preserve:

* text
* placement
* visibility rules
* zoom behaviour
* hierarchy/importance
* orientation

Do not create labels for every tiny map object if Pygame does not do so.

Avoid excessive scene-tree nodes.

If labels can be batched or drawn through a lightweight system, prefer that.

---

# 7. Road markings and road colours

Complete the visual road presentation.

This includes, where present in Pygame:

* lane/edge markings
* centre lines
* dashed lines
* solid lines
* directional markings
* special road markings
* road surface colours
* road-class-specific appearance

Do not infer traffic lanes for navigation in this phase.

This phase is rendering only.

The eventual navigation system must not depend on a client-only approximation created here.

Ensure markings remain stable when chunks unload and reload.

Avoid duplicated markings at chunk boundaries.

---

# 8. Building detail

This is an important architectural step.

Godot currently uses flat top-down buildings rather than Pygame's old slanted/isometric facade renderer.

Do **not** bring back the old facade renderer.

Instead, implement a lightweight top-down building-detail representation that preserves the advantages of the Godot view.

Investigate what can reasonably be represented from existing building data:

* roof shapes
* roof colours
* building outlines
* entrances if already available
* building categories
* windows where a top-down representation makes sense
* other visually important building details

The previous phase established that Pygame's lit windows cannot simply be copied because its windows are drawn on slanted facades.

Therefore:

* do not fake the old facade windows in a flat top-down view
* design a suitable top-down equivalent if useful
* keep lit-window parity explicitly partial if there is no visually correct representation

The result should remain lightweight.

---

# 9. Open-roof canopies and fuel stations

Fix the visual problem where solid building/canopy geometry hides fuel pumps.

Implement the correct top-down representation for open-roof canopies.

The canopy should visually read as an overhead structure while still allowing the fuel pumps underneath to be visible.

Preserve existing fuel-pump positions and server gameplay behaviour.

This should also address the deferred godot-12 item:

> fuel pumps hidden under the solid canopy

Do not modify fuel simulation.

Do not implement the fuel-price HUD unless it is trivial and directly part of the same existing rendering/data path. Otherwise leave it explicitly deferred.

---

# 10. Rail bridges

Implement the static visual representation of rail bridges/overpasses where Pygame renders them.

Correctly represent:

* bridge deck
* road/rail crossing relationship
* visual layering
* supports where appropriate

Do not implement train physics or route logic.

The purpose here is visual world completeness before navigation.

---

# 11. Underground levels

Inspect the existing parking-garage and underground-level representation.

This phase should establish the **rendering** required for underground levels where feasible, but must not become a navigation phase.

If the current server already provides map-level information:

* render the correct level
* hide geometry belonging to other levels as appropriate
* preserve existing `Car.map_level` semantics
* preserve existing chunk loading

Do not implement new underground routing.

Do not invent client-side level transitions.

If a missing server-side representation prevents correct rendering, add only the minimal authoritative data required.

---

# 12. Tire tracks

Implement the visual tire-track representation if it already exists in Pygame.

Determine whether tracks are:

* persistent world state
* transient effects
* weather-dependent
* vehicle-dependent

Use the existing architecture.

Do not create an unbounded accumulation of Godot nodes.

If tracks are transient, implement an appropriate bounded/lifetime-based rendering mechanism.

If they are authoritative server state, render that state rather than simulating it locally.

---

# 13. Snow readability

Fix the readability issue identified in godot-15:

> white trip/odometer text is difficult to read against snow.

Do this in the existing HUD architecture.

Do not change the visual identity unnecessarily.

The solution should work both:

* on normal terrain
* on snow-covered terrain

Do not introduce a client-local weather detector.

---

# 14. Headlight beam road-layer limitation

Godot-15 left headlight beams partially complete because beams do not yet account for vehicles under a higher road.

Investigate whether the existing world/road representation can solve this cleanly.

If the server already has the required road-level information, expose only what is needed.

Do not introduce a general-purpose client physics or occlusion system.

If solving this correctly would require navigation/road-topology architecture that belongs to the next phase, leave it partial and document the reason.

Do not force a fragile workaround merely to mark the parity item complete.

---

# 15. Traffic-light deferred issue

The godot-12 deferred issue remains:

> traffic-light phases are only sent within 600 m.

Do not redesign the traffic-light protocol in this phase unless the static-world implementation genuinely requires it.

If it remains deferred, leave it explicitly documented.

---

# 16. Protocol and chunk design

Any new static-world data must follow the established rules:

* deterministic
* compact
* exactly one owning chunk
* no duplicates
* safe to unload/reload
* backwards-compatible where practical

Do not add large per-tick payloads for static objects.

Static data belongs in chunk data.

Dynamic state belongs in tick/state data.

Do not send information every tick merely because it is easier.

---

# 17. Performance

Performance is a hard requirement.

The previous phase initially reached 92.9 MiB before batching and finished at approximately 78.7 MiB.

Continue to batch static drawing.

Pay particular attention to:

* road markings
* curbs
* landuse polygons
* parking areas
* labels
* building details
* signs
* bus stops
* bridges

Avoid:

* one Node2D per tiny marking
* one node per curb segment
* one node per road label
* per-frame rebuilding of static geometry
* unnecessary duplicate copies of map geometry

Measure:

* FPS
* static memory
* startup time
* chunk load/unload cost

Compare against godot-15.

If memory increases significantly, investigate whether the increase is caused by:

* genuinely required map data
* duplicate representations
* excessive Godot nodes
* unbatched geometry

Fix avoidable overhead.

---

# 18. Tests

## Python

Add/update tests for:

* chunk assignment
* no duplicate static objects
* protocol serialization
* road-marking data
* sign/bus-stop/camera data
* building/canopy data
* bridge/level data where applicable

Do not weaken existing tests.

The unexplained godot-14 screenshot test has not recurred. If it reappears, investigate it rather than masking it.

## Godot

Extend the existing test suite for:

* landuse
* parking
* traffic islands
* curbs
* crossings
* speed bumps
* signs
* speed cameras
* bus stops
* labels
* road markings
* road colours
* building detail
* open-roof canopies
* visible fuel pumps
* rail bridges
* underground rendering
* tire tracks if implemented
* snow HUD readability
* chunk unload/reload
* duplicate prevention

Keep the existing 197+ checks intact.

---

# 19. Real-server Oulu verification

Use the real Oulu server.

Verify at minimum:

1. Roads and markings render correctly.
2. Curbs and traffic islands match the map.
3. Crossings and speed bumps appear correctly.
4. Signs, cameras and bus stops appear correctly.
5. Labels appear at appropriate zoom.
6. Buildings remain visually correct in the flat top-down view.
7. Fuel pumps are visible under open-roof canopies.
8. Rail bridges have correct visual layering.
9. Underground/level rendering behaves correctly where testable.
10. Tire tracks behave correctly if implemented.
11. Snow remains readable in the HUD.
12. Existing godot-15 street lights, seasons, headlight beams and scenery remain intact.
13. Chunk unload/reload does not duplicate or lose static objects.

Use real-server screenshots and pixel checks where practical.

---

# 20. Documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Document:

* all newly migrated static-world categories
* protocol additions
* batching strategy
* building-detail approach
* canopy representation
* underground rendering status
* remaining deliberate differences
* performance measurements

Update the parity table accurately.

Do not mark navigation complete.

---

# 21. Acceptance criteria

The phase is complete when:

* The remaining major static-world presentation is implemented.
* Landuse, parking and traffic islands are rendered.
* Curbs are rendered.
* Crossings and speed bumps are rendered.
* Signs, speed cameras and bus stops are rendered.
* Labels are rendered.
* Road markings and road colours are rendered.
* Building detail has a suitable top-down Godot representation.
* Open-roof canopies no longer hide fuel pumps.
* Rail bridges are rendered.
* Underground rendering is implemented where supported by the existing architecture.
* Tire tracks are implemented where appropriate.
* Snow HUD readability is fixed.
* Headlight road-layer handling is either correctly completed or deliberately documented as partial with a concrete architectural reason.
* Existing godot-15 behaviour remains intact.
* No client-side collision or navigation is introduced.
* Python tests pass.
* Godot tests pass.
* Real-server Oulu verification succeeds.
* Performance remains acceptable and static drawing remains batched.
* Documentation is updated.
* Changes are committed and pushed.
* No Git tag is created or pushed.

At the end, provide a concise report containing:

1. Files changed
2. Protocol changes
3. Server changes
4. Godot changes
5. Static-world items completed
6. Items deliberately left partial
7. Tests
8. Real-server verification
9. Performance measurements
10. Updated parity counts
11. Remaining gaps before navigation
12. Commit hashes

Do not stop at an architectural proposal. Implement the phase fully.
