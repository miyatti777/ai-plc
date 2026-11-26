---
name: ppm-update
description: ポートフォリオ層の日次の画面（その日の WillDo）を、終わった仕事に合わせて更新する。載っている行は [x] にし、載っていない今日の完了は振り返りの DONE（WillDo外）に書く。今日のリストに行は足さない。
---

# Codex adapter: ppm-update

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-update/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 置き場と行番号は共通の部品 `.claude/skills/ppm/ppm_files.py` で読む。書くのはその日の WillDo の決めた行（完了の印と振り返りの「DONE（WillDo外）」）、その日の日記の「緊急」の行の完了の印、First Task の印だけで、正本の「ストレージ操作」の形に従う。5つの欄と日記に行は足さない。
3. 案内する日次の入口は `$skill-name` に読み替えて示す。
4. 正本や共通の部品が欠ける場合は実行せず、欠落内容を報告する。
