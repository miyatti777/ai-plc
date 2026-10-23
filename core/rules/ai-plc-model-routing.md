> 🏷️ **Type:** rule / **Context:** タスク別モデル選択・Advisor相談の共通契約
> **Updated:** 2026-10-14（既定: Operation は Opus）/ 2026-10-02 / **Evidence:** 固定架空課題・既存ログインでのCLI試行、Codex での Operation の実測

# AI-PLC モデル選択とAdvisor

## 発動

**実行環境の既定（2026-10-14。下の発動条件に関わらず常に適用）:** 本人のモデル指定が無いとき、Operation（/04-operation の Phase 4 実行と Phase 5.5 の修正）は **Claude Code の Opus**（effort は下表の deep 行＝low を既定）で行い、下のルーティング推奨（fast/standard）より優先する。Codex（gpt-6.1-sol・gpt-6-astra 等の全モデル）は Collection・調査・読取専用スキル（plc-brief / plc-consult / plc-next / plc-status-audit）を既定の範囲とする。**Codex で /04-operation を求められたら:** 本人のモデル指定が無ければ Claude Code への切替を案内して止まり、本人が Codex での実行を明示したときだけそのモデルで続行する（既定の上書き。「ユーザー指定モデルを優先する」）。根拠: Codex で Operation を実行した1件の Layer の実測（executor codex・本人申告では gpt-6.1-sol。3タスクで backlog 5,410 行・Documents 145・消費 1,248 分・2タスク blocked・成果 0）。1件の実測なので一般化せず、見直しは2環境比較の結果で行う。

本人がモデル選択/Advisorを依頼したとき、またはintent/backlogのLayer/Taskに `model_routing: true` を明示したときに適用する。TaskのfalseはLayerのtrueを上書きする。指定なしは既存の実行方法を維持する（ただし上の「実行環境の既定」は model_routing の指定に関わらず適用する）。親セッションの既定モデルやユーザー設定は書き換えない。

Operation Phase 3でTask/Contextを読み、Phase 4の担当実行前に適用する。ConstructionのAgentが無くても同じ入口を使う。Agent定義等に既存モデル指定があれば `model_override` として優先する。

## 選択入力と共通CLI

Taskの本文/AC/guardrailsから曖昧さ `ambiguity`、複雑さ `complexity`、変更影響 `impact` をlow/medium/highで判定し、機械的に検証できるかを `verifiable` booleanにする。Stage名は選択条件にしない。欠測はstandardである。判断根拠はTaskの実行記録に残す。

JSONファイル例:

```json
{"ambiguity":"low","complexity":"low","impact":"low","verifiable":true,"failed_attempts":0}
```

```bash
python3 .claude/skills/plc-model-routing/scripts/aiplc_model_routing.py --task <task-input.json> --environment claude-code
python3 .claude/skills/plc-model-routing/scripts/aiplc_model_routing.py --task <task-input.json> --environment codex
```

入力の任意項目は `model_override`、`effort_override`、`failed_attempts`。指定モデルのeffortが不明ならnullとし、サポートを確認してから渡す。Pythonのrecommend関数には `available_models` を渡せる。CLIのreadyは利用可能性の実機確認を意味しない。

- 全てlowで機械検証可能ならfast。
- 変更影響highまたは人の判断だけで検証する仕事はdeep。
- 他はstandard。曖昧さ/複雑さhigh、または失敗1回ならdeepのAdvisorを付ける。
- 失敗2回ではstop。既存の「2回で停止」を昇格や別モデル再試行で回避しない。
- ユーザー指定モデルを優先する。利用不能時はunavailableとして理由を記録し、明示した代案を選ぶ。黙ってfallbackしない。

2026-10-02の初期対応（最適性の証明ではない）:

| 役割 | Claude Code model / effort | Codex model / effort |
| --- | --- | --- |
| fast | haiku / low | gpt-6-luna / high |
| standard | sonnet / medium | gpt-6.1-sol / medium |
| deep / Advisor | opus / low | gpt-6-astra / low |

ローカル試行で指定と応答を確認した組み合わせ。モデル名/effortは環境間の共通尺度ではなく、利用可能性やモデルの更新時には小さく再確認する。

## 実行環境へ渡す

モデル指定は実在するtool/CLI引数へ渡す。CCはAgent toolのmodelまたはモデル指定CLI、Codexはspawn_agentのmodel/reasoning_effortまたは `codex exec --model` 等。実行前に環境のtool schema/CLI helpとモデルの対応effortを確認する。CCのAgent toolにeffort引数が無ければ指定したと報告せず、inherit/未確認を記録する。

Codexでモデルoverrideが必要ならfull-history forkを使わず、Taskと必要入力を明示する。担当/Advisorの成果物作成委譲は本人または適用指示が許可する範囲のみ。追加の外部送信・モデル呼出・費用・永続設定変更の権限をこの規約から増やさない。モデル指定CLIの実行を、現在の親チャットの自動切替と報告しない。

## Advisorと独立検証

Advisorには判断を要する問い・Goal・必要な証拠だけを渡し、担当が助言を受け取って続ける。共通の別モデル相談を基本経路にする。CC native Advisorを使う場合は全会話が渡るという違いを明示する。初期の試行ではnative機能の実機成立や親切替を試していないため、共通CLI相談の結果から成立を推定しない。

Advisorは作成側であり独立reviewerではない。04-operation Phase 5.5・BT-B/BT-Cの、成果物とGoal/ACのみの入力・read-only・snapshot・P0-P3報告・未解決P0-P2ゼロ・全AC達成の完了ゲートを維持する。Advisorへ相談した事実で独立checkerを省略しない。

## 記録と未取得値

TaskのDocuments実行記録に `environment / recommended_role / recommended_model / requested_model / actual_model / actual_model_status / actual_model_evidence / requested_effort / observed_effort / selection_reason / advisor_kind / advisor_model / consultation_evidence / fallback_reason / output_path / ac_verdict / duration_seconds / usage / evidence_limits` を分けて残す。取得できない値はnullと理由を記す。

保存CLI記録はenvironment、exit_code、stdout、requested_model、requested_effort、duration_secondsを持つJSONとし、次で正規化できる。このコマンドは外部呼出をしない。

```bash
python3 .claude/skills/plc-model-routing/scripts/aiplc_model_routing.py --record <saved-run.json>
```

CCでは消費tokenがあるresult.modelUsageのIDを実使用の根拠とする。複数モデルならactual_modelsを保存し単一のactual_modelは確定しない。Codex 0.159.2のexec JSONではserved-model IDを取得できなかった。モデル自己申告やconfig/要求値だけでactual_modelを埋めず、null / unverified（未確認）を残す。未取得を明示した導入・利用は可能だが、特定モデルの実使用確認を要求する個別ACは未確認のまま通さない。

usageはAdvisor/ハーネス固定contextを含む範囲を明記する。CCのlist-price estimateをsubscription実請求額と扱わず、少数試行から一般的な費用・速度・品質の優越を主張しない。
