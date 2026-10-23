---
name: plc-consult
description: AI-PLC進行中のアイデア相談。今のLayerと照らして却下／タスク内で修正／Re-Inception／Re-Collection／いつかやるに振り分け、所感と次のコマンドを返す（読み取り専用）。「どう思う？」「次どのコマンド？」で使用する。
---

# Codex adapter: plc-consult

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-consult/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 読み取り専用。intent.yaml・backlog.yaml・成果物・Registry を書き換えず、判定・理由・コピペ用プロンプトを返して止まる。
3. コピペ用プロンプトの `/01-collection` 〜 `/04-operation`（`-jev` 版は凍結中のため出さない）・`/plc-someday` は、Codex では同名の `$skill` 指定に読み替えて示す。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
