# Calendar and seasons implementation prompt

Implement a real in-game calendar and four visual/physical seasons for Road Rage Trip.

## Product behaviour

- In **Keikkakuski / Gig driver** mode, show a date-and-time picker after mode selection and before gameplay. The player may choose a valid Gregorian date from today back through the same calendar date one year earlier, plus any minute of day, with keyboard and mouse controls. Draw navigation arrows as geometry rather than relying on font glyph coverage. Career mode keeps its curated/default start unless explicitly redesigned later.
- The selected local date and time are the single source of truth for the session. Game-time acceleration must advance both time and date across midnight; leap years and month lengths must be correct.
- Display the date as well as `HH:MM` in the HUD. Keep existing debug clock controls working, including crossing day boundaries.
- Display a deterministic typical Finnish temperature beside the clock. It must vary with day of year, local time and latitude (northern Finland is colder than southern Finland).
- Keep the latitude-aware Finnish thermal-season classification for named seasons, weather and physical rules. A thermal transition takes effect only after seven consecutive modeled daily mean temperatures remain beyond its threshold: spring above 0 °C, summer above +10 °C, autumn below +10 °C, and winter below 0 °C. Until the seventh qualifying day, keep the preceding season.
- Visual nature must transition continuously rather than waiting for the strict thermal boundary. Derive deterministic winter/spring/summer/autumn appearance weights from the modeled daily mean, annual warming/cooling direction and latitude. Blend vegetation, tree crowns, snow cover and water ice with those weights. Northern locations must enter autumn colors earlier and retain spring snow later; for example, Oulu on 23 September should already look predominantly autumnal even if its formal thermal season is still summer.
- Solar position, sunrise/sunset, lighting and street lights must use the current calendar date rather than a hard-coded date. Finland's UTC offset/DST is a follow-up unless implemented consistently.
- Winter: snow-covered grass/natural scenery and tree crowns; slippery roads; all lakes, rivers and waterways have an opaque white frozen surface. Snow and ice cover must be visual even when precipitation is clear.
- Spring: lighter vegetation than summer, deterministic occasional residual snow piles, and sparse ice plates on otherwise open water.
- Summer: preserve the current appearance and grip.
- Autumn: yellow, ochre and brown vegetation/tree crowns.
- Dynamic weather remains independent state but is season-compatible: autumn and winter weather periods have a 50% chance of precipitation and last between zero and 24 game-hours. Falling precipitation follows the current air temperature independently of ground cover: snow at or below +1 °C, slush above +1 °C but below +5 °C, and rain at +5 °C or warmer. A later increment may implement snow accumulation/melting; do not conflate permanent winter ground cover with active snowfall.
- When a rain period begins, independently choose whether it is a thunderstorm: 50% in summer, 10% in spring and autumn, and 0% in winter. Thunderstorms produce intermittent lightning flashes and audible thunder; snow and slush never thunder.

## Architecture

- Add a small calendar/season domain module with a `Season` enum, latitude-aware thermal-season lookup, and an advancing game datetime. It must not import Pygame or rendering code.
- Pass explicit season/date state into simulation and rendering boundaries. Avoid separate month checks scattered across modules.
- Include both the named season and continuous appearance weights in static render-cache keys so changing color/snow/ice blends cannot reuse stale scenery, trees, grass or water.
- Keep seasonal palette transforms deterministic and centralized. Preserve non-vegetation surfaces such as asphalt, construction, paved plazas and water unless a specific seasonal treatment is defined.
- Apply winter road grip through the physics surface model, not by faking rain wetness. Existing ice/snow OSM surfaces must remain at least as slippery as seasonal winter asphalt.
- Protocol/server snapshots eventually need the full ISO datetime and season so remote clients render the authoritative state. Maintain backward compatibility while that is phased in.

## Tests and acceptance criteria

- Unit-test all thermal thresholds, their seven-day persistence, latitude-dependent season differences, leap-day/midnight rollover, and invalid picker dates.
- Test that solar output changes between winter and summer for identical clock time/location.
- Test seasonal palette output: summer unchanged, spring lighter, winter snow-white vegetation, autumn yellow/brown.
- Test gradual visual transitions independently of thermal labels, including autumnal Oulu on 23 September, multi-day spring snow melt, and later snow retention at higher latitude.
- Test cache keys differ by season.
- Test winter asphalt grip is lower than dry summer asphalt and does not exceed explicit snow/ice grip.
- Test gig-driver selection is honored while career/default and headless flows remain usable.
- Run the existing test suite; no regressions in weather wetness, grip, scenery caching, or solar throttling.

## Suggested increments

1. Calendar model, gig-driver picker, HUD date, and date-aware solar calculation.
2. Seasonal scenery/trees/background palettes and cache invalidation.
3. Winter road grip and season-aware weather defaults.
4. Snow piles, precipitation constraints, accumulation/melting, protocol persistence and save/resume support.
