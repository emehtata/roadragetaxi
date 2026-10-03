## Task: Build a generic OSM place extractor for Road Rage Taxi

**Repository:** `https://github.com/emehtata/roadragetaxi`
**Branch:** `release/0.15.0alpha`

### Goal

Add a standalone build-time tool that extracts interesting fixed locations from an existing Finland OSM PBF file and writes them to a compact JSON file that the game can load at runtime.

The first target categories are:

* major airports
* railway stations

The architecture must be generic enough to add other place categories later, for example:

* bus stations
* ferry terminals
* harbours
* major landmarks
* other important transportation hubs

### Important architectural constraint

**Do NOT revive, depend on, or modify the currently disabled BIN architecture.**

The desired data flow is:

```text
Finland OSM PBF
      |
      v
tools/extract_places.py
      |
      v
data/places.json
      |
      v
Road Rage Taxi runtime
```

The PBF is build/development input only.

The game must not need the PBF at runtime.

The resulting JSON should be small, deterministic, human-readable, and suitable for committing to the repository.

---

# Phase 1 — Inspect the existing implementation

Before writing code, inspect the repository thoroughly.

Find:

1. Existing PBF loading/parsing code.
2. Existing OSM extraction utilities.
3. Existing dependencies that can parse `.osm.pbf`.
4. Existing map/coordinate abstractions.
5. Existing JSON data-loading conventions.
6. Existing tests for map/PBF functionality.
7. Existing `tools/` or equivalent developer/build tooling.
8. Existing runtime data directories.
9. Any existing concept of locations, POIs, destinations, landmarks, airports, railway stations, etc.
10. Any code that could accidentally make this feature depend on the disabled BIN architecture.

Reuse existing PBF parsing infrastructure where practical.

Do not introduce a new OSM/PBF library if the repository already has a suitable parser.

Do not duplicate existing PBF parsing logic unnecessarily.

Before implementing, briefly document the relevant existing architecture in the implementation/report.

---

# Phase 2 — Design the place data model

Create a generic place representation.

The JSON should be designed around a stable place identity rather than hard-coded airport/station fields.

A place should contain at least:

```json
{
  "id": "airport_efou",
  "type": "airport",
  "name": "Oulun lentoasema",
  "lat": 64.9301,
  "lon": 25.3546
}
```

Where useful, include additional metadata such as:

```json
{
  "osm": {
    "type": "node|way|relation",
    "id": 123456789
  }
}
```

Optional category-specific metadata may include:

```json
{
  "iata": "OUL",
  "icao": "EFOU"
}
```

Do not require airport-specific fields for every place.

The schema must remain generic.

Suggested top-level structure:

```json
{
  "version": 1,
  "source": "finland-latest.osm.pbf",
  "places": [
    {
      "id": "airport_efou",
      "type": "airport",
      "name": "Oulun lentoasema",
      "lat": 64.9301,
      "lon": 25.3546
    }
  ]
}
```

Do not blindly copy the example values above. Obtain the actual values from the PBF.

---

# Phase 3 — Define extraction rules

Implement extraction through configurable category definitions rather than hard-coding separate parser functions such as:

```text
extract_airports()
extract_railway_stations()
```

Prefer a generic mechanism conceptually like:

```text
PlaceCategory
    |
    +-- airport
    +-- railway_station
    +-- bus_station
    +-- ferry_terminal
    +-- harbour
```

The exact implementation is up to the existing project architecture.

The initial categories must include:

## Airports

Extract significant OSM airport/aerodrome objects.

Use appropriate OSM tags such as:

```text
aeroway=aerodrome
```

Do not automatically treat every tiny airfield as a major destination.

The extractor should distinguish between useful passenger/transport destinations and insignificant small aviation sites where possible using available OSM metadata.

Preserve useful identifiers such as IATA/ICAO codes when present.

## Railway stations

Extract railway stations using appropriate OSM tags such as:

```text
railway=station
```

and account for the fact that an OSM station may be represented by different element types.

Do not turn every railway platform into a separate railway station.

Avoid duplicates where the same physical station is represented by multiple related OSM elements.

---

# Phase 4 — Coordinate selection

This is important.

OSM objects are not always simple points.

An airport may be represented by an area/polygon.

A railway station may be represented by a node, way, or relation.

The extractor must therefore determine a single representative coordinate for every exported place.

Preferred strategy:

1. Use a clearly designated OSM point representing the feature when available.
2. Otherwise calculate a suitable representative point for the geometry.
3. For an area/polygon, use an appropriate representative point/centroid.
4. Do not simply use an arbitrary first coordinate.
5. Keep the coordinate inside the relevant feature whenever practical.

The final JSON should contain:

```text
lat
lon
```

as the runtime destination coordinate.

Also preserve the originating OSM element identity when available:

```json
"osm": {
  "type": "way",
  "id": 123456789
}
```

This makes the generated data traceable.

---

# Phase 5 — Deduplication

Implement deterministic deduplication.

Potential duplicates must be investigated rather than simply removed by name.

For example, avoid producing:

```text
Oulun rautatieasema
Oulun rautatieasema
Oulu railway station
```

as three independent destinations if they represent the same physical station.

However, do not aggressively merge unrelated places merely because their names are similar.

Document the deduplication strategy.

The generated output must be deterministic:

* same PBF
* same tool version
* same extraction configuration

must produce the same JSON ordering and content.

Sort output deterministically, for example by:

```text
type
name
id
```

or another clearly documented stable ordering.

---

# Phase 6 — Configuration

Make extraction categories configurable.

A reasonable structure could be:

```text
tools/
    extract_places.py
    places_config.py
```

or a configuration file if that fits the existing project better.

The configuration should make it straightforward to add:

```text
bus_station
ferry_terminal
harbour
landmark
```

later without rewriting the PBF parser.

Do not over-engineer this into a large framework.

The goal is a small, maintainable developer tool.

---

# Phase 7 — Command-line interface

Provide a useful CLI.

For example:

```bash
python tools/extract_places.py \
    path/to/finland.osm.pbf \
    data/places.json
```

Support at least:

```text
--help
```

and sensible error handling for:

* missing PBF
* invalid PBF
* missing output directory
* unsupported input
* parsing errors

If the project already has a CLI convention, follow it.

The tool should print a useful summary such as:

```text
Reading: finland.osm.pbf

Extracted places:
  airports:          25
  railway stations:  180
  total:             205

Output:
  data/places.json
```

The exact numbers must come from the actual input PBF.

---

# Phase 8 — Runtime loader

Inspect whether the game already has an appropriate data-loading abstraction.

If one exists, integrate `places.json` through it.

If not, add a small generic loader rather than scattering JSON parsing throughout the game.

The runtime should be able to do something conceptually like:

```python
places = load_places(...)
```

and query:

```python
places.find(...)
places.by_type("airport")
places.by_type("railway_station")
```

Do not implement routing to the places in this task unless the existing architecture makes that trivial and it is clearly separated.

This task is about creating the authoritative fixed-location dataset.

The next task can connect:

```text
Place coordinates
        |
        v
nearest routable road node
        |
        v
route planner
```

---

# Phase 9 — Data generation

Use the existing Finland PBF available in the development environment to generate the initial JSON.

Do not manually type the Finnish airport/station coordinates.

The resulting `places.json` must be generated from the PBF.

Verify that important Finnish locations are represented, including at minimum:

* Helsinki-Vantaa airport
* Oulu airport
* Rovaniemi airport
* Tampere-Pirkkala airport
* Turku airport
* Kuopio airport
* Vaasa airport
* major Finnish railway stations

Do not assume that these exact names or OSM representations exist unchanged in the PBF. Verify them from the actual extracted data.

Do not fabricate missing locations.

If a requested location is genuinely absent from the PBF, report that fact rather than manually inserting it.

---

# Phase 10 — Tests

Add focused tests for the extractor.

At minimum test:

1. Node-based place extraction.
2. Way/area-based place extraction.
3. Representative coordinate calculation.
4. Category matching.
5. Deduplication.
6. Deterministic output ordering.
7. OSM source metadata.
8. Optional airport metadata.
9. Invalid/missing input handling.
10. JSON schema/content validation.

Use small synthetic OSM/PBF fixtures if practical.

Do not make the test suite depend on the full Finland PBF.

Also test that adding a new category to the configuration does not require changes to the core extraction algorithm.

---

# Phase 11 — Real PBF validation

After the unit tests pass, run the extractor against the real Finland PBF.

Inspect the generated JSON manually/programmatically.

Produce useful statistics:

```text
Total places
Places by category
Places without names
Duplicate candidates
Places with OSM source metadata
Airports with IATA
Airports with ICAO
```

Look specifically for:

