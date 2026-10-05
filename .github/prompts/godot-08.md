# Godot-07 Hotfix: Vehicle Jitter and Stuck Throttle

## Objective

Investigate and fix two gameplay/input regressions observed when manually driving the current Godot build:

1. The player's taxi/car visibly vibrates or jitters on screen while driving.
2. The vehicle continues driving after the player releases the accelerator.

These are functional regressions and must be fixed before starting the next parity phase.

Do not assume the cause. Trace the complete input → client state → server/simulation → rendered vehicle path first.

## Current state

The latest Godot work is already pushed.

Godot-07 consists of commits:

* `16fc87f` through `6ae6837`
* branch: `release/v0.16.0g-alpha`

The parity audit currently reports:

* 30/108 rows complete
* 18 partial
* 52 missing
* all existing tests passing

Do not reset, rebase, or discard this work.

Do not create Git tags.

Pushing commits is allowed.

## Bug 1: vehicle visual jitter

Reproduce the problem in the windowed Godot client.

Determine whether the jitter originates from:

* conflicting local prediction and server-authoritative position updates
* interpolation between server snapshots
* interpolation using inconsistent timestamps
* physics-frame vs render-frame updates
* vehicle transform being written by multiple systems
* camera following a different position than the vehicle
* integer/pixel rounding
* coordinate conversion
* velocity being applied twice
* stale network state being rendered after a newer state
* duplicate vehicle updates
* input/state synchronization
* any recent Godot-07 rendering change

Do not simply add smoothing until the actual source is understood.

### Investigation requirements

Trace:

```text
keyboard/controller input
        ↓
Godot input state
        ↓
outgoing control command
        ↓
server/simulation vehicle state
        ↓
incoming state update
        ↓
Godot vehicle state
        ↓
vehicle transform
        ↓
camera transform
        ↓
render
```

Identify which component owns the authoritative vehicle position.

Check whether the vehicle position is updated from more than one source during a frame.

Check both `_process()` and `_physics_process()` paths and any network polling/update callbacks.

If interpolation is used, verify that:

* interpolation never moves backwards
* old snapshots cannot overwrite newer snapshots
* interpolation timestamps are monotonic
* teleport/large corrections are handled separately
* interpolation does not fight direct transform assignment

Do not reduce the problem by simply lowering the interpolation factor.

## Bug 2: accelerator remains active after release

Reproduce this reliably.

Determine exactly where the accelerator state becomes stuck.

Check:

* Godot input handling
* key-down/key-up events
* continuous input polling
* focus/window activation handling
* command serialization
* command transmission
* server-side input state
* client-side prediction
* command/state acknowledgement
* input timeout/reset behavior

The expected behavior is:

```text
press accelerator
    → vehicle accelerates

release accelerator
    → accelerator becomes inactive
    → subsequent commands/state reflect inactive accelerator
    → vehicle no longer receives continued throttle input
```

Do not fix this by applying an arbitrary timeout unless the architecture already uses an intentional input timeout.

If the problem is caused by a missing key-release event, fix the input-state ownership rather than adding a workaround.

Also test:

* normal press/release
* repeated press/release
* releasing after holding for several seconds
* changing direction immediately after release
* braking after acceleration
* releasing the key while the window loses focus
* pressing and releasing while the game is receiving network updates

If the game intentionally allows the vehicle to coast after throttle release, distinguish that from the bug. The problem is that the vehicle currently appears to continue receiving acceleration input.

## Regression investigation

Compare the current implementation against the last known-good driving behavior.

Use git history to identify changes affecting:

* Godot input
* vehicle control
* network state
* vehicle transforms
* camera
* rendering/update loops

Do not assume the regression was introduced by the latest commit merely because it is recent.

Use `git diff` and targeted historical inspection as needed.

## Tests

Add deterministic regression tests for both bugs where practical.

At minimum, test the logical input state:

* accelerator pressed → active
* accelerator released → inactive
* release does not leave stale accelerator state

For the jitter issue, add a regression test around the underlying state/update logic if the root cause can be represented deterministically.

Do not create a fragile screenshot-based test merely to prove that something "looks stable".

Preserve the existing test suite.

Run:

```text
make godot-test
make godot-selftest
make audio-check
```

Also run the relevant Python tests if the fix touches shared protocol/server behavior.

The known three BIN map-format failures remain expected and should not be treated as regressions.

## Manual verification

After the automated tests pass, run the game windowed and manually verify:

1. Drive forward continuously.
2. Release the accelerator.
3. Confirm the vehicle no longer receives throttle input.
4. Accelerate and brake repeatedly.
5. Turn while accelerating.
6. Release accelerator while turning.
7. Observe the vehicle at different speeds.
8. Observe the vehicle while the camera follows it.
9. Verify that the vehicle no longer visibly vibrates/jitters.
10. Verify that the fix remains stable while network updates arrive.

If possible, record a short before/after observation or quantitative measurement of the vehicle position over consecutive frames.

## Important scope restriction

Do not use this task to implement new rendering parity.

Do not implement:

* day/night
* traffic lights
* taxi stands
* fuel stations
* roadworks
* road names
* speed limits
* meet-and-greet UI
* booked-passenger arrow
* route planning migration
* rain/snow parity
* street lights
* additional map protocol data

Those belong to later phases.

This task is strictly about restoring correct driving behavior and eliminating the observed visual vehicle jitter.

## Documentation

If the root cause is architectural or affects the Godot client update model, document it briefly in the relevant architecture/migration documentation.

Do not change parity counts unless the fix actually changes a parity row.

## Completion criteria

The task is complete only when:

* the accelerator reliably stops being active after release
* the vehicle no longer exhibits the observed visual jitter
* the underlying causes have been identified, not merely masked
* regression tests exist for the relevant logic
* all existing Godot tests pass
* Godot self-test passes with zero underruns
* audio-check remains clean
* no unrelated parity work has been introduced

At the end, report:

1. root cause of the jitter
2. root cause of the stuck accelerator
3. files changed
4. tests added
5. test results
6. manual verification results
7. commits created
8. whether the commits were pushed

Do not create a Git tag.
