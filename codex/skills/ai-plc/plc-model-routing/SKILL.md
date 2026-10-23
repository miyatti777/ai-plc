---
name: plc-model-routing
description: AI-PLCのタスク内容に応じた担当モデルとAdvisor相談を、共通正本に従ってCodexで選択・実行する。モデル選択・相談の明示依頼またはmodel_routingを指定したLayer/Taskで使用する。
---

# Codex adapter: plc-model-routing

1. [Codex実行環境の読み替え](../references/codex-runtime.md) とリポジトリルートの `.claude/skills/plc-model-routing/SKILL.md`、そこで指定する共通ruleを読む。手順と完了条件は正本を使う。
2. 共通CLIのTask選択では `--environment codex` を使い、現在のtool schema/CLI helpで実在するmodel/推論強度を確認して渡す。モデルoverrideのあるspawn_agentはfull-history forkを使わず、Taskと必要入力を明示する。担当/Advisorの成果物作成委譲は明示承認の範囲に従う。
3. 現行exec JSONからserved-model IDが取得できなければactual_model=null/未確認を残す。requested model、設定、自己申告から補完しない。親チャットを自動切替済みとは報告しない。`--record` で保存CLI記録を正規化できる。
4. Advisorと独立reviewerを分ける。04-operationとBT checkerの契約は正本のまま維持する。
