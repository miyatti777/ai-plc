---
name: ppm-pmo
description: 複数案件を横断するPMO業務（週次状況整理・案件間依存・共有資源の競合・共通課題・責任者向け報告・決定の案件別引継ぎと反映確認）。
---

# Codex adapter: ppm-pmo

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-pmo/SKILL.md` を最後まで読み、その手順を正本として実行する。正本の `<SKILL_DIR>` は `.claude/skills/ppm-pmo` と読む。
2. 補助スクリプトは正本の `scripts/portfolio.py`・`scripts/readback.py`（読み取り・判定のみ。出力は指定した新しいフォルダにだけ書く）を使う。
3. 案件の正本・計画を書き換えない。責任者の判断と送信は人が行う。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
