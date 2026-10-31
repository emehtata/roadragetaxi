# Integrate Road Rage into the Taxi Driver Combat System

## Objective

Extend the existing taxi driver conflict and fighting system so that the existing road rage meter directly influences combat effectiveness.

Road rage must be a gameplay mechanic, not merely a visual indicator. Higher road rage should make the player more dangerous in a fight, while extreme rage should introduce meaningful disadvantages that prevent it from being an unconditional advantage.

Apply the mechanic to NPC taxi drivers as well, wherever the existing simulation architecture supports it. Player and NPC combat must use the same underlying combat resolution rules, with participant-specific road rage values.

## 1. Audit the existing implementation first

Inspect the current repository before changing anything.

Identify:
- The existing road rage meter, its range, and how its value changes.
- All existing road rage thresholds, effects, decay rules, and reset conditions.
- The current combat or taxi driver conflict implementation.
- The authoritative Python simulation code that resolves combat actions and outcomes.
- The participant attributes currently used to determine attacks, defense, damage, intimidation, retreat, and fight resolution.
- The current Godot UI and presentation of the road rage meter.
- Existing player and NPC state models and relevant tests.

Reuse the existing road rage system and combat architecture. Do not create a second rage meter, duplicate rage calculations, or introduce an independent combat system.

If the combat system has not yet been implemented, report that dependency and implement only the compatible integration points that are supported by the existing code. Do not fabricate missing classes, APIs, or files.

## 2. Define how road rage affects combat

Use the existing road rage value and its actual range. Do not assume a range of 0–100 without verifying it.

Normalize the value only where necessary for calculations.

Implement a smooth, bounded relationship between road rage and combat effectiveness. Avoid abrupt jumps at arbitrary thresholds unless the existing game design explicitly requires them.

Road rage should influence the following combat dimensions where supported by the current combat model:

### Attack effectiveness
Higher rage increases the probability of a successful attack or otherwise improves the effectiveness of offensive actions.

### Intimidation
Higher rage increases the likelihood that an opponent will hesitate, retreat, or surrender when the existing combat state and participant behavior make such an outcome possible.

### Pain tolerance or stagger resistance
Higher rage may reduce the chance that minor combat impacts interrupt the participant's next action. Do not make participants invulnerable or eliminate the consequences of being hit.

### Defensive control
At very high rage, defensive effectiveness should decrease. A highly enraged participant may attack more aggressively but become easier to outmaneuver or counter.

### Overall balance
Road rage must influence combat outcomes without guaranteeing victory. Fighting ability, the opponent's attributes, action selection, random variation, and the current combat state must remain relevant.

Use conservative initial tuning values. Keep the formulas and tuning parameters centralized in the existing configuration or combat-balancing mechanism where appropriate.

Do not implement the illustrative percentages from design discussions as fixed requirements. Determine suitable initial values from the actual combat system and document the resulting formula.

## 3. Use the same mechanics for players and NPCs

The existing road rage system must be the source of truth for both players and NPC taxi drivers.

For the player:
- Use the player's actual road rage value when resolving combat actions.
- Changes in road rage should affect subsequent combat decisions without requiring a restart of the fight.
- Do not allow the Godot client to submit an arbitrary rage value or directly determine combat effectiveness.

For NPCs:
- Use an existing NPC rage, aggression, or equivalent state if one already represents the intended mechanic.
- If NPC road rage does not exist, determine whether the existing behavior model can support it without introducing unnecessary state duplication.
- Keep NPC rage bounded and compatible with the current NPC lifecycle.
- Ensure that NPC-versus-NPC fights and player-versus-NPC fights use the same underlying combat formulas.

Do not automatically equate permanent personality traits with temporary road rage. If both exist, keep their roles distinct: personality influences behavior and reaction tendencies, while current road rage represents the participant's temporary emotional state.

## 4. Preserve authoritative simulation

All combat modifiers and outcomes must be calculated by the Python simulation server.

Godot may display rage-dependent reactions and animations, but it must not:
- Calculate authoritative hit outcomes.
- Apply combat bonuses independently.
- Override the server's combat state.
- Modify the participant's rage value without server validation.

Reuse the existing client-server protocol. Add protocol fields only if necessary for correct synchronization or presentation.

Ensure that combat results remain valid under delayed updates, repeated messages, participant despawning, and conflict cancellation.

## 5. Integrate with existing presentation

Inspect the existing road rage UI and combat animations before making changes.

If appropriate for the current presentation:
- Make highly enraged combatants appear more aggressive.
- Allow intimidation and retreat behavior to reflect the current rage values.
- Reuse existing combat animations and audio.
- Keep UI changes minimal unless the current rage indicator does not communicate the mechanic adequately.

Do not add a new rage bar if the game already has one.

Visual effects must reflect the authoritative simulation state rather than independently inventing combat outcomes.

## 6. Testing requirements

Add automated tests using the repository's existing test framework.

Test at least:

1. A low rage value produces the expected baseline combat modifiers.
2. Increasing rage improves the intended offensive modifiers.
3. Extreme rage reduces the intended defensive modifier.
4. All modifiers remain within their configured bounds.
5. Identical combat situations with controlled randomness can be tested deterministically.
6. High rage does not guarantee a hit or victory.
7. Combat outcomes still depend on opponent attributes and the current combat state.
8. Player and NPC participants use the same underlying modifier calculations.
9. Changes in rage during an active fight affect subsequent actions correctly.
10. Rage values outside the valid range are handled safely.
11. Existing road rage behavior outside combat remains unchanged unless an explicit dependency requires otherwise.
12. Existing combat, NPC, simulation, and protocol tests continue to pass.

Avoid brittle tests that assert an entire fight must be won or lost from a single rage value when randomness or multiple attributes legitimately influence the outcome. Prefer testing the actual modifier calculations and controlled combat scenarios.

## 7. Performance and maintainability

The mechanic must add negligible overhead to the normal simulation.

- Calculate modifiers only when needed for combat decisions, or reuse existing cached values if appropriate.
- Avoid additional per-frame work for NPCs that are not fighting.
- Avoid repeated global NPC scans.
- Do not introduce a new global NPC cap.
- Do not refactor unrelated simulation or rendering systems.
- Preserve the current game architecture and rendering performance.

## 8. Documentation and delivery

Document:
- The actual road rage value range.
- The combat formula and modifier bounds.
- How road rage affects offense, intimidation, and defense.
- How player and NPC participants share the mechanics.
- The tuning parameters and their defaults.
- Any limitations caused by missing combat or NPC functionality.

Run the relevant tests and report their actual results.

Use atomic Git commits for logical implementation milestones. Do not create Git tags unless explicitly requested.

## Final report

Summarize:
1. How road rage now influences combat.
2. The exact formula and initial tuning values.
3. How NPCs and players share the mechanics.
4. Files and protocol components changed.
5. Tests executed and their actual results.
6. Any remaining limitations or follow-up work.

Begin by auditing the current implementation. Integrate with existing systems rather than assuming the earlier design proposal matches the code exactly.