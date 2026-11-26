---
description: "ポートフォリオ層: 状況確認。進行中は TODO の一覧、今日は WillDo、First Task と自分が関わる未完了 Task の件数。Layer のパスを渡したときだけ intent・backlog を見る。読み取り専用"
argument-hint: "[summary|inflight|today|detail] または Flow の Layer パス"
allowed-tools: Read, Glob, Grep, Bash
---

Read the skill at `.claude/skills/ppm-status/SKILL.md` and execute it.

Scope: $ARGUMENTS

- empty / summary → in-progress rows of the TODO list + today's WillDo + today's open 緊急 rows + First Task (no task IDs in titles)
- inflight → the TODO list's in-progress rows only
- today → today's WillDo and today's open 緊急 rows in the diary only
- detail → also open each work row's `layer` note and give one next step per row (no IDs). Do not open the Layers of rows in the private section unless the user names that item
- a path starting with `Flow/` → that Layer's intent status and the names of up to 3 open backlog tasks

Read the files only through `.claude/skills/ppm/ppm_files.py` and `.claude/skills/ppm-status/owner_open_count.py`. Do not write any file. Do not add rows to the WillDo. Use `--show-private` only when the user asks for private items.
