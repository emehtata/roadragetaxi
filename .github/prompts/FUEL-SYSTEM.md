# Fuel system implementation prompt

Implement fuel consumption and refueling for The Road Rage Trip in two phases.

## Product behaviour

- Every player taxi has a 60-liter fuel tank and starts half full, with 30 liters.
- Fuel consumption is based on actual distance traveled, speed, throttle, and braking input.
- Typical steady driving around 90 km/h should consume approximately 10 L/100 km.
- Aerodynamic demand raises consumption at high speed; at 200 km/h the baseline is approximately 20 L/100 km.
- Actual forward acceleration from the physics model raises consumption above the speed baseline, so consumption at a given speed is visibly higher while accelerating than while cruising. Aggressive throttle may add a small immediate demand penalty before measured acceleration catches up.
- While braking, fuel consumption drops near zero. Do not treat distance traveled under braking as normal powered driving.
- Show live consumption in L/100 km above the remaining liters and tank percentage in a clearly visible HUD fuel gauge. Use warning colors below 20% and a critical color below 8%.
- Fuel is authoritative simulation state, not a renderer-only counter. Include it in client/server snapshots.
- Clamp fuel to the range `0..capacity`; never allow negative fuel.
- When fuel reaches zero, propulsion stops, the engine switches off, and the car comes to a stop.

## Phase 1: respawn recovery

- Use a 60-liter tank and implement the consumption model, HUD gauge, empty-tank behavior, localization, and tests.
- Notify the player once when the tank becomes empty and instruct them to respawn.
- A successful player-car respawn refills the tank to 60 liters and restarts the engine only when the tank is empty. Ordinary respawns preserve the current fuel amount.
- Do not charge money for Phase 1 respawn fuel.

## Phase 2: fuel stations

- Use existing OSM `amenity=fuel` scenery as refueling locations.
- Let the driver stop at a fuel station and press a dedicated, documented button to refuel.
- A station visit may fill the tank incrementally or in one transaction, but it must never exceed tank capacity.
- Fuel price varies from €1.50 to €3.00 per liter. Make station pricing deterministic for a station/session and show the price before purchase.
- Deduct the exact purchased fuel cost from the taxi balance. Define behavior for insufficient funds and test partial filling if supported.
- Show clear prompts for entering range, starting/stopping refueling, liters purchased, total cost, and a full tank.
- Replace Phase 1's respawn refill with station-based recovery once the station flow is complete; retain a deliberate emergency recovery path so a save cannot become permanently unplayable.

Phase 2 implementation uses `G` to buy fuel while stopped within 8 meters of a pump. It fills the tank in one transaction, or buys a partial amount with the entire available balance. The earlier empty-tank-only 60-liter respawn refill remains the deliberate emergency recovery path; respawning with fuel remaining still preserves that fuel.

## Architecture and tests

- Keep fuel-consumption math in a small Pygame-independent module with pure functions.
- Consume fuel in the authoritative simulation tick after actual movement distance is known.
- Preserve backward compatibility when applying snapshots that predate fuel fields.
- Unit-test the 90 km/h and 200 km/h reference points, throttle penalty, braking behavior, distance conversion, clamping, starvation, respawn refill, protocol round-trip, and HUD rendering.
- Run focused simulation, physics, protocol, and HUD tests plus compilation and diff checks.
