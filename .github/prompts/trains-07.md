# Railway Phase 7 – Passenger Taxi Demand and Nearest Taxi Stand

## Objective

Extend the existing railway passenger system so that some arriving railway passengers can become taxi customers.

For each railway passenger who has taxi demand, determine the **nearest existing taxi stand** to the railway station.

Important:

**Taxi stands already exist in the game. Do NOT create, import, modify, relocate, or duplicate taxi stands in this phase.**

The goal is only to connect railway passengers with the existing taxi stand system.

Do not implement phone pre-booking or meet & greet yet.

---

# 1. Inspect the existing implementation first

Before changing code, inspect:

* railway passenger model
* train passenger/manifest system
* passenger alighting logic
* visible pedestrian representation
* railway station representation
* existing taxi stand representation
* taxi stand spatial/indexing logic
* taxi/passenger system
* world-coordinate system
* existing random passenger/demand generation
* existing tests

Do not assume filenames, class names or APIs.

Reuse the existing implementations.

Do not create a parallel taxi stand system.

---

# 2. Existing taxi stands are authoritative

The game already has taxi stands.

Use those existing taxi stands as the only source of taxi pickup locations.

Do NOT:

* create new taxi stands
* add fallback taxi stands
* generate taxi stands near railway stations
* modify OSM taxi stand import
* move existing taxi stands
* duplicate an existing taxi stand
* create a railway-specific taxi stand type

The railway passenger system should simply query the existing taxi stand collection.

---

# 3. Find the nearest taxi stand

For each railway station, determine the nearest existing taxi stand.

Conceptually:

```text
Railway station
      ↓
query existing taxi stands
      ↓
calculate distance
      ↓
nearest taxi stand
```

Use the existing world-coordinate/distance conventions.

Do not introduce a new coordinate system.

The association should be deterministic.

If the existing project already has a spatial index for taxi stands, use it rather than scanning every taxi stand unnecessarily.

---

# 4. Station → taxi stand association

Create a lightweight association between a railway station and its nearest existing taxi stand.

Conceptually:

```python
station.nearest_taxi_stand_id
```

or an equivalent structure appropriate for the existing architecture.

Do not duplicate the entire taxi stand object into the railway station.

Store an identifier/reference.

The association should be calculated when station/world data is initialized or otherwise cached, not repeatedly every frame.

---

# 5. No suitable taxi stand

If the game contains no taxi stand at all, or no valid taxi stand can be associated with the station:

```text
nearest_taxi_stand = None
```

Do not invent a fallback location.

The passenger can still exist as a railway passenger.

They simply cannot currently use the taxi system.

Log useful diagnostic information if appropriate.

Do not produce repeated per-frame warnings.

---

# 6. Passenger taxi demand

Extend the existing railway passenger data so that a passenger can have a transportation intent.

Use the project's existing passenger-state conventions if they already provide an equivalent concept.

Conceptually:

```text
WALK
TRAIN_TRANSFER
TAXI
```

Do not assume every passenger needs a taxi.

Taxi demand should be generated for only a subset of railway passengers.

The exact probability should be configurable through the existing configuration mechanism if one exists.

Do not invent a new environment variable or configuration system.

If there is no existing configuration mechanism suitable for this, use a clearly named constant in the most appropriate existing module rather than introducing unnecessary infrastructure.

---

# 7. Deterministic/reproducible demand

Use the project's existing random-number-generation conventions.

If the game already supports deterministic seeds, passenger taxi demand must respect them.

The same game seed should produce reproducible passenger demand.

Do not introduce a separate uncontrolled random generator.

---

# 8. Passenger taxi destination

A taxi passenger needs a destination, but do not implement a sophisticated destination/pathfinding system yet.

Inspect how existing taxi customers or destinations are represented.

Reuse that system if possible.

For this phase, the railway passenger should at minimum contain enough information to support:

```text
passenger
    ↓
transportation intent = TAXI
    ↓
origin station
    ↓
nearest existing taxi stand
    ↓
destination
```

If the existing game already has suitable taxi destinations, use them.

Do not create a new destination/POI framework.

---

# 9. Passenger state after leaving train

When a taxi-demand passenger leaves the train:

```text
train passenger
      ↓
alights
      ↓
visible pedestrian
      ↓
transportation intent = TAXI
      ↓
associated with nearest existing taxi stand
```

The passenger must retain the same passenger identity.

Do not create a new passenger identity at the station.

---

# 10. Movement toward the taxi stand

A taxi-demand passenger should eventually be able to move toward the associated taxi stand.

