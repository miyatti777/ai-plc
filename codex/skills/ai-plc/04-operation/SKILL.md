---
name: 04-operation
description: AI-PLC Stage 4 Operation。BacklogとAgent定義に従ってタスクを実行し、成果物生成、検証、ステータス更新、Propagationを行う。
---

# Codex adapter: AI-PLC Stage 4

このadapterはCodex固有の入口だけを提供し、処理本文は`.claude`互換runtimeの正本を使う。

## 前提確認（変更前に必須）

repository root基準で、次の4ファイルがregular fileとして存在し読めることを確認する。

- `.claude/skills/ai-plc/04-operation/SKILL.md`
- `.claude/rules/ai-plc-system.md`
- `.claude/rules/ai-plc-session.md`
- `.claude/rules/ai-plc-adaptive.md`

1件でも欠落・読取不能なら、成果物、backlog、context、DB、Wikiその他のファイルを変更せず、欠落pathを列挙して停止する。

## 実行

1. 必須3 Rulesを上記順で最後まで読む。
2. 正本`.claude/skills/ai-plc/04-operation/SKILL.md`を最後まで読む。
3. Knowledge Lintでは`.claude/skills/ai-plc/04-operation/knowledge-lint.md`、Platform Builderでは同階層の`platform-builder.md`を読む。
4. DB、Wiki、Rules、Templatesは正本に記載された`.claude/`配下へ解決する。
5. Claude Codeのスラッシュ形式は、Codexでは対応する`$skill-name`へ変換する。Claude CodeのAgent toolは利用可能なCodex sub-agentへ変換する。
6. 正本Phase 5.5のmaker≠checker規定は、Codex sub-agent reviewerを起動する明示的要求として扱う。Agent定義の`delegable: false`は成果物作成の委譲だけを禁止し、独立reviewerを禁止しない。
7. reviewerが利用不能、起動失敗、または出力未取得の場合だけ正本のセルフ検証fallbackを使用し、理由をVerification recordへ記録する。
8. Phase 7を含め、正本のClaude Code native memory参照を`~/.claude`へ解決してはならない。Codexでは読取・更新とも行わず、Propagationへ`変更なし — スキップ（Codex adapter: Claude native memory非対象）`と記録する。

## Read-only diagnostics

ユーザーが`AI-PLC prerequisite diagnostics`を明示した場合は正本のStage処理を実行せず、変更0で停止する。正本Skillと必須3 Rulesの4件ごとに`absolute_path`、`sha256`、最初のH1、末尾のversion行を`prerequisite_diagnostics`として返す。4件のいずれかが欠落・読取不能なら`status: blocked`と対象pathを返す。Rules 3件は併せて`rule_diagnostics`として識別できるようにする。
