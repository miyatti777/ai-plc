---
name: ppm-inflight
description: ポートフォリオ層・進行中の候補の洗い出し。Layer の intent.yaml から進行中の候補を集め、TODO の一覧との差分を示す。読み取り専用で、反映は ppm-todo。
---

# Codex adapter: ppm-inflight

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-inflight/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 道具は正本の `.claude/skills/ppm-inflight/list_inflight.py`（読み取り専用。部品は `.claude/skills/ppm/ppm_files.py`）。TODO の一覧・Layer・Registry には書かない。
3. 反映を頼まれたら `$ppm-todo` を案内して止まる。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
