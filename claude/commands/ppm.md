---
description: "ポートフォリオ層の入口: 依頼の目的から日次の入口・他の PPM スキル・AI-PLC の Stage を1つ選び、既存の案件の再開も判定する"
argument-hint: "いまの状況 / 明日の計画 / 仕事の棚卸し / この Layer を再開 など"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

Read `.claude/skills/ppm/SKILL.md` and execute it for: $ARGUMENTS

Pick exactly one destination from the skill's table and read that SKILL.md. Pass the user's scope and authorization through unchanged.
This entrypoint does not itself approve list updates, external collection, or Stage checkpoints. If the TODO list does not exist, ask before creating it from the bundled template.
