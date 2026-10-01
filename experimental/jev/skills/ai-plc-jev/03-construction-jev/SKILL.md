---
name: 03-construction-jev
description: 【実験版・Jev監視つき】ai_plc_construction - AI-PLC Stage 3。本体03-constructionに-jev表記を足した薄いラッパー。
---

# AI-PLC Stage 3: Construction（Jev実験版）

> 🧪 **実験版（ai-plc-jev 1.12.0-exp.2）:** 手順は本体 `.claude/skills/ai-plc/03-construction/SKILL.md` を**そのまま読んで実行する**。本ファイルは差分だけを定義する。呼ぶ条件は本体と同じ（RUL_plc_adaptive §6。Agent 定義が要るときだけ）。Constructionに Jev の判定は入れない（Agent定義の項目有無はコードで、中身は Stage 4 の独立reviewerで見るため）。

## 本体との差分
1. **Next Action のコピペ用プロンプト:** `/04-operation-jev` 形式で書く
2. **会話監視（凍結中）:** 会話監視 hook は新しく登録しない。登録している場合は外してかまわない
