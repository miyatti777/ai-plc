---
name: plc-consult
description: AI-PLC進行中のアイデア相談。今のLayerと照らして却下／今のタスク内で修正／Re-Inception／Re-Collection／いつかやるに振り分け、所感と次のコマンドを返す（読み取り専用）。
---

# Codex adapter: AI-PLC アイデア相談

このadapterはCodex固有の入口だけを提供し、処理本文は`.claude`互換runtimeの正本を使う。

## 前提確認（変更前に必須）

repository root基準で、次の4ファイルがregular fileとして存在し読めることを確認する。

- `.claude/skills/plc-consult/SKILL.md`
- `.claude/rules/ai-plc-system.md`
- `.claude/rules/ai-plc-session.md`
- `.claude/rules/ai-plc-adaptive.md`

1件でも欠落・読取不能なら、判定を行わず、欠落pathを列挙して停止する。

## 実行

1. 必須3 Rulesを上記順で最後まで読む。
2. 正本`.claude/skills/plc-consult/SKILL.md`を最後まで読む。
3. 読み取り専用。intent.yaml・backlog.yaml・成果物・Registryを変更せず、判定・理由・コピペ用プロンプトを返して停止する。grep・cat・`plc_query.py active`などのread-onlyコマンドは実行できる。
4. コピペ用プロンプトの`/01-collection`〜`/04-operation`は、対応する`$skill-name`へ変換して示す。
5. 正本のClaude Code native memory参照を`~/.claude`へ解決してはならない。

## Read-only diagnostics

ユーザーが`AI-PLC prerequisite diagnostics`を明示した場合は正本の処理を実行せず、変更0で停止する。正本Skillと必須3 Rulesの4件ごとに`absolute_path`、`sha256`、最初のH1、末尾のversion行を`prerequisite_diagnostics`として返す。4件のいずれかが欠落・読取不能なら`status: blocked`と対象pathを返す。Rules 3件は併せて`rule_diagnostics`として識別できるようにする。
