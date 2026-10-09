# Road Rage Trip — Phase 10: Preserve Level-Relevant Underground Roads

You are working on the `Road Rage Trip` repository.

**Branch:** `release/0.15.0alpha`

This is **Phase 10** of the parking-garage / map-level implementation.

Phases 1–9 have established:

* `ParkingGarage`
* `Car.map_level`
* level-aware rendering
* level-aware driving networks
* level-aware collision/environment checks
* `LevelConnector`
* `world.level_connectors`
* connector-to-road topology through `road_osm_ids`
* actual player level transitions through resolvable parking entrances
* multi-level roads such as `level=0;-1` being available on the relevant level networks

Phase 9 exposed an important data limitation:

> Several parking entrances reference underground-looking roads that are dropped during OSM import because those roads do not have a clean explicit `level=*`.

This phase investigates and, where safely possible, preserves those roads.

---

# 1. Objective

Improve the OSM import so that underground/garage roads which are genuinely relevant to level connectors are not unnecessarily discarded.

The primary target is the Oulu data found during Phase 9:

```text
22 parking entrances
21 have road_osm_ids
7 reference an underground-looking road that was dropped during import
```

The goal is **not** to make all tunnels into underground roads.

The goal is:

```text
OSM data
    ↓
explicit level evidence
    ↓
safe preservation
```

Only roads whose logical level can be established from explicit, reliable evidence may become level-aware roads.

---

# 2. Hard semantic rule

The existing map-level rules remain authoritative.

Never infer:

```text
tunnel=yes      → map_level=-1
covered=yes     → map_level=-1
layer=-1        → map_level=-1
location=underground → map_level=-1
```

Those tags describe physical/structural properties, not the game's logical map level.

This phase must **not** weaken that rule.

---

# 3. Why this phase exists

Phase 9 found two kinds of connector situations.

Some connectors work:

```text
outside road
level=0

parking entrance

inside road
level=0;-1
```

The topology explicitly proves:

```text
0 ↔ -1
```

Other connectors reference roads which are missing because the road importer previously discarded them.

The relevant pattern is approximately:

```text
parking entrance
      |
      +---- outside road
      |
      +---- underground-looking tunnel/service road
                         |
                         X dropped during import
```

The connector therefore cannot resolve its topology.

This phase investigates whether the missing road's logical level can be established **without guessing**.

---

# 4. First task: audit the actual implementation

Before changing code, inspect:

```text
osm/build.py
osm/models.py
osm/parking.py
osm/pbf_source.py
osm/overpass.py
map_level.py
level_transitions.py
world cache
AutoFetchManager
Way
LevelConnector
```

Find the exact code that currently decides whether an underground-looking road is retained or dropped.

In particular inspect the Phase 4 logic involving:

```text
level < 0
location=underground
parking=underground
parking=multi-storey
parking=sheds
parking=carports
covered=yes
covered=arcade
tunnel=yes
building_passage
```

Do not modify this logic until the actual data has been inspected.

---

# 5. Reproduce the seven Oulu cases

Use the existing Oulu benchmark/import data and identify the seven connector cases reported by Phase 9.

For each affected connector, collect:

```text
connector OSM ID
connector position
connector parking tag
connector level
connector road_osm_ids
each referenced road OSM ID
each road's highway
each road's service
each road's tunnel
each road's covered
each road's layer
each road's location
each road's parking
each road's level
each road's indoor
building/garage relationship where available
```

Also inspect adjacent roads connected to the same entrance.

Do not rely only on the already parsed `Way` objects if the dropped road is no longer represented.

Inspect the source OSM/PBF representation when necessary.

---

# 6. Classify the seven cases

Create a diagnostic classification.

For each dropped road determine whether it is:

1. clearly surface-level
2. clearly underground but with no explicit logical level
3. explicitly multi-level through another connected road
4. part of a garage where the level is known elsewhere
5. genuinely ambiguous

Do not implement anything merely because it belongs to category 2.

Category 2 is intentionally still ambiguous under the game's rules.

---

# 7. Search for explicit topology evidence

The important question is:

> Can the missing road's level be established by another OSM object connected to it?

Investigate:

```text
parking entrance
adjacent road
connected road
multi-level road
garage entrance
garage internal road
building level
relation membership
```

For example, this may be safe:

```text
outside road:
level=0

connector

missing tunnel road:
tunnel=yes
```

but that alone is NOT enough.

However, if the OSM topology contains:

```text
outside road:
level=0

connector

missing road A:
tunnel=yes

connected road B:
level=0;-1
```

then the topology may provide explicit evidence that road A is part of the same `0 ↔ -1` path.

Whether that is safe must be determined from the actual OSM structure.

Do not assume it is safe merely because it looks plausible.

---

# 8. Distinguish level evidence from physical evidence

Create this conceptual separation:

```text
Physical evidence:
    tunnel=yes
    covered=yes
    layer=-1

Logical level evidence:
    level=-1
    level=0;-1
    another explicit OSM level relation
```

Only the second category can establish `map_level`.

Physical evidence may help identify candidate roads for investigation, but it must never independently assign the level.

---

# 9. Connector topology may provide context, not automatic level inference

A connector gives us:

```text
road_osm_ids
```

and therefore identifies roads physically passing through the entrance node.

That is useful.

But do not automatically conclude:

```text
connector linked to garage
→ missing road is underground
→ therefore level=-1
```

That is still inference.

The connector can be used as part of a larger explicit OSM topology proof only if the data supports it.

---

# 10. Investigate road continuity

For each dropped road, inspect its endpoints and connected OSM ways.

Determine:

```text
What road does it connect to?
What level does that road explicitly declare?
Does the missing road form part of a continuous OSM route?
Does another way on that route explicitly identify the logical level?
```

A safe result might look like:

```text
Way A:
level=0;-1

Way B:
tunnel=yes

Way C:
level=-1
```

where the topology unambiguously establishes that B belongs to the `-1` route.

But do not generalize from this example without verifying the actual OSM topology.

---

# 11. Do not propagate levels blindly

Do NOT implement:

```text
connected to level=-1 road
    →
everything connected to it gets map_level=-1
```

That could incorrectly classify:

* surface roads
* ramps
* bridges
* parking entrances
* roads crossing levels
* complex intersections

Level propagation must only be introduced if the actual OSM semantics and topology justify it.

If safe propagation cannot be defined precisely:

```text
keep the road dropped
```

is the correct result.

---

# 12. Prefer explicit OSM data over inferred topology

If OSM contains:

```text
level=-1
```

use it.

If OSM contains:

```text
level=0;-1
```

preserve it as a multi-level road.

If OSM contains neither, do not manufacture:

```text
level=-1
```

just because:

```text
tunnel=yes
```

or because the road is inside a parking garage.

---

# 13. Consider whether the current importer is too aggressive

Inspect the Phase 4 rule:

> Underground-looking roads with a clean explicit `level=*` are retained in `world.level_ways`; those without clean level information are dropped unless already covered by another existing exception.

Determine whether there is a narrower exception that safely preserves the affected roads **without assigning them a logical level**.

For example, it may be useful to preserve an unresolved road as data:

```text
Way.map_level = None
Way.level = None
```

without putting it into a level-specific network.

However:

> Do not do this merely to make the connector work.

Preserving a road with unknown level is only useful if the existing architecture can represent it without accidentally making it a surface road.

---

# 14. Critical distinction: unknown is not surface

The current architecture uses:

```python id="5e6g7n"
Way.map_level is None
```

for surface-visible/level-less roads.

Therefore be extremely careful.

If an underground road with unknown level is stored as:

```python id="ry7jvn"
map_level = None
```

it may accidentally become:

```text
surface road
```

through existing Phase 6 logic.

Do not introduce such a regression.

If an unresolved underground road cannot safely exist in the current `Way` representation, keep it out of the drivable network.

---

# 15. Do not alter `parse_map_level()`

The existing parser is intentionally strict.

It accepts clean single integers such as:

```text
-1
0
1
+1
```

and rejects values such as:

```text
0;-1
0-1
1.5
0;x
```

Do not loosen this function.

Phase 9 already introduced:

```python id="qyrf2p"
explicit_levels(way)
```

for topology analysis.

Continue using that separation.

---

# 16. Multi-level roads remain multi-level

A road such as:

```text
level=0;-1
```

must continue to behave as Phase 9 established:

* `map_level=None`
* remains in the surface network
* appears in `LevelRoadNetworks` for each explicitly named off-surface level
* can be used from either level
* can participate in connector topology

Do not replace this with:

```text
map_level=-1
```

---

# 17. Potential safe improvement: preserve unresolved source data

If investigation shows that a dropped road is important for future topology but cannot yet be assigned a logical level, consider whether the importer should retain a **non-drivable source record**.

For example, a separate collection could theoretically represent:

```text
unresolved underground way
```

but:

> Do not create such a system unless the actual Phase 10 cases demonstrate that it is necessary.

Avoid introducing a parallel road model merely for seven cases.

First try to solve the problem using the existing `Way` / `level_ways` architecture.

---

# 18. Garage data is not level evidence

Do not use:

```text
ParkingGarage.levels
```

to assign a road's `map_level`.

For example:

```text
garage levels = -1,-2,-3
road inside garage
no level tag
```

must remain unresolved.

The fact that the road is inside a garage with underground levels does not identify which level the road belongs to.

---

# 19. Building levels are not road levels

Likewise:

```text
building:levels
building:levels:underground
```

must not be copied onto roads.

These tags describe building floors.

They do not establish the logical level of an individual road.

---

# 20. Relations

Inspect garage relations where relevant.

Phase 8 established a limitation:

> An entrance on a member way of a garage relation may not receive `garage_osm_id`.

Do not solve this by changing garage association semantics.

If relation membership provides explicit level information, document it and use it only if the information is genuinely about the road's level.

Otherwise leave the road unresolved.

---

# 21. Import design

If a safe improvement is found, implement it at the appropriate import/build stage.

Do not patch the result after the world has already been built.

The logical flow should remain:

```text
OSM source
    ↓
parse
    ↓
classify
    ↓
build Way
    ↓
map-level handling
    ↓
world/cache
```

Avoid:

```text
world built
    ↓
special Phase 10 repair pass
    ↓
mutate roads
```

unless the existing architecture already uses such a synchronization mechanism.

---

# 22. Do not add a connector-specific importer

Do not create:

```text
parking entrance importer
underground tunnel importer
garage tunnel importer
```

as separate pipelines.

The connector information already exists.

The road importer should remain responsible for deciding whether a road is represented.

---

# 23. Cache format

If the `Way` model or world representation changes:

* update the cache format according to existing conventions
* ensure old caches rebuild safely
* preserve compatibility semantics

If no persisted representation changes, do not increment the cache version unnecessarily.

---

# 24. Overpass

Do not add new Overpass requests unless required.

The necessary parking entrances are already fetched by Phase 8.

If additional OSM tags are already present in the existing query, reuse them.

The goal is to improve interpretation of existing data, not increase network traffic.

---

# 25. Tests first

Before implementing a general solution, create focused tests representing the discovered Oulu cases.

At minimum test:

### Explicit underground road

```text
level=-1
```

→ preserved as level -1.

### Multi-level road

```text
level=0;-1
```

→ preserved and available on both relevant networks.

### Tunnel without level

```text
tunnel=yes
level=None
```

→ must NOT become `map_level=-1`.

### Covered road without level

```text
covered=yes
level=None
```

→ must NOT become underground.

### Layer without level

```text
layer=-1
level=None
```

→ must NOT become underground.

### Garage without road level

```text
garage.levels=(-3,-2,-1)
road.level=None
```

→ must remain unresolved.

### Topologically supported case

If the audit establishes a safe explicit topology rule, add a test for that exact rule.

Do not create a generic propagation test unless the implementation explicitly guarantees that behaviour.

---

# 26. Regression tests

Verify that existing behaviour remains unchanged:

* surface roads remain surface
* explicit level roads remain level-aware
* multi-level roads remain multi-level
* bridges/tunnels using only `layer` remain surface logical level
* underground roads without explicit level are not accidentally promoted to surface driving roads
* Phase 9 connector transitions still work
* unresolved connectors remain unresolved

---

# 27. Oulu acceptance data

After implementation, produce a table similar to:

```text
Connector | Missing road | OSM tags | Safe level? | Result
```

For all seven previously affected cases.

Classify each as:

```text
preserved
still unresolved
not a valid level connector
```

Do not force all seven to become usable.

A successful Phase 10 may legitimately leave several or all seven unresolved.

Correctness is more important than connector count.

---

# 28. Important success criterion

The target is NOT:

```text
22 connectors
→ 22 working transitions
```

The target is:

```text
maximum amount of correctly represented OSM data
without inventing logical levels
```

If the correct answer for a road is:

```text
unknown
```

keep it unknown.

---

# 29. Performance

Benchmark the Oulu importer before and after.

Record:

* build time
* peak memory if the existing benchmark records it
* number of ways
* number of retained level-aware ways
* number of retained multi-level ways

Also verify runtime performance.

There must be:

```text
no per-frame scan over dropped/import-only roads
no new per-frame OSM processing
no new network calls
```

If an unresolved source collection is introduced, it must not participate in gameplay queries.

