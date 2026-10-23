---
name: plc-next
description: AI-PLCの直前の結果と案件正本から、欠けた次の選択肢・おすすめ・開始文を補い、有効な既存Next Actionは再提示する。相談・再計画・次工程実行はしない。
---

# Codex adapter: plc-next

1. [Codex実行環境の読み替え](../references/codex-runtime.md)を読み、リポジトリルートの `.claude/skills/plc-next/SKILL.md` を最後まで読んで正本として使う。
2. 読取専用。正本の案内復元だけを行い、auto/force中もこの呼出しで次工程を実行しない。委譲済み範囲を新しい再承認待ちに戻さない。
3. 開始文の `/01-collection`〜`/04-operation`・`/plc-*` は同名の `$skill` に読み替え、Layer/Task/制約を保持する。未掲載なら実在adapterの絶対パスを添えて「このSKILL.mdを読んで実行」と案内する。正本や開始先が欠ける場合は不足を報告し、仮の入口を作らない。
