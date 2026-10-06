# Godot Parity Phase 3 — Taxi Information

## Objective

Implement the next recommended phase from
`docs/architecture/godot-pygame-rendering-parity.md`:

1. Send the live taximeter, fare distance, passenger happiness, and elapsed
   fare time in `state.taxi`.
2. Show those values in Godot's existing fare/mission HUD while a passenger
   is being driven.
3. Send the price of the fuel station currently within refuelling range and
   show it in Godot's existing fuel gauge.

This is one small additive state-protocol extension plus presentation. Keep
the Python simulation authoritative and preserve the existing fare, fuel,
driving, camera, and rendering rules.

Do not combine this work with navigation, road rage, weather presentation, or
any later parity phase.

---

## 1. Read the current implementation first

Before changing code, trace the complete current flow:

* Pygame taxi banner in `render/hud.py::draw_hud`
* Pygame fuel-price text in `render/hud.py::_draw_fuel_meter`
* `TaxiManager.live_fare_cents`, `fare_distance_m`,
  `passenger_happiness`, `elapsed_time`, and `fare_started_at` in `taxi.py`
* fare lifecycle and state values in `TaxiManager.update`
* `nearest_fuel_station`, `fuel_station_price_cents`, and
  `FUEL_STATION_RANGE_M` in `fuel.py`
* refuelling's use of those helpers in `simulation.py`
* the Pygame caller's nearby-station lookup in `main/__init__.py`
* state construction and compatibility handling in `protocol.py`
* server broadcasting in `server/__init__.py`
* Godot fare text in `godot/hud.gd`
* Godot fuel gauge in `godot/instruments.gd`
* the existing protocol, server-integration, and Godot test patterns

Use the current repository as the source of truth. Do not infer behaviour
from this prompt when the implementation answers it directly.

---

## 2. Preserve the existing rules

This phase exposes values that the simulation already owns. Do not calculate
fare, distance, happiness, time, or fuel price independently in Godot.

The current simulation remains responsible for:

* starting and stopping the fare meter
* calculating the live fare
* accumulating fare distance from the odometer
* accumulating elapsed fare time
* changing passenger happiness
* choosing the deterministic station price
* deciding which pump is within the existing 8 m refuelling range

Do not alter fare formulas, score, tips, passenger behaviour, fuel purchase
rules, station range, or station pricing.

---

## 3. Extend `state.taxi`

Add only the fields needed by this phase to the existing `taxi` object in a
state message:

```text
live_fare_cents
fare_distance_m
passenger_happiness
elapsed_time
fuel_station_price_cents
```

The first four values come directly from `TaxiManager`.

`fuel_station_price_cents` is the deterministic price of the nearest fuel
station within the same `FUEL_STATION_RANGE_M` used by refuelling, or null
when no pump is in range. Use the existing `nearest_fuel_station()` and
`fuel_station_price_cents()` helpers; do not duplicate their distance or
pricing logic. Use the taxi/car position, matching Pygame and refuelling.

Keep the extension additive and compatible with clients or fixtures where
the new fields are absent. Do not add a new message type or endpoint. Do not
bump the protocol version unless the repository's established rules require
it for additive state fields.

Avoid adding cached or parallel fare state. A direct read during normal state
construction is sufficient. If the station lookup is found to be materially
expensive, reuse an existing world/spatial lookup; do not build a speculative
index for this phase.

---

## 4. Show live fare information in Godot

Extend the existing fare/mission text rather than adding a second HUD panel.

When the passenger is being driven to the drop-off and the fare has started,
show the same information as Pygame:

* destination/mission line already shown by Godot
* elapsed time in whole seconds
* live fare, formatted as euros from integer cents
* fare distance in kilometres with two decimals
* passenger happiness as a rounded percentage

Do not show made-up live values during pickup, passenger walking/boarding, or
when there is no passenger. Keep the current pickup, walking, and no-fare
texts unchanged.

Treat missing or malformed fields safely. An older state must still render
the existing mission text without crashing; omit unavailable detail rather
than displaying misleading zeroes.

