# Road Rage Trip — Preserve Explicit Level-Aware Underground Roads

Repository: `emehtata/roadragetaxi`

Branch:

`release/0.15.0alpha`

## Context

The map-level and OSM level metadata work is now implemented.

Current architecture:

* `ParkingGarage.levels` is the garage-level model.
* `Way.map_level` represents the explicit logical level of an individual way.
* `Building.map_level` does the same for buildings.
* `Car.map_level` is currently always `0`.
* OSM `level=*` is parsed only when it is a single clean integer.
* OSM `layer=*` remains completely separate.
* `building:levels` remains the building's floor count and does not set `map_level`.
* No level is inferred from garage geometry.
* Level metadata is stored in world-cache format 19 and survives tile streaming.
* The render gate is NOT implemented yet.

All tests currently pass.

However, the latest implementation report identifies an important issue:

> A `service` or `track` road that looks underground (`level<0`, `tunnel=yes`, `parking=underground`, `covered=yes`, ...) is currently dropped during import.

This must be investigated before implementing the render gate.

---

# Goal

Ensure that an OSM road with an explicit logical `level=*` is not accidentally discarded merely because it is an underground/covered garage road.

The principle should be:

```text
explicit OSM level
    -> map_level
    -> runtime world object
    -> later visibility filtering
```

The render gate will decide whether the object is visible.

The importer should not delete a valid level-aware object merely because it is underground.

---

# 1. Inspect before changing anything

Find the exact code responsible for dropping:

* `highway=service`
* `railway=track`
* and other potentially underground ways

when they have characteristics such as:

```text
level<0
tunnel=yes
parking=underground
covered=yes
```

Determine:

1. Why was this filtering introduced?
2. Which OSM objects was it intended to suppress?
3. Which existing tests depend on it?
4. Is it preventing surface-map pollution from underground roads?
5. Can the same problem now be solved by `map_level` visibility instead?

Do not remove the filtering blindly.

---

# 2. Preserve the original intent

The existing filtering presumably exists because underground garage aisles must not appear as ordinary surface roads.

That requirement remains valid.

For example:

```text
highway=service
level=-1
```

must NOT appear on the surface world.

But the correct long-term solution is:

```text
Way.map_level = -1
```

followed by level-aware visibility:

```text
current_map_level = 0
    -> hidden

current_map_level = -1
    -> visible
```

rather than:

```text
OSM
 -> underground
 -> delete object permanently
```

The render gate is not active yet, so be careful about surface rendering compatibility.

---

# 3. Determine the safest transitional behaviour

Because the render gate is not implemented yet, do not simply retain underground ways in the normal renderable road collection if that would make them appear on the surface.

We need a safe transitional architecture.

Possible approaches include:

### Option A — Keep them in the world but make the current surface renderer ignore them

If the existing road/render architecture can do this cleanly using `map_level`, prefer this.

### Option B — Keep them as level-aware world data but exclude them from the legacy surface-road collection

If the architecture distinguishes world data from renderable surface roads, use that.

### Option C — Introduce the smallest necessary separation

If neither existing architecture can safely retain the objects without rendering them on the surface, introduce the smallest data-path change necessary.

Do NOT implement the full render gate in this task.

The purpose is only to ensure the objects survive import and remain available for the next phase.

---

# 4. Explicit level must take precedence over "underground" classification

Consider:

```text
highway=service
level=-1
covered=yes
```

The object should survive as:

```text
map_level=-1
```

It must not be deleted solely because:

```text
covered=yes
```

Similarly:

```text
highway=service
level=-2
```

must survive if the OSM data explicitly places it on level `-2`.

Likewise:

```text
highway=service
level=-1
parking=underground
```

must remain available to the level-aware world.

---

# 5. Be careful with objects without `level=*`

Do NOT simply keep every underground-looking road.

For example, if the existing importer sees:

```text
highway=service
covered=yes
```

with no:

```text
level=*
```

do not invent:

```text
map_level=-1
```

