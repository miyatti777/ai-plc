---
name: 01-collection
description: AI-PLC Stage 1 Collection。GoalとModeからExecution Contextを確立し、Context Store、intent.yaml、context.yaml、backlog.yamlを生成する。
---

# Codex adapter: AI-PLC Stage 1

このadapterはCodex固有の入口だけを提供し、処理本文は`.claude`互換runtimeの正本を使う。

## 前提確認（変更前に必須）

repository root基準で、次の4ファイルがregular fileとして存在し読めることを確認する。

- `.claude/skills/ai-plc/01-collection/SKILL.md`
- `.claude/rules/ai-plc-system.md`
- `.claude/rules/ai-plc-session.md`
- `.claude/rules/ai-plc-adaptive.md`

1件でも欠落・読取不能なら、Scope、Flow、DB、Wikiその他のファイルを変更せず、欠落pathを列挙して停止する。

## 実行

1. 必須3 Rulesを上記順で最後まで読む。
2. 正本`.claude/skills/ai-plc/01-collection/SKILL.md`を最後まで読む。
3. 正本の手順を実行し、DB、Wiki、Rules、Templatesは`.claude/`配下へ解決する。
4. Claude Codeのスラッシュ形式は、Codexでは`$01-collection`〜`$04-operation`へ変換する。
5. Claude CodeのAgent toolは、ユーザーまたは適用中の指示が明示的に許可・要求した場合だけCodex sub-agentへ変換する。それ以外はメインエージェントで実行する。
6. 正本のClaude Code native memory参照を`~/.claude`へ解決してはならない。Codexでは読取・更新とも行わず、該当Propagationは`変更なし — スキップ（Codex adapter: Claude native memory非対象）`と記録する。

## Read-only diagnostics

ユーザーが`AI-PLC prerequisite diagnostics`を明示した場合は正本のStage処理を実行せず、変更0で停止する。正本Skillと必須3 Rulesの4件ごとに`absolute_path`、`sha256`、最初のH1、末尾のversion行を`prerequisite_diagnostics`として返す。4件のいずれかが欠落・読取不能なら`status: blocked`と対象pathを返す。Rules 3件は併せて`rule_diagnostics`として識別できるようにする。
