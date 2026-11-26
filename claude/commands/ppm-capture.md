---
description: "ポートフォリオ層: 差し込みの「やること」を振り分けて記録する（今日中に実害→今日の日記の緊急／期日あり→その日の日記／期日なし→TODO の一覧の進行中か雑務／将来の案件→いつかやる／迷ったら明日）。今日の WillDo には足さない"
argument-hint: "やること（1〜2行）"
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

Read the skill at `.claude/skills/ppm-capture/SKILL.md` and execute it.

Input to capture: $ARGUMENTS

Steps:
0. If the input is long context (3+ lines, a file, a transcript), reply in one line that importing long context is not handled by this skill, and stop.
1. Run `date +%Y-%m-%d` alone to fix today and tomorrow.
2. Rewrite the input into one plain line (the SKILL's P1–P6 check) before routing.
3. Route: urgent (ask the user first) → today's diary 緊急 / has a day → that day's diary 予定タスク / no day: future project → `python3 .claude/db/plc_query.py someday-add`, running project → TODO list in-progress section, small chore → TODO list misc section / unsure → tomorrow's diary. AIPM Layers → point to /pm-suggest and stop.
4. NEVER add to today's WillDo. Find places only through `.claude/skills/ppm/ppm_files.py`; create a missing diary from the template via `ppm_files.load_template`; ask before creating a missing TODO list.
5. Report the destination and the reason in one line.
