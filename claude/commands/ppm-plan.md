---
description: "ポートフォリオ層: 前夜の計画。翌日の WillDo を First Task → 差し込み → 繰り越し → TODO から → Daily Task の順で組み、空き時間と件数の上限に収め、OK の後に保存する"
argument-hint: "[today|YYYY-MM-DD]（省略時は翌日。今日の WillDo が無ければ今日か明日かを聞く）"
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

Read the skill at `.claude/skills/ppm-plan/SKILL.md` and execute it.

Target date: $ARGUMENTS

Steps:
1. Run `date +%Y-%m-%d` alone, then decide the target date (argument first; no argument and no WillDo for today → ask today or tomorrow; otherwise tomorrow).
2. Check the target day's schedule if a calendar connection can be read (`ppm.sources.calendar: auto`); otherwise ask the user for the free hours, and fall back to `ppm.plan.capacity_hours`.
3. Collect carry-over and inserted rows with `.claude/skills/ppm/ppm_files.py carry --date <target>` (add `--with-target-urgent` when planning today): it looks back to the last day with a WillDo (rows marked `→ 繰り越し` or unmarked; never `→ TODO へ` / `→ やめた`) and reads the diaries in between. Collect the other candidates with `.claude/skills/ppm/ppm_files.py`, `.claude/skills/ppm-plan/scheduled_today.py`, `.claude/skills/ppm-plan/aipm_due_items.py` and `.claude/skills/ppm-status/owner_open_count.py` (read only). Do not copy backlog task IDs into the WillDo rows.
4. Build First → 差し込み → 繰り越し → TODOから → Daily, rewrite each row in plain words (Daily rows stay verbatim), apply `max_items` (non-Daily only) and the free hours (all five sections, Daily included). Fill TODOから only within what is left. On overflow, send 差し込み rows from the bottom to the next day's diary; if First + 繰り越し + Daily alone still exceed, show it as is and ask the user which carried rows to move.
5. Show the draft and STOP for the user's OK. After OK, in the same turn, write the WillDo from the template (`ppm_files.load_template`) and the overflow rows. Chat-only drafts are not done.
