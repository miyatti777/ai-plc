---
description: "議論・議事録・選定施策を起点に、対象リポジトリの実構造にgroundしたエンジニア向けStory+Specを収束生成する"
argument-hint: source(選定Doc/議事録/Chat) [feature_label] [target_repo] [backlog_db_url]
allowed-tools: Read, Write, Bash, Glob, Grep, WebFetch, WebSearch, Agent
---

Read the skill at `.claude/skills/utility/spec-story-starter/SKILL.md` and execute it.

Input: $ARGUMENTS

必須入力（`source` / `feature_label`）が不足している場合は、実行前にユーザーへ確認する。`target_repo` / `backlog_db_url` / `spec_output` / `detail_level` は任意（未指定時はスキルの既定に従い、出力先は `Flow/[YYYYMM]/[YYYY-MM-DD]/[feature_label]/`）。
