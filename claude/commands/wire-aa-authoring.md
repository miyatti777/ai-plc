---
description: "Story/Specと対象リポジトリを起点に、画面UIの現状→変更後をASCII Artワイヤフレームで描き、Storyに設計決定ログを追記する"
argument-hint: story(パス/参照) [spec] [target_repo] [screens] [tier lite|full]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

Read the skill at `.claude/skills/utility/wire-aa-authoring/SKILL.md` and execute it.

Input: $ARGUMENTS

必須入力（`story`）が不足している場合は、実行前にユーザーへ確認する。`spec` / `target_repo` / `screens` / `tier` / `update_story` は任意（未指定時はスキルの既定に従う。`tier` 既定=full、`update_story` 既定=true、`target_repo` 未指定=カレント）。`spec-story-starter` の次段として使う。
