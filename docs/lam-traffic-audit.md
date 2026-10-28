# Traffic simulation and Digitraffic LAM audit

**Reviewed:** 2026-10-28
**Scope:** Investigation and implementation proposal only. No simulation behavior was changed.

## Executive summary

NPC traffic already has an offline demand model. It scales vehicle targets with nearby mapped population, road class, game hour, weekday/weekend and month. Its hourly and monthly curves are explicitly estimates shaped after Finnish traffic counts; the game does not currently consume LAM measurements or station-specific profiles. Traffic density is an expected moving-vehicle target implemented through parked-car trip starts and passing-traffic spawns, rather than a traffic-flow count on each road.

LAM is a good source for calibrating the *shape* of traffic demand and checking direction-specific speeds. Fintraffic documents over 450 stations, station road-address metadata, live directional count/speed sensors, historical hourly reports, and day/station raw vehicle detections. The detailed station endpoint includes road number, road section and distance along that section, which OSM `Way` does not store. Some major roads can be matched with `ref`, geometry, direction and that road-address metadata. The match must be made and reviewed offline; proximity alone is not reliable around parallel carriageways, ramps and urban streets. LAM coverage is sparse and biased toward monitored roads, so unmatched roads need the current estimated fallback.

The recommended first release is a small, offline set of normalized hourly profiles for manually verified station-road matches. Use historical volumes to shape demand and measured speeds to validate congestion; do not equate raw vehicle counts with the game's much smaller NPC population. Keep the simulation authoritative on the Python server, select profiles during existing population updates, and leave network access out of normal gameplay. Add capacity and bottleneck behavior only after the demand profiles are calibrated and the existing interaction model is measured against them.

## Audit of the current simulation

### Vehicle creation, routes and lifecycle

