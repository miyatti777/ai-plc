---
name: 01-collection
description: ai_plc_collection - AI-PLC Stage 1。Execution Contextを確立し、外部・内部情報源からコンテキストを収集・構造化する。
---

# AI-PLC Stage 1: Collection

パイプライン（Collection → Inception → Construction → Operation）の初期化ステージ。Goal と Mode を受け取り、Execution Context（Scope）を確立し、Context を収集・構造化する。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7（4パート）/ Phase遷移通知は §8 / Mob CP出力は §9 に従う。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| goal | ✅ | 達成すべき目標の自然言語記述 |
| mode | ⭕ | direct / platform_builder（デフォルト: direct） |
| owner / deadline | ⭕ | デフォルト: 現在のユーザー / +30d |
| parent_scope | ⭕ | 親ScopeのURL/パス。Sub-Agent Scope作成時に指定 |
| scope_name | ⭕ | デフォルト: Goalから自動生成 |

## 実行フロー

### Phase 0: Scope判定

- parent_scope なし & 既存Scope指定なし → `pipeline_init`（新規パイプライン）
- parent_scope あり → `sub_agent_scope`（親配下のsublayers/に作成、親Context継承）
- 既存Scope指定あり → `scope_reinit`（構造・成果物を保持してIntent/Manifestを更新）

### Phase 1: Adaptive Workflow深度判定

RUL_plc_adaptive §1 に従い simple / standard / complex を判定し、結果と根拠をユーザーに報告する（変更指示があれば従う。停止はしない）。深度はintent.yamlに記録する。

### Phase 2: ディレクトリ構造生成

`Flow/[YYYYMM]/[YYYY-MM-DD]/[Scope名]/` に作成（既存Flowを使用。日付フォルダは当日分を使用、なければ作成）:

```
[Scope名]/
├── intent.yaml / context.yaml / backlog.yaml（空で初期生成）
├── Context/      （Context Store）
├── Agents/       （Stage 3で生成）
├── sublayers/    （Stage 2で生成）
└── Documents/    （Stage 4で生成）
```

sub_agent_scope時は親の `sublayers/` 配下に同構造。scope_reinit時は既存構造を維持。

### Phase 3: Intent生成（intent.yaml）

```yaml
scope_id: "L-MMDD"            # 自動採番（重複時は L-MMDD-2 等。Sub: L-MMDD-SG1）
scope_name: "[Scope名]"
status: active
workflow_depth: standard      # Phase 1の判定結果
goal:
  description: "[Goal]"
  success_criteria: []        # Context収集後に設定
mode: direct                  # direct / platform_builder
owner: "[Owner]"
deadline: "YYYY-MM-DD"
parent_scope: null
sub_agent_scopes: []          # Stage 2で生成
sync_targets: []              # Phase 6.5で設定（スキーマ: RUL_plc_system §9）
```

### Phase 3.5: Project Registry登録

`.claude/db/ai_plc.db` の `projects` テーブルに登録（scope_id/name/goal/owner/status=active/mode/depth/system=AI-PLC/parent_scope/top_page_url/start_date/deadline）し、「📊 Project Registryに登録しました」と通知する。scope_reinit時はスキップ。

### Phase 4: Context Collection

1. ワークスペース検索で関連情報を収集（優先順位: RUL_plc_system §16）
2. Standard/Complex では外部情報源（Web検索等）も活用
3. sub_agent_scope では親のContext Storeを読み込み、Context Cascade 3分類（RUL_plc_system §2）で継承
4. `Context/` にカテゴリ別ドキュメントとして格納（例: 01_チーム構成.md, 02_関連リンク集.md, 03_技術スタック.md, 04_制約条件.md — Goalに応じて調整）

### Phase 5: Context Manifest生成（context.yaml）

```yaml
version: "1.0"
scope_id: "L-MMDD"
generated_at: "YYYY-MM-DD"
parent_context_store: null      # sub_agent_scope時は親Context/のパス
context_documents:
  - name: "[カテゴリ名]"
    url: "@Context/01_[カテゴリ].md"
    summary: "[3-5行の要約]"
inheritance_rules:
  global_immutable: ["vision", "tech_stack"]
  overridable: ["deadline", "budget"]
  local_only: ["team", "tools"]
```

### Phase 6: Parameter Store生成 [platform_builder時のみ]

変数化可能なポイントを特定し `variables.yaml`（variables: 型/説明/必須/デフォルト + variable_mappings: task_id→変数）を生成する。direct時は作成しない。

### Phase 6.5: External Sync設定

intent.yamlのsync_targetsを設定する: ユーザー指定の同期先があればそれを、なければデフォルト（`.claude/db/ai_plc.db` の tasks テーブル、auto_create: true, push — RUL_plc_system §9）を自動設定し、「📊 External Sync設定: [設定内容]」とログ出力する。ユーザーが「同期不要」と明言した場合のみ `[]` のまま。

### Phase 7: Mob Checkpoint（停止）

ここで必ず停止し、ユーザーの応答を待つ:

1. 作成した構造と深度判定結果を確認表示
2. RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を出力
3. Next Action: A=/02-inception 実行（⭐推奨） / B=Context追加修正（+コピペ用プロンプト。表記は RUL_plc_session §7.4「実行形式は環境の正」。即実行禁止）

## Re-Collection（Backtrack対応）

BT-B（ゴールドリフト）/ BT-C（全完了GAP分析）から scope_reinit で呼び出される再実行モード（RUL_plc_adaptive §5）:

1. 既存intent.yamlを読み込み、Backlog完了実績 vs 元ゴールの到達度を分析
2. GAP分析（達成済み / 未達成 / 新規発見）を表形式で出力
3. 判定: GAPなし→完了推奨 / GAPあり→Intent.goal更新+Re-Inception推奨 / ドリフト→ゴール再定義+追加Context収集
4. ゴール変更時はContext Store追加収集 + Manifest更新

## 出力

intent.yaml / context.yaml / Context/（常に） / backlog.yaml（空で初期生成） / variables.yaml（platform_builder時のみ）→ Stage 2: SKL_plc_02_inception へ。

---
**作成日:** 2026-04-06 ｜ **更新日:** 2026-07-07 ｜ **バージョン:** 2.0（Fable観点軽量化: 指示形1本化。Wiki波及はOperation Propagationに一本化し本スキルから削除）
