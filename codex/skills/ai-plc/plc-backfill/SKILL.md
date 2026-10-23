---
name: plc-backfill
description: AI-PLCのスキルを通さずに済ませた作業を、あとから対象Layerに記録する（書き起こし・backlogへad-hocで追加・04-operation Phase 5.5〜7で検証後にcompleted）。書き込み前に承認を取る。「Propagationして」「さっきの作業を記録して」で使用する。
---

# Codex adapter: plc-backfill

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-backfill/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 書き込み（Documents・backlog.yaml・context.yaml・Registry）は、正本の手順 4 の承認ブロックでユーザーの承認を得てからだけ行う。
3. 手順 6 の Phase 5.5〜7 は `.agents/skills/ai-plc/04-operation/SKILL.md`（Codex アダプター経由で正本）に従って実行する。reviewer の起動要否・起動方法・フォールバックは同アダプターと正本の発動強度に従う。pipeline_variant: jev の Layer も同じ（Jev 実験版は凍結中）。
4. コピペ用プロンプトの `/01-collection` 〜 `/04-operation`・`/plc-*`（`/plc-backfill` 自身を含む）は、Codex では同名の `$skill` 指定に読み替えて示す。
5. 正本が欠ける場合は実行せず、欠落内容を報告する。
