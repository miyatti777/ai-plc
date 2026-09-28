---
name: 02-inception-jev
description: 【実験版・Jev監視つき】ai_plc_inception - AI-PLC Stage 2。本体02-inceptionに、分解承認前のJev成功条件カバー判定と-jev表記を足した薄いラッパー。
---

# AI-PLC Stage 2: Inception（Jev実験版）

> 🧪 **実験版（ai-plc-jev 1.8.0-exp.1）:** 手順は本体 `.claude/skills/ai-plc/02-inception/SKILL.md` を**そのまま読んで実行する**。本ファイルは差分だけを定義する。

## 本体との差分
1. **Phase 4（分解承認）の直前:** intent.yaml が `jev_monitor: true` のとき、分解案を backlog.yaml（または一時ファイル）に書いた状態で `python3 .claude/ai-plc-jev/scripts/jev_coverage_check.py --layer <Layer> [--backlog <一時backlog>]` を実行し、出力の1行目を分解テーブルの直後に「🧭 Jev成功条件カバー判定」として示す。「対応しない可能性」が出た成功条件は、メインモデルが本当にタスクが欠けているかを判断し、欠けていれば分解案に追加するか理由を書く（ヒントに止める権限はない・自動でタスクを足さない）。スキップ・無効の場合はそのまま続行する
2. **判定の記録:** 承認時に、ヒントが妥当だったか（accept / reject）をユーザーに確認し `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <decision_id> accept|reject` で記録する（集計: `--noise-report --use-case coverage`）
3. **Next Action のコピペ用プロンプト:** `/03-construction-jev` 形式で書く（Re-Inception後も同じ）
4. **会話監視:** 会話監視 hook（`.claude/ai-plc-jev/scripts/jev_prompt_hook.py`）を settings に登録している場合だけ、このコマンドを `Layer: <パス>` 付きで打つと、そのセッションで会話監視が有効になる（登録手順は `.claude/ai-plc-jev/scripts/README_jev.md`）
