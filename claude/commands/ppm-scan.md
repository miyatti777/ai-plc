---
description: "ポートフォリオ層: 指定範囲の Notion・本人の公開 Slack 発言から案件の候補を1回だけ集め、収集メモにする（TODO への反映は利用者の TODO 管理で）"
argument-hint: "集める範囲（Notion のページ・Slack のワークスペース・期間）"
allowed-tools: Read, Write, Bash, Glob, Grep
---

Read `.claude/skills/ppm-scan/SKILL.md` completely and execute it.
Scope: $ARGUMENTS

Use only the read-only connectors that are actually available; if none are, say so and stop. Save only the collection memo. Do not change the TODO list, backlog, Registry, Notion or Slack. Return the candidates with their evidence and the memo path, and stop there.
