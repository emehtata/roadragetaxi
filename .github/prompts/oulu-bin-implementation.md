You are working on the Road Rage Taxi / The Road Rage Trip repository:

https://github.com/emehtata/roadragetaxi

**Current branch:** `release/0.15.0alpha`

## Goal

Integrate the new city-specific V2 road-network binary files into the game's runtime road-network/routing system.

The primary goal is to allow predefined cities to load their road network from a compact pre-generated `.bin` file instead of downloading/extracting the road network dynamically.

However, the **existing OSM/Overpass/PBF-based implementation MUST remain fully functional as a fallback**.

This fallback is essential because the game supports custom cities. A player must be able to configure a city that does not have a pre-generated `.bin` file and still use the existing dynamic OSM/PBF mechanism.

The architecture should therefore become:

```text
                    City configuration
                           │
                           ▼
                 Is a city BIN available?
                    /                 \
                  YES                  NO
                   │                    │
                   ▼                    ▼
             Load city BIN       Existing OSM/PBF
                   │               / Overpass path
                   │                    │
                   └────────┬───────────┘
                            ▼
                     Common road API
                            │
                            ▼
                    Existing game systems
```

Do NOT redesign the whole game.

Do NOT remove the existing OSM/PBF implementation.

Do NOT change rendering, NPC behavior, traffic simulation, residents, traffic lights, physics, or unrelated systems unless a very small compatibility change is genuinely required.

---

# 1. First inspect the existing implementation

Before modifying anything, inspect the repository carefully.

In particular, identify:

- current city configuration and city selection;
- how predefined cities are represented;
- how custom cities are represented;
- current OSM/PBF loading;
- current Overpass loading;
- current road-network data structures;
- current routing implementation;
- how road geometry is accessed;
- how nodes and ways are identified;
- where road data is cached;
- how the current tile-based map streaming interacts with road data;
- whether the current routing system expects a complete graph or tile-local data;
- existing V2 Finland road binary generator;
- existing V2 road binary loader;
- Oulu benchmark implementation;
- multi-city benchmark implementation.

Relevant existing tools/files are likely under:

```text
tools/osm/
src/theroadragetrip/osm/
tests/
```

But do not assume exact filenames. Find the actual implementation first.

Do not duplicate an existing loader if a suitable V2 loader already exists.

---

# 2. Understand the existing V2 binary format

The repository already contains a V2 road-network binary implementation.

The benchmarked format has approximately these characteristics:

Finland-wide:

```text
File size:          ~129.54 MiB
Ways:               1,038,925
Nodes:              10,325,748
Geometry points:    11,548,814
Road length:        ~334,849 km
```

Oulu 20×20 km:

```text
Binary:             ~1.48 MiB
Ways:               22,193
Nodes:              87,084
Geometry points:    114,123
Road length:        ~2,123 km

Cold load:          ~0.34 s
Additional RSS:     ~25 MiB
Peak RSS:           ~48 MiB
```

Other benchmarked cities:

```text
Helsinki:
    binary       ~3.78 MiB
    additional RSS ~77.55 MiB
    cold load    ~0.95 s

Tampere:
    binary       ~2.23 MiB
    additional RSS ~42.11 MiB
    cold load    ~0.56 s

Rovaniemi:
    binary       ~0.39 MiB
    additional RSS ~6.68 MiB
    cold load    ~0.08 s
```

These are benchmark results, not requirements. Do not hard-code these numbers into the implementation.

The important point is that city-specific binaries are small enough to load at runtime.

---

# 3. Proposed runtime architecture

Introduce a clear separation between:

### Road data source

```text
CityRoadDataSource
```

or an equivalent abstraction appropriate for the existing architecture.

Possible implementations:

```text
BinaryRoadDataSource
OsmRoadDataSource
```

The exact class/module names are up to you after inspecting the existing code.

The rest of the game should ideally not need to know whether the road network came from:

- a `.bin`;
- PBF;
- Overpass;
- another existing fallback source.

The common API should expose whatever the existing routing/NPC systems actually need.

Do not create an unnecessarily large abstraction layer.

Keep it simple and compatible with the existing architecture.

---

# 4. City BIN lookup

For predefined cities, introduce a deterministic mapping from city identity to its road BIN.

For example:

```text
maps/
    roads/
        oulu.bin
        helsinki.bin
        tampere.bin
        rovaniemi.bin
```

The actual directory and filename convention should follow the repository's existing asset/data conventions.

Do not invent a completely new configuration mechanism if an appropriate one already exists.

The important behavior is:

```text
known city + BIN exists
        -> use BIN

known city + BIN missing
        -> use existing fallback

custom city
        -> use existing fallback
```

This means a missing binary must **never make the game fail simply because the city has no pre-generated binary**.

---

# 5. Explicit fallback behavior

The fallback is a hard requirement.

Implement logic equivalent to:

```python
if city_has_prebuilt_road_bin(city):
    try:
        load_binary_road_network(city)
    except Exception:
        log_warning(...)
        fall_back_to_existing_osm_path()
else:
    use_existing_osm_path()
```

However, do not blindly catch every exception if the existing project's error-handling conventions provide a better mechanism.

The important requirement is:

### A broken or missing BIN must not prevent the existing OSM/PBF implementation from working.

Log enough information to make the fallback understandable.

For example:

```text
Prebuilt road network not available for custom city 'X';
using existing OSM/PBF road loading.
```

or:

```text
Failed to load prebuilt road network for Oulu;
falling back to existing OSM/PBF road loading: <error>
```

Do not hide real errors silently.

---

# 6. Custom city compatibility

This is particularly important.

The game currently allows users to customize cities.

Do not assume that every city has:

- a BIN;
- a fixed predefined city ID;
- a bundled OSM dataset.

A custom city should continue to use the existing dynamic data path.

For example:

```text
Predefined Oulu
    -> oulu.bin

Predefined Helsinki
    -> helsinki.bin

Predefined Tampere
    -> tampere.bin

Predefined Rovaniemi
    -> rovaniemi.bin

Custom city "MyCity"
    -> existing OSM/PBF/Overpass implementation
```

Do not silently substitute the nearest predefined city's BIN for a custom city.

Do not use Oulu's BIN for an arbitrary city.

Do not require users to generate a BIN just to create a custom city.

---

# 7. Preserve existing routing semantics

The binary road network must provide the same semantic information required by the current routing system.

Do not rewrite routing just because the source is changing.

First determine exactly what the current routing code expects.

Pay particular attention to:

- node IDs;
- way IDs;
- road geometry;
- road directionality;
- one-way roads;
- road classifications;
- links;
- intersections;
- connectivity;
- speed information if currently used;
- road names if currently used;
- any metadata used by routing or traffic;
- coordinate conversion;
- nearest-road lookup;
- graph construction.

If V2 does not currently expose something that routing needs, determine whether:

1. the existing V2 loader already contains it;
2. it can be derived without changing the binary format;
3. a small adapter is sufficient.

Do not change the V2 file format unless absolutely necessary.

---

# 8. Preserve `complete_ways` semantics

The existing city BIN generation uses OSM extraction behavior where a way may be included when it intersects the extraction area while retaining its complete geometry.

This behavior is intentional.

Do not clip or alter road geometry during runtime loading.

Do not introduce artificial endpoints merely because a way crosses the nominal 20×20 km city boundary.

---

# 9. Do not remove tile streaming yet

The current game has an existing map/tile streaming system.

Do not replace the entire map streaming architecture in this task.

The first objective is specifically:

```text
city road network
        ↓
prebuilt BIN when available
        ↓
existing routing/NPC systems
```

Rendering/static map data can continue using the current implementation.

This task is NOT:

- a complete map renderer rewrite;
- a replacement for Overpass;
- a replacement for the OSM cache;
- a complete offline-map implementation;
- a new routing engine;
- a C server migration.

Keep the scope controlled.

---

# 10. Runtime loading

Implement the smallest practical runtime integration.

For a predefined city:

```text
select city
    ↓
resolve city BIN
    ↓
load binary
    ↓
construct the road representation expected by routing
    ↓
start gameplay
```

For a custom city:

```text
select custom city
    ↓
no BIN
    ↓
existing OSM/PBF/Overpass path
    ↓
start gameplay
```

If city switching is already supported, ensure that:

```text
City A BIN
    ↓
unload
    ↓
City B BIN
```

does not leave stale road data from City A.

Do not introduce a global cache that keeps every city loaded indefinitely.

The intended model is approximately:

```text
                    active city
                        │
                        ▼
                  one road BIN
                        │
                     gameplay
                        │
                        ▼
                 unload on change
```

---

# 11. Memory behavior

The whole point of this integration is to avoid loading the complete Finland road graph into Python memory.

Do NOT automatically load:

```text
finland-roads-v2.bin
```

at startup.

Do NOT build a global Python representation of the entire Finnish road network.

Only load the road network needed by the active predefined city.

For custom cities, preserve the existing behavior.

---

# 12. Startup behavior

Add clear logging around the selected road source.

For example:

```text
Road network source: prebuilt binary
City: Oulu
File: ...
Load time: ... ms
Ways: ...
Nodes: ...
Geometry points: ...
```

For fallback:

```text
Road network source: existing OSM/PBF fallback
City: MyCustomCity
Reason: no prebuilt binary
```

Do not spam the log for every individual road.

---

# 13. Validation

Create focused tests for the new behavior.

At minimum test:

### Predefined city with BIN

```text
Oulu
    -> BIN selected
    -> BIN loads
    -> road network is available
```

### Predefined city without BIN

Temporarily point the test at a missing BIN.

Expected:

```text
BIN unavailable
    -> fallback selected
```

### Custom city

Use a custom city configuration.

Expected:

```text
custom city
    -> no BIN lookup/substitution
    -> existing OSM/PBF path
```

