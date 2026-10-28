# Live clock and Digitraffic MQTT

Status: **phases 1 (live clock), 2 (MQTT client), 3a (live road weather) and
3c (live road ice) implemented (2026-10-28)**. Phase 3b (ploughs from
`maintenance-v2`) is not started.

Digitraffic's MQTT feed (`wss://tie.digitraffic.fi:443/mqtt`) is live "now"
data. It only matches the game when game time is the computer's clock, so it
depends on the live clock below. The REST data in
[digitraffic-road-data.md](digitraffic-road-data.md) follows any game time and
stays the source for historical play.

Plan:

1. Live clock (no network).
2. MQTT client on the server: a background thread, a bounded queue drained a
   fixed number of messages per tick, reconnect with backoff, subscriptions
   only for stations near the map. Live messages are never cached or saved.
3. First consumers: `maintenance-v2` (ploughs) and `weather-v2` (road surface).
   `tms-v2` (NPC traffic density) only after a review against
   [the traffic-law guide](finnish-npc-traffic-law.md).

## Phase 1: live clock

Settings → gameplay → "Real-time clock" (`--live-clock`, config
`game.live_clock`, off by default).

- Game time is the computer's clock in Finnish time, read on every tick
  (`server._utc_now`), not integrated from `dt`: no drift, DST included.
- `time_scale` is 1.0 always, also without a fare: no 60x.
- A picked start time or a save's time jumps to now. The launcher skips the
  start-time picker.
- Weather and other dynamics still advance on real `dt`.
- Test: `test_the_live_clock_is_the_computers_clock` (start jump, 1x, the
  repeated autumn hour).

## Phase 2: MQTT client

`digitraffic_mqtt.LiveFeed`, started by the server only when the live clock
and realtime road data are both on (no setting of its own).

- paho-mqtt 2.1 (EPL-2.0 or EDL-1.0, used under EDL-1.0) over
  `wss://tie.digitraffic.fi:443/mqtt`, header
  `Digitraffic-User: RoadRageTrip/live-feed`.
- `connect_async`: startup never waits for the network. paho's thread
  reconnects with 1 s to 5 min backoff and resubscribes on every connect.
- Messages are JSON-decoded on paho's thread and queued, at most 2000 (the
  oldest is dropped and counted). `drain(limit)` hands the tick a bounded
  batch. Nothing is cached or saved.
- `<root>/status` messages give each feed's own last update and are kept out
  of the queue.
- Subscribed so far: `weather-v2/status` and `maintenance-v2/status` only.
  Phase 3 adds the data topics and the tick's drain.
- F12 snapshot `live_feed`: connected, topics, received, queued, dropped,
  last message age, each feed's age.

Checked on the live broker on 2026-10-28: connected, both status feeds
arrived (ages 11 s and 43 s), and the calendar matched the system clock at
1x. In a 40 s probe, `maintenance-v2/routes/state-roads` and one weather
station sent nothing, so consumers must not expect steady traffic.

## Phase 3a: live road weather

`digitraffic_mqtt.RoadWeather`, fed by the server's tick
(`LIVE_FEED_PER_TICK` = 200 messages at most).

Why phase 2 saw no weather data: it subscribed to status topics only, and
station 1001 (the first probe's choice) is silent; its `dataUpdatedTime`
(2025-10) is metadata, not data, so the catalogue cannot tell live stations
from dead ones. The whole `weather-v2/#` stream is about 120 messages/s.

- The station catalogue (`/api/weather/v1/stations`, REST, cached a day) is
  read on a thread. The 6 nearest `GATHERING` stations to the taxi are
  subscribed (`weather-v2/<id>/#`), picked again after 2 km.
- A station sends its sensors only every few minutes, staggered, and the
  broker retains nothing: in a 150 s probe 3 of 6 stations sent nothing.
  So newly picked stations are seeded from `/api/weather/v1/stations/<id>/data`
  (REST, on a thread). Readings merge by time: an older value never replaces
  a newer one.
- Each sensor is taken from the nearest station with a reading under 30 min
  old, so silent stations are skipped.
- `observation()` is a `weather_history.HourlyWeather` (source `observed`)
  with air temperature (sensor 1), wind (16, 18) and precipitation as a WMO
  wawa code: the PWD form (25), else the rain class (22). It replaces FMI's
  hourly observation in `_update_outside` while fresh.
- Road state (27) sets the road wetness: dry 0, moist 0.4, wet, salty or
  slush 1. Frost, snow, ice and a sensor fault leave the game's own wetness.
- F12 snapshot `live_feed.road_weather`: stations, nearest, readings, the
  observation and the road wetness.

Checked live on 2026-10-28 (sample map, Oulu): within 30 s, 287 readings
from the nearest stations; the game took 12.2 °C, dry, wind 2.4 m/s from
197°, and the road went from the start's generated 0.99 wetness to the
station's dry 0.0.

Not yet used: road surface temperature, freezing point and frost/ice
states (the game derives ice from air temperature and wetness).

## Phase 3c: live road ice

`RoadWeather.road_ice()` sets `WeatherSystem.road_ice_override`, which
`road_ice_fraction` (the taxi's grip, `simulation.py` `black_ice`) returns in
place of its own rule (the wetness, whenever the air is below 0 C).

| Road state (sensor 27) | Road ice |
| --- | --- |
| ice (7) | 1.0 |
| frost (5) | 0.5, thin and patchy |
| wet and salty (4), moist and salty (8) | 0: salt keeps it from freezing |
| dry (1) | 0 |
| moist (2), wet (3), slush (9) | its wetness (0.4 or 1.0) when the road surface (sensor 3, TIE_1) is at or below the water's freezing point (sensor 10), else 0; 0 C without a freezing point |
| fault (0), unknown (13 and others), no fresh reading | the game's own rule |

Checked on 2026-10-28: no Finnish station had a frozen road (coldest 0.0 C,
dry); near Oulu the road was dry at 10.9 C and road ice 0.0. Two stations
sent road state 13, which the sensor catalogue does not describe.

The HUD still shows only wetness; ice changes the taxi's grip.
