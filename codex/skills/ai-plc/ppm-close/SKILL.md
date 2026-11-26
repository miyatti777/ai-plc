---
name: ppm-close
description: ポートフォリオ層の終業。その日の WillDo の実行率、振り返り（FUN・DONE・DONE（WillDo外）・LEARN・満足度）、未完了の行の扱い（繰り越し・TODO へ戻す・やめる）を利用者の OK の後に書き、続けて翌日の WillDo を組む。
---

# Codex adapter: ppm-close

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-close/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 置き場と行番号は共通の部品 `.claude/skills/ppm/ppm_files.py` で読む。振り返りの確認と未完了の行の扱いは Codex の質問UIで聞き、OK の前に書かない。やめる行は必ず確かめる。書くのは、その日の WillDo の振り返りと未完了の行の末尾の扱いの印、その日の日記の「緊急」の行の扱いの印（WillDo に同じ題名の行が無いものだけ）、「TODO へ戻す」と決めた行を足す TODO の一覧の雑務の節（案件そのものなら進行中の節）だけで、正本の「ストレージ操作」の形に従う。繰り越す行を翌日の日記には書かない。
3. 翌日の WillDo は `.claude/skills/ppm-plan/SKILL.md` の手順で組む（その案の OK は別に取る）。案内する入口は `$skill-name` に読み替えて示す。
4. 正本や共通の部品が欠ける場合は実行せず、欠落内容を報告する。
