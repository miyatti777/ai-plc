---
name: ppm-capture
description: ポートフォリオ層の差し込みの入口。途中で出てきたやることを、今日（実害が出るときだけ・確認つき）・その日の日記・TODO の一覧（進行中か雑務）・いつかやる、に振り分けて1行で記録する。迷ったら明日。今日の WillDo には足さない。長い文脈の取り込みは扱わない。
---

# Codex adapter: ppm-capture

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-capture/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 置き場と節は共通の部品 `.claude/skills/ppm/ppm_files.py` で読み、無い日記は同じ部品の雛形（`load_template`）から作る。TODO の一覧が無いときは、作る前に利用者に聞く。いつかやるは `.claude/db/plc_query.py someday-add` だけで登録する。
3. 今日（緊急）に入れる前の確かめは、Codex の質問UIで1問ずつ行う。案内する入口は `$skill-name` に読み替えて示す。
4. 正本や共通の部品が欠ける場合は実行せず、欠落内容を報告する。