* duplicate railway stations
* tiny private airfields incorrectly classified as major destinations
* missing major airports
* strange coordinates
* unnamed objects
* obviously incorrect representative points

Do not silently discard suspicious records.

If filtering is necessary, document the rule.

---

# Phase 12 — Documentation

Add a concise developer document explaining:

1. Why `places.json` exists.
2. That the PBF is build-time input.
3. How to run the extractor.
4. Which categories currently exist.
5. How categories are defined.
6. How representative coordinates are selected.
7. How deduplication works.
8. How to add another category.
9. How to regenerate the JSON when the Finland PBF is updated.

Make clear that `places.json` is generated data and should not normally be hand-edited.

---

# Architectural constraints

Keep this feature completely independent from the disabled BIN architecture.

Do not:

* re-enable BIN loading
* modify BIN generation
* add a second BIN format
* make the game require a PBF
* make runtime network/API calls to discover these places
* hard-code hundreds of coordinates
* hard-code individual airports into game logic
* introduce a global singleton unnecessarily
* add threading merely for extraction
* add a large dependency when an existing PBF parser can be reused

The generated JSON is the runtime source of truth.

---

# Future compatibility

Design the data so that the same places can later be used by different vehicle/network types.

For example:

```text
Oulu Airport
    |
    +-- taxi destination
    +-- bus destination
    +-- train destination
    +-- tram destination
```

Do not introduce concepts such as:

```text
TaxiAirportDestination
TaxiRailwayDestination
```

The place itself belongs to the world.

Vehicles and transport networks decide how they can reach it.

This is important because Road Rage Taxi may eventually support other vehicle types and transportation modes.

---

# Performance expectations

The extractor is a build-time tool, so raw extraction speed is less important than correctness and maintainability.

However:

* avoid quadratic algorithms over the entire Finland PBF
* avoid loading unnecessary geometry into memory when the parser allows streaming
* avoid retaining the entire PBF in memory
* keep generated JSON compact
* do not perform network requests

Runtime loading of `places.json` should be trivial compared with the existing map loading.

---

# Final validation

Before finishing:

```bash
git diff --check
```

Run the focused extractor tests.

Run the relevant existing test suite.

Run the extractor against the real Finland PBF.

Validate the generated JSON.

If practical, run the game and verify that `places.json` loads without affecting normal startup or gameplay.

Do not mix unrelated optimizations or refactoring into this task.

---

# Final report

Create:

```text
docs/bin-loader-v15-places.md
```

or another appropriate documentation filename if the repository has a better convention.

The report must contain:

## 1. Existing architecture

What PBF parsing/extraction infrastructure already existed.

## 2. Implementation

Files added/changed and why.

## 3. Data model

Show the actual JSON schema.

## 4. Extraction rules

Explain airport and railway-station matching.

## 5. Coordinate selection

Explain how node, way, and relation geometries become one coordinate.

## 6. Deduplication

Explain exactly how duplicate places are handled.

## 7. Real Finland PBF results

Report actual extracted counts and notable results.

## 8. Validation

List tests and their results.

## 9. Runtime integration

Explain how the game loads and accesses the generated place data.

## 10. Future extensions

Explain how bus stations, harbours, ferry terminals and landmarks can be added.

## 11. Explicit non-goals

State that BIN architecture was intentionally not used or modified.

---

## Success criteria

This task is complete only when:

* [ ] Existing PBF handling has been inspected and reused where appropriate.
* [ ] A generic place extraction tool exists.
* [ ] Airports can be extracted from the Finland PBF.
* [ ] Railway stations can be extracted from the Finland PBF.
* [ ] Node/way/relation representations are handled appropriately.
* [ ] Every exported place has a usable `lat`/`lon`.
* [ ] OSM source identity is preserved where available.
* [ ] Duplicate physical locations are handled deterministically.
* [ ] Output ordering is deterministic.
* [ ] `places.json` is generated from the real Finland PBF.
* [ ] The generated JSON contains the important Finnish airports and railway stations actually present in the PBF.
* [ ] Runtime loading is independent of the PBF.
* [ ] BIN architecture remains untouched and disabled.
* [ ] Focused tests pass.
* [ ] Existing relevant tests pass.
* [ ] `git diff --check` passes.
* [ ] Documentation/report is complete.

**Do not stop after creating the extractor. Generate the real `places.json`, validate its contents, integrate the runtime loader, run the tests, and report the actual results.**
