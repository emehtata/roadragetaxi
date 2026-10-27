## Additional Phase — Realistic Traffic Volume by Location, Time, and Season

### Objective

Make ambient NPC traffic reflect realistic Finnish traffic patterns. The current simulation produces too many vehicles on remote rural roads, including at 01:00 on an October night in sparsely populated parts of Sysmä.

Integrate traffic demand with the municipality-based population and settlement-density model described in this task. Do not treat vehicle traffic as independent of geography, time, or season.

### 1. Audit the existing traffic model

Identify every source of NPC vehicles and traffic demand, including:
- Ambient vehicle spawning.
- Destination-driven trips.
- Commuting and daily activity schedules.
- Event-related traffic.
- Traffic generated near the player or along nearby roads.
- Vehicle respawning and replacement after despawning.

Determine why vehicles repeatedly appear on remote roads at night. Check for unconditional spawn rates, fixed minimum traffic levels, excessive spawn retries, and vehicle replacement rules that ignore local traffic demand.

Fix the underlying cause rather than adding a special-case rule for Sysmä.

### 2. Calculate traffic demand

Create a shared traffic-demand model using:
- Local population and settlement intensity.
- Road classification and the road's actual role in the road network.
- Time of day.
- Day of the week, including weekends and public holidays where supported.
- Month and season.
- Relevant destinations and trip purposes.
- Existing event and activity schedules.

Use these inputs to estimate the relative likelihood and volume of traffic in each area and time period.

Do not assume that every mapped road should continuously contain NPC vehicles. A road's existence does not imply that traffic must be visible at all times.

### 3. Apply realistic Finnish daily and seasonal patterns

Use configurable traffic-demand curves rather than a single global spawn probability.

Expected qualitative behavior:

- **Urban daytime:** relatively high traffic, with morning and afternoon peaks where appropriate.
- **Urban late night:** substantially lower traffic, but occasional vehicles remain plausible.
- **Suburban areas:** moderate daytime traffic and much lower overnight traffic.
- **Small villages:** intermittent traffic, with long quiet periods at night.
- **Remote rural roads:** very sparse traffic, especially overnight.
- **Remote rural roads at approximately 01:00 in October:** normally no visible ambient vehicles for extended periods may be entirely appropriate.
- **Summer holiday areas:** seasonal increases only where the available geographic and destination data supports them.
- **Event traffic:** localized and time-limited, with demand consistent with the event's actual location and schedule.

Do not make rural roads permanently empty. Preserve plausible occasional trips, including long-distance travel and essential traffic, without forcing vehicles to appear at fixed intervals.

These are target behaviors, not fixed universal vehicle counts. Calibrate parameters against credible traffic statistics if available, and clearly label any values that remain estimates.

### 4. Separate trip demand from visible vehicle spawning

Where practical, model a trip's probability first and then determine whether it should produce a simulated vehicle in the player's vicinity.

A vehicle should not be spawned merely because the player has entered an area with insufficient traffic.

If the existing simulation uses destination-driven trips, preserve that architecture and ensure that trip generation respects local demand. Avoid a separate ambient spawning mechanism that silently overrides the traffic-demand model.

Vehicle despawning and replacement must not maintain an artificial minimum number of cars in low-demand areas.

### 5. Integrate with the municipality population model

Use the same underlying geographic population-intensity model for pedestrians and traffic, but do not use identical multipliers for both.

Traffic also depends on road function, trips passing through the municipality, and destinations outside the immediate area. A remote through-road may have occasional passing vehicles even where local population is low.

Avoid using municipality population divided by area as the sole predictor of traffic. Use it as one input alongside settlement distribution, road classification, time, and trip purpose.

### 6. Deterministic regression tests

Add tests that reproduce the reported problem and verify relative traffic demand across:
- A dense urban center at daytime and at night.
- A suburb during rush hour and late night.
- A small village after midnight.
- A remote rural road in Sysmä at 01:00 in October.
- The same rural road during daytime.
- A rural road during a supported seasonal or special event.
- A major road crossing a sparsely populated municipality.

Use fixed random seeds and run repeated trials. Verify that expected traffic rates differ substantially between high-demand and low-demand scenarios.

Do not require every random sample to produce exactly zero vehicles. Instead, test statistically that remote overnight traffic is very rare and that the model does not keep replacing vehicles to maintain an artificial traffic level.

Include diagnostics that explain the calculated traffic demand and the reasons a vehicle trip or spawn was accepted.

### 7. Performance and delivery

Reuse spatial indexes and precomputed demand data where possible. Avoid recalculating the full geographic model every frame.

Preserve FPS, existing gameplay, and server-authoritative simulation. Do not change the map-data architecture or address the existing PBF loading/stuttering issue as part of this work.

Document the traffic model, configurable parameters, test results, and any unsupported assumptions. Commit and push the working branch if permitted by the existing workflow. Do not create or push Git tags.