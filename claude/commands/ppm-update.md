---
description: "ポートフォリオ層: その日の WillDo と日記の緊急を終わった仕事に合わせて更新する。載っている行は [x]、載っていない今日の完了は DONE（WillDo外）へ。行は足さない"
argument-hint: "[YYYY-MM-DD]（省略時は今日）や「〇〇が終わった」"
allowed-tools: Read, Edit, Bash, Glob, Grep
---

Read the skill at `.claude/skills/ppm-update/SKILL.md` and execute it.

Input: $ARGUMENTS（日付なら対象日。省略時は今日）

Steps:
1. Run `date +%Y-%m-%d` alone. If the input is a date, use it.
2. Find and read that day's WillDo with `python3 .claude/skills/ppm/ppm_files.py willdo --date <day>`. If it is missing, stop and point to /ppm-plan.
3. Collect today's completions (the user's words, Layers / backlog tasks with `completed_at` on that day — read only; tasks without `completed_at` cannot be found this way, so rely on the user's words for them). Matching rows in the WillDo or in that day's diary 緊急 section (`ppm_files.py diary --date <day>`) → `- [x]`. Unmatched completions → `### DONE（WillDo外）`.
4. WRITE the file in this turn with Edit. Do not only report in chat. Do not add rows to sections 1–5.
5. Report the path and the counts.
