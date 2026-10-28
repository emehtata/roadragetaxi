# Live clock and Digitraffic MQTT

Status: **phase 1 (live clock) implemented (2026-10-28)**. Phases 2–3 (the
MQTT client and its first consumers) are not started.

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
