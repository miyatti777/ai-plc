---
description: "AI-PLC: 現在のLayer・Task進捗を表示"
argument-hint: Layer path (optional — defaults to latest Flow directory)
allowed-tools: Read, Glob, Grep, Bash
---

Check the current project status:

1. Find the latest Layer in `Flow/` (or use $ARGUMENTS if specified)
2. Read `intent.yaml` and report: scope_id, status, goal, owner, deadline
3. Read `backlog.yaml` and report task progress:
   - Total tasks, completed, in_progress, pending
   - List any blocked or overdue tasks
4. Check for sub-scopes and their status

Output a concise status summary in Japanese.
