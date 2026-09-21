# Calendar and seasons implementation prompt

Implement a real in-game calendar and four visual/physical seasons for Road Rage Trip.

## Product behaviour

- In **Keikkakuski / Gig driver** mode, show a date-and-time picker after mode selection and before gameplay. The player must be able to choose any valid Gregorian date and minute of day with keyboard and mouse controls. Career mode keeps its curated/default start unless explicitly redesigned later.
- The selected local date and time are the single source of truth for the session. Game-time acceleration must advance both time and date across midnight; leap years and month lengths must be correct.
- Display the date as well as `HH:MM` in the HUD. Keep existing debug clock controls working, including crossing day boundaries.
- Display a deterministic typical Finnish temperature beside the clock. It must vary with day of year, local time and latitude (northern Finland is colder than southern Finland).
- Provide a reusable thermal-season classification based on the Finnish seven-consecutive-day mean-temperature convention: winter below 0 °C, summer above +10 °C, spring while warming between those thresholds, and autumn while cooling between them. Keep the initial visual three-month seasons separate until a deliberate migration is made.
- Seasons are month based for the first release:
  - winter: December, January, February
  - spring: March, April, May
  - summer: June, July, August
  - autumn: September, October, November
- Solar position, sunrise/sunset, lighting and street lights must use the current calendar date rather than a hard-coded date. Finland's UTC offset/DST is a follow-up unless implemented consistently.
- Winter: snow-covered grass/natural scenery and tree crowns; slippery roads; all lakes, rivers and waterways have an opaque white frozen surface. Snow and ice cover must be visual even when precipitation is clear.
- Spring: lighter vegetation than summer, deterministic occasional residual snow piles, and sparse ice plates on otherwise open water.
- Summer: preserve the current appearance and grip.
- Autumn: yellow, ochre and brown vegetation/tree crowns.
- Dynamic weather remains independent state but is season-compatible: autumn weather periods have a 50% chance of rain and winter periods have a 50% chance of visible falling snow. These periods last between zero and 24 game-hours. A later increment may implement snow accumulation/melting; do not conflate permanent winter ground cover with active snowfall.

## Architecture

- Add a small calendar/season domain module with a `Season` enum, month-to-season mapping, and an advancing game datetime. It must not import Pygame or rendering code.
- Pass explicit season/date state into simulation and rendering boundaries. Avoid separate month checks scattered across modules.
- Include season in static render-cache keys so changing season cannot reuse stale summer scenery or trees.
- Keep seasonal palette transforms deterministic and centralized. Preserve non-vegetation surfaces such as asphalt, construction, paved plazas and water unless a specific seasonal treatment is defined.
- Apply winter road grip through the physics surface model, not by faking rain wetness. Existing ice/snow OSM surfaces must remain at least as slippery as seasonal winter asphalt.
- Protocol/server snapshots eventually need the full ISO datetime and season so remote clients render the authoritative state. Maintain backward compatibility while that is phased in.

## Tests and acceptance criteria

- Unit-test all month boundaries, leap-day/midnight rollover, and invalid picker dates.
- Test that solar output changes between winter and summer for identical clock time/location.
- Test seasonal palette output: summer unchanged, spring lighter, winter snow-white vegetation, autumn yellow/brown.
- Test cache keys differ by season.
- Test winter asphalt grip is lower than dry summer asphalt and does not exceed explicit snow/ice grip.
- Test gig-driver selection is honored while career/default and headless flows remain usable.
- Run the existing test suite; no regressions in weather wetness, grip, scenery caching, or solar throttling.

## Suggested increments

1. Calendar model, gig-driver picker, HUD date, and date-aware solar calculation.
2. Seasonal scenery/trees/background palettes and cache invalidation.
3. Winter road grip and season-aware weather defaults.
4. Snow piles, precipitation constraints, accumulation/melting, protocol persistence and save/resume support.
