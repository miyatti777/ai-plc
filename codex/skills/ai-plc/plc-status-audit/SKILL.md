---
name: plc-status-audit
description: AI-PLCのステータス点検（intent・backlog・Registry の食い違い）。「ステータス点検」「閉じ忘れ」で使用する。
---

# Codex adapter: plc-status-audit

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-status-audit/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 点検スクリプトは `.claude/ai-plc-jev/scripts/aiplc_status_audit.py`（Jev 実験版 `--with-jev` に同梱。CC 配置だけに入る）を使い、Registry は `.claude/db/ai_plc.db` を読む。スクリプトが無ければ正本のとおり「ステータス点検は Jev 実験版を入れたときだけ使えます」と伝えて止める。
3. 既定は読み取り専用。--apply … --yes はユーザーが承認した承認ファイルに対してだけ実行する。--jev は外部送信を伴うため、求められたときだけ使う。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
