---
name: plc-model-routing
description: AI-PLCのタスク内容に応じて担当モデルとAdvisor相談を選び、実行環境へモデル指定を渡す。モデル選択・相談の明示依頼またはmodel_routingを指定したLayer/Taskで使用する。
---

# plc-model-routing

1. リポジトリルートの `.claude/rules/ai-plc-model-routing.md` と対象Layerのintent、backlog Task/AC/guardrails、必要Contextを読む。新しいGoalや固定Stage別モデルを仮定しない。
2. Task本文から選択入力JSONをLayerのDocumentsへ保存し、`python3 .claude/skills/plc-model-routing/scripts/aiplc_model_routing.py --task <入力JSONファイル> --environment claude-code` で役割/model/effort/相談条件/理由を得る。既存Agent定義や本人のモデル指定をmodel_overrideとして優先する。CLIは選択と記録正規化のみで、モデル呼出や設定変更はしない。
3. 実在するモデル・tool引数・effort対応と既存の委譲/送信承認を確認する。許可された担当Agentのmodelまたはモデル指定CLIへ渡す。Advisorが必要なら別モデル相談役へ必要な問いと証拠を渡し、助言を担当へ戻す。利用不能や承認外なら理由と代案を提示し、黙って別モデルで実行しない。2失敗の停止を優先する。
4. 保存CLI記録は `python3 .claude/skills/plc-model-routing/scripts/aiplc_model_routing.py --record <run.json>` で正規化できる。推奨/要求/実使用を区別する。CCのmodelUsageなどruntime metadataが無ければ実使用はnull/未確認。effortも要求と実測を分ける。モデル自己申告から補完しない。
5. モデル選択根拠、Advisor入出力、成果物、AC、所要、取得可能usage/限界をTaskのDocuments実行記録へ残す。独立レビューは04-operation Phase5.5とBT checkerの正本契約を維持する。

Codexでは `.agents/skills/ai-plc/plc-model-routing/SKILL.md` の環境差分を適用する。
