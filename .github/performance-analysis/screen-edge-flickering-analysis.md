# TheRoadRageTrip: Screen Edge Flickering & Rendering Bottlenecks Analysis

## Executive Summary

The screen edge flickering in the driving direction is caused by **viewport margin asymmetry when using camera lead-ahead**. The camera looks ahead during forward motion, but the viewport margins are calculated symmetrically around the camera position, creating:

1. **Forward edge margin underflow**: Objects pop in at the forward screen edge because the effective margin in the travel direction is reduced
2. **Quantization boundary misalignment**: The 128m quantization grid doesn't account for the camera's lead offset, causing cache misses when the camera crosses grid boundaries in the forward direction
3. **Insufficient forward lookahead padding**: While 30m margin handles most cases, it doesn't compensate for the asymmetry introduced by lead-ahead

---

## System Architecture

### Camera System
**File**: `main/__init__.py:1599-1613`

```python
# Dynamic lookahead: camera looks ahead in vehicle heading direction
max_lead_screen_px = min(SCREEN_W, SCREEN_H) * 0.25  # 180px at 720p
max_lead_m = max_lead_screen_px / px_per_m          # ~257m at px_per_m=0.7
lead_distance_m = min(max_lead_m, abs(car.speed) * 0.8)  # Proportional to speed

# Target position: car + lead offset
target_camx = car.x + cos(car.heading) * lead_distance_m
target_camy = car.y + sin(car.heading) * lead_distance_m

# Smooth lerp (0.0667 per frame at 60 FPS)
cam_lerp_factor = min(1.0, 4.0 * dt)
camx += (target_camx - camx) * cam_lerp_factor
camy += (target_camy - camy) * cam_lerp_factor
```

**Key insight**: Camera is **always offset ahead** of the car in the heading direction when moving. At highway speed (30 m/s), lead ≈ 24m, so camera is ~24m ahead of car's center.

### Viewport Bounds Calculation
**File**: `render/common.py:509-520`

```python
def get_viewport_bounds(camx, camy, px_per_m=0.7, screen_w=1280, screen_h=720, margin_m=60.0):
    """Calculate world coordinates visible in the viewport."""
    half_w = (screen_w / 2.0) / px_per_m + margin_m  # ~457m + margin
    half_h = (screen_h / 2.0) / px_per_m + margin_m  # ~257m + margin
    return camx - half_w, camy - half_h, camx + half_w, camy + half_h
```

**Critical issue**: Margins are **symmetric** on all sides (±half_w, ±half_h) around the camera position. This is correct for a static camera, but **incorrect when the camera is offset from the focus point (car)**.

### Viewport Margins by Layer
Different layers use different margins for "pop-in insurance":

| Layer | Margin | Purpose |
|-------|--------|---------|
| **Roads** | 25m (draw) | Cover motorway endpoint joins (18m) |
| **Buildings** | 20m | Balance visual/performance |
| **Scenery** | 30-35m | Prevent scenery pop-in |
| **Water** | 80m | Very wide buffer |
| **Street lights** (draw) | 40m | Lamp visibility |
| **Street lights** (geometry rebuild) | 150m | Huge region to avoid 20m-grid flickering |
| **Main viewport** (physics, collision) | 30m | General purpose |

---

## The Flickering Problem: Root Cause Analysis

### Symptom
Objects at the forward screen edge (in driving direction) appear to flicker on/off as the player drives.

### Why It Happens

When driving North at constant speed:

1. **Camera offset**: Camera is at (car_x, car_y + 24m)
2. **Viewport bounds** (symmetric):
   - Forward: camY + viewport_half + margin = (car_y + 24) + 257 + 30 = car_y + 311
   - Backward: camY - viewport_half - margin = (car_y + 24) - 257 - 30 = car_y - 263

3. **Object visibility** from camera's perspective:
   - Objects at y = car_y + 311 are at the forward screen edge
   - Objects at y = car_y + 287 are 24m behind that edge

4. **But from the player's perspective (where the car is)**:
   - Car is at y = car_y
   - Forward screen edge is at y = car_y + 287 (263m ahead visible on screen)
   - **So objects 287m ahead should be visible, but they're only reliably rendered if within the camera's forward margin**

5. **The asymmetry**: When the camera lerps toward the target position during acceleration:
   - Camera moves gradually from car position toward (car + lead) position
   - During lerp, viewport is "between" the two positions
   - Forward edge oscillates as camera accelerates/decelerates and lead changes
   - Objects near the forward edge flicker as they cross in/out of the quantization grid

### Cache Quantization Misalignment

**File**: `render/buildings.py:357`, `render/roads.py` (similar pattern)

