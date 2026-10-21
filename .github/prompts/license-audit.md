# Road Rage Taxi — Commercial Release License and Attribution Audit

## Objective

Audit and fix the project's licensing, third-party notices, data attribution, and asset distribution so that Road Rage Taxi can be commercially distributed as a paid game on Steam.

**The game's own source code must remain licensed under the MIT License.** Do not replace the project's MIT license or relicense original game code under another license.

This task is about establishing and documenting distribution rights. Do not assume that a file is commercially usable merely because it is publicly available, included in the repository, or already used by the game.

## Mandatory constraints

- Keep the project's own game code under MIT.
- Preserve the existing game architecture, gameplay, visuals, performance, and FPS.
- Do not introduce unrelated gameplay or rendering changes.
- Do not change the map-data architecture or introduce a binary map format.
- Do not fix or modify the existing PBF loading/stuttering behavior.
- Do not remove assets or features simply to make the audit pass without first documenting the issue and evaluating alternatives.
- Do not invent licenses, copyright holders, source URLs, permissions, or attribution requirements.
- Do not treat a license identifier, repository README, or asset filename as sufficient evidence if the actual license terms are unavailable.
- Do not create or push Git tags.
- Pushing a working branch is permitted.
- Write all code, documentation, audit findings, and commit messages in English.

## Phase 1 — Establish the current licensing baseline

Inspect the actual repository and current branch before making changes.

Review at least:

- `LICENSE`
- `README.md`
- `THIRD_PARTY_LICENSES.md`
- `src/theroadragetrip/assets/DATA_LICENSES.txt`
- `src/theroadragetrip/sounds/LICENSE`
- `pyproject.toml` and all dependency declarations and lock files
- Godot project configuration and any Godot add-ons
- Windows packaging, PyInstaller configuration, build scripts, release workflows, and bundled executables
- All distributed assets, including images, fonts, audio, maps, geographic data, and generated data files

Identify the exact version and commit being audited. Distinguish between files present in the development repository and files actually included in each release package.

Confirm that the original game code remains MIT-licensed. Preserve existing copyright notices and avoid claiming ownership of third-party material.

## Phase 2 — Build a complete asset and dependency inventory

Create a machine-readable inventory and a human-readable report covering all files and dependencies distributed with the game.

For each relevant item, record:

- File, directory, dependency, or package name
- Purpose and whether it is shipped to players
- Origin and upstream project or provider
- Copyright holder, where known
- Exact license and version, where established
- Evidence: license file, authoritative URL, package metadata, or explicit permission
- Required copyright notice, attribution, source-code offer, or other obligations
- Whether commercial use and redistribution are permitted
- Whether modification or redistribution imposes additional conditions
- Audit status: verified, conditional, unresolved, or not distributable as currently packaged
- Required remediation and the responsible release artifact

Do not silently classify unknown licenses as permissive.

Include transitive dependencies, bundled tools, and executable components, not just direct Python dependencies.

## Phase 3 — Audit software licenses

Audit Python dependencies, Godot and its components, plugins, build tools, bundled executables, and any other distributed software.

Pay particular attention to:

- MIT, BSD, Apache-2.0, MPL, LGPL, GPL, and other licenses with different notice, source-distribution, or relinking requirements
- `osmium-tool` and any other GPL-licensed software included in Windows packages
- Whether a dependency is bundled, dynamically linked, statically linked, or invoked as a separate executable
- Required license texts, copyright notices, source availability, and corresponding-source obligations
- Whether the actual packaging method complies with each component's license

Do not assume that including GPL-licensed software automatically makes the entire game GPL-licensed. Equally, do not assume that keeping components in separate files automatically resolves every distribution obligation.

Where compliance depends on legal interpretation, document the exact facts and flag the question for review rather than making an unsupported conclusion.

Retain the game's MIT license and add third-party notices without changing the license of original game code.

## Phase 4 — Audit OpenStreetMap and geographic data

Inspect all OSM-derived data and every data-generation or packaging step that distributes it.

Identify:

- Which files contain OSM-derived data
- Whether they are raw extracts, modified extracts, generated databases, or rendered output
- Whether they contain OSM data mixed with non-OSM sources
- The source extract, retrieval date, processing steps, and relevant license
- Whether generated or cached data is included in the repository or release packages
- Which attribution and database-sharing obligations apply to each distributed artifact

Pay special attention to `places.json` and all other OSM-derived data identified in the repository.

