# Responsive gameplay HUD corrections

## Goal
Fix VQA-035–037: keep the fare meter, status, fuel instruction and lower control hint readable at 800×600, while preserving the normal 1280×720 HUD.

## Files to change
- `godot/hud.gd`: correct default meter placement and constrain/wrap hint/notice text using available viewport space.
- `godot/tests/hud_responsive_layout.gd` and `godot/tests/manifest.txt`: focused layout regression checks with an unsaved production HUD.
- `tools/visual_scenarios.json`: named real-map HUD cases at both required resolutions; preserve existing shared edits.
- `godot/visual_test.gd` / `tools/visual_test.py`: only minimal scenario setup/readiness support needed to show the exact HUD branches and requested viewport size.
- `docs/visual-quality-corrections.md`: link VQA-035–037 to corrected screenshots, passing readiness and verification; preserve original audit evidence.

## Behaviour / acceptance criteria
1. At 800×600 and 1280×720 with default unsaved layout, a visible live fare meter and its information line stay wholly on screen and do not intersect the drawn score/money, clock or weather rectangles. Use actual scaled rectangles after layout settles.
2. Fix the default placement once in the HUD layout path. Continue using `HudLayout.place` and existing panel identities; retain meter dragging/scaling and status dragging/scaling. Existing explicit offsets/scales must not be cleared, migrated or saved by this fix.
3. In the fuel-stop state (`fuel_station_price_cents` present, engine on, nonzero speed), the entire localized instruction is readable inside the viewport with horizontal margins. Wrap as needed; do not truncate, remove words or shrink the font to hide overflow. Returning to a short notice must restore its natural dimensions.
4. House-door, home-door and building-interaction control hints stay wholly on screen and above or otherwise clear of OpenStreetMap attribution. Attribution stays visible. Wrapped hints must not overlap that credit; empty/hidden hint and notice-priority behaviour remain correct.
5. Repeated `show_state` calls and resize 1280×720→800×600→1280×720 settle to valid rectangles without retained oversized widths/heights or progressive movement. Check English, Finnish and German text using existing translations.
6. Keep current font sizes, colors, borders, text contents, data-source notice timing and notice priority. The default 1280×720 positions remain visually consistent except where avoiding an actual collision requires movement.
7. Render named scenarios `vqa_hud_fare_800`, `vqa_hud_fuel_stop_800`, `vqa_hud_house_hint_800` and corresponding `_1280` cases. Reuse a sourced existing city pose and weather; a client-only display fixture may supply the exact HUD state without sending fabricated simulation commands.
8. Capture only after normal map/weather/camera readiness and HUD-specific readiness: exact expected text/state visible, requested viewport size, layout settled, relevant rectangles on screen/nonintersecting. Inspect every screenshot and retain `result.json`; a generic gameplay image without the affected branch does not count.
9. Validate parsing and focused tests before independent tester review. Ship this as one HUD-layout commit with spec, code, tests and correction evidence; stage only owned changes.

## Tests to add
- `godot/tests/hud_responsive_layout.gd::test_live_fare_status_bounds`: instantiate the production HUD at both sizes and assert scaled meter/status bounds do not intersect; fails on VQA-035.
- `godot/tests/hud_responsive_layout.gd::test_fuel_notice_wrap_and_reset`: long fuel instruction fits for en/fi/de, then short/hidden notice resets dimensions; fails on VQA-036 and retained-wrap regressions.
- `godot/tests/hud_responsive_layout.gd::test_control_hint_credit_clearance`: house/home/building hints fit and clear the attribution for en/fi/de; fails on VQA-037.
- `godot/tests/hud_responsive_layout.gd::test_resize_and_custom_layout_preserved`: repeat state/size changes, retain explicit meter/status offset/scale values and existing panel registration; use `HudLayout.new(false)` so no player file is touched.

## Out of scope
VQA-034 indoor hint, vehicle/prop geometry, snowfall, new HUD customization options, changing translations or game rules, full HUD redesign, new simulation fixtures, and unrelated worktree edits.
