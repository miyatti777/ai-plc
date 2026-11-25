---
description: "ポートフォリオ層の Collection: 依頼や新しい案件を受けたとき、既存の案件（Registry と各 Layer の intent・context）を集めて照らし、似た案件を最大3件と行き先（既存の続き／新しい Layer／いつかやる）を勧める。読み取り専用"
argument-hint: "依頼の言葉"
allowed-tools: Read, Bash, Glob, Grep
---

Read the skill at `.claude/skills/ppm-collection/SKILL.md` and execute it.

Request to look up: $ARGUMENTS

Steps:
1. Decide visibility (`private` only for personal-life requests, else `company`) and run `python3 .claude/skills/ppm-collection/collect.py --text "<request>" --visibility <v>` from the repo root.
2. Read the returned goal / success criteria / context summaries and pick up to 3 candidates whose purpose matches, plus 「どれでもない」. Name-only candidates are judged by name only.
3. Recommend one destination from the SKILL's table and give copy-paste prompts. Read-only: never write to the Registry, Layers or Stock, and do not run the next command until the user explicitly asks.
