---
name: plc-registry
description: AI-PLCの Project Registry（.claude/db/ai_plc.db）を照会・追加する。
---

# Codex adapter: AI-PLC Registry

このadapterはCodex固有の入口だけを提供し、処理本文は`.claude`互換runtimeの正本を使う。

## 前提確認（変更前に必須）

repository root基準で、次の4ファイルがregular fileとして存在し読めることを確認する。

- `.claude/skills/plc-registry/SKILL.md`
- `.claude/rules/ai-plc-system.md`
- `.claude/rules/ai-plc-session.md`
- `.claude/rules/ai-plc-adaptive.md`

1件でも欠落・読取不能なら、DB、Layer ファイルその他の状態を変更せず、欠落pathを列挙して停止する。

## 実行

1. 必須3 Rulesを上記順で最後まで読む。
2. 正本`.claude/skills/plc-registry/SKILL.md`を最後まで読む。
3. コマンドとデータは正本に記載されたパスを使用する。
4. dashboard / projects / active / tasks / SELECT はread-only確認として実行できる。add-project、add-task、UPDATEはユーザーが明示した操作範囲だけ実行する。
5. Claude Code固有のAgent toolまたは起動表記が現れた場合は、許可されたCodex sub-agentまたは対応する`$skill-name`へ変換する。
6. 正本のClaude Code native memory参照を`~/.claude`へ解決してはならない。Codexでは読取・更新とも行わず、該当処理は`変更なし — スキップ（Codex adapter: Claude native memory非対象）`と記録する。

## Read-only diagnostics

ユーザーが`AI-PLC prerequisite diagnostics`を明示した場合は正本の処理を実行せず、変更0で停止する。正本Skillと必須3 Rulesの4件ごとに`absolute_path`、`sha256`、最初のH1、末尾のversion行を`prerequisite_diagnostics`として返す。4件のいずれかが欠落・読取不能なら`status: blocked`と対象pathを返す。Rules 3件は併せて`rule_diagnostics`として識別できるようにする。
