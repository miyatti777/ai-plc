---
name: ppm-plan
description: ポートフォリオ層の前夜の計画。翌日の WillDo を First Task → 差し込み → 繰り越し → TODO から → Daily Task の順で組み、空き時間と件数の上限に収め、利用者の OK の後に保存する。溢れた分は翌日の日記へ送る。
---

# Codex adapter: ppm-plan

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-plan/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 候補は共通の部品 `.claude/skills/ppm/ppm_files.py` と、`.claude/skills/ppm-plan/scheduled_today.py`・`.claude/skills/ppm-plan/aipm_due_items.py`・`.claude/skills/ppm-status/owner_open_count.py`（どれも読むだけ）で集める。
3. 予定表は、この環境で読める接続があるときだけ読む。無ければ空き時間を利用者に聞き、分からなければ設定の容量で組む。案の確認は Codex の質問UIで行い、OK の前に書かない。
4. 正本や共通の部品が欠ける場合は実行せず、欠落内容を報告する。