Determine, based on the actual data structure and usage, whether ODbL obligations apply to a database or whether an output is a produced work. Do not automatically conclude that the whole game must be open source, and do not automatically conclude that every generated dataset is exempt.

Implement clear and appropriately visible OpenStreetMap attribution in the game. Ensure that players can find the attribution from a suitable in-game location, such as the main menu, credits, or map view. Include the required copyright and license information and a suitable link to the OSM copyright/licensing page.

If database redistribution requires additional notices, license terms, or access to the corresponding database, implement the necessary release documentation and packaging. Do not publish sensitive development information or unrelated proprietary material.

## Phase 5 — Audit all non-code assets and external data

Review every distributed sound, image, texture, icon, font, music track, generated audio file, and other non-code asset.

Inspect the entire sound directory and its associated license documentation. Do not assume that all audio files share the same license.

For each asset, establish whether commercial use, modification, redistribution, and inclusion in a paid game are permitted. Preserve attribution and notices where required.

Audit the sources and terms for:

- DVV-derived names
- Digitraffic railway schedules and compositions
- Wikipedia-derived municipality data
- Liiga and Veikkausliiga schedules, results, team names, attendance figures, and venue data
- Other external APIs, scraped data, downloaded datasets, and generated files

For sports data, distinguish between the rights to factual information, the terms governing the source service, and any protected databases, branding, or other material. Do not treat public accessibility as permission to redistribute the dataset commercially.

If the applicable rights or terms cannot be verified, document the uncertainty and provide a specific remediation path, such as obtaining permission, replacing the dataset with an appropriately licensed source, or excluding the affected data from the commercial release. Do not silently remove working gameplay features.

## Phase 6 — Make the licensing documentation release-ready

Update existing documentation rather than creating conflicting license statements.

Ensure the repository contains:

1. The original MIT `LICENSE` for the game's own code.
2. A complete and accurate third-party software notice.
3. An asset and data licensing document with attribution and source references.
4. Clear OpenStreetMap attribution and license information.
5. Any required third-party license texts and source-code or source-access instructions.
6. A concise commercial-release checklist describing any remaining conditional or unresolved items.

Keep license files and notices synchronized with the dependencies and assets actually shipped in each release.

Do not add boilerplate claims that all content is MIT-licensed. Explicitly distinguish original game code from third-party code, datasets, and assets.

## Phase 7 — Validate the release packages

Inspect the actual release-building process and, where possible, build the relevant release artifacts.

Verify that:

- Required license and attribution files are present in the shipped packages.
- Bundled executables and libraries have their required notices and source-access arrangements.
- Game UI attribution is visible and legible.
- Documentation points to the correct upstream sources.
- No required notice refers to a missing file.
- No unreviewed asset or dependency is accidentally introduced into the release.
- The game still starts and existing automated tests pass.
- Licensing changes do not alter gameplay or degrade performance.

Add a repeatable audit script or test where practical. It should detect missing license metadata and newly added assets or dependencies that lack an audit entry. It must not claim to determine legal compatibility automatically.

## Deliverables

Produce:

- `LICENSE_AUDIT.md`: executive summary, scope, methodology, evidence, findings, and remaining risks.
- An updated `THIRD_PARTY_LICENSES.md` covering software and bundled tools.
- An updated `src/theroadragetrip/assets/DATA_LICENSES.txt`, or a better-organized equivalent, covering data and non-code assets.
- Any required in-game attribution changes.
- A repeatable validation script or test, where practical.
- A list of all files changed and the reason for each change.
- A final table of verified, conditional, unresolved, and non-compliant items.

The final report must clearly answer:

1. Is the project's own code still MIT-licensed?
2. Which components may be distributed commercially with the current evidence?
3. Which obligations must be fulfilled before a paid Steam release?
4. Which items still require permission, replacement, additional source distribution, or legal review?
5. Can the current release package be considered ready for commercial distribution based on the evidence actually found?

Do not declare the project commercially release-ready if any material distribution rights remain unresolved.

## Completion and Git workflow

Run relevant tests and packaging checks. Review the final diff for accidental gameplay or architecture changes.

Commit the work on the current working branch and push the branch if the repository's existing workflow permits it. Do not create or push any Git tags.

In the final response, summarize what was verified, what was changed, the test results, and every remaining blocker. Clearly separate evidence-based findings from issues requiring legal review.

This is a technical licensing audit, not a substitute for legal advice where rights or license interpretation remain uncertain.