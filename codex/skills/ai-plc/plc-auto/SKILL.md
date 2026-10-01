---
name: plc-auto
description: 固定Goalをnative Goalに設定し、この会話のAI-PLC Layerを自動完走する。利用者が $plc-auto の開始を明示した場合に使う。
---

# Codex adapter: plc-auto

このSkillは明示実行によるnative Goalの専用入口。通常Stageの待機は変更しない。

1. リポジトリルート基準で `.claude/skills/plc-auto/SKILL.md`、`references/goal-preset.md`（同Skillディレクトリ内）、`.claude/rules/ai-plc-system.md`、`ai-plc-session.md`、`ai-plc-adaptive.md` の存在・可読性を確認する。欠落があればパスを報告して停止する。
2. 上記3 RulesとSkill正本を最後まで読む。固定Goalは正本から読む。
3. 正本の手順で実際のGoal機能を確認し、利用者の明示実行の場合だけ設定する。通常Stageの「Goalを作らない」はこの専用入口には適用しない。引用・編集・説明では起動しない。
4. Stageの `/01-collection`〜`/04-operation` は `$01-collection`〜`$04-operation` へ読み替え、実行Stageの正本を読む。未承認の外部送信・公開・既存Goal上書きをしない。
