---
name: ship
description: Prompt -> spec -> implement -> test pipeline using the spec-writer, implementer and tester subagents. Use when the user types /ship <prompt>.
---
Run sequentially, passing only paths/short text between agents (not file contents):

1. Agent `spec-writer` with the user's prompt → returns spec path. Show the path.
2. Agent `implementer` with the spec path.
3. Agent `tester` with the spec path.
4. If `VERDICT: FAIL`: send the tester's failures to `implementer` (SendMessage, same agent) and re-run `tester`. Max 5 loops, then stop and report.
5. On PASS: run the `finalizer` agent with the spec path, the tester's verdict and the
   user's wish (default: commit and push; "no commit" / "do not push" if the user said so).
   It commits atomically (spec + code + tests), pushes, and reports verdict and commit in ≤6 lines.
   On FAIL or after 5 loops, do not run it: ask user for direction.

Every step must end with that agent's report. If an agent returns without a report
(stopped with work still running, or with no final message), do not treat it as done:
resume the same agent with SendMessage and ask it to finish and report, then keep
polling (every 5 minutes while work runs) until the report arrives. Never run the next
step on an unreported result.