### Broken BIN

Provide an invalid/corrupt BIN.

Expected:

```text
load fails
    -> fallback
```

unless the project's existing error-handling policy explicitly requires startup failure for corrupt packaged assets.

### City switching

If city switching exists:

```text
Oulu
    -> Helsinki
    -> Oulu
```

Verify that:

- correct BIN is loaded each time;
- no stale road graph remains;
- the game does not accumulate one full road graph per city.

---

# 14. Integration testing

After implementing the change, run:

```bash
pytest -q
```

Also run focused tests for:

- V2 binary loader;
- city benchmark;
- new runtime integration;
- existing OSM/PBF fallback.

Do not "fix" unrelated existing test failures unless your changes actually caused them.

Clearly distinguish:

```text
new failures caused by this change
```

from:

```text
pre-existing failures
```

---

# 15. Performance measurement

Add a small runtime benchmark or diagnostic if the existing benchmark infrastructure can be reused.

For at least Oulu, measure:

```text
BIN path:
    file size
    load time
    loaded road count
    memory impact if practical
```

Compare against the already measured benchmark.

Do not rerun the full Finland benchmark unless necessary.

The expected order of magnitude for Oulu is approximately:

```text
~1.5 MiB binary
~0.3–0.4 s cold load
~25 MiB additional RSS
```

Treat these only as reference values.

If your implementation is significantly slower or uses dramatically more memory, investigate why before considering the task complete.

---

# 16. Preserve current behavior

This is a compatibility task.

The following must continue working:

- predefined cities;
- custom cities;
- OSM data loading;
- PBF loading;
- Overpass fallback;
- existing road routing;
- NPC routing;
- resident routing;
- traffic;
- traffic lights;
- existing map rendering;
- existing tile streaming;
- existing caches.

Do not remove existing code merely because the BIN path makes it unnecessary for predefined cities.

The old path is still required for custom cities.

---

# 17. Code quality requirements

Follow the repository's existing coding style.

Prefer small, explicit changes.

Avoid:

- unnecessary abstractions;
- speculative frameworks;
- new dependencies unless absolutely necessary;
- global mutable state;
- hard-coded absolute paths;
- hidden fallback behavior;
- duplicate binary loaders;
- duplicated road-network representations.

Use existing utilities where possible.

Do not invent environment variables or configuration settings without first checking whether the project already has an appropriate configuration mechanism.

---

# 18. Documentation

Add concise documentation explaining:

1. what a city road BIN is;
2. how predefined cities use it;
3. that custom cities continue using the existing OSM/PBF/Overpass path;
4. how the fallback works;
5. where city BIN files are stored;
6. how a new predefined city can be given a BIN later.

Do not document the BIN as replacing OSM entirely.

The intended architecture is:

```text
Prebuilt city BIN
        ↓
fast local road-network source

Existing OSM/PBF/Overpass
        ↓
universal fallback for cities without a BIN
```

---

# 19. Important constraints

DO NOT:

- remove the existing OSM/PBF fallback;
- require a BIN for custom cities;
- replace custom-city functionality;
- load the entire Finland BIN at startup;
- rewrite routing unnecessarily;
- rewrite rendering;
- rewrite tile streaming;
- modify the V2 binary format without strong justification;
- migrate anything to C in this task;
- introduce a new database system;
- download road data for a city that already has a valid packaged BIN;
- silently use another city's BIN for a custom city.

DO:

- inspect the current architecture first;
- reuse the existing V2 loader;
- integrate the BIN at the road-data boundary;
- keep fallback behavior explicit;
- keep custom cities working;
- add tests;
- measure runtime performance;
- document the architecture.

---

# 20. Final deliverables

When finished, provide:

1. Summary of the architecture you found.
2. Files changed.
3. How predefined-city BIN selection works.
4. How custom-city fallback works.
5. How corrupted/missing BINs are handled.
6. Tests added.
7. Test results.
8. Runtime benchmark results for at least Oulu.
9. Any limitations or follow-up work that should be done later.

The implementation should leave the project in this state:

```text
                         ┌─────────────────────┐
                         │     City selected   │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ Prebuilt BIN exists?│
                         └───────┬───────┬─────┘
                                 │ YES   │ NO
                                 ▼       ▼
                         ┌──────────┐  ┌──────────────────┐
                         │ City BIN │  │ Existing OSM/PBF │
                         │  loader  │  │    fallback      │
                         └─────┬────┘  └────────┬─────────┘
                               │                │
                               └───────┬────────┘
                                       ▼
                              ┌─────────────────┐
                              │ Common road     │
                              │ representation  │
                              └────────┬────────┘
                                       ▼
                              ┌─────────────────┐
                              │ Routing / NPC / │
                              │ traffic systems │
                              └─────────────────┘
```

The critical requirement is that **the new BIN path is an optimization and packaged-data path, not a replacement for the game's existing ability to work with arbitrary custom cities.**