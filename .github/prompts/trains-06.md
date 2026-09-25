# Railway Phase 6 – Real Train Composition and Wagon Visuals

## Objective

Extend the existing railway system so that trains are no longer rendered as a fixed `1 locomotive + 5 wagons` consist.

Use Digitraffic railway composition data when available to determine:

* number of vehicles
* vehicle order
* vehicle type
* vehicle length when available
* total train length when available
* relevant vehicle services/type information

Use the resulting composition data both for the current train and as **historical composition knowledge for future scheduled instances of the same train**.

The existing smooth train movement, timetable handling, station routing, platform/track selection and passenger system must remain intact.

This phase is primarily about **train composition data and visual representation**.

---

# 1. Inspect the existing implementation first

Before changing code, inspect:

* train entity/model
* train schedule model
* timetable/GTFS importer and cache
* train rendering
* current fixed `1 + 5` representation
* railway path/movement implementation
* station/platform/track handling
* existing data-cache conventions
* existing tests

Do not assume filenames, classes, APIs or storage formats.

Reuse the existing architecture where possible.

Avoid unrelated refactoring.

---

# 2. Digitraffic composition data

Use the official Digitraffic railway composition API:

`/compositions/<departure_date>/<train_number>`

Verify the current API structure against the official Digitraffic documentation before implementation.

Composition data may only become available relatively close to a train's departure.

This means the system must support both:

1. compositions observed from Digitraffic
2. compositions learned from the local historical cache

The game must not require a live network connection during gameplay.

---

# 3. Composition cache

Implement a persistent local composition cache using the project's existing cache conventions.

The cache must preserve enough information to distinguish:

* train number
* departure date
* train type/series where available
* composition
* observation/fetch timestamp

The cache should support historical observations.

Conceptually:

```text
Composition cache
│
├── exact observations
│   ├── date + train number
│   └── composition
│
└── reusable composition knowledge
    ├── train number
    ├── train type/series
    └── most recently observed composition
```

The exact file/database format should follow the existing project architecture.

Do not introduce a database if the existing project uses simple local cache files.

---

# 4. Reuse cached compositions for future schedules

This is an important requirement.

A composition retrieved for one scheduled occurrence should be reusable when a future scheduled occurrence of the same train is encountered.

For example:

```text
2026-09-25 train 123
    → Digitraffic composition retrieved
    → cache composition

2026-09-26 train 123
    → no current composition available
    → reuse cached composition for train 123
```

The cache therefore acts as a **learned composition database**, not merely a temporary HTTP cache.

Prefer the most recent relevant composition.

When multiple historical observations exist, prefer:

1. exact date-specific composition
2. latest composition for the same train number
3. suitable composition for the same train type/series
4. generic fallback

The implementation may use additional confidence rules if the existing data model supports them.

Do not invent complex machine-learning or statistical prediction.

A simple deterministic cache lookup is sufficient.

---

# 5. Updating historical knowledge

Whenever a newer valid Digitraffic composition is obtained:

1. use it for the current train
2. store it in the exact dated cache
3. update the reusable historical composition record

Do not overwrite historical observations in a way that destroys useful information.

Keep enough metadata to know when a composition was observed.

If practical, retain multiple historical observations rather than only one.

---

# 6. Composition fallback hierarchy

Resolve a scheduled train's composition using this hierarchy:

### 1. Exact composition

```text
departure date + train number
```

Use it if available.

### 2. Historical train-number composition

If no exact composition exists, use the most recent suitable composition previously observed for the same train number.

### 3. Train-series/type default

If no train-number history exists, use a known default based on the train type/series.

### 4. Generic fallback

Only as a final fallback use the existing generic representation.

The existing `1 locomotive + 5 wagons` may remain as the final fallback, but it must no longer be the normal representation.

---

# 7. Be conservative about historical reuse

Historical composition data is useful, but it is not guaranteed to remain identical forever.

Therefore:

* record observation timestamps
* prefer newer observations
* do not claim historical data is guaranteed to be the current real composition
* allow fresh Digitraffic data to replace older knowledge
* keep the fallback system robust

Do not implement an arbitrary short expiry that makes historical data useless.

The purpose of the cache is specifically to allow the game to use composition knowledge for future schedules.

---

# 8. Composition model

Create a clean internal representation.

Conceptually:

```python
TrainComposition
    vehicles
    total_length_m
    maximum_speed_kmh
    source
    observed_at
```

And:

```python
TrainVehicle
    position
    vehicle_type
    wagon_type
    length_m
    services
```

Use the actual fields available from Digitraffic.

Do not invent API fields.

---

# 9. Vehicle lengths

If Digitraffic provides vehicle-level length information, use it.

If individual length is unavailable:

* use a sensible type-specific default when the type is known
* otherwise use the existing generic wagon length

If `totalLength` is available, use it as reference/validation data.

Do not force every train to the same visual length.

---

# 10. Wagon visual profiles

Introduce a lightweight visual abstraction:

```python
WagonVisualProfile
    base_color
    secondary_color
    pattern
    sprite_type
```

The exact implementation should follow the existing rendering architecture.