- `NPCVehicleManager` in [`npc.py`](../src/theroadragetrip/npc.py#L4203) owns NPC vehicles, drivers, targets and diagnostics. Startup population is filled by `populate_initial` from random query points around the player; `_pick_npc_destination_candidates` then prefers valid parking or scenery/building destinations. Failed placement attempts are bounded (`populate_initial`, `npc.py:4637-4695`).
- During play, `_run_population_tick` retires eligible far/off-screen parked vehicles and tops up population gradually (`npc.py:5616-5758`). Moving traffic below target can be created by `_transit_spawn_steps` / `_spawn_transit_vehicle`, which select nearby route graph nodes and plan short routes (`npc.py:5438-5550, 5891-5916`). Parked vehicles can also start resident trips through `_find_npc_trip_steps` / `find_and_start_npc_trip` (`npc.py:2017-2150` and route jobs around `npc.py:5917-6045`). Route jobs complete asynchronously within a bounded per-frame time budget.
- `TrafficWorld` builds route graphs from loaded OSM `Way` geometry and plans a route on those graphs (`traffic_world.py:67-130, 280-340, 440-620`). Routes are selected between viable destinations or as short transit routes; they are not selected from LAM origin/destination flows.
- Vehicles are removed when parked and sufficiently far away, when a wreck times out, or after specified recovery failures; moving vehicles are not ordinarily removed mid-trip (`npc.py:5616-5712`). Active simulation is spatially limited, and vehicles beyond the simulation area retain state until they re-enter or are cleaned up.

### Roads, context and existing demand

- `osm.models.Way` stores projected polyline points, `highway`, width, OSM `osm_id`, `ref`, `oneway`, lane counts, speed limit, layer, bus routes and other OSM properties (`osm/models.py:13-56`). It has no Finnish road-section number/distance address and no LAM station or volume field. OSM parsing retains road references, direction, lane counts and parsed `maxspeed` (`osm/build.py:1340-1555`).
- `population.py` estimates local residents/visitors from building types and footprints. `NPCVehicleManager.set_local_density` recounts nearby people only when the player enters a 100 m cell (`npc.py:4586-4608`). Municipality density is used in the pedestrian model; NPC traffic's local scale comes from buildings around the player.
- The current demand model uses local people, an OSM road-class through-traffic factor, weekday/weekend hourly curves, month factors and a Friday/Saturday nightlife term (`population.py:117-165`). The values are comments-labeled estimates, not fitted to a LAM station. The code uses the game clock set by `simulation.py:697-703`; motorcycle and cycling activity also vary by season (`npc.py:4618-4629`).
- There is no traffic-specific holiday calendar beyond the fixed Finnish holidays and Midsummer dates coded in `population.py:130-147`; Easter and Ascension are explicitly not handled. There is no observed traffic profile by urban/rural class. Population density and road class provide coarse proxies.
- `set_local_density` converts demand into `expected_moving` and a randomized integer moving target (`npc.py:4610-4634`). `_run_population_tick` tries to fill that target with moving vehicles (`npc.py:5840-5916`). The game therefore controls population and the chance/rate of generating trips, not a target number of real-world vehicles per lane-hour.

### Speed, interactions, congestion and controls

- An NPC's desired speed starts from the current OSM road's `speed_limit_kmh`, is capped by its vehicle definition, and is further reduced for traffic rules, arrival, off-road access, corners and obstructions (`npc.py:2915-2993`). `update_car_physics` advances the vehicle toward that target (`npc.py:3200-3217`). Speed is not based on LAM speeds, traffic volume or an explicit segment capacity.
- Congestion can emerge locally from individual vehicles. `nearest_vehicle_ahead` searches the vehicle's forward lane corridor; `update_npc` reduces target speed using the lead vehicle's speed and following gap (`traffic_rules.py:76-114`, `npc.py:2995-3044`). Crashed or stopped vehicles can block and trigger waiting/passing behavior. Nearby traffic queries use a spatial grid rather than all-to-all scans (`npc.py:6430-6457`).
- Traffic lights apply direction- and approach-specific stop/speed decisions to NPCs (`npc.py:2915-2923`, `traffic_rules.py:213-270`). Signs and crossing-yield logic also constrain speed (`npc.py:2924-2940`). Signalized intersections can therefore create queues through vehicle interactions, but there is no explicit network queue, lane discharge, demand/capacity ratio, or shockwave model.
- Generated and live roadworks currently affect the player's taxi movement and speed limit (`simulation.py:478-490, 545-550`; live source is `digitraffic_road.py`). `NPCVehicleManager` and `TrafficWorld` do not read the live-roadwork manager. Roadworks are therefore not a general NPC capacity/closure input. Roadside crashes and signalized roadwork behavior can affect NPCs only where represented as actual obstacles or traffic lights.

### Update cadence and performance boundaries

- NPC movement, traffic decisions, collision checks, spatial indexing and current obstacle following run in the server simulation update each frame (`simulation.py:687-712`, `npc.py:6364-6504`). This is per active vehicle and bounded by active viewport/simulation areas and nearby spatial queries.
- Population recalculation and spawn/despawn work runs every `NPC_POPULATION_TICK_S` (2 s), with local building counts cached by 100 m cell (`npc.py:233-300, 4586-4635, 6492-6505`). Route searches run as jobs with a shared per-frame budget (`npc.py:286-300, 5217-5265, 5616-5640`).
- Initial fill happens at world load. Route graph build and map loading happen on load or streamed map changes (`traffic_world.py:509-582`). These are natural places for loading an offline profile index; LAM-to-OSM matching belongs in an offline preprocessing tool, not a simulation tick.
- Existing diagnostics expose traffic demand parts, moving targets, population counts and route-job statistics (`npc.py:4420-4454, 4630-4635`). Those can support profile debugging without adding a Godot-side traffic model.

## Verified Digitraffic LAM data

Current documentation and representative JSON responses were checked on 2026-10-28. Fintraffic describes more than 450 LAM stations; each station measures passing time, direction, lane, speed, vehicle length, headway and vehicle class ([LAM documentation](https://www.digitraffic.fi/en/road-traffic/lam/)).

| Purpose | Current endpoint / response | Relevant fields and limits |
| --- | --- | --- |
| Station inventory | [`/api/tms/v1/stations`](https://tie.digitraffic.fi/api/tms/v1/stations) | GeoJSON FeatureCollection. Point coordinates are `[longitude, latitude, elevation]`; properties include `id`, `tmsNumber`, `name`, `bearing`, `collectionStatus`, `dataUpdatedTime` and `state`. `collectionStatus` can indicate a temporarily removed station. |
| One station's road metadata | [`/api/tms/v1/stations/{id}`](https://tie.digitraffic.fi/api/tms/v1/stations/23001) | The sample feature has `roadAddress.roadNumber`, `roadSection`, `distanceFromRoadSectionStart`, `carriageway` and `side`, plus `direction1Municipality`, `direction2Municipality`, `sensors`, `freeFlowSpeed1/2`, `bearing`, `startTime` and collection/state fields. The route `{id}` is **not necessarily** the raw-data `tmsNumber`: sample feature `id=23001` has `tmsNumber=1`. |
| Sensor definitions/constants | [`/api/tms/v1/sensors`](https://tie.digitraffic.fi/api/tms/v1/sensors), [`/api/tms/v1/stations/{id}/sensor-constants`](https://tie.digitraffic.fi/api/tms/v1/stations/23001/sensor-constants) | Sensor definitions give id, name, unit, direction and description. Station-specific constants include `MS1/MS2` maximum hourly lane volumes, `VVAPAAS1/VVAPAAS2` free-flow reference speeds and `Tien_suunta`; values vary by station and date interval. |
| Current measurements | [`/api/tms/v1/stations/data`](https://tie.digitraffic.fi/api/tms/v1/stations/data), [`/api/tms/v1/stations/{id}/data`](https://tie.digitraffic.fi/api/tms/v1/stations/20002/data) | Response `stations[]` includes identifiers, `dataUpdatedTime` and `sensorValues[]`; each value has `id`, `stationId`, `name`, `shortName`, `timeWindowStart`, `timeWindowEnd`, `measuredTime`, `unit` and `value`. Sensor IDs 5054/5055 are 60-minute directional passings (`kpl/h`); 5056/5057 are 60-minute directional mean speeds (`km/h`). Five-minute rolling/interval sensors also exist. |
| Historical reports | [TMS statistics form](https://tie.digitraffic.fi/ui/tms/history/index_en.html) | Prebuilt reports are available at hourly granularity and can be filtered/summarized by date, direction, lane and vehicle class. Volume history starts in 2010; speed history in 2020. The public documentation presents this as a report form, not a stable general-purpose query API. |
| Historical raw detections | `https://tie.digitraffic.fi/api/tms/v1/history/raw/lamraw_[tmsNumber]_[yy]_[ordinalDay].csv` | One semicolon-separated file per station per day, with local Finnish time (EET/EEST), length, lane, direction, vehicle class, speed and a `faulty` flag. File-based raw history starts in December 2021; daily files are published the next day, typically 08:00–09:00. |

Live sensor data is cached for one minute; MQTT/WebSocket is also available. Historical corrected hourly volumes are generally published the following morning; a small subset requiring review can take several days. Counts in corrected volume reports may differ from speeds/raw records because those use actual detections and do not receive the same volume correction. These are different products and should not be mixed without recording provenance. The raw CSV documentation currently lists vehicle classes 1–9, but its `faulty` rule says classes greater than 7 are invalid. That inconsistency needs to be resolved against actual files before class-specific processing ([raw field/class documentation](https://www.digitraffic.fi/en/road-traffic/lam/#tms-raw-data)).

Digitraffic requires gzip support on API requests. Its published unauthenticated general limit is 60 requests/minute per IP for `tie.digitraffic.fi` V1 APIs; `Digitraffic-User` allows substantially more, without a specific higher number in the general guidance. Respect `Cache-Control`/`max-age` rather than polling faster than endpoint updates. Fintraffic open data is CC BY 4.0 and may be used commercially with source, license link, copyright/disclaimer preservation and a note/link when changed ([API usage guidance](https://www.digitraffic.fi/en/support/instructions/), [terms](https://www.digitraffic.fi/en/terms-of-service/)).

## Mapping stations to the game roads

The game converts OSM lon/lat and LAM GeoJSON lon/lat into EPSG:3067 metre coordinates (`world_loader.py:84-92`, `osm/build.py:727-740`). That gives a common projected coordinate system for a spatially indexed offline candidate search. A station is a point on a measured road section, not a universal sample for all roads in its vicinity.

The game's `Way` includes OSM road `ref`, polyline geometry, segment headings, `oneway`, lane counts, road class and speed limit (`osm/models.py:13-56`). A LAM station provides road number/section/distance along the section, carriageway and side. These attributes can narrow a match, but there is no existing road-section address or directional traffic-profile key on a `Way`. A station's direction 1/2 is tied to the Finnish road-address direction, not automatically OSM point order. Two-way OSM ways and divided carriageways need different direction handling.

Recommended match workflow:

1. Convert each station coordinate to EPSG:3067. Reject stations not collecting data or without adequate road metadata.
2. Find nearby OSM segments using a spatial index, first requiring compatible road `ref`/road number when present. Compare the station road direction and candidate segment headings, and use carriageway/side metadata where represented.
3. Reject candidates outside a conservative distance or with a close competing parallel road, ramp, frontage road or incompatible layer. Do not transfer a motorway count to an adjacent local street.
4. Store a reviewed association to the station and a road segment or continuous section, plus the mapping from LAM direction 1/2 to OSM travel direction. Keep unmatched stations and roads unmatched; use the fallback profile there.

Direct calibration is feasible for selected numbered main roads with matching OSM `ref`, geometry and unambiguous direction. The current data is insufficient for an automatic nationwide match with confidence: road-section identifiers and kilometering are absent from OSM `Way`, references may be missing or inconsistent, dual carriageways may be encoded differently, and stations are unevenly distributed. Urban streets and roads without a corresponding station should use estimated profiles, not nearest-station values. This preprocessing should also check station age, collection status, sensor availability and historical data completeness.

## Proposed profile model

Keep a generated, versioned local file, keyed by a curated game road section and direction. A compact initial record could contain:

```text
schema_version, source_updated, osm_way_ids/segment_span,
station_id, station_tms_number, road_number, road_section,
direction_mapping, match_distance_m, match_quality,
sample_period, quality/completeness,
weekday_hourly_volume_factor[24], weekend_hourly_volume_factor[24],
optional monthly factors, directional free_flow_speed,
optional hourly speed_ratio[24]
```

For the first iteration, normalize each station's hourly volume by its own representative average or peak, with weekday/weekend separation. That supplies the time shape without pretending the simulated car count equals Finland's actual flow. Keep direction separate. Choose month/season factors only after enough complete station-month samples support them; otherwise retain the current `MONTH_FACTOR` estimate. Store sample counts/quality and report dates, and fall back for incomplete bins. Historical reports are preferable for count calibration because their hourly totals are inspected and corrected. Raw detections can provide lane/class analysis after the class-code inconsistency and local-time/DST handling are resolved.

LAM vehicle classes distinguish cars/vans, trucks, buses, articulated/heavy trucks, car-trailers, motorcycles/mopeds and HCT. These do not map one-to-one to game vehicle plugin types or ownership. First use aggregate directional volumes for demand shape. Add class mix only where there are sufficient valid samples and an explicit mapping to the game's vehicle distribution; do not interpret the LAM class as occupancy, household ownership or trip purpose.

Use existing road class, local mapped population and municipality density as the fallback context. LAM supplies observed station-road flow, direction, time-of-day, day-type and (in raw/report breakdowns) vehicle class and speed. Urban/suburban/rural factors, destination purpose, roads without sensors, yearly seasonality and the simulated-to-real vehicle scale remain estimates. A local population baseline should still contribute on streets without LAM coverage.

## Congestion modelling options

The key quantities are different:

- **Volume** is observed vehicle passings per time interval at a station.
- **Demand** is vehicles attempting to enter/use the game road network.
- **Capacity** is the flow the road or bottleneck can serve; station `MS1/MS2` provide lane-specific reference maxima at stations, not universal capacities.
- **Congestion** is a queue or reduced speed when demand approaches/exceeds capacity or a bottleneck reduces discharge.

The current game has a compact population budget, local trips, passing traffic, vehicle-to-vehicle following, traffic lights and stopped/crashed obstacles. A high measured volume may flow freely; use speed relative to free-flow speed and capacity utilization to distinguish it from congestion. LAM's directional average speeds and sensor constants can validate or calibrate typical behavior, not directly set each NPC speed.

Options, from lower to higher scope:

1. **Hourly profile weights for NPC spawn/trip demand.** Direct fit with `traffic_demand` and `set_local_density`; minimal structural change. Use measured relative profiles, not raw hourly vehicle totals.
2. **Road-class and area baseline refinement.** Replace or calibrate `THROUGH_TRAFFIC` and generic time curves only where verified station matches exist; preserve building-density and fallback estimates elsewhere.
3. **Directional road demand and spawn distribution.** Assign profile multipliers to route segments/directions so traffic distribution follows the data and avoids spawning all added vehicles near one player-centered ring. Requires route-segment/profile association and careful count accounting.
4. **Capacity and bottlenecks.** Use OSM lanes/width, local signals, and station-specific free-flow capacities to estimate discharge limits. Queue buildup should result from individual vehicles waiting/following at constrained nodes. A time-dependent closure/speed reduction for NPCs would be needed to make roadworks affect flow; current live roadworks are taxi-only.
5. **Speed-profile calibration or a macroscopic flow model.** Compare simulated directional speed distributions to historical LAM speed ratios. Explicit link queues or flow conservation would be a substantial model extension; it is not needed for an initial profile integration and would need separate evidence and performance testing.

Do not use a single global NPC cap as the realism fix. The game already has configurable city target/min/max populations and a moving target. Any future compute budget should preserve relative per-road/per-direction demand, use distance/visibility-aware simulation and bounded route-job work, and account for simulated flow in aggregate when distant vehicles are not individually ticked.

## Performance and offline operation

- **Preprocessing:** station downloads, date filtering, hourly aggregation, normalization and station-to-OSM matching are offline jobs. Build a spatial index once; avoid a station-by-every-road full scan. No runtime cost beyond loading a small profile file.
- **Storage estimate:** 450 stations × 2 directions × 2 day types × 24 float32 factors is about 169 KiB before identifiers/metadata. Optional month, class and hourly speed arrays increase this, but a compressed curated file should remain small. This is an estimate, not a measured repository artifact.
- **Runtime lookup:** attach profile IDs to matched route segments at load/preparation time or use a segment-keyed dictionary. Read a fixed number of factors when the game clock/profile bucket changes or during the existing 2 s population tick. This is constant-time per current profile lookup and avoids scans over stations each frame.
- **Traffic simulation cost:** adding moving vehicles increases the existing per-active-vehicle decisions, physics and collision work. Keep movement server-side, preserve spatially bounded obstacle queries and the existing route-job time budget, and measure p95 frame/tick time before raising targets. No safe numeric cost estimate for more active vehicles is available from this audit.
- **Offline/fallback behavior:** gameplay should never need a network request. Missing file, unmatched road, stale station, unavailable hourly bin or parse error should select the current estimated model and log diagnostics rather than prevent world loading. Live TMS is optional and unnecessary for the first phase.

## Validation strategy

Use a fixed seed, same OSM extract and same game-clock scenarios for baseline and profile-enabled runs. For selected verified station roads, record simulated vehicle crossings at a directional virtual detector over game-clock hours. Compare normalized patterns rather than absolute counts until a defensible game-to-real scale exists.

Measure:

- Normalized hourly profile error (for example mean absolute error in hourly shares) separately for weekday/weekend and each direction.
- Simulated and observed morning, afternoon, daytime and overnight flow shares, including low-volume rural nights.
- Directional median speed as a fraction of station free-flow reference, and the fraction of bins below documented traffic-state thresholds where comparable measurements exist.
- Number and duration of queues at signalized junctions, roadworks/incidents, and bottlenecks; ensure high volume with adequate capacity remains mostly free-flowing.
- Error and fallback counts by road class/setting, and how many stations were excluded for poor match or incomplete data.
- Server simulation p50/p95 update time, route-job backlog, active vehicle count and peak memory against the baseline, on a representative dense and rural map.

Use distinct station groups for divided highway, undivided rural road and urban/suburban arterial where matching metadata is sound. Compare weekdays with weekdays, weekends with weekends, and similar season/weather where speed is evaluated. An A/B on the same seeds isolates profile effects; held-out stations or dates avoid judging the profile on the samples used to fit it. Counts and speeds may have different correction histories, so preserve product type and timestamp in the comparison.

## Incremental implementation roadmap

| Phase | Purpose and changes | Benefit / risk | Independent check |
| --- | --- | --- | --- |
| 0. Verify sample and export path | Select roughly 6–12 representative stations; fetch station metadata and historical hourly reports across weekday/weekend and more than one season. Confirm station ID vs `tmsNumber`, report export format, completeness, and class-code handling. No production changes. | Establish feasibility before code. Risk: the statistics form may not offer a supported bulk/API export. | Save a small reviewed sample, document provenance and reproduce its hourly aggregates. |
| 1. Offline profile builder | Add a standalone preprocessing tool for a narrow station subset. Aggregate corrected hourly volumes, normalize directional weekday/weekend curves, report gaps and write versioned generated data. Keep raw detections optional. | Creates compact offline data with no runtime network. Risk: bad DST or station-quality handling biases shapes. | Compare generated totals and missing bins against source reports; verify deterministic output. |
| 2. Curated OSM mapping | Preprocess station coordinates/road addresses against OSM `ref`, segment geometry and headings; persist only unambiguous road-section/direction associations. Do not change simulation behavior yet. | Enables evidence-based road-specific profiles. Risk: missing refs and parallel roads; reject uncertain matches. | Manually inspect every sample association on a map and test direction mapping/thresholds. |
| 3. Server-side demand integration | Load the local file as optional world data. At the existing population update, use the matched direction/profile time factor to modulate expected passing demand; retain local building demand and current estimate as fallback. Do not add a per-tick network query. | Adds observed temporal and directional variation offline. Risk: more active NPCs increase server cost and could distort distribution if demand is applied globally. | Test missing/corrupt data fallback, deterministic profiles, per-direction hourly targets and bounded route jobs. Compare to baseline metrics. |
| 4. Calibrate speed and bottlenecks | Use held-out station speed ratios and station capacity constants to calibrate signal/queue discharge behavior. Add NPC roadwork/incident effects only as a separate server change with lawful controls and bounded queries. | Can create believable congestion while distinguishing free-flow volume from queues. Highest gameplay/performance risk; requires focused design and tests. | Compare speed/queue metrics at matched stations and run traffic-law scenarios plus performance profiles. |
| 5. Broaden coverage | Expand station groups and regenerate profiles as source data changes; keep unmatched roads on fallback. Include required attribution and provenance in distributed docs/data. | Better coverage without online dependency. Risk: station coverage and quality remain uneven. | Validate new mappings and held-out dates; track match/quality coverage per region and road class. |

## Capability summary

| Capability | Status |
| --- | --- |
| NPC vehicle population, parked/moving lifecycle, OSM routes and per-vehicle following | Present in Python simulation. |
| Population-sensitive demand, road-class through factor, weekday/weekend/hour/month estimates and seasonal vehicle mix | Present, but estimated and not station-calibrated. |
| Road type, OSM `ref`, geometry, lanes, direction and speed limits | Present in loaded OSM `Way` data. |
| Offline time profiles and road-specific demand weights | Can be added with a generated local profile file and a small server-side lookup. |
| Directional measured volumes, speeds, road addresses and station capacity reference | Requires Digitraffic data and preprocessing; already exposed by documented LAM endpoints/reports. |
| Reliable nationwide station-to-OSM segment mapping | Requires curated preprocessing; current fields do not support a guaranteed automatic match everywhere. |
| Explicit segment capacity/flow conservation, queue spillback, and NPC response to roadworks | Significant simulation-model changes; not present today. |
| Mandatory live data during gameplay | Not needed and not recommended. |

## Open questions and assumptions before implementation

1. Can the historical statistics form provide repeatable batch export for a selected station/date range, or should the first builder use a limited number of daily raw files and accept their correction limits?
2. What are the actual current data availability, completeness and collection-status distributions for candidate stations across years and seasons?
3. How should the raw CSV's listed classes 8 and 9 be reconciled with the documented `faulty` test that rejects classes above 7? Confirm against samples or Fintraffic before class-level use.
4. What tolerance and review policy are acceptable for OSM `ref` normalization, station-to-road distance, heading difference, direction mapping and divided-carriageway association?
5. Which game-time timezone and repeated/missing daylight-saving hour convention should profile lookup use? Raw timestamps are Finnish local time, while live API timestamps use ISO UTC.
6. What is the desired simulated-to-real flow scale and acceptable profile error? The game samples only a fraction of vehicles, and there is no existing calibrated conversion.
7. Should capacity/speed calibration affect only moving NPC demand, or should it also change routes, signal queues, and roadwork/incident handling? Those are separate gameplay decisions and require server-side traffic-law review.
8. What attribution text, license link and source update metadata should ship with any generated data and be shown in a commercially distributed build?

## Sources

- [Fintraffic LAM documentation](https://www.digitraffic.fi/en/road-traffic/lam/)
- [Digitraffic road traffic endpoint directory](https://www.digitraffic.fi/en/road-traffic/)
- [Current Digitraffic Road API Swagger](https://tie.digitraffic.fi/swagger/)
- [Digitraffic API usage, caching and request limits](https://www.digitraffic.fi/en/support/instructions/)
- [Fintraffic terms and CC BY 4.0 attribution](https://www.digitraffic.fi/en/terms-of-service/)
- [Existing population and traffic-demand model](population-model.md)
- [Finnish NPC traffic-law requirements](finnish-npc-traffic-law.md)

## Phase 0: sample and export path (done 2026-10-28)

Verified against real files rather than the documentation alone:

- **Export path:** the per-day raw files work as a batch source:
  `https://tie.digitraffic.fi/api/tms/v1/history/raw/lamraw_<tmsNumber>_<yy>_<ordinal day>.csv`,
  about 2.5 MB and 40 000 vehicles a day for an Oulu main road. The
  statistics form was not needed.
- **Station id vs `tmsNumber`:** different for many stations (`24201` → `1201`,
  `23153` → `153`). Raw files use `tmsNumber`, the detail endpoint the id.
- **Missing days answer HTTP 403, not 404** (the file store's convention):
  st847 Oulunlahti has no files for January 2026. Treat 403 as "no data".
- **Field order** (no header line): station; yy; ordinal day; hour; minute;
  second; 1/100 s; length m; lane; direction (1/2); vehicle class; speed km/h;
  faulty (0/1); three technical fields. Times are Finnish local time.
- **Open question 3 answered from the data:** classes 8 (motorcycles and
  mopeds) and 9 (HCT) are marked valid (`faulty` 0) in the files; the
  documented "class > 7 is faulty" rule is stale. The `faulty` flag itself
  is applied correctly (e.g. 76 faulty of 40 852 records at vt4 Välivainio),
  so the builder takes it as given and counts every class.
- **DST:** sample weeks avoid the clock-change Sundays (a 23- or 25-hour
  day), so local hours need no correction.

## Phase 1: offline profile builder (done 2026-10-28)

`tools/lam_profiles.py` writes `src/theroadragetrip/assets/traffic/lam_profiles.json`
(about 31 KB; CC BY 4.0, in the licence inventory). Downloads are reduced to
hourly counts per direction and cached in `~/.cache/RoadRageTrip/lam/`, so a
rebuild is offline and byte-identical.

- **Stations (11):** urban: vt4 Oulu Välivainio, vt22 Oulu Kaukovainio,
  st847 Oulunlahti, vt1 Espoo Hirvisuo, st101 Helsinki Vartiokylä (Ring I),
  kt45 Oulunkylä; rural: vt4 Ii, vt22 Muhos, kt86 Liminka, st816 Hailuoto,
  vt5 Kuusamo.
- **Sample:** one Monday–Sunday week per season in 2026, holiday-free and
  clear of clock changes: 19 Jan, 20 Apr, 13 Jul (the holiday season, kept on
  purpose), 12 Oct. 300 of 308 station-days exist: st847 lacks 4 January
  days, st816 Hailuoto has only its October week.
- **Per station:** weekday/weekend hourly curves, total and per direction,
  as shares of the station's average weekday peak hour (population.py's
  convention); each sampled month's weekday total against their mean; the
  weekday peak in vehicles an hour; road address, direction municipalities
  and free-flow speeds for the phase 2 match.
- **Urban and rural curves:** the mean of the stations with at least 21
  sampled days (Hailuoto stays in the file, out of the means).

Measured against the current estimates (`population.py`):

| | Estimate | Urban | Rural |
| --- | --- | --- | --- |
| Weekday 07–08 (morning peak) | 0.85 | 0.67 | 0.57 |
| Weekday peak | 1.00 at 16 | 1.00 at 15 | 0.99 at 15 |
| Weekday 02–03 (night) | 0.02 | 0.04 | 0.03–0.04 |
| Weekend peak | 0.80 at 12–13 | 0.71 at 14–15 | 0.88 at 15–16 |
| Mean absolute error, weekday / weekend | | 0.041 / 0.067 | 0.057 / 0.059 |
| July weekday total against the year | 1.00 | 0.82–1.05 (holidays empty the cities) | 1.05–1.45 (summer travel) |

The estimate's shape is close on urban weekdays; it overstates the morning
peak, puts the afternoon peak an hour late, makes weekends peak too early
and too low on rural roads, and its single month curve cannot fit both
settings: urban July is the quietest sampled month, rural July the busiest.

## Phase 3, first step: measured curves in the demand model (2026-10-28)

Before any per-road matching (phase 2), the measured *group* curves replace
`population.py`'s estimated clock, since every NPC trip start and moving
target already goes through `hour_demand`:

- `population.load_measured_curves` reads `lam_profiles.json` once at import:
  the urban and rural weekday/weekend curves, and per setting the mean of the
  group stations' month factors, interpolated linearly around the year
  (urban: 1.06 April to 0.93 July; rural: 0.83 January to 1.26 July).
- The local people fraction picks the mix (`URBAN_PEOPLE_FRACTION` 0.5: a
  suburb counts as fully urban, a village mostly rural). A heuristic: the
  stations are main roads, the blend weight is not fitted.
- Missing or unreadable file: the estimates stay, with a warning.
- Cost: the same 24-value lookups at the same 2 s population tick.

Effects: the weekday afternoon peak moves from 16 to 15, the morning peak
drops from 0.85 to about 0.6–0.7, nights rise from 2–3 % to 4–8 % of the
peak, weekends peak in the afternoon, rural summer is busier and urban July
quieter. One regression limit moved: a remote Sysmä tertiary road at 01:00
in October now wants 0.022 moving cars on average (limit raised from 0.02 to
0.03, about one car wanted in 45 minutes); the measured rural night share is
higher than the estimate was.

Not done yet: phase 2's per-station road matching, direction-specific
curves, and the validation runs with a virtual detector on matched roads.

## Phase 2: station to OSM road matching (2026-10-28)

`tools/lam_profiles.py` now stores each station's `osm_match` in
`lam_profiles.json`: the matched OSM ways and, per way, which LAM direction
its forward and backward travel is (`null` where one-way). Overpass answers
are cached beside the counts, so rebuilds stay offline and identical.

Rules (`match_station`):

- Candidates: drivable main-road ways (motorway to unclassified, no `*_link`
  ramps) within 40 m whose `ref` includes the station's road number.
- Heading: the road's chord within 75 m of the station must run within 50
  degrees of the station's `bearing` either way. The API's bearings are
  coarse: vt22 Muhos 45 degrees and st816 Hailuoto 31 degrees off the road,
  so 30 rejected them wrongly; the `ref` match already fixes the road, the
  tolerance only rules out crossing ones.
- Ambiguous, rejected: another parallel road without that ref within 10 m
  farther than the match (a frontage or service road).
- Divided roads keep every parallel carriageway piece within 40 m.
- Direction 1 is toward `direction1Municipality`, along `bearing`. The
  carriageway field is not used: vt1 Espoo, a motorway, says `ONE_CARRIAGEWAY`.

Review of the 11 stations:

| Station | Result | Review |
| --- | --- | --- |
| vt4 Oulu Välivainio | rejected: no bearing in the API | left unmatched rather than guessed |
| vt22 Oulu Kaukovainio | 2 one-way carriageways | both exist as game `Way.osm_id`; inbound (→ Oulu) 0.54 at 07, outbound 0.59 at 16 |
| st847 Oulunlahti | two-way road | → Oulu 0.34 at 07 against → Kempele 0.17 |
| vt1 Espoo Hirvisuo | eastbound + westbound in 2 pieces | → Helsinki 0.38 at 07, → Turku 0.72 at 16 |
| st101 Vartiokylä (Ring I) | 2 one-way carriageways | a ring road: no inbound direction to confirm |
| kt45 Oulunkylä | northbound in 2 pieces (3 → 4 lanes), southbound | → Helsinki 0.47 at 07, → Tuusula 0.56 at 16 |
| vt4 Ii Myllykangas | two-way road | **not confirmed**: more traffic toward Kemi in the morning (perhaps the Kemi–Tornio industry); check before relying on its directions |
| vt22 Muhos Riihikylä | two-way road | matched after the tolerance change |
| kt86 Liminka | two-way road | |
| st816 Hailuoto | two-way road in 2 pieces | matched after the tolerance change; only one sampled week |
| vt5 Kuusamo | two-way road | |

The direction convention is confirmed by the urban radial roads' commuter
peaks (inbound in the morning, outbound in the afternoon). Still no
simulation change: phase 3 can attach a station's per-direction curves to
these ways.
