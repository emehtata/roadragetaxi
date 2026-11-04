---
name: ship
description: Prompt -> spec -> implement -> test pipeline using the spec-writer, implementer and tester subagents. Use when the user types /ship <prompt>.
---
Run sequentially, passing only paths/short text between agents (not file contents):

1. Agent `spec-writer` with the user's prompt → returns spec path. Show the path.
2. Agent `implementer` with the spec path.
3. Agent `tester` with the spec path.
4. If `VERDICT: FAIL`: send the tester's failures to `implementer` (SendMessage, same agent) and re-run `tester`. Max 2 loops, then stop and report.
5. On PASS: commit atomically (spec + code + tests) per AGENTS.md, push. Report verdict + commit in ≤5 lines.