The important requirement is that different vehicle types can have visually distinct appearances while **green remains the dominant colour of the railway vehicles**.

---

# 11. Green visual language

Use different shades of green to distinguish vehicle types.

### Standard passenger wagon

* primary green
* no special pattern

### Restaurant wagon

* green remains the primary colour
* white striping
* clearly visible at normal gameplay zoom

For example:

```text
GREEN GREEN GREEN GREEN
WHITE WHITE WHITE WHITE
GREEN GREEN GREEN GREEN
```

The exact stripe orientation should fit the existing sprite/rendering style.

### Other special vehicles

Use subtle differences such as:

* lighter green
* darker green
* secondary green
* small white details
* simple patterns

Avoid unrelated colours.

---

# 12. Map real composition data to visual profiles

Use the strongest available information:

1. explicit vehicle/wagon type
2. service information
3. train type/series
4. generic passenger vehicle

For example:

```text
restaurant/catering service
    → green + white stripe visual profile
```

Unknown vehicles should use the standard green passenger appearance.

Do not invent classifications unsupported by the actual Digitraffic data.

---

# 13. Rendering

The train remains one moving railway entity.

Do not implement independent pathfinding for individual wagons.

The locomotive/train movement remains the source of truth.

Precompute longitudinal offsets from the vehicle lengths:

```text
locomotive
    ↓
wagon 1 offset
    ↓
wagon 2 offset
    ↓
wagon 3 offset
    ↓
...
```

Render every vehicle at its corresponding position along the same railway path.

This must work with arbitrary train lengths.

Examples:

```text
[LOCO][W1][W2]
```

```text
[LOCO][W1][W2][W3][W4][W5][W6][W7][W8]
```

---

# 14. Performance

Composition loading/parsing must not happen in the per-frame loop.

Precompute:

* vehicle lengths
* vehicle offsets
* visual profiles
* any other immutable composition data

The existing smooth train movement must remain smooth.

Do not perform HTTP requests during gameplay rendering.

Do not repeatedly parse composition JSON.

Do not resolve visual profiles every frame.

---

# 15. Integration with timetable

The existing timetable remains authoritative for:

* train existence
* schedule
* station calls
* direction
* arrival/departure times

Composition data determines:

* vehicles
* vehicle order
* vehicle length
* visual appearance

Use the existing train identity.

Do not create a second independent timetable system.

---

# 16. Offline operation

The railway system must work without network connectivity.

Possible states:

```text
Fresh composition available
    → use fresh composition
```

```text
No fresh composition
    + historical composition exists
    → use historical composition
```

```text
No composition history
    + train type known
    → use train-type default
```

```text
Nothing known
    → use generic fallback
```

The game must never fail to create a train merely because composition data is unavailable.

---

# 17. Tests

Add tests for:

### Composition parsing

Verify realistic Digitraffic data.

### Cache persistence

Verify that a retrieved composition survives and can be loaded later.

### Historical reuse

Verify:

```text
date A + train 123
    → composition stored

date B + train 123
    → composition reused when date B has no exact data
```

### Fresh data priority

Verify:

```text
historical composition
        ↓
new Digitraffic composition
        ↓
new composition wins
        ↓
historical reusable record is updated
```

### Fallback

Verify the complete hierarchy:

```text
exact
→ historical train number
→ train type/series
→ generic fallback
```

### Vehicle order

Verify vehicle positions are preserved.

### Vehicle lengths

Verify lengths and offsets.

### Visual classification

At minimum:

```text
standard passenger wagon
    → standard green

restaurant/catering wagon
    → green + white stripes

unknown wagon
    → standard green
```

### Offline operation

Verify cached composition can be used without network access.

### Rendering

Test trains with:

* 2–3 vehicles
* 5 vehicles
* 10+ vehicles

### Performance

Run the existing railway benchmark and verify there is no meaningful FPS regression.

---

# 18. Scope limits

Do NOT implement:

* passenger capacity
* seating
* restaurant gameplay
* ticketing
* signalling
* collision avoidance
* shunting
* coupling/uncoupling
* locomotive switching
* dynamic consist changes
* multiplayer synchronization

Those belong to future phases.

---

# 19. Implementation workflow

Work incrementally:

1. Inspect current railway implementation.
2. Identify all fixed `1 + 5` assumptions.
3. Inspect existing timetable/cache architecture.
4. Implement Digitraffic composition parsing.
5. Implement persistent composition cache.
6. Implement historical composition reuse.
7. Implement exact → historical → train-type → generic fallback.
8. Integrate composition into the existing train model.
9. Replace fixed wagon count.
10. Precompute vehicle offsets.
11. Implement wagon visual profiles.
12. Implement green shade variations.
13. Implement restaurant wagon white striping.
14. Integrate rendering.
15. Add tests.
16. Run existing railway tests.
17. Run gameplay/performance tests.
18. Review the diff for unnecessary changes.

Do not rewrite working railway systems merely to introduce composition support.

At the end, report:

* files changed
* Digitraffic API integration
* cache format and location
* historical reuse logic
* fallback hierarchy
* supported vehicle classifications
* wagon visual profiles
* vehicle positioning/length calculation
* tests executed
* performance comparison
* known limitations