The established rule remains:

> No logical level is inferred from geometry or other underground hints.

Therefore:

```text
level missing
```

must remain:

```text
map_level=None
```

unless the existing importer has an independent, documented reason to classify the object differently.

Do not turn:

```text
tunnel=yes
```

into:

```text
map_level=-1
```

Do not turn:

```text
layer=-1
```

into:

```text
map_level=-1
```

---

# 6. Investigate `parking=underground`

Pay particular attention to:

```text
parking=underground
```

because the existing filtering may have been designed around parking features rather than actual road levels.

Distinguish between:

```text
parking facility metadata
```

and:

```text
road logical level
```

For example:

```text
amenity=parking
parking=underground
```

is a parking facility.

It already has:

```text
ParkingGarage.levels
```

when applicable.

That does not automatically mean an arbitrary nearby road should be assigned a level.

---

# 7. `layer=*` remains separate

Do not change the existing rule:

```text
layer != map_level
```

For example:

```text
highway=service
layer=-1
```

without `level=*` must NOT become:

```text
map_level=-1
```

Likewise:

```text
highway=service
layer=-1
level=-2
```

must retain:

```text
layer=-1
map_level=-2
```

---

# 8. Test with explicit level-aware garage roads

Add tests for cases such as:

```text
highway=service
level=-1
```

and:

```text
highway=service
level=-2
covered=yes
```

and:

```text
highway=service
level=-1
tunnel=yes
```

and, if relevant:

```text
railway=track
level=-1
```

Verify that they survive the OSM build pipeline with:

```text
map_level=-1
```

or:

```text
map_level=-2
```

as appropriate.

---

# 9. Test surface compatibility

Because the render gate is not implemented yet, verify that existing surface rendering behaviour does not regress.

In particular, existing surface roads must continue to behave exactly as before.

An underground level-aware road must not suddenly become a normal surface road merely because it is now retained.

If the current architecture makes that impossible without implementing the full render gate, stop at the smallest safe data separation and document the remaining limitation.

Do not implement the render gate as part of this task.

---

# 10. Test existing filtering behaviour

Preserve tests for legitimate filtering.

If the importer intentionally drops some underground-like objects for reasons unrelated to logical levels, retain those rules where they are still correct.

The task is NOT:

> "Keep every underground OSM object."

The task is:

> "Do not permanently discard an object that has an explicit logical `level=*` merely because it is underground/covered."

---

# 11. Performance

This must remain an import/build-time decision.

Do not introduce:

* per-frame geometry checks;
* garage polygon containment;
* OSM tag parsing during rendering;
* network operations;
* new per-frame scans;
* a new spatial index solely for this fix.

The runtime render path should remain unchanged.

---

# 12. Documentation

Update `docs/parking-garages.md` if necessary.

Document the important distinction:

```text
OSM level=-1
    -> object survives as map_level=-1

OSM layer=-1
    -> rendering order only

underground-looking object without level
    -> no inferred map_level
```

Also document any remaining transitional limitation caused by the fact that the render gate is not yet active.

---

# 13. Acceptance criteria

The task is complete when:

* The existing underground-road filtering has been inspected and understood.
* Explicit `level=*` is not lost merely because a road is underground/covered.
* `Way.map_level` survives through the existing build/cache/streaming pipeline.
* No level is inferred from `layer=*`.
* No level is inferred from `tunnel=*`, `covered=*`, or geometry.
* Objects without explicit `level=*` retain their existing behaviour.
* Existing legitimate filtering remains intact.
* Explicit level-aware garage roads have automated tests.
* Existing tests continue to pass.
* The render gate is NOT implemented in this task.
* No meaningful runtime performance cost is introduced.

At the end, report:

1. The original underground-road filtering rule.
2. Why it existed.
3. What changed.
4. Which underground objects now survive.
5. Which objects are still intentionally dropped.
6. Tests added/updated.
7. Total test count and result.
8. Confirmation that rendering code was not changed.