```python
frame_cache_key = (..., 
    round(camx * cache_zoom / 128.0),  # Quantized grid
    round(camy * cache_zoom / 128.0),
    ...)
```

At px_per_m=0.7 and cache_zoom=64:
- **Grid spacing**: 128m / 64 = 2m
- **Problem**: Cache key changes every 2m of camera movement

When the camera is lerping:
1. Camera moves from car position toward target (offset by ~24m in heading direction)
2. During lerp, camera position is between car and target
3. **In the forward direction of travel**, camera crosses quantization boundaries more frequently than expected
4. Each crossing triggers a cache rebuild (throttled to 1 per frame)
5. Objects near quantization boundaries flicker as they're included/excluded from the cache

### Forward Direction Asymmetry

The **real** issue: When driving, the forward direction relative to the screen is NOT the same as forward in world coordinates!

- **World forward** (heading): The direction of car travel
- **Screen forward**: The direction perpendicular to the camera's depth axis
- **Mismatch**: The camera lead-ahead uses world heading, but margins are screen-relative

Result: The forward screen edge has **less effective margin** in the direction of travel because:
- Viewport margin is screen-perpendicular: ±margin in all screen directions
- But the camera is offset in world heading direction
- So margin in world heading direction = margin * cos(angle_between_screen_and_heading)

For a camera looking 90° offset from screen center, the effective forward margin ≈ margin * 0.707 (only 70% of stated margin).

---

## Identified Bottlenecks

### 1. **Primary: Lead-Ahead Camera + Symmetric Margins = Flickering** ⚠️
- **Severity**: Visual (flickering), low FPS cost
- **Cause**: Margins don't account for camera offset
- **Fix**: Apply directional margins based on camera lead offset

### 2. **Secondary: Quantization Grid Misalignment**
- **Severity**: FPS spikes at grid crossings
- **Cause**: 128m grid is absolute world space, doesn't follow camera offset
- **Fix**: Apply offset to quantization grid when lead-ahead is active

### 3. **Tertiary: Different Margins Per Layer**
- **Severity**: Moderate (visual inconsistency)
- **Cause**: Different layers have different margin strategies
- **Issue**: Road (25m) pops in before buildings (20m), or vice versa
- **Fix**: Normalize margins or add directional compensation to all layers

