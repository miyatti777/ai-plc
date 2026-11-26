---
name: ppm-todo
description: ポートフォリオ層・TODO の一覧の見直し。Layer と TODO の一覧の差分と、待ち／要確認の行の見直しを提案し、本人が承認した行だけを一覧に書く。最後に今の状況をまとめる。WillDo には足さない。
---

# Codex adapter: ppm-todo

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-todo/SKILL.md` を最後まで読み、その手順を正本として実行する。置き場と節の名前は `.claude/skills/ppm/ppm_files.py`（設定 `.ai-plc/config.yaml` の `ppm:`）で決まる。
2. 道具は正本のもの（`.claude/skills/ppm-inflight/list_inflight.py`、`.claude/skills/ppm-todo/inflight_programs.py`・`todo_waiting.py`・`todo_summary.py`）を使う。書くのは本人が承認した行だけで、待ちの行は `todo_waiting.py --apply <承認ファイル> --write`、進行中の行は承認の後に編集で書く。承認ファイルはリポジトリの外に置く。
3. 本人の承認を待つ所では止まる。WillDo・Layer・Registry・外のサービスには書かない。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
