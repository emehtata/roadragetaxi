# Repo documentation cleanup

## Goal
Remove finished-work prompts, superseded audits and dead references so docs
only describe current truth. Documentation only; no behaviour change.

## Proof method
For each file: `git grep -F "<basename>" -- . ":!<file>"` outside its own
directory. Results below were checked 2026-11-13. Re-run before deleting.

## Delete (nothing links to it)
1. `.github/prompts/rrt-019-crash-physics-01.md`, `rrt-019-in-house-02.md`,
   `rrt-019-in-house-03.md`, `rrt-019-rush-hour-01.md`,
   `rrt-021-humans-and-animals-3d.md`, `rrt-021-vehicles-polish-3d.md`:
   one-off task prompts for finished 0.19/0.21 work; zero inbound references.
2. `.github/prompts/rrt-021-simulation-performance-audit.md` together with
   `.github/performance-analysis/rrt-021-simulation-optimization.md` (its only
   referrer) and `rrt-021-simulation-performance-audit.md` plus
   `rrt-021-simulation-performance-audit-data/`: finished audit, not in the
   performance README index, no other inbound links.
3. `.github/performance-analysis/rrt-021-audit-fixes.md`,
   `rrt-021-optimization-data/`: not in the index, zero inbound links (the
   data folder only from step 2 files); the audit header says all findings are
   fixed. (`rrt-021-rubberband-profile.md` was wrongly listed here: see Keep.)
4. `docs/architecture/archive/godot-pygame-rendering-parity.md` (2679 lines)
   and `godot-rendering-migration.md`: Pygame client was removed in 0.17.0;
   only each other links to them.
5. (Withdrawn) `tools/rtx/custom0-1dd330f7.patch` stays: see Keep.

## Keep (referenced or current)
- `.github/prompts/license-audit.md`, `LICENSE_AUDIT.md` (linked from README,
  THIRD_PARTY_LICENSES.md, a spec).
- `docs/lam-traffic-audit.md`: cited by `npc.py`, `tools/lam_profiles.py`, tests.
- `docs/architecture/archive/simulation-rendering.md`: linked from
  `godot-client.md` and `simulation.py` docstring.
- `.github/performance-analysis/`: README, `2026-10-27-load-and-render.md`,
  `map-loading-02.md`, `rrt-019.1-fps-audit*`, `rrt-019-sim-audit-data/`,
  `rrt-021-cache-decode.md`, `visibility-first-2026-10-18.md` (linked from
  godot-client.md). All indexed by the README.
- `.github/performance-analysis/rrt-021-rubberband-profile.md`: linked from the
  kept `rrt-021-cache-decode.md` and lists open next steps.
- `tools/rtx/custom0-1dd330f7.patch`: the committed port of `custom0.patch`
  for the fork head; its content differs.
- `TESTING.md` (used by tests/CI), `.github/TODO.md`, `copilot-instructions.md`,
  `docs/motorway-traffic/motorway_spawn.patch`, all feature docs in `docs/`
  and `docs/specs/`, RTX docs.
- Untracked/ignored (`tools/poly/`, `.claude/skills/godot-skills`,
  `game-mechanics-optimizations/`, `graphify-out/`, `*.log`): not touched.

## Stale links to fix
- `.github/performance-analysis/README.md`: no entries point at deleted files
  (verify after step 2/3; remove any added).
- Comments citing prompts that no longer exist in `.github/prompts/`; reword to
  drop the path (keep the rule described): `src/theroadragetrip/tile_streaming.py:24`
  (map-loading-01.md), `npc.py:4` (autonomous-driving.md), `physics.py:51,105`
  (GRIP.md, SKIDMARK.md), `activities/base.py:1` and `activities/README.md:3`
  (residents-live.md), `osm/traffic_signals.py:4` (TRAFFICLIGHTS_PROMPT.md),
  `tests/test_grip.py:1`, `tests/test_g_force.py:2`.
- Task-id labels for the deleted prompts: `docs/home-interiors.md:136` and
  `godot/home_walk.gd:1` (rrt-019-in-house-02); reword in plain words.
- `docs/parking-garages.md:10`: `garage-NN.md` prompts do not exist; reword.
- `docs/architecture/archive/simulation-rendering.md` lines 6, 126, 200: cite
  missing `client-server-*.md` prompts; replace with plain text.
- README.md and AGENTS.md currently have no broken relative links; keep so.

## Acceptance criteria
1. Every file in "Delete" is gone (`git ls-files` shows none).
2. `git grep -F` for each deleted basename and directory returns nothing.
3. A link checker over README.md, AGENTS.md and every tracked `docs/**/*.md`
   and `.github/**/*.md` reports no missing relative target.
4. No source, test or comment mentions a `.github/prompts/*.md` path that does
   not exist.
5. `docs/specs/`, `finnish-npc-traffic-law.md`, `visual-testing.md` and the
   three RTX docs are byte-identical to before.
6. Full test suite passes unchanged (`make test` or `pytest`, nothing deselected).

## Tests to add
`tests/test_doc_links.py::test_relative_markdown_links_resolve`: walks README.md,
AGENTS.md, docs/**/*.md and fails on any missing relative link target; fails
today only if a stale link exists, and guards future deletions.
`::test_no_missing_prompt_references`: greps src/ and tests/ for
`.github/prompts/<name>.md` and asserts the file exists; fails today for
GRIP.md, SKIDMARK.md and others.

## Out of scope
Rewriting doc content, merging feature docs, touching specs, code behaviour,
untracked work, git history rewriting.
