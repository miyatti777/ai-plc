---
name: 03-construction-jev
description: 【実験版・Jev監視つき】ai_plc_construction - AI-PLC Stage 3。本体03-constructionに-jev表記と会話監視の有効化を足した薄いラッパー。
---

# AI-PLC Stage 3: Construction（Jev実験版）

> 🧪 **実験版（ai-plc-jev 1.8.1-exp.1）:** 手順は本体 `.claude/skills/ai-plc/03-construction/SKILL.md` を**そのまま読んで実行する**。本ファイルは差分だけを定義する。Constructionに Jev の判定は入れない（Agent定義の項目有無はコードで、中身は Stage 4 の独立reviewerで見るため）。

## 本体との差分
1. **Next Action のコピペ用プロンプト:** `/04-operation-jev` 形式で書く
2. **会話監視:** 会話監視 hook（`.claude/ai-plc-jev/scripts/jev_prompt_hook.py`）を settings に登録している場合だけ、このコマンドを `Layer: <パス>` 付きで打つと、そのセッションで会話監視が有効になる（登録手順は `.claude/ai-plc-jev/scripts/README_jev.md`）