However, do not create a new pedestrian navigation system in this phase.

Inspect the existing pedestrian movement implementation.

If it already supports movement toward arbitrary world positions, use it.

If it does not, establish only the smallest interface necessary for a passenger to receive:

```text
target = nearest existing taxi stand
```

Do not implement advanced pedestrian routing yet.

The passenger must never be instructed to walk along railway tracks.

---

# 11. Taxi stand association must survive passenger lifecycle

The association must remain valid through:

```text
waiting passenger
→ boarding train
→ train manifest
→ alighting
→ station pedestrian
→ taxi-demand passenger
```

The passenger should retain:

```text
station_id
taxi_stand_id
```

or equivalent references.

Do not repeatedly rediscover the taxi stand after every passenger state transition.

---

# 12. Do not implement pre-booking yet

This phase must prepare the data model for the next phase.

A future pre-booking will need to associate a passenger with:

```text
passenger
train
station
taxi stand
destination
```

Do not implement:

* phone UI
* booking notifications
* booking fee
* €8 payment
* reservation status
* meet & greet
* passenger identification
* pickup timeout

Those belong to later phases.

---

# 13. Visual behaviour

Do not add a special visual marker for taxi-demand passengers yet.

They should remain ordinary pedestrians.

The important requirement is that the pedestrian entity can still be traced back to the underlying railway passenger.

A future phase will use this identity to make pre-booked passengers distinguishable from the rest of the crowd.

---

# 14. Performance

Taxi demand must not introduce expensive per-frame work.

Do not:

* calculate the nearest taxi stand every frame
* scan every taxi stand for every pedestrian every frame
* repeatedly calculate station/stand distances
* create new spatial indexes if an existing one can be reused

Prefer:

```text
station initialization
       ↓
nearest taxi stand lookup
       ↓
cached station → stand association
```

Passenger instances should then reference the cached association.

---

# 15. Tests

Add tests for:

### Nearest stand

Given several existing taxi stands:

```text
station
  ├── stand A: 500 m
  ├── stand B: 120 m
  └── stand C: 300 m
```

the station must resolve to:

```text
stand B
```

### Existing stands only

Verify that the implementation never creates a taxi stand.

### No stand

Verify:

```text
no existing taxi stands
    → nearest_taxi_stand = None
```

and the railway passenger system continues to work.

### Taxi demand

Verify that:

* some passengers receive TAXI intent
* not all passengers receive TAXI intent
* existing passenger types continue to work

### Deterministic demand

Verify that passenger demand respects the existing random seed mechanism.

### Passenger identity

Verify that the same passenger identity survives:

```text
train manifest
→ alighting
→ station pedestrian
```

### Association

Verify that a taxi-demand passenger receives the correct station and taxi stand reference.

### Lifecycle

Verify that the taxi stand association remains available after the passenger leaves the train.

### Performance

Verify that nearest-stand resolution is not performed in the per-frame update loop.

Run the existing railway, passenger and taxi tests.

---

# 16. Implementation workflow

Work incrementally:

1. Inspect the current railway passenger implementation.
2. Inspect the existing taxi stand implementation.
3. Identify the existing taxi stand collection/spatial index.
4. Implement nearest-existing-stand lookup.
5. Cache the station → nearest taxi stand association.
6. Extend passenger data with transportation intent if necessary.
7. Implement TAXI demand using the existing random system.
8. Associate taxi-demand passengers with their station and nearest taxi stand.
9. Preserve passenger identity through train alighting.
10. Connect the passenger to the existing pedestrian movement system where possible.
11. Add tests.
12. Run existing railway/passenger/taxi tests.
13. Run a gameplay test with a realistic number of railway passengers.
14. Review the diff and remove unnecessary changes.

---

# 17. Acceptance criteria

This phase is complete when:

* existing taxi stands are discovered and reused
* no new taxi stands are created
* every railway station can resolve its nearest existing taxi stand when one exists
* taxi demand is generated only for a subset of railway passengers
* taxi-demand passengers retain their identity
* taxi-demand passengers know which station and existing taxi stand they are associated with
* passengers can transition from train → pedestrian without losing this information
* no expensive nearest-stand search occurs every frame
* existing railway/passenger/taxi functionality continues to work
* tests pass
* there is no meaningful FPS regression

At the end, report:

* files changed
* how existing taxi stands are discovered
* how nearest-stand selection works
* how station → stand associations are cached
* how taxi demand is generated
* passenger state changes
* tests executed
* performance impact
* any limitations that should be addressed before implementing phone pre-booking