---

# 30. Phase 9 regression

After Phase 10, verify the two currently working Oulu transitions:

```text
636848833
0 ↔ -1

4116535367
0 ↔ -2
```

They must continue to work exactly as before.

Do not sacrifice existing valid transitions while attempting to recover the seven unresolved cases.

---

# 31. No gameplay redesign

This phase must not implement:

* new level transitions
* new transition detection
* new connector behaviour
* NPC underground traffic
* pedestrian underground movement
* cross-level routing
* garage parking
* ramp physics
* transition animation

The only gameplay effect should be that a previously missing, safely identifiable road may become available to the existing Phase 9 topology.

---

# 32. Required implementation workflow

Follow this order.

## Step 1 — Audit importer

Find exactly why each of the seven roads is dropped.

## Step 2 — Inspect source OSM

Inspect the raw tags and topology around every affected connector.

## Step 3 — Classify

Determine whether the missing level is:

* explicit
* safely derivable from explicit topology
* ambiguous

## Step 4 — Write focused tests

Tests must describe the actual discovered semantics.

## Step 5 — Implement only a justified rule

Do not generalize beyond what the OSM data supports.

## Step 6 — Rebuild Oulu

Run the actual importer.

## Step 7 — Validate connectors

Compare Phase 9 and Phase 10 connector resolution.

## Step 8 — Run regression tests

Run the complete test suite.

## Step 9 — Benchmark

Compare import/runtime performance.

## Step 10 — Review semantics

Explicitly verify that no physical OSM tag has accidentally become a logical map level.

---

# 33. Things explicitly NOT to implement

Do NOT implement:

* `tunnel=yes → map_level=-1`
* `covered=yes → map_level=-1`
* `layer=-1 → map_level=-1`
* `location=underground → map_level=-1`
* garage level propagation
* building floor propagation
* nearest-level inference
* nearest-garage inference
* connector-distance inference
* arbitrary graph-level propagation
* "everything connected to underground road is underground"
* automatic surface fallback for unknown underground roads
* new connector types
* cross-level routing
* NPC level changes
* pedestrian level changes
* new transition state machines
* network fetching
* new Overpass endpoint logic
* loading screens
* unrelated performance refactoring

---

# 34. Acceptance criteria

Phase 10 is complete only when:

* [ ] All seven Phase 9 dropped-road cases have been individually audited.
* [ ] Their raw OSM tags have been inspected.
* [ ] Their surrounding OSM topology has been inspected.
* [ ] Each case has been classified as safe, unresolved, or irrelevant.
* [ ] No level is inferred from `tunnel`.
* [ ] No level is inferred from `covered`.
* [ ] No level is inferred from `layer`.
* [ ] No level is inferred solely from `location=underground`.
* [ ] No level is inferred from `ParkingGarage.levels`.
* [ ] No level is inferred from building floor counts.
* [ ] `parse_map_level()` remains strict and unchanged semantically.
* [ ] `explicit_levels()` remains the mechanism for multi-level raw values.
* [ ] `level=0;-1` behaviour from Phase 9 remains intact.
* [ ] Any new preservation rule is backed by explicit OSM/topology evidence.
* [ ] Unknown underground roads cannot accidentally become surface roads.
* [ ] Phase 9's two working Oulu transitions still work.
* [ ] No unrelated connectors become resolvable through guesswork.
* [ ] World/cache semantics remain correct.
* [ ] Existing tests pass.
* [ ] New tests cover the actual Phase 10 rule.
* [ ] Oulu is rebuilt and revalidated.
* [ ] Import/build performance shows no significant regression.
* [ ] Runtime frame performance shows no significant regression.
* [ ] No new per-frame processing of unresolved source roads is introduced.

---

# 35. Final implementation report

Provide a concise final report containing:

1. files changed
2. why each of the seven Oulu roads was originally dropped
3. raw OSM patterns found
4. topology findings
5. which cases can be safely preserved
6. which cases remain unresolved and why
7. exact rule implemented
8. how unknown roads are prevented from becoming surface roads
9. cache/version changes
10. Oulu before/after statistics
11. Phase 9 regression results
12. tests added and results
13. full test-suite result
14. import/build benchmark before/after
15. runtime benchmark before/after
16. remaining limitations

Clearly separate:

```text
implemented in Phase 10
```

from:

```text
intentionally left unresolved
```

The implementation must prioritize semantic correctness over increasing the number of usable garage entrances.

Never invent a logical map level from physical OSM characteristics.
