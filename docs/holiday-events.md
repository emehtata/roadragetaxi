# Calendar events

Events use the simulation's Finnish-local calendar, including when starting at
a historical date or crossing midnight. They repeat every year:

- New Year: fireworks from 31 December 18:00 until 1 January 02:00 (exclusive).
- Halloween: pumpkins and candle lanterns in house yards from 31 October 18:00
  until 1 November 06:00 (exclusive).
- Christmas Eve: some adult male pedestrian residents wear Santa's red coat,
  white beard and hat throughout 24 December. Their normal walking, crossing,
  collision and activity rules are unchanged; no extra population is spawned.
- Christmas house lights follow `window_decorations`, the existing season from
  the first Sunday of Advent through 6 January (Epiphany). A short warm light
  string follows one fixed eave of each house: the mapped entrance facade,
  or its longest edge when no entrance is mapped. There are no added yard trees
  or whole-roof outlines. Apartment and commercial styles are excluded.


The server sends `calendar.holidays` and pedestrian `costume`. Static map chunks
carry `holiday_yards`, positions beside tagged houses, checked against building,
road/path and water geometry. These decorative spots do not grant driving or
parking access. Unknown/missing house tags mean no yard decoration at that house.

Godot draws at most 64 visible yard decorations and 12 animated firework sites,
with 24 sparks each. Firework sites cover the whole town (a fixed 80 m grid,
about one cell in three), not only house yards. The yard query runs at most twice per second, scans at most
2048 candidates and is disabled outside event dates. Fireworks are visual only:
no explosions, damage, sounds, roof illumination or traffic changes. Surface
events are hidden underground. An older server without holiday flags shows none.

Exterior Christmas strings query only nearby house footprints, at most 48
houses and 2048 candidates per refresh. Each house contributes at most 48 bulbs;
the bulbs and their faint glow share two drawing batches. In the 3D building
mode, eaves use the same camera projection and height as the buildings. The flat
2D mode uses footprint edges. Light placement stays fixed as the camera moves.
No additional map downloads or cache format changes are needed.
