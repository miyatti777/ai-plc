---
description: "ポートフォリオ層: 終業。その日の WillDo の実行率→振り返り（FUN・DONE・DONE（WillDo外）・LEARN・満足度）→未完了と今日の緊急の扱い（繰り越し・TODO へ戻す・やめる）→OK の後に行の末尾へ印を書く→翌日の WillDo を組む（/ppm-plan）"
argument-hint: "[YYYY-MM-DD]（省略時は今日。翌朝に前日分を締めることもできる）"
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

Read the skill at `.claude/skills/ppm-close/SKILL.md` and execute it.

Target date: $ARGUMENTS（省略時は今日）

Steps:
1. Run `date +%Y-%m-%d` alone. Read the day's WillDo with `python3 .claude/skills/ppm/ppm_files.py willdo --date <day>`; if missing, stop and point to /ppm-plan.
2. Count total / done / carried / rate (the day's diary 緊急 rows are listed separately, outside the rate). Re-collect today's completions at this point (Layer tasks are found only when they have `completed_at`; ask the user for the rest).
3. Draft FUN / DONE / DONE（WillDo外） / LEARN, ask for 満足度, and propose a disposition for each unfinished row and each open 緊急 row (carry over / back to the TODO list / drop — dropping always needs the user's yes; unfinished Daily rows get no mark unless the user wants them tomorrow). Rewrite rows to be carried or sent back. Show all of it in ONE message and STOP.
4. After OK, in the same turn: write the 振り返り into the WillDo, append the mark (` → 繰り越し`, ` → 繰り越し: <rewritten row>`, ` → TODO へ`, ` → やめた`) to the end of each decided row (keep `- [ ]`), and add rows sent back into the TODO list's misc section. Do NOT write carried rows into the next day's diary (ppm-plan reads the marks).
5. Then run the ppm-plan steps for the next day (its own OK). Do not rewrite the TODO list's in-progress rows; point to /ppm-todo if it is installed.