Use the current English Godot HUD style. Do not introduce localization or a
new UI framework in this phase.

---

## 5. Show the nearby fuel price

Extend the existing fuel gauge in `godot/instruments.gd`.

When `state.taxi.fuel_station_price_cents` is numeric, show a compact line
equivalent to Pygame's:

```text
G: REFUEL  1.89 €/L
```

Requirements:

* use the exact authoritative cents value from the state
* show it only while a station is within the server's refuelling range
* hide it when the field is null, absent, or invalid
* keep the existing fuel amount, reserve arc, and consumption display
* ensure the added line fits the current fuel-gauge box at supported window
  sizes
* do not derive proximity from loaded Godot chunks

The map's station price board remains unchanged.

---

## 6. Scope and protected systems

Do not change:

* fare calculation, fare lifecycle, score, tips, or happiness rules
* fuel consumption, refuelling, price generation, or station range
* vehicle movement or physics
* V/B toggles, score HUD, or career summary from `godot-final-02`
* camera following, interpolation, or jitter fixes
* map chunks or the 2D/3D rendering pipeline
* building, lighting, weather, phone, or audio systems

Do not implement:

* navigation route or N toggle
* road rage
* precipitation or weather audio
* speech, subtitles, announcements, or next-train UI
* lane assist, respawn, trip reset, pause/settings, or historical weather

No new dependency is needed.

---

## 7. Tests

Add the smallest deterministic regression checks at the layer that owns each
contract.

### Python/protocol

Cover at least:

1. all four live fare fields in a state equal the `TaxiManager` values
2. zero and boundary values serialize without being omitted or changed
3. the station price is null outside the existing 8 m range
4. the station price matches `fuel_station_price_cents()` inside range
5. nearest-station selection matches `nearest_fuel_station()` when more than
   one station is eligible
6. encoding/decoding preserves the added values
7. existing refuelling uses the same price and range

Reuse existing protocol fixtures and fuel helpers. Do not create a mock
protocol separate from production state construction.

### Godot

Cover at least:

1. a drop-off fare formats fare, distance, happiness, and elapsed time
2. pickup, walking, and no-passenger states retain their existing text
3. missing/malformed live fields do not crash and are omitted
4. positive, zero, and cent-level fare values format correctly
5. the fuel gauge formats an in-range price from cents
6. null, absent, and invalid prices are hidden
7. changing or leaving a station causes the gauge to redraw appropriately

Prefer extending `godot/tests/run_tests.gd` and existing Python tests over
adding a new test harness.

Run at minimum:

```bash
pytest -q tests/test_protocol.py tests/test_fuel.py
make godot-test
make godot-selftest
```

Also run any server-integration test directly affected by state construction.
Distinguish unrelated pre-existing failures from regressions.

Manually verify:

1. accept and pick up a passenger
2. confirm the live meter starts and increases during the fare
3. confirm distance, elapsed time, and happiness update
4. complete the fare and confirm the ordinary no-fare HUD returns
5. approach a real fuel pump and confirm its exact board price appears in the
   gauge only within refuelling range
6. refuel and confirm the charged price matches the displayed price
7. drive away and confirm the price disappears
8. verify normal driving, camera, V/B controls, score, and career summary
   remain unchanged

---

## 8. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* live taximeter, fare distance, happiness, and elapsed time
* fuel-station price in the gauge
* `godot-final-03` implementation and tests

Update protocol documentation if it enumerates the contents of `state.taxi`.
Do not rewrite or re-audit the whole parity document.

---

## 9. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Create clear commits and push them when implementation and validation are
complete. Do not create or push a Git tag.

---

## Final report

Report:

### Implementation

* exact fields added to `state.taxi`
* how live fare details are shown
* how the nearby fuel price is selected and shown
* any existing contract that differed from this prompt

### Tests

* exact commands and results
* manual scenarios checked
* any unrelated failures

### Regression and performance

* confirmation that fare/fuel rules, driving, camera, and rendering are
  unchanged
* measured or reasoned cost of the station lookup and HUD changes

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
