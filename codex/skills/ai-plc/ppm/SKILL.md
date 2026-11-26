---
name: ppm
description: ポートフォリオ層の入口。依頼の目的から、日次の入口（状況確認・翌日の計画・差し込み・完了の反映・終業・TODO の見直し）や他の PPM スキル・AI-PLC の Stage のどれを使うかを1つ選び、既存の案件の再開も判定する。
---

# Codex adapter: ppm

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm/SKILL.md` を最後まで読み、その表から依頼に合う行き先を1つ選んで、その正本（`.claude/skills/<行き先>/SKILL.md`）だけを読んで実行する。部品（`ppm_files.py`・`ppm_route.py`・`templates/`・`README.md`）は `.claude/skills/ppm/` にある。
2. 行き先の `/ppm-*`・Stage・補助スキルは `$skill-name` に読み替えて示す。`ppm_route.py` が返す `prompt` は読ませる一文で、シェルで評価しない。
3. 元の依頼の範囲・途中の承認点を保ち、入口を使ったことや候補を出したことを、一覧の書き換え・外の収集の承認にしない。TODO の一覧が無いときは、雛形から作るかを本人に聞いてから作る。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
