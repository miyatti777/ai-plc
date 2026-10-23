---
name: plc-db-sync
description: AI-PLCのローカルSQLite DBとNotion DBをpull、push、sync、statusで双方向同期する。DB同期、Notion反映、同期状態確認で使用する。
---

# Codex adapter: AI-PLC DB Sync

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-db-sync/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. コマンドとデータは正本に記載された `.claude/db/` 配下を使用する。
3. 読み取り確認として実行できる範囲と、状態を変更するコマンドの扱いは、正本の Agent Rules に従う。状態を変更するコマンドは、ユーザーが要求した操作範囲だけ実行する。
4. 正本が欠ける場合は同期を開始せず、欠落内容を報告する。DB・前提条件の扱いは正本の Prerequisites に従う。