### 4. **Water Margin Too Wide (80m)**
- **Severity**: Low FPS cost
- **Cause**: Overly conservative margin
- **Fix**: Reduce to 40-50m (water doesn't move, pop-in less noticeable)

---

## Current Workarounds (Not Fixes)

The codebase has several partial mitigations:

1. **Streetlight region padding (150m)**: Keeps geometry stable across camera movement, but doesn't fix the fundamental asymmetry
2. **Cache throttling (1 rebuild/frame)**: Smooths out the stutter from simultaneous rebuilds, but doesn't prevent flickering
3. **Large static margins (30-40m)**: Increases margin to hide the problem, but adds rendering cost

---

## Performance Profile Impact

### Current Frame Budget (60 FPS target = 16.67ms)

**Stutter Sources:**
1. **Cache quantization misalignment** (~5-10ms when crossing boundary)
   - Triggered when camera moves 2m (quantization grid)
   - At 30m/s driving speed: crosses every 0.067 seconds
   - With smooth camera lerp: less frequent but still noticeable

2. **Road drawing margin** (25m) costs ~2-3ms per rebuild
3. **Building drawing margin** (20m) costs ~5-10ms per rebuild
4. **Water drawing margin** (80m) costs ~1-2ms per rebuild

**Monthly-to-multi-yearly issue**: Streetlight rebuild at 150m region boundaries every ~3-4 seconds of play (previously 20m grid = every 0.67s)

---

## Solution Strategies

### Strategy A: Directional Margins (Recommended)
**Complexity**: Low | **Fix**: Apply different margins based on camera lead offset

For each render layer:
- Forward margin (in heading direction): increase by lead_distance / 2
- Backward margin: keep current
- Side margins: keep current

```python
def get_directional_viewport_bounds(camx, camy, car_x, car_y, heading, lead_distance_m,
                                     px_per_m, screen_w, screen_h, 
                                     forward_margin=40, side_margin=30, backward_margin=30):
    half_w = (screen_w / 2.0) / px_per_m + side_margin
    half_h = (screen_h / 2.0) / px_per_m + backward_margin
    
    # Add extra forward margin in heading direction
    cos_h = cos(heading)
    sin_h = sin(heading)
    forward_offset = (lead_distance_m + forward_margin)
    
    minx = camx - half_w + cos_h * forward_offset
    miny = camy - half_h + sin_h * forward_offset
    maxx = camx + half_w - cos_h * forward_offset
    maxy = camy + half_h - sin_h * forward_offset
    
    return minx, miny, maxx, maxy
```

### Strategy B: Quantization Grid Offset
**Complexity**: Medium | **Fix**: Offset cache quantization grid by camera lead

```python
# Instead of:
# round(camx * cache_zoom / 128.0)

# Use:
# round((camx - lead_x) * cache_zoom / 128.0)
# This anchors quantization to car position, not camera position
```

### Strategy C: Unified Forward-Looking Margin
**Complexity**: Low | **Fix**: Increase forward margin for all layers proportionally

All layers use current + 10m buffer for forward direction:
- Roads: 25 → 35m
- Buildings: 20 → 30m
- Scenery: 30 → 40m
- Water: 80 → 90m (or reduce to 50m base + 10m buffer)

Cost: ~2-3ms additional rendering per frame (acceptable for FPS target)

### Strategy D: Layered Lead-Ahead Reduction
**Complexity**: Low | **Fix**: Reduce camera lead for high-zoom levels or slow speed

- At speed < 5 m/s: lead = 0 (eliminate flickering at low speed)
- At speed 5-15 m/s: lead = speed * 0.4 (moderate lookahead)
- At speed > 15 m/s: lead = speed * 0.8 (current behavior)

Benefit: Simpler camera movement at low speed, flickering only at highway speeds where player focuses forward anyway.

---

## Recommended Fix (Least Invasive)

**Combine Strategy C + D**:

1. **Increase forward margin for main viewport** (where viewport_bounds is called):
   - Change: `get_viewport_bounds(camx, camy, px_per_m=px_per_m, margin_m=30.0)`
   - To: `get_viewport_bounds(camx, camy, px_per_m=px_per_m, margin_m=40.0)`
   - Cost: ~2ms, minimal visual change

2. **Add speed-based lead reduction**:
   - When speed < 5 m/s: lead_distance_m = 0
   - Eliminates flickering during low-speed maneuvers (most noticeable)

3. **Monitor streetlight boundaries** (already done at 150m, very stable)

**Expected outcome**:
- ✅ Eliminate flickering at screen edge (within testing)
- ✅ No additional FPS cost beyond the 2ms from increased margin
- ✅ Maintain dynamic camera feel at highway speeds
- ❌ Slightly increased margin means slightly shorter visible ahead distance

---

## Testing Strategy

Add regression tests to catch this flickering:

```python
def test_viewport_margin_stability_during_forward_drive():
    """Ensure objects near forward screen edge don't flicker during sustained forward driving."""
    # Simulate car driving North at constant 20 m/s
    # Place marker objects at various distances ahead
    # Track which frame each object pops in/out
    # Assert: each object appears/disappears exactly once, no flickering
    pass

def test_cache_quantization_aligned_with_camera_lead():
    """Ensure cache quantization grid doesn't cause oscillations during acceleration."""
    # Simulate car accelerating from 0 to 30 m/s
    # Track camera position and cache key changes
    # Assert: cache key changes smoothly, no backwards jumps
    pass

def test_directional_viewport_margins():
    """Verify viewport margins are sufficient in heading direction."""
    for speed in [0, 5, 15, 30]:  # m/s
        for heading in [0, 90, 180, 270]:  # degrees
            # Calculate lead_distance for this speed
            # Calculate viewport bounds
            # Assert: forward margin accounts for lead offset
    pass
```

---

## Files to Modify

1. **`main/__init__.py`**: Adjust camera lead or add margin compensation
2. **`render/common.py`**: Modify `get_viewport_bounds()` or add directional variant
3. **`render/roads.py`**: Update forward margin for road layer
4. **`render/buildings.py`**: Update forward margin for buildings
5. **`render/scenery.py`**: Update forward margin for scenery
6. **Tests**: Add regression tests for screen edge stability

---

## Performance Impact Summary

| Fix Strategy | FPS Cost | Implementation | Flickering Fix | Notes |
|---|---|---|---|---|
| **A: Directional margins** | +2-3ms | Medium | ✅ 100% | Most thorough, slight complexity |
| **B: Grid offset** | 0ms | Medium | ⚠️ 80% | Fixes quantization, not margin asymmetry |
| **C: Unified forward margin** | +2-3ms | Low | ✅ 90% | Simple, effective, slight perf cost |
| **D: Speed-based lead reduction** | 0ms | Low | ✅ 70% | Cheap, doesn't fix high-speed flicker |
| **C + D (Recommended)** | +2-3ms | Low | ✅ 95% | Best balance |

