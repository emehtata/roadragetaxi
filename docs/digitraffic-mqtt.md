# Live clock and Digitraffic MQTT

Status: **phases 1 (live clock) and 2 (MQTT client) implemented
(2026-10-28)**. Phase 3 (the first consumers) is not started.

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
