Perform a comprehensive audit of the game's OSM map rendering and identify **OSM-derived visual features that are available in the imported data but are currently not rendered, only partially rendered, or rendered incorrectly**.

The immediate motivation is missing features such as **traffic islands**, but do not limit the investigation to traffic islands. The goal is to systematically discover what important real-world map features are still missing from the game's visual representation.

Do not blindly implement a predefined list. First inspect the actual codebase and the actual OSM data structures used by the game.

---

# 1. Audit the complete OSM data pipeline

Trace the entire flow:

```text
OSM PBF
  ↓
OSM parsing
  ↓
internal map representation
  ↓
cache / binary cache
  ↓
map loading
  ↓
geometry generation
  ↓
renderer
```

Identify:

* Which OSM objects are currently parsed
* Which OSM tags are preserved
* Which OSM tags are discarded
* Which objects are converted into internal game objects
* Which objects are available internally but never rendered
* Which objects are rendered only in certain circumstances
* Which OSM features are completely ignored

Inspect all relevant code rather than relying on assumptions about what the game supports.

---

# 2. Build an OSM rendering coverage report

Create a clear inventory of currently supported OSM features.

Categorize them approximately as:

```text
SUPPORTED AND RENDERED
PARTIALLY SUPPORTED
PARSED BUT NOT RENDERED
NOT PARSED
UNKNOWN / NEEDS INVESTIGATION
```

Include at least:

### Roads and transportation

Investigate tags such as:

* highway
* highway=* variants
* lanes
* oneway
* junction
* roundabout
* service
* access
* bicycle
* foot
* cycleway
* sidewalk
* crossing
* traffic_calming
* speed limits
* turn lanes
* bus lanes
* bus stops
* taxi stands
* parking lanes

Do not assume every tag needs to become a separate visible object. Determine which ones have meaningful visual consequences.

---

# 3. Roadside and traffic infrastructure

Explicitly investigate whether the following are present in the source OSM data and whether they are rendered:

* traffic islands
* pedestrian islands
* refuge islands
* medians
* road dividers
* bollards
* barriers
* guard rails
* crash barriers
* curbs
* kerbs
* traffic signs
* traffic signals
* pedestrian crossings
* zebra crossings
* stop lines
* give-way markings
* road markings
* lane separators
* turning lanes
* bus stops
* street lamps
* parking meters
* street furniture

Traffic islands are particularly important.

Investigate common OSM representations such as:

```text
highway=traffic_island
traffic_calming=island
barrier=*
area=yes
```

and any other representations actually found in the game's OSM data.

Do not assume a traffic island is always represented by one specific tag.

---

# 4. Buildings and urban structures

Audit rendering of:

* building
* building:part
* building levels
* building height
* building entrances
* building outlines
* walls
* fences
* gates
* garages
* carports
* sheds
* industrial buildings
* commercial buildings
* residential buildings

Determine whether building geometry is currently only used for collision/occlusion or also visually represented.

If building metadata is already available, identify opportunities to improve visual representation without unnecessarily increasing rendering cost.

---

# 5. Parking infrastructure

Since NPC parking is being developed, perform a particularly thorough audit of parking-related OSM data.

Investigate:

* amenity=parking
* amenity=parking_space
* parking=*
* parking:lane=*
* parking:orientation=*
* parking:condition=*
* parking:access=*
* capacity
* disabled parking
* loading bays
* taxi stands
* bicycle parking
* motorcycle parking
* covered parking
* parking entrances

Determine which of these are:

```text
parsed
stored
used by NPC parking
rendered
```

Do not implement visual parking features that contradict the existing NPC parking model.

---

# 6. Pedestrian infrastructure

Audit:

* sidewalks
* footways
* pedestrian areas
* crossings
* pedestrian islands
* steps
* pedestrian bridges
* pedestrian tunnels
* plazas
* promenades
* paths

Determine whether they are:

* rendered
* used only for routing
* used only for collision
* ignored

The visual map should distinguish major pedestrian infrastructure from ordinary road surfaces where practical.

---

# 7. Cycling infrastructure

Investigate:

* cycleways
* cycle lanes
* shared paths
* bicycle crossings
* bicycle parking
* cycleway=*
* segregated
* bicycle access

Determine whether these are visually represented and whether they can be rendered efficiently using the existing road/line rendering system.

---

# 8. Public transport

Audit OSM features such as:

* bus stops
* tram stops
* railway stations
* tram tracks
* railway tracks
* platforms
* shelters
* transit-related road infrastructure

Determine what is already rendered and what is missing.

Do not introduce gameplay functionality merely because an OSM feature exists. This task is primarily about **visual completeness**, unless an existing gameplay system already depends on the feature.

---

# 9. Natural and landscaping features

Audit non-road/non-building features including:

* parks
* grass
* forests
* individual trees
* tree rows
* hedges
* flower beds
* gardens
* scrub
* water
* ponds
* rivers
* streams
* beaches
* cliffs
* embankments

Investigate which of these are present in the PBF and currently ignored.

Prioritize features that materially improve the visual representation of an urban environment.

---

# 10. Land use and areas

Investigate area features such as:

* landuse=residential
* landuse=commercial
* landuse=industrial
* landuse=retail
* landuse=forest
* landuse=grass
* landuse=meadow
* leisure=park
* leisure=pitch
* leisure=playground
* leisure=sports_centre
* amenity=*
* natural=*

Determine whether these areas are currently rendered, converted into generic terrain, or discarded.

Do not blindly render every OSM polygon. Identify useful visual categories.

---

# 11. Street furniture and small details

Investigate whether the OSM data contains:

* benches
* waste baskets
* bollards
* poles
* street lights
* fire hydrants
* mailboxes
* fountains
* bicycle racks
* bus shelters
* information boards
* advertising structures

Classify these separately because thousands of individual point objects could have a significant performance impact.

Recommend appropriate rendering strategies:

```text
few objects
    → normal sprite/object

many repetitive objects
    → instanced/batched rendering

mostly decorative
    → optional detail layer
```

Do not introduce thousands of expensive Pygame surfaces unnecessarily.

---

# 12. Compare source data against renderer

The most important part of this task is identifying the gap:

```text
OSM provides feature
        ↓
parser sees feature?
        ↓
internal representation?
        ↓
renderer supports feature?
        ↓
visible in game?
```

For every important missing feature, document the exact point where it disappears.

Example:

```text
traffic island
    ↓
present in PBF
    ↓
parsed as OSM way
    ↓
tag preserved
    ↓
stored in map cache
    ↓
NO RENDERER
```

This is much more useful than simply saying "traffic islands are missing."

---

# 13. Inspect real OSM data

Use the project's actual OSM/PBF-derived data and existing map cache where possible.

Do not rely exclusively on generic OSM documentation.

Determine which tags/features actually occur in the game's target data.

Produce a frequency/coverage report where practical, for example:

```text
Feature/tag                  Count      Rendered
------------------------------------------------
highway=traffic_island      184        NO
amenity=parking              92        YES
highway=street_lamp         1240       NO
barrier=bollard             367        NO
...
```

The exact table should be generated from the actual available dataset or parser output if feasible.

If the full Finland PBF is too large to scan repeatedly, use the existing parsed/binary representation or an appropriate sampled region first, then verify implementation assumptions against the full data where practical.

---

# 14. Prioritize the missing features

After the audit, create a prioritized implementation plan.

Use categories such as:

### High priority

Features that strongly affect road/city realism:

* traffic islands
* medians
* curbs
* pedestrian crossings
* road markings
* parking infrastructure
* sidewalks
* barriers
* building entrances/access
* major public transport infrastructure

### Medium priority

Features that improve environmental detail:

* trees
* street lamps
* bollards
* fences
* bus shelters
* parks
* playgrounds
* bicycle infrastructure

### Low priority

Small decorative features that are unlikely to materially affect gameplay or visual readability.

Do not assign arbitrary numerical scores.

Explain the reasoning for the priority categories.

---

# 15. Traffic islands — implement as the first concrete feature

After completing the audit, implement traffic islands if the audit confirms they are currently missing.

The implementation must support the actual OSM representations found in the project data.

A traffic island should:

* appear in the correct world position
* have the correct approximate shape
* remain aligned with the road geometry
* not be rendered as a road surface
* visually separate the two drivable areas
* be treated as non-drivable geometry where appropriate
* interact correctly with NPC vehicle movement
* not allow NPCs to drive across it
* remain compatible with pedestrian crossings

If a traffic island is polygonal, render its polygon rather than reducing it to a point.

If the same geometry is relevant to collision, reuse the geometry rather than maintaining separate visual and collision definitions.

---

# 16. Rendering architecture

Do not create a special-case renderer for every new OSM tag.

Introduce reusable feature categories where appropriate.

For example:

```python
MapFeature
    ├── AreaFeature
    ├── LinearFeature
    ├── PointFeature
    ├── RoadFeature
    └── TrafficInfrastructureFeature
```

Adapt this concept to the existing codebase rather than introducing unnecessary abstraction.

The renderer should be able to support additional OSM features later without requiring a major rewrite.

---

# 17. Interaction with traffic simulation

Some visual OSM features also have physical meaning.

Make sure the audit distinguishes:

```text
visual-only feature
physical obstacle
drivable geometry
pedestrian geometry
traffic-control feature
```

For example:

```text
traffic island
→ visible
→ non-drivable
→ may separate lanes
→ may contain pedestrian crossing/refuge
```

Similarly:

```text
curb
→ visible
→ non-drivable
→ vehicle boundary
```

Avoid duplicating geometry between renderer and traffic simulation.

Where possible, establish a shared map-geometry representation.

---

# 18. Performance requirements

The game must remain performant with large OSM areas.

Do not render every OSM object as an individual Pygame object.

Use appropriate strategies such as:

* geometry batching
* cached surfaces
* tile/chunk rendering
* spatial visibility filtering
* precomputed geometry
* sprite atlases
* reusable surfaces
* level-of-detail where appropriate

Static OSM features should be cached whenever possible.

Do not repeatedly parse OSM tags or regenerate static geometry during normal gameplay.

---

# 19. Debug feature inventory

Add a debug option that can display the OSM feature type under the cursor or when selecting a map object.

For example:

```text
FEATURE
type: traffic_island
source: OSM
id: 123456789
rendered: yes
drivable: no
```

This will be useful when investigating future rendering gaps.

If an object is parsed but not rendered, make that state easy to diagnose.

---

# 20. Do not implement everything in one uncontrolled change

First perform the audit.

Then:

1. Document the current OSM rendering coverage.
2. Identify the highest-value missing features.
3. Implement the feature infrastructure needed for those features.
4. Implement traffic islands first.
5. Add the next few high-priority features that can reuse the same infrastructure.
6. Keep unrelated gameplay changes out of this task.

Do not rewrite the entire renderer unless the audit demonstrates that it is genuinely necessary.

---

# 21. Final report

After the investigation and implementation, provide a concise but concrete report containing:

```text
1. Current OSM rendering coverage

2. Important OSM features currently missing

3. Features parsed but not rendered

4. Features not currently parsed

5. Traffic island representations found in the data

6. Traffic island implementation

7. Other high-priority rendering gaps

8. Changes made

9. Files changed

10. Performance considerations

11. Recommended next rendering features
```

Most importantly:

**Do not guess what the game is missing. Inspect the actual parser, cache, internal map model, renderer and available OSM data and derive the missing-feature list from evidence in the code and data.**
