# Responsive indoor first-person hint

## Goal
Fix VQA-034 so the complete localized indoor control hint remains readable at 640×480 and 1280×720, including its conditional action prompts.

## Files to change
- `godot/home_first_person.gd`: constrain the shared hint to viewport margins, wrap it and let its height grow upward as text or viewport size changes.
- `godot/tests/home_first_person.gd`: extend the existing production-view regression checks for hint bounds, text branches and resizing.
- `tools/visual_scenarios.json`: add named indoor-hint cases at the two audited resolutions with sourced fixture provenance.
- `godot/visual_test.gd` / `tools/visual_test.py`: only minimal scenario setup/readiness support for the existing HomeFirstPerson view; reuse the audit fixture approach where suitable.
- `docs/visual-quality-corrections.md` and `docs/visual-quality-corrections/indoor-hint/`: VQA-034 correction notes, inspected screenshots and readiness results; preserve original audit evidence.

## Behaviour / acceptance criteria
1. At 640×480 and 1280×720, the hint and every rendered text line fit inside the viewport with horizontal margins and the existing bottom clearance. Grow upward for wrapped text; do not clip the last action or extend below the viewport.
2. Retain the complete existing translations, font size, colors, shadow, centered alignment and mouse filtering. Use the current Label/platform wrapping and sizing facilities; do not shorten text, hide prompts or shrink the font to make it fit.
3. Verify English, Finnish and German for the base hint and the longest combination: at the exit, not yet chosen as home, mouse released. Exit, choose-home and resume prompts still appear only under their existing conditions.
4. Repeated process/layout updates and resize 1280×720→640×480→1280×720 settle correctly. Returning from the longest hint to the shortest restores its natural height without retained oversized dimensions or progressive movement.
5. Fix the shared HomeFirstPerson hint once so all generated plans inherit it. Preserve camera/controller, input handling, pause/resume, entry/exit, home selection and exterior HUD behavior; no player settings or saves may be read or written for verification.
6. Add named scenarios `vqa_indoor_hint_640` and `vqa_indoor_hint_1280`, using the actual HomeFirstPerson/HomePlayer3D and an existing recorded real-house plan with documented provenance. A client-only inspection fixture may supply that plan; use no replacement gameplay camera or fabricated server entry command.
7. Readiness must confirm the requested viewport, loaded nonempty interior geometry, active existing indoor camera, player settled on its floor, expected complete localized hint/state, completed draw frames and settled text bounds. If run with the simulation, retain its normal map/weather readiness before indoor setup. Failed readiness produces no accepted screenshot.
8. Render and visually inspect both named cases with the longest hint, retaining screenshot and result metadata (locale, fixture ID, camera, resolution, hint text/line count/bounds, renderer and revision). Check the other locales through the focused production-view regression and render any locale whose layout differs materially.
9. Parse changed scripts, run the focused regression and relevant manifest check, then obtain independent tester PASS. Commit this correction separately from VQA-035–037 and other audit findings; stage only owned changes.

## Tests to add
- `godot/tests/home_first_person.gd::test_hint_wraps_all_prompts`: at both sizes and en/fi/de, assert the exact longest composed text, no hidden lines and full text/Label bounds inside margins; fails on the current fixed-height single-line overflow.
- `godot/tests/home_first_person.gd::test_hint_resize_and_reset`: exercise long→short text and both resize directions after settling; assert correct prompt conditions, readable lines and restored height; catches stale wrapping/height and state regressions.
- Reuse the existing home-plan entry/teardown checks; add no separate controller or generalized layout framework.

## Out of scope
Other audit findings, translation changes, gameplay/input changes, interior geometry or lighting, new camera systems, saved HUD preferences, viewports below 640×480 and unrelated shared-tree edits.
