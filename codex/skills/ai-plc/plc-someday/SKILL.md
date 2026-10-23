---
name: plc-someday
description: いつかやるPJストック（Registry planned＋S-ID）の登録・一覧・着手・取り消し。「いつかやりたい」「いつかやるリスト」で使用する。
---

# Codex adapter: plc-someday

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-someday/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. コマンドとデータは正本に記載された `.claude/db/` 配下（`plc_query.py`・`ai_plc.db`）を使用する。
3. 登録・着手・取り消しは Registry に書き込むため、ユーザーが求めた操作だけを実行する。着手で出るコピペ用プロンプトは Codex では該当スキル（01-collection）名に読み替えて示す。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
