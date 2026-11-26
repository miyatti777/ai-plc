---
name: ppm-status
description: ポートフォリオ層の状況確認。進行中の案件を TODO の一覧から、今日やることを WillDo と日記（緊急・WillDo に無い予定）から読み、First Task と自分が関わる未完了 Task の件数を添えて見せる。Layer のパスを渡したときだけ intent・backlog を見る。読み取り専用。
---

# Codex adapter: ppm-status

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-status/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 置き場と見出しは共通の部品 `.claude/skills/ppm/ppm_files.py`、件数は `.claude/skills/ppm-status/owner_open_count.py` で読む（どちらも読むだけ）。どのファイルにも書かない。
3. 案内する日次の入口・Stage・補助スキルは `$skill-name` に読み替えて示す。
4. 正本や共通の部品が欠ける場合は実行せず、欠落内容を報告する。
