---
name: plc-registry
description: AI-PLC Project Registry（.claude/db/ai_plc.db）の照会と追加。「Registry見せて」「プロジェクト一覧」で使用する。
---

# Codex adapter: plc-registry

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-registry/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. コマンドとデータは正本に記載された `.claude/db/` 配下（`plc_query.py`・`ai_plc.db`）を使用する。
3. 照会（dashboard / projects / tasks / SELECT）は自由に実行してよい。add-project / add-task / UPDATE はユーザーが求めた範囲だけ実行する。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
