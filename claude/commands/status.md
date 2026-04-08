---
description: Show current AIPO Layer and Task status
argument-hint: Layer path (optional — defaults to latest Flow directory)
allowed-tools: Read, Glob, Grep, Bash
---

Check the current project status:

1. Find the latest Layer in `Flow/` (or use $ARGUMENTS if specified)
2. Read `layer.yaml` and report: layer_id, status, goal, owner, deadline
3. Read `tasks.yaml` and report task progress:
   - Total tasks, completed, in_progress, pending
   - List any blocked or overdue tasks
4. Check for sublayers and their status

Output a concise status summary in Japanese.
