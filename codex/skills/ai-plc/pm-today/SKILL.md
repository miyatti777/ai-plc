---
name: pm-today
description: "pm-today: AIPM の箱の中から今日動かす1件を選ぶ（書かない）（AIPM を選んだ Layer だけ）"
---

# Codex adapter: pm-today

1. [Codex実行環境の読み替え](../references/codex-runtime.md)を読み、リポジトリルートの `.claude/skills/aipm-guided/ops/today.md` を最後まで読んで正本として使う。
2. 正本の「使える Layer」の確かめ方・動き・進め方・守ることをそのまま守る。書く操作は試す→本人の確定→`--apply` の順で、本人の確定なしに `--apply` しない。
3. `/pm-*`・`/01-collection`〜`/04-operation`・`/plc-*` は同名の `$skill` に読み替える。
