---
description: Create daily task list and review progress
allowed-tools: Read, Write, Bash, Glob, Grep
---

Read the skill at `.claude/skills/utility/daily-ops/SKILL.md` and execute the daily task creation workflow.

Steps:
1. Check today's date and create the Flow directory if needed
2. Find active Layers with pending tasks
3. Generate today's task list based on priorities
4. Report yesterday's completed tasks (if any)

Output the daily plan as a markdown file in today's Flow directory.
