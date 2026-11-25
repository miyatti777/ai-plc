---
name: ppm-scan
description: ポートフォリオ層。依頼された範囲の Notion・本人の公開 Slack 発言と関連する返信から、まだ一覧に無い案件の候補を根拠つきで1回だけ集め、収集メモにする（メモを返すところまで）。
---

# Codex adapter: ppm-scan

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-scan/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. connector・API は、この Codex 環境で使える読み取りの道具に置き換える。使えないものは「未取得」として返す。
3. 書いてよいのは収集メモ1つだけ。TODO の一覧・backlog・Registry・Notion・Slack は変えない。定期の収集は設定しない。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
