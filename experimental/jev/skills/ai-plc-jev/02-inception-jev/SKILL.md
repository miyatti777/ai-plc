---
name: 02-inception-jev
description: 【実験版・Jev監視つき】ai_plc_inception - AI-PLC Stage 2。本体02-inceptionに-jev表記を足した薄いラッパー（成功条件カバー判定は凍結中）。
---

# AI-PLC Stage 2: Inception（Jev実験版）

> 🧪 **実験版（ai-plc-jev 1.12.0-exp.2）:** 手順は本体 `.claude/skills/ai-plc/02-inception/SKILL.md` を**そのまま読んで実行する**。本ファイルは差分だけを定義する。

## 本体との差分
1. **（凍結中・実行しない）成功条件カバー判定:** 1.12.0-exp.2 から凍結中。`jev_coverage_check.py` は呼ばない（`jev_monitor: true` でも）
2. **（凍結中）カバー判定の記録:** 1 を呼ばないので記録もしない。過去のカバー判定の未確認分は 5 で回収できる
3. **Next Action のコピペ用プロンプト:** `construction.required` で `/03-construction-jev` または `/04-operation-jev` を選んで書く（Re-Inception後も同じ）。Phase 6 の「自動で進めるなら」の /goal 1行も、開始列を -jev 版のコマンドにする（`pipeline_variant: jev`）
4. **会話監視（凍結中）:** 会話監視 hook は新しく登録しない。登録している場合は外してかまわない
5. **未確認の判定の回収（`jev_monitor: true` の Layer だけ）:** 承認・完了報告の進捗表示に `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --pending --layer <Layer>` の件数を「🧭 未確認の Jev 判定: N件」として出し（0件なら 0件と出す）、Next Action のコピペ用プロンプトは**すべての選択肢**にその出力の「貼り付け用」1行を含める（記憶で書かない。0件なら書かない）。利用者の返答に「Jev判定 X・Y は accept」「全部accept」等があれば、示した貼り付け用1行の ID だけを `--only` に渡して `--override-pending accept|reject --layer <Layer> --only X・Y [--except <ID> ...]` で記録する（示した後にできた判定は記録しない）。記録はタスクの実行より先に行う
