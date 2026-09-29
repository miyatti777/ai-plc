---
name: plc-backfill
description: AI-PLCのスキルを通さずに済ませた作業を、あとから対象Layerに記録する（書き起こし・backlogへad-hocで追加・04-operation Phase 5.5〜7で検証後にcompleted）。書き込み前に承認を取る。
---

# Codex adapter: AI-PLC スキル外作業の事後記録

このadapterはCodex固有の入口だけを提供し、処理本文は`.claude`互換runtimeの正本を使う。

## 前提確認（変更前に必須）

repository root基準で、次の5ファイルがregular fileとして存在し読めることを確認する。

- `.claude/skills/plc-backfill/SKILL.md`
- `.claude/skills/ai-plc/04-operation/SKILL.md`
- `.claude/rules/ai-plc-system.md`
- `.claude/rules/ai-plc-session.md`
- `.claude/rules/ai-plc-adaptive.md`

1件でも欠落・読取不能なら、記録を行わず、欠落pathを列挙して停止する。

## 実行

1. 必須3 Rulesを上記順で最後まで読む。
2. 正本`.claude/skills/plc-backfill/SKILL.md`を最後まで読む。
3. 書き込み（Documents・backlog.yaml・context.yaml・Registry）は、正本の手順4の承認ブロックでユーザーの承認を得てからだけ行う。
4. 手順6のPhase 5.5〜7は、Codex adapter `04-operation`（正本`.claude/skills/ai-plc/04-operation/SKILL.md`）に従って実行する。reviewerの起動要否・起動方法・フォールバックは同adapterと正本の発動強度に従う。
5. コピペ用プロンプトの`/01-collection`〜`/04-operation`・`/plc-*`（`/plc-backfill`自身を含む）は、対応する`$skill-name`へ変換して示す。
6. 正本のClaude Code native memory参照を`~/.claude`へ解決してはならない。

## Read-only diagnostics

ユーザーが`AI-PLC prerequisite diagnostics`を明示した場合は正本の処理を実行せず、変更0で停止する。正本Skill・04-operation正本と必須3 Rulesの5件ごとに`absolute_path`、`sha256`、最初のH1、末尾のversion行を`prerequisite_diagnostics`として返す。5件のいずれかが欠落・読取不能なら`status: blocked`と対象pathを返す。Rules 3件は併せて`rule_diagnostics`として識別できるようにする。
