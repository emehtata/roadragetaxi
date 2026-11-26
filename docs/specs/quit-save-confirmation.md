# Quit save confirmation

## Goal
When quitting a saveable game from the pause menu, ask whether to save before exiting instead of immediately saving and quitting.

## Files to change
- `godot/startup.gd`: replace the pause-menu Quit callback with a confirmation menu and guarded save-and-quit action.
- `godot/i18n.gd`: Finnish, English and German confirmation title, question and save-and-quit action.
- `godot/tests/pause_save.gd`: exercise confirmation choices, asynchronous acknowledgement and failure/retry behavior.
- `tools/visual_scenarios.json` and the smallest necessary visual-test harness files: register and render the named `pause_quit_save_confirmation` UI scenario.

## Behaviour / acceptance criteria
1. In a gig-driver or simulation game for which `_can_save()` is true, clicking pause-menu Quit opens a confirmation; opening it neither saves nor exits. The game stays paused.
2. Finnish displays “Lopeta peli?” and asks “Haluatko tallentaa pelin ennen lopettamista?”. The choices clearly mean “Tallenna ja lopeta”, “Lopeta tallentamatta” and “Peruuta”; English and German provide equivalent localized text.
3. Save and quit sends one existing save request and exits only after the server acknowledges success. Preserve the existing save-slot/thumbnail behavior and bounded timeout.
4. A failed, disconnected or timed-out save keeps the game open, displays the localized failure message, and permits retry, explicit quit without saving, or cancellation.
5. Quit without saving exits without sending a save request. Cancel and Escape return to the pause menu without saving or exiting; cancellation is the initially focused choice.
6. While a save is pending, repeated activation, quit-without-saving and Escape cannot trigger competing saves, exit early or navigate away from the pending operation. Choices become usable again after failure.
7. The standalone pause-menu Save action still saves without quitting. Existing behavior for Quit from the launch menu and modes where `_can_save()` is false is preserved.
8. `pause_quit_save_confirmation` passes readiness checks for the actual visible confirmation, localized question and all three usable choices, then captures a screenshot. Inspect the rendered Finnish view for clipping, focus and readable choices before completion; keep evidence local.

## Tests to add / update
- `godot/tests/pause_save.gd` — `test_quit_opens_confirmation`: no save occurs on Quit; all choices are present; cancel/Escape return safely. Fails with the current immediate-save callback.
- Same file — `test_save_and_quit_acknowledgement`: one request while pending; no early exit; acknowledged success exits. Cover failure followed by retry.
- Same file — `test_quit_without_saving`: explicit discard exits with zero save requests, including after failure.
- Same file — `test_manual_save_and_unsaveable_quit`: preserve manual Save and non-saveable behavior; check new text exists in FI/EN/DE.
- Run the focused pause-save cases, relevant Godot parser/manifest checks and the passing named visual scenario; do not broaden into unrelated gameplay checks.

## Out of scope
Save format/server persistence changes, career autosave policy, main-menu return flow, operating-system window-close behavior, and menu redesign.
