# Phone messages and calls (plan, not implemented)

Status: **plan only** (2026-10-16). Branch `release/0.17.0alpha`.

## Today

The phone has two modes, both driven by the server's `phone.busy`
(`TaxiManager.has_job()`):

- **Free:** ride offers and Ennakkotilaus requests; accept or decline them.
- **A job on** (a fare, or an accepted pre-booking not yet finished):
  navigation only. Nothing can be accepted, so nothing is queued.

This plan adds a third kind of content that arrives in both modes: SMS
messages and phone calls. They are flavour and pressure, not a second job
system.

## The idea

The taxi driver's phone never stays quiet. Most of what arrives is annoying,
some of it is useful, and a few messages are pure Finnish everyday absurdity.
The phone is one more thing that raises the driver's blood pressure. Ignoring
it is often the right call, but not always.

## Senders

Each sender has a tone, how often they write, and what answering or ignoring
does.

| Sender | Example (fi / en) | Effect |
| --- | --- | --- |
| **Dispatcher** ("Taksikeskus") | "Missä olet? Asiakas odottaa jo 4 min." / "Where are you? The client has waited 4 min." | Only during a pickup that is running late. Rage +. Ignoring it: nothing, it just nags again. |
| **The passenger you are fetching** | "Oon se punanen takki pysäkillä" / "I'm the red coat at the stop" | Useful: a hint to the pickup point. Pre-booked train passengers: "Juna myöhässä 5 min" (when the timetable says so). |
| **Your current passenger** (from the back seat) | "Voisitko ajaa vähän hitaammin" / "Could you drive a bit slower" | Their happiness: obey (drive under the limit for 20 s) for a small tip bonus. |
| **The boss / car owner** | "Muista tankata ennen vuoron loppua." / "Fill up before the shift ends." | Career: a small score bonus if done; a reminder only. |
| **Authorities and bills** | "Pysäköintivirhemaksu 80 €…", "Nopeusvalvontakamera: …" | Tied to real game events: a speed camera hit sends the fine as an SMS. No new penalties, the existing one is just told this way. |
| **Family** | "Ostatko maitoa kotimatkalla?" / "Can you buy milk on the way home?" | Flavour. Answering with a canned reply while stopped: rage −. |
| **Spam** | "Onneksi olkoon! Olet voittanut…" / "Congratulations! You've won…" | Rage + when opened. Deleting it is satisfying: rage −, a little. |
| **Other drivers** (competitor taxis) | "Kiitti siitä keikasta 😏" / "Thanks for that fare 😏" | When a competitor takes an offer you declined or let expire. Rage +. |
| **Weather service** | "Liukkausvaroitus Oulu klo 18–24" / "Slippery-roads warning Oulu 18–24" | From the real or generated weather (FMI or the generator); a useful warning. |

## Calls

- A call rings (ringtone loop), with the caller's name on the phone.
- **Answer** (a key, say `Y`) or **decline** (`X`, as today). Not answering
  within 15 s is a missed call, and some callers then send an SMS.
- An answered call plays a short voice line (TTS, as the chatter already uses)
  and shows a subtitle. Who calls:
  - **The dispatcher** about a late pickup.
  - **A pre-booked client** whose train has arrived: "Olen tolpalla, missä
    olet?" / "I'm at the stand, where are you?"
  - **The boss.**
  - **Wrong numbers**, rarely: "Onko siellä pizzeria?" / "Is that the pizzeria?"
- **Passenger in the car:** answering while a passenger rides costs a little
  happiness. Declining the boss costs a little career score.

## Driving and the phone (game policy)

Law: § 98 forbids using a handheld phone while driving
(docs/finnish-npc-traffic-law.md); the player's taxi follows the same rule.

- **Reading an SMS** opens it only when the taxi is stopped. While moving, the
  phone shows "Uusi viesti – lue pysähdyttyäsi" / "New message – read when
  stopped".
- **Calls are hands-free:** answering is allowed while driving.
- **Rage-taxi twist:** an option to read it anyway while moving. That costs
  passenger happiness, and a speed camera within range also "catches" the
  phone use as its own fine.

## Pacing and rules

- **Server-authoritative:** `phone_messages.py` decides what arrives. State
  carries `phone.messages` (unread count, the last few messages), plus
  `phone.call` (ringing, or in progress) and events (`sms_received`,
  `call_ringing`, `call_ended`).
- **Rate:**
  - Ordinary messages at most one per 2–4 game minutes, calls at most one per
    10 game minutes.
  - Event-driven ones come right away, rate-limited per sender: dispatcher on a
    late pickup, speed camera fine, competitor took your fare, train late.
- **Never during:**
  - the meet & greet prompt;
  - the first 5 s after a collision;
  - the start sign;
  - the city summary;
  - a ringing call already on.
- **Bounded:** at most 20 messages kept; the oldest go.
- **Rage meter:** effects go through existing rage power, passenger happiness
  and the career score, with small values (±0.05 rage), so they nudge the
  player and never decide the game.
- **Localization:** every message in Finnish and English; the name pools are
  the existing resident names.

## Client (Godot)

- **Phone UI:**
  - An "SMS" tab beside the offers and the navigation, with an unread badge on
    the closed phone (the HUD corner).
  - A message list; Enter opens a message, `X` deletes it, `1`–`3` send canned
    replies ("Tulossa" / "On my way", "Ok", "Ei käy" / "Can't").
- **Call screen:** caller name, answer and decline, a call timer; the subtitle
  bar for the voice line.
- **Sounds:**
  - Generated with ai-audio-studio (`tools/generate_audio.sh`): `ui.sms_received`
    (a short buzz, two variations) and `ui.ringtone` (a loop, two).
  - Voices with Chatterbox in ai-audio-studio, as `sounds/<speaker>_chatter/`
    already does: a dispatcher voice and caller lines.

## Phases

1. **SMS only, event-driven:**
   - speed-camera fine;
   - dispatcher on a late pickup;
   - competitor took your fare;
   - pre-booked train late.

   Phone tab, unread badge, read only when stopped, sound. Tests: rate limits,
   "never during", event-to-message.
2. **Random flavour SMS:** family, spam, boss, weather, plus canned replies and
   their small rage and happiness effects.
3. **Calls:** ringtone, answer and decline, hands-free voice lines with
   subtitles, missed call to SMS, passenger and career effects.
4. **The rage twist:** reading while moving (camera fine, passenger reaction),
   then tune the rates from playtests.

## Open questions

- Should calls and messages exist in career mode only, or in gig mode too?
- Does a deleted spam message really lower rage, or is that too gamey?
- Which key answers a call? `Y` is free today; `Enter` is the phone's accept.
