# Performance Analysis & Optimization Reports

This folder contains technical deep-dives into rendering performance, bottlenecks, and optimization opportunities in TheRoadRageTrip.

## Contents

### [bin-loader-v6-illuminated-windows.md](./bin-loader-v6-illuminated-windows.md)

**Status**: Implemented; corrects V4 attribution
**Date**: 2026-09-23
**Focus**: Incremental illuminated-window cache; finds `draw_street_lights` (roads.py) is the real remaining merge-window cost

### [bin-loader-v5-tile-merge.md](./bin-loader-v5-tile-merge.md)

**Status**: Implemented; caveats documented
**Date**: 2026-09-23
**Focus**: Budgeted/incremental `AutoFetchManager` tile-world merge (removes the ~535 ms synchronous merge frame; typical merge frame now ~4 ms)

### [bin-loader-v4-frame-spike-analysis.md](./bin-loader-v4-frame-spike-analysis.md)

**Status**: Completed Analysis
**Date**: 2026-09-23
**Focus**: Decomposing the ~440-560ms worst-case frame left after bin-loader-v3's incremental map-sync work

**Key Findings**:
- Root cause: `AutoFetchManager.integrate_completed_tiles()`'s synchronous tile merge (osm/autofetch.py) - 70% of the measured spike, previously invisible to the profiler entirely
- Secondary: `draw_illuminated_windows()`'s non-incremental window-glow cache (render/buildings.py), silently folded into `render:lighting`
- Also secondary: `spatial_grid_immediate`/`building_grid_immediate` (main.py) - a synchronous rebuild path separate from bin-loader-v3's incremental one for the same grids
- Separate, unrelated finding: `TaxiManager.generate_offers()` → `pick_random_building_point()`/`pick_random_road_point()` (taxi.py) - an unindexed brute-force nearest-road scan, up to ~650ms, recurring independently of tile boundaries
- Profiler bug found and fixed: `render:labels`'s timer wasn't rescoped after the lighting block, so it silently double-counted lighting+weather time
- `map_sync:taxi`/`map_sync:traffic` (flagged as "remaining synchronous work" in bin-loader-v3) are confirmed cheap, one-shot-per-world-load costs - not the cause
- Road rendering remains ruled out

**Includes**:
- Frame-by-frame spike decomposition with exact function/line attribution
- Tile-boundary trigger sequence
- Contribution table for the measured spike frame
- Recommended next optimization target (not implemented, per the task's own scope)

### [screen-edge-flickering-analysis.md](./screen-edge-flickering-analysis.md)

**Status**: Completed Analysis  
**Date**: 2026-09-11  
**Focus**: Screen edge flickering during forward driving & rendering bottlenecks

**Key Findings**:
- Root cause: Viewport margin asymmetry from camera lead-ahead system
- Secondary issue: Cache quantization grid misalignment
- Recommended fix: Increase forward margin (30m → 40m) + reduce lead at low speed
- Estimated FPS impact: +2ms per frame (acceptable)

**Includes**:
- System architecture overview (camera, viewport, margins)
- Root cause analysis with visual examples
- Performance bottleneck catalog
- 4 fix strategies with trade-offs
- Testing recommendations
- Files requiring modification

## How to Use These Reports

1. **For immediate fixes**: Jump to "Recommended Fix" sections
2. **For understanding**: Read "Root Cause Analysis" sections
3. **For planning**: Review "Performance Impact Summary" tables
4. **For implementation**: Check "Files to Modify" sections

## Contributing

When adding new performance analyses:
1. Use the same structure as `screen-edge-flickering-analysis.md`
2. Include root cause analysis (not just symptoms)
3. Provide multiple fix strategies with trade-offs
4. Estimate FPS/memory impact
5. Add testing recommendations
6. Update this README with a link to your analysis

---

**Last Updated**: 2026-09-11  
**Related**: See also `/src/theroadragetrip/render/` for rendering code
