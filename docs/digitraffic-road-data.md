# Digitraffic road data: roadworks, traffic messages, variable signs and TMS

Status: **phases 0 and 1 implemented (2026-10-26)**: live roadworks for the
player behind Settings → gameplay → "Real roadworks (Digitraffic)"
(`--road-digitraffic`, off by default). See "Implemented so far" below; the
rest is design. This document records what the
Digitraffic Road API offers, as inspected on 2026-10-26 (API build
`2026.10.14-1`, <https://tie.digitraffic.fi/swagger/>). It also shows how
each dataset maps onto the game's existing systems, and proposes an
implementation order with acceptance checks.

Work that changes NPC behaviour from this data (roadworks, speed limits,
closures, temporary lights) must follow
[the Finnish NPC traffic-law guide](finnish-npc-traffic-law.md) (AGENTS.md).
Traffic decisions stay on the Python server; Godot only draws them.

## Implemented so far

| Part | Where | Notes |
| --- | --- | --- |
| Client and cache | `digitraffic_road.DigitrafficClient` | gzip, `Digitraffic-User: RoadRageTrip/road-data`, backoff (30 s → 5 min), Deprecation/Sunset logging. **Every successful answer is cached with no expiration** in `~/.cache/RoadRageTrip/digitraffic_road.sqlite` (gzip bodies, keyed by the exact URL), outside `osm_cache/` so "clear map cache" leaves it; failures and invalid JSON are never cached. |
| Queries | `roadworks_params`, `RoadDataService` | One query is one snapped 0.4° × 0.2° tile (about 19 × 22 km) and one 15-minute **game-time** window, so it repeats exactly. Replays and restarts read the cache; live play gets a new window every 15 game minutes. Tiles within 5 km of the taxi are fetched on a background thread. |
| Roadworks | `parse_roadworks`, `RoadworkPhase.active` | The newest version per `situationId`. A phase follows its dates, and with `restrictionsLiftable` also its weekday working hours (local time). |
| Matching | `match_roadwork` | Samples every 10 m, nearest drivable surface way within 15 m and 30°, and a 10 m bonus for the matching `Way.ref` road number. At least 60 % of samples must match. Placed as 50 m `Roadwork` pieces; the speed limit covers `speed limit length` centred on the works. |
| In the game | `simulation.py`, `protocol.py` | The speed limit drives the rage meter, passenger comfort and the HUD sign. A closed lane stops the taxi only in the right-hand half (in the way's direction); `road closed` blocks the whole road. Generated roadworks are unchanged. |
| Client | `entity_layer._live_roadworks`, `map_chunk.draw_roadwork` | Cones and barriers for closed lanes and roads, with barriers and speed signs only at a run's open ends. |
| Map | `Way.ref` | The OSM road number is kept on `Way` (world cache format 56). |
| Diagnostics | F12 snapshot `live_roadworks` | Situations fetched, network requests made, and every placed piece. |

Verified on the real map on 2026-10-26 at 13:00: on Kainuuntie in Oulu (road 22,
OSM limit 60), two live roadworks matched to `ref 22` and the HUD showed 50.

Not yet done from phase 1: temporary traffic lights and alternating one-lane
traffic. Which lane is closed is not in the data, so the right-hand one is
assumed. Phases 2–6 are not started: NPC handling, signs, messages and TMS.

## 1. API facts that every client needs

| Fact | Detail |
| --- | --- |
| Base URL | `https://tie.digitraffic.fi` |
| Compression | **gzip is required.** A request without `Accept-Encoding: gzip` gets HTTP 406 ("Use of gzip compression is required"). |
| Identification | Send `Digitraffic-User: RoadRageTrip/<component>`, as `railway_import.py` and `composition_import.py` already do for rata.digitraffic.fi. |
| Licence | CC BY 4.0. Attribute "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY", as for the train data. |
| Coordinates | GeoJSON, WGS84, `[lon, lat]`. Bounding-box parameters are `xMin`/`xMax` (lon) and `yMin`/`yMax` (lat). |
| Times | ISO 8601 UTC (`…Z`). Working hours inside roadwork phases are local wall-clock times ("10:00") with an English weekday. |
| Deprecation signal | Deprecated APIs return `Deprecation: true` and `Sunset: <date>` headers. Read them and log a warning. |
| Polling | `GET /api/info/v1/update-times` gives each API's `dataUpdateInterval` and `recommendedFetchInterval` (table below). |
| Push alternative | MQTT over WebSocket. TMS topics are `tms-v2/<stationId>/<sensorId>`; the "v2" is the topic scheme, not a REST version. Polling at the recommended intervals is enough for this game; MQTT is optional. |

### Versions to use

Checked against the live headers on 2026-10-26:

| API | Use | Status |
| --- | --- | --- |
| Traffic message | **V2** `/api/traffic-message/v2/…` | V1 returns `Deprecation: true`, `Sunset: 2026-10-20`, so it is already past sunset. Do not use V1. |
| Variable sign | **V1** `/api/variable-sign/v1/…` | current, no deprecation headers |
| TMS (traffic measurement system, "LAM") | **V1** `/api/tms/v1/…` | current, no deprecation headers; there is no REST V2 (`/api/tms/v2/*` returns 404) |
| Weather (road weather stations) | **V2** `/api/weather/v2/…` | V1 returns `Sunset: 2027-04-13` |
| Maintenance tracking | V1 | current |

### Refresh intervals (from `update-times`)

| Endpoint | Data changes | Recommended fetch |
| --- | --- | --- |
| `traffic-message/v2/roadworks`, `…/traffic-announcements` | real time | 1 min |
| `variable-sign/v1/signs` | real time | 1 min |
| `variable-sign/v1/signs/code-descriptions` | static | 1 day |
| `tms/v1/stations/data` | every 5 min | 1 min |
| `tms/v1/stations`, `tms/v1/sensors`, `…/sensor-constants` | static | 1 hour |
| `traffic-message/v2/locations`, `…/area-geometries` | yearly | 1 day |
| `weather/v2/stations/data` | every 5 min | 1 min |

The game needs far less than the recommended rate. Proposed rates are in §7.

## 2. Coverage: what the data does and does not describe

- **State road network only.** All sampled roadworks and announcements came
  from Fintraffic's road traffic centres (`sender`: "Fintraffic
  Tieliikennekeskus", plus Tampere, Turku and Helsinki). They describe
  numbered roads in the state road register. Of the 490 roadworks nationwide,
  road numbers fell in these bands: 166 in 1–99, 108 in 100–999, 80 in
  1000–9999 and 136 at 10000 or above. **Municipal city streets are not
  covered.** Kuusamontie (road 20) in Oulu is in the data; a residential
  street in Tuira is not.
- **Consequence:** in a city centre, live data adds roadworks and signs on
  the arterial and through roads (vt4, vt20 and vt22 around Oulu). On
  intercity trips ([national-navigation.md](national-navigation.md)) it
  covers almost everything the player drives.
- **Finnish only.** Every roadwork and announcement had `language: "fi"`.
  Titles and descriptions are Finnish free text. The game shows English and
  German players localized text built from the structured fields (`features`,
  `restrictions[].type`), and shows the Finnish title verbatim only in the
  Finnish UI.
- **Snapshot volumes, Oulu box (lon 25.2–25.8, lat 64.85–65.15):** 8
  roadworks, 61 variable signs (30 showing text) and 28 TMS stations.
  Nationwide: 490 roadworks (467 active now), 11 active announcements (30
  over the last 36 h), 567 signs and 521 TMS stations (89 with state `OK`).

## 3. What the game has today

| Area | Today | Gap the data fills |
| --- | --- | --- |
| Roadworks | `roadworks.create_roadworks()` places 3 random 25–55 m zones on drivable ways at world load. `lane_closed` adds two temporary `TrafficLight`s. The simulation **blocks the player completely** inside a zone (`simulation.py`, `roadwork_blocked`). Protests avoid zones. | Real locations, extents, phases and working hours, plus real restrictions: speed limit and its length, lane closed, alternating one-lane traffic, temporary lights, road closed, detour. **NPC traffic ignores roadworks entirely** (no reference in `npc.py` or `traffic_world.py`), so that gap has to be closed for live data too. |
| Speed limits | `Way.speed_limit_kmh` from OSM `maxspeed`, default 50. Speeding raises the rage meter; there are speed cameras. | Variable speed limits (303 signs) and roadwork speed limits override the OSM value where they apply. |
| Traffic incidents | NPC crashes are simulated locally (`_trigger_vehicle_accident`). | Real accidents, closures and congestion as news, routing penalties and optional staged scenes. |
| Traffic volume | `population.traffic_demand()`: a modelled hourly profile (`hour_demand`), road-class `THROUGH_TRAFFIC` and local population. | TMS measured volumes and speeds: calibrate the model offline, and optionally drive live congestion near stations. |
| Weather | FMI observations (`weather_history.py`, SQLite cache, background thread, opt-in). | Road weather stations add road surface temperature, surface state, friction (`KITKA1`) and ice amount, which the grip and ice model currently estimates. Optional (§8). |
| Map data | OSM has road numbers (`ref=4`, `ref=E8;21`), but the game's `Way` does not keep them: `osm/build.py` reads `ref` only to make a display name ("Valtatie 4") for unnamed roads and then discards it. A named road like Kuusamontie (vt20) keeps no number. `Way` keeps `osm_id`, `highway`, `lanes`, `oneway`, `layer` and `speed_limit_kmh`. | Keeping `ref` on `Way` lets Digitraffic's road numbers pick the right way; without it, matching is geometry only (§7.3). |

## 4. Roadworks — `GET /api/traffic-message/v2/roadworks`

Parameters: `from` (default now − 1 h), `to`, and the bounding box. The
response is a GeoJSON `FeatureCollection` of `TrafficAnnouncementFeatureV2`.

### Data model, as observed

- `geometry`: `MultiLineString` (431 of 490) or `Point` (59). Lines follow the
  roadway.
- `properties.situationId` (`GUID…`) and `version`: one situation is updated
  in place. Key the cache on `situationId` and keep the highest `version`.
- `properties.announcements[]`: one per language (only `fi` seen), each with:
  - `title`, `location.description`, and `locationDetails.roadAddressLocation`
    with a `primaryPoint` and `secondaryPoint` (road number, section,
    distance, road name, municipality) and a `direction` (`both` 349,
    `unknown` 92, `pos` 32, `neg` 17);
  - `features[]`: human-readable summary items such as "Nopeusrajoitus" with
    a quantity of 30 km/h;
  - `timeAndDuration.startTime` and `endTime` for the whole situation;
  - `roadWorkPhases[]`: 1 phase in 462 of 490, up to 7. Each phase has its
    own `location` and `geometry` details, `timeAndDuration`, `workingHours[]`
    (weekday, start, end), `workTypes[]`, `restrictions[]`,
    `restrictionsLiftable` (whether the restrictions lift outside working
    hours), `severity` (`low` 46, `high` 406, `highest` 86),
    `slowTrafficTimes` and `queuingTrafficTimes`.

### Restriction types → game behaviour

These are the counts across 538 phases, with a proposed effect for each. All
effects are applied by the server; NPC handling follows the traffic-law guide.

| `restrictions[].type` | Count | Proposed game effect |
| --- | ---: | --- |
| `speed limit` (+ `speed limit length`, m) | 379 / 346 | The zone's effective speed limit for the player (rage meter, speed cameras) and for NPC target speed, over the stated length centred on the work geometry. |
| `slow moving maintenance vehicle` | 303 | Spawn a slow works vehicle (existing plough/tractor kinds) moving within the zone during working hours. |
| `single lane closed` / `multiple lanes closed` | 102 / 17 | Close the matching lane(s) of the way inside the zone: cones, lane-change merge for NPCs, a collision box for the player. |
| `single alternate line traffic` | 74 | One lane shared both ways: the existing roadwork `TrafficLight` pair, or a flagger NPC. |
| `traffic lights` | 57 | Temporary lights at both ends (existing `create_roadworks` pattern). |
| `narrow lanes` | 90 | Narrower lanes: reduced NPC speed and no passing (law guide, passing rules). |
| `intermittent short term stops` / `…stops and closure effective` / `…short term closure` | 87 / 81 / 5 | Periodic stops: a flagger or a light holds traffic for a short cycle. |
| `road closed` / `single carriageway closed` | 13 / 1 | Closed: routing avoids the way and the player meets barriers. This is the only case that keeps today's "blocked" behaviour. |
| `detour` (+ `detour length`, `…surface`, `…curves`, `…gross weight limit`, `detour signs`) | 37 | Route around via the graph; show detour signs; the descriptive fields are display only. |
| `contra flow traffic` | 4 | Display only at first (two-way traffic on one carriageway is a complex lane model). |
| `narrow or closed pedestrian and bicyle path` (sic) | 39 | Pedestrians and cyclists avoid or are rerouted from the matched footway or cycleway. |
| `vehicle width/height/length/gross weight limit` | 36 / 5 / 2 / 2 | Applies to NPC trucks and buses by vehicle definition; the taxi always fits. |
| `estimated delay` (+ `during rush hour`) | 13 / 13 | The navigation ETA adds the delay; the phone shows it. |
| `road surface gravel` / `milled` / `paved` | 8 / 1 / 6 | Surface grip and sound (existing surface handling). |
| `open fire heater in use` | 7 | Display only (a warning sign). |

Work types (`workTypes[].type`, such as `buried cables`, `bridge`,
`resurfacing`, `lighting` or `road surface marking`) choose the scenery
props, the sound loop and the phone text. `other` (522) is the most common;
its `description` is Finnish free text.

### Time handling

- A phase is active when the game clock (`calendar.current`, Finnish local
  time) is inside its `timeAndDuration` **and**, if it has `workingHours`,
  inside a listed weekday and time window. Outside working hours, restrictions
  stay in force unless `restrictionsLiftable` is true. Cones and signs
  normally stay overnight.
- **Historical game time:** `from`/`to` return situations active in a past
  window. A one-day window in September 2026 returned 38 roadworks around
  Helsinki, and one in October 2025 returned 7, so older history is thinner.
  Retention is not documented. Cache what was fetched (§7.2) and fall back to
  generated roadworks when the past window is empty.

### Fallback

Live roadworks **replace** the random ones only where they exist and match a
loaded way. Where the area has none (city streets, offline, the setting
off), `create_roadworks()` keeps generating random ones, so city play does
not lose roadworks.

## 5. Traffic messages — `GET /api/traffic-message/v2/traffic-announcements`

These have the same parameters and the same feature shape as roadworks
(`situationType: "traffic announcement"`).

- `trafficAnnouncementType` observed: `general`, `preliminary accident
  report`, `accident report` and `ended`. The API also defines
  `retracted`, and `unconfirmed observation`.
  **`ended` and `retracted` versions close the situation:** remove it, never
  show it as new.
- `features[]` seen over 36 h:
  - "Onnettomuus" (accident), 13;
  - "Tie on suljettu liikenteeltä" (road closed), 5;
  - "Palava ajoneuvo tiellä" (vehicle on fire);
  - "Eläimiä tiellä" (animals on the road);
  - "Rikkoutunut ajoneuvo tiellä" (broken-down vehicle);
  - ferry capacity changes and log-floating interruptions;
  - "Liikenne ruuhkautuu" (congestion).
- Geometry is `MultiLineString`, `LineString` or `Point`. Area announcements
  carry region geometry; use `?includeAreaGeometry=false` on
  `messages/{situationId}` and fetch `area-geometries` only if needed.
- History of one situation: `GET /api/traffic-message/v2/messages/{situationId}/history`.

**Game uses (proposed):**

1. **Phone/radio news**: a "Liikennetiedote" item for situations within N km
   of the player or on the active navigation route. The title is shown
   verbatim in Finnish; other languages are built from `features` names
   through a localization table (fi/en/de).
2. **Routing**: "road closed" and closed-lane features give a cost penalty,
   or block the matched edges, in `TrafficWorld` for the situation's
   lifetime. Navigation reroutes, using the existing graph-revision mechanism.
3. **Staged scene (optional, later)**: on a matched way within the loaded
   area, place a static incident: wreck, hazard lights, police car, cones.
   Reuse the existing crash state and police vehicles; never simulate the
   crash.
4. **Ferry and weight items**: display only.

Weight restrictions (`/weight-restrictions`) and exempted (oversize)
transports (`/exempted-transports`, empty when sampled) are low priority.
Exempted transports could later spawn an escorted wide load on an intercity
road.

## 6. Variable signs — `GET /api/variable-sign/v1/signs`

These are the latest values for each sign over the last 60 days. Use
`?deviceId=` for one sign, `/signs/history?deviceId=` for 7 days of history
(or `effectiveDate=` for an older day), and `/signs/code-descriptions` for
the warning-symbol codes.

### Data model, as observed

Each feature is a `Point` with these properties:

- `id` (for example `VME/TIO020811`);
- `type`: `SPEEDLIMIT` 303, `INFORMATION` 202, `WARNING` 62;
- `displayValue`: the speed for `SPEEDLIMIT` (`120` 114, `100` 121, `80` 38,
  `60` 13, `70` 3, `50` 1, empty 13), or a warning code for the others;
- `roadAddress` ("road section distance", for example `"1 31 4765"`),
  `direction` (`INCREASING` or `DECREASING`, missing on 114),
  `carriageway`;
- `effectDate`, and `reliability` (`NORMAL`, or `MALFUNCTION` on 2);
- `textRows[]`: `screen`, `rowNumber` and `text`; 148 signs have text, with
  1–3 rows and one screen.

Warning codes (`code-descriptions`):

| Code | Meaning | Code | Meaning |
| --- | --- | --- | --- |
| 133 | congestion | 147 | dangerous shoulders |
| 141 | uneven road | 154 | ski track |
| 142 | road works | 155 | elks |
| 143 | loose gravel | 156 | reindeer |
| 144 | slippery road | 165 | traffic lights |
| 183 | crosswind | 189 | other danger |

Text quirks to handle:

- **Mis-encoded text** appears in the data (`ILMA +10 Â°C`). Repair it with a
  latin-1 → utf-8 round trip, guarded so correct text is never altered.
- **Route-number tokens** such as `[tie_3]` and `[tie_45]` appear in
  travel-time rows ("KEHÄ I RING via [tie_3] +0 min"). Render them as the
  road-number shield.
- The image endpoint `/api/variable-sign/v1/images/{text}` renders **digits
  only** (`120` returns an SVG; letters return 400 "Invalid symbol"), so
  Godot draws sign text itself.

### Game behaviour (proposed)

- **Placement:** match each sign to the nearest way within 30 m whose
  heading agrees with `direction`. Draw it at the roadside: a gantry on
  multi-lane roads, a post otherwise. Speed signs use the existing
  speed-limit sign art; text signs use an amber matrix style. Hide signs
  with `reliability: MALFUNCTION`, or show them blank.
- **Legal effect:** a variable speed limit is a binding traffic-control
  device. From the sign onwards, in its direction, the shown limit replaces
  `Way.speed_limit_kmh` for the player (rage meter, cameras) and for NPCs. It
  lasts until the next speed sign (fixed or variable) or the end of the
  matched road; a cap on the length is an open question. Confirm in the
  traffic-law guide before implementing.
- `WARNING` signs: `144` slippery and `183` crosswind could feed warnings to
  the HUD; `155` and `156` elk and reindeer tie into the existing wildlife.
  `INFORMATION` text is display only.
- **History:** for a past game time within 7 days, use `/signs/history`;
  older than that, use only static signs. Never back-fill today's values
  into the past.

## 7. Shared ingestion design (proposed)

### 7.1 One module, opt-in

`src/theroadragetrip/digitraffic_road.py`, enabled by a setting next to the
existing "real-time trains (Digitraffic)" and "FMI weather" toggles, with
`--digitraffic-road/--no-digitraffic-road` on the CLI like
`--historical-weather`. With it off or offline, behaviour is exactly today's.

- **Background thread** (as `weather_history.py` does): never on the
  simulation tick. Results are handed over through a lock-protected
  snapshot that the tick only reads.
- **Bounding box:** the active map area plus a margin, and the intercity
  route corridor while one is active. Re-query when the player leaves the
  box.
- **Rates for this game:** roadworks every 5 min; announcements and signs
  every 2 min; TMS data every 5 min (it changes every 5 min); static
  metadata once per session, cached for a day. That is well under
  Digitraffic's recommendations.
- **Errors:** bounded exponential backoff with a log entry. Repeated 406,
  Deprecation or Sunset responses are logged once per session.

### 7.2 Cache

SQLite under `~/.cache/RoadRageTrip/`, in the same style as the weather and
railway caches:

- situations stored by `(situationId, version)`;
- sign values by `(id, effectDate)`;
- TMS 5-minute rows by `(station, window start)`;
- static metadata by date.

With this cache, historical-mode replays and offline restarts see the same
data. Old rows are pruned by age, for example 30 days for live polls; the
offline profile tables in §9.2 are kept.

### 7.3 Matching to the game map

- Project `[lon, lat]` with the world's existing EPSG:3067 transformer, the
  same one `world_loader` uses for OSM.
- **Lines** (roadworks and announcements): sample every 10 m. For each
  sample, take the nearest drivable surface way within 15 m whose segment
  heading is within 30° of the line, and assign start and end metres along
  that way. Reject a match covering less than 60 % of samples, and log it in
  the F12 debug snapshot.
- **Points** (signs, stations, point roadworks): take the nearest way within
  30 m; for signs, also match the heading to `direction`.
- **Road numbers:** keep the OSM `ref` tag on `Way` (for example `ref=4` or
  `ref=E8;21`). `osm/build.py` already reads it for unnamed roads' display
  names; it needs a field and a world-cache format bump. Where a candidate's
  `ref` contains the situation's road number, prefer it. This separates the parallel service
  roads that run beside the vt4 motorway. It is optional, but it makes
  matching much more reliable.
- Matching runs when map chunks load (bounded per frame, like the other
  chunk work), never across the whole map at once. Keep map-layer separation:
  only surface ways (`map_level is None`) are matched.

### 7.4 Protocol

The Godot client gets only what it draws:

- **Roadworks:** zone geometry, props and lights, through the existing
  `map_chunks` `"roadworks"` kind, extended with restriction kinds.
- **Signs:** a new chunk kind `"variable_signs"` (position, heading, type,
  display value, text rows), refreshed when values change.
- **News:** text items through the existing phone and notification channels.

No client ever sends Digitraffic data to the server.

## 8. Optional extensions found during inspection

| Data | Endpoint | Possible use |
| --- | --- | --- |
| Road surface state and friction | `weather/v2/stations/data` (530 stations; sensors `KITKA1`, `TIENPINNAN_TILA_1`, `TIE_1` surface temperature, `JÄÄN_MÄÄRÄ1` ice amount, `VAROITUS_1`) | Calibrate the existing grip and ice model near a station, instead of estimating from air temperature. |
| Maintenance tracking | `maintenance/v1/tracking/routes/latest` (bounding box, tasks; 0 features in Oulu on 2026-10-26, no snow) | Place snowploughs and gritters where real ones drove (the game has ploughs). |
| Counting sites | `counting-site/v2/values` (pedestrians and cyclists, daily, from the day before) | Calibrate cyclist and pedestrian shares by city. |

## 9. Traffic measurement system (TMS) — `/api/tms/v1/…`

### 9.1 Data model, as observed

**`/stations`** (static) gives a `Point` per station with:

- `tmsNumber` and `name`, for example `vt4_Oulu_Kaakkuri_LML`;
- `collectionStatus` (`GATHERING`, `REMOVED_TEMPORARILY`, …) and `state`
  (`OK` 89, with many `null`).

**`/stations/{id}`** adds:

- `direction1Municipality` and `direction2Municipality`, for example Kemi
  and Jyväskylä, which say which way each direction runs;
- `freeFlowSpeed1/2` (km/h, for example 95);
- `roadAddress` (`roadNumber`, `roadSection`,
  `distanceFromRoadSectionStart`, `carriageway`, `side`);
- `purpose`.

**`/stations/sensor-constants`** gives `VVAPAAS1/2` (free-flow speed) and
`MS1/2` (capacity, vehicles per hour per lane per direction, for example
4000).

**`/stations/data`** gives the current `sensorValues[]` per station: `name`,
`value`, `unit`, `measuredTime`, and `timeWindowStart`/`End` for fixed
windows. Of 521 stations, about 490 report:

| Sensor | Meaning |
| --- | --- |
| `OHITUKSET_60MIN_KIINTEA_SUUNTA1/2` | vehicles per hour, fixed 60-minute window |
| `OHITUKSET_5MIN_LIUKUVA_SUUNTA1/2` | vehicles per hour, sliding 5-minute window |
| `KESKINOPEUS_5MIN_LIUKUVA_SUUNTA1/2`, `…_60MIN_KIINTEA_…` | mean speed in km/h |
| `…_VVAPAAS1/2` (unit `***`) | mean speed as a **percentage of free-flow speed** (0–10 stationary … 100+ free) |
| `…_MS1/2` (unit `***`) | volume as a **percentage of capacity** `MS1/2` |
| `OHITUKSET_5MIN_KIINTEA_KAISTA1…n`, `LIUKUVA_NOPEUS_KAISTA_n` | per lane, at some stations |

`KIINTEA` is a fixed window; `LIUKUVA` is a sliding window of the last n
minutes. Example, Kaakkuri (vt4) at 18:10 on 2026-10-26, direction 1:
948 vehicles/h over 5 min, mean 97 km/h, 102 % of free flow, 24 % of
capacity.

**Raw per-vehicle history:**
`/history/raw/lamraw_{tmsNumber}_{yy}_{dayOfYear}.csv` is one semicolon row
per passing vehicle; one sampled station-day had 6,823 rows. The columns
(Digitraffic TMS documentation) are:

1. TMS point id
2. year
3. ordinal date
4. hour
5. minute
6. second
7. 1/100 second
8. length (m)
9. lane
10. direction
11. vehicle class
12. speed (km/h)
13. faulty (0 valid, 1 faulty)
14. total time (technical)
15. time interval (technical)
16. queue start (technical)

Vehicle classes are:

| Class | Vehicle |
| --- | --- |
| 1 | car or van |
| 2 | truck without trailer |
| 3 | bus |
| 4 | semi-trailer truck |
| 5 | truck with trailer |
| 6 | car with trailer |
| 7 | car with trailer or camper |
| 8 | motorcycle or moped |
| 9 | high-capacity truck |

The documentation also treats classes above 7 as faulty, which contradicts
classes 8 and 9. Treat 8 and 9 as valid only when `faulty` is 0.

### 9.2 Game uses (proposed)

1. **Offline calibration (first, safest).** A tool,
   `tools/build_traffic_profiles.py`, downloads raw history for the stations
   in the game's cities, for example 4 weeks per station. It builds
   - hour × weekday volume profiles per road class (motorway, trunk,
     primary), normalised to the daily total;
   - a vehicle-class mix per road class and hour;
   - mean speed relative to the posted limit.

   The result is a small committed JSON asset. `population.hour_demand` /
   `THROUGH_TRAFFIC` and the NPC vehicle-type distribution are then fitted
   to it, replacing guessed curves with measured ones without any network
   access at runtime.
2. **Live congestion near stations (optional).** For a station within the
   loaded area, its 5-minute `VVAPAAS` percentage scales NPC target speed on
   the matched way and direction. For example, 40 % of free flow means NPCs
   cruise at 40 % of the limit and queue. The `MS` percentage scales the
   moving-traffic target on that road, inside the existing population caps,
   never above `max_count`. Smooth both over minutes so traffic never
   jumps.
3. **Intercity ETA.** Station speeds along an intercity route adjust the
   navigation ETA and the fare estimate on congested segments.
4. **Historical mode.** Live `/stations/data` is "now" only. For a past game
   time, use the cached rows if present, otherwise the offline profiles. The
   raw CSV of that day is too large to fetch per session. Never apply
   today's live values to a past date.

## 10. Proposed implementation order

Each phase is its own commits with tests. All phases are opt-in and keep
today's behaviour when the data is missing.

| Phase | Scope | Acceptance |
| --- | --- | --- |
| 0 | `digitraffic_road.py` client: gzip, `Digitraffic-User`, backoff, Deprecation/Sunset logging, SQLite cache, setting and CLI flag. `Way.ref` from OSM. | Unit tests with recorded fixtures (no network in tests); 406 and timeout handled; cache round trip; flag off means no requests. |
| 1 | Roadworks: fetch, phase/time evaluation, line matching, restriction → effect for the player (speed limit, lane closure, road closed, temporary lights). Random roadworks remain the fallback. | The Kuusamontie fixture: a 30 km/h zone 600 m long on the matched vt20 way, active only Wednesday 10–14 local, and a closed lane drawn and collidable. F12 snapshot lists the matches. Godot screenshot inspected. |
| 2 | NPC handling of roadworks (all of them, random ones too): reduced speed, merging out of a closed lane, alternating one-lane traffic at the lights, avoiding closed roads in routing. | Traffic-law guide scenarios; `traffic-law-reviewer` agent run; no NPC drives through a closed lane in a headless soak test. |
| 3 | Variable signs: matching, drawing, speed-limit override for the player and NPCs, encoding repair, `[tie_N]` shields. | A recorded `SPEEDLIMIT 80` on vt4 changes the rage threshold and camera limit downstream; a `MALFUNCTION` sign has no effect; screenshot inspected. |
| 4 | Traffic messages: news on the phone, route penalties for closures, `ended`/`retracted` handling, fi/en/de texts. | A closed road reroutes navigation; an `ended` version removes the item; English UI shows no Finnish free text except names. |
| 5 | TMS offline profiles tool and committed asset; demand model and vehicle mix fitted to it. | Profile asset reproducible from the tool; existing population tests pass; benchmark of `set_local_density` unchanged. |
| 6 | Optional: live TMS congestion, road-weather grip, maintenance ploughs. | Bounded per-frame cost measured; caps unchanged. |

## 11. Open questions

1. Does a variable speed limit end at the next fixed sign only, or also at a
   junction? This must be settled in the traffic-law guide before phase 3.
2. Should live roadworks replace the random ones within the same area, or
   add to them? This document proposes "replace where present".
3. Staged accident scenes (§5.3) put police and wreck props on real crash
   locations in near real time. Is that acceptable in tone, or should
   announcements be news only?
4. Matching quality without `ref` in dense junction areas is unmeasured.
   Phase 0 should report match rates for Helsinki, Tampere and Oulu before
   committing to the thresholds above.
