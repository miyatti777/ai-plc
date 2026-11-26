---
description: "ポートフォリオ層: Layer と TODO の一覧の差分と、待ち／要確認の見直しを提案 → 本人が承認した行だけ一覧に書く → 最後に今の状況をまとめる。WillDo には足さない"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Read the skill at `.claude/skills/ppm-todo/SKILL.md` and execute it.

Steps:
1. Run `date +%Y-%m-%d` alone. If the TODO list (path from `.claude/skills/ppm/ppm_files.py paths`) does not exist, ask before creating it from the bundled template.
2. Run `python3 .claude/skills/ppm-inflight/list_inflight.py` (read-only). For the whole picture, run `python3 .claude/skills/ppm-todo/inflight_programs.py` (`--detail` for each row); it groups by business project only when the Registry has the business tables, otherwise it prints a flat list.
3. Run `python3 .claude/skills/ppm-todo/todo_waiting.py` and show the proposed fixes for the waiting section. Do not read calendars or mail, and do not open links in the rows.
4. Show everything in plain Japanese (一覧にある／足す候補／外す候補／期限を過ぎたか止まっている) and stop for the user's OK.
5. After OK, recheck against the current file, then write only the approved rows: waiting rows through an approval JSON outside the repository with `todo_waiting.py --apply <file>` then `--write`; in-flight rows with Edit, only in the in-flight sections. Read back and confirm nothing else changed. Never touch the misc section, the parked section or unheaded paragraphs.
6. Do not add rows to today's WillDo. Do not write the Registry, Layers or external services.
7. Finally (even if nothing was written), run `python3 .claude/skills/ppm-todo/todo_summary.py` and show the short summary.
