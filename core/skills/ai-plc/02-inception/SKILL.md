---
name: 02-inception
description: ai_plc_inception - AI-PLC Stage 2。Goalを分析し、BacklogとSub-Agent Registryを生成する。
---

# AI-PLC Stage 2: Inception

Goalを分析し、Sub-Agent Scope（SubLayer）とTask（実行単位）に再帰的に分解するステージ。Sub-Agent Scopeが生成されると、そのスコープ内でStage 1から再びパイプライン全体が展開される（Fractal Decomposition）。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7 / Phase遷移通知は §8 / Mob CP出力は §9 に従う。

**自動完走モード:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Mob Checkpoint・Next Action・タスク選択で待たずに進める（無ければ本 SKILL のとおり止まる）。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| Intent + Context Manifest + Context Store | ✅ | Stage 1の生成物 |
| decomposition_strategy | ⭕ | product_manager / system_architect / content_strategist / tech_lead / generic。デフォルト: AI自動判定 |

## 実行フロー

### Phase 1: Auto-Research

intent.yaml / context.yaml / Context Store を読み込み、Goal達成に必要な追加情報をワークスペース/Web検索で収集する。

### Phase 2: Decomposition Strategy選択

Goalの性質から最適な戦略を判定する（ユーザー指定があれば優先。判定結果を報告して続行）:

| 戦略 | 適用 | 分解の特徴 |
| --- | --- | --- |
| product_manager | プロダクト開発・改善 | Discovery→Delivery、MVP思考 |
| system_architect | システム構築・基盤整備 | 設計→実装→運用、モジュール分割 |
| content_strategist | コンテンツ制作・発信 | 企画→制作→配信 |
| tech_lead | コーディングPJ（複数実装タスク） | Adaptive Skip判定 + SubLayer分割 |
| generic | その他 | Contextから動的判断 |

### Phase 3: Goal分解

Goalを2種に分類する:

- **SubLayer化:** 複数Taskで構成 / 独自Contextが必要 / 他者に委譲可能 / 独立スケジュール → 再帰展開（詳細タスクは親で作らない。親のmodeを継承）
- **Task化:** 1-2日で完結 / これ以上分解不要 / 管理・調整系

### Phase 4: Mob Checkpoint — 分解承認（停止）

ここで必ず停止し、承認を待つ（タスク数が少なくても省略しない）:

1. SubLayer/Task分解テーブル（ID・名称・type・priority・依存・見積・AC の要点・Agent 定義の要否〔要なら理由＝RUL_plc_adaptive §6 の①〜⑤〕）を提示
2. セッション分割判定（SubLayer≥3 or Task≥10 → RUL_plc_session §1に従い分割推奨を明記）
3. 承認後フロー1行 + 🙋承認待ちブロック（OK / 修正: [指示] / 差し戻し）

### Phase 5: Backlog + Sub-Agent Registry生成

承認後、backlog.yaml を生成する:

- **全タスク必須フィールド:** `id` / `name` / `description` / `type` / `priority` / `status` / `owner` / `estimated_hours` / `command` / `origin`（commandはmanagement系タスクのみnull可）、standard 以上は `acceptance_criteria`（検証できる形のリスト）。任意: `guardrails`（タスク固有の禁止事項・途中で人に確認する点）/ `delegable`（既定 false。true は途中で人の確認が要らないタスクだけ）/ `command_template_ref`（Agent 定義を作ったときだけ。Construction が書く）
- **トップレベル必須:** `focus_strategy` / `focus_strategy_reason` / `focus_strategy_confirmed_by` / `decomposition_pattern` / `sublayers` / `tasks` / `summary`（task_count / p0_tasks / p1_tasks / p2_tasks / next_action）/ `construction`（required / reason / tasks — RUL_plc_adaptive §6）。任意: `decisions`（Layer 共通の決めごと・禁止事項）
- 再分解があった場合は `refactoring_log` も記録
- SubLayerがあれば `sublayers/` にフォルダを作成し、各SubLayerに「次のステップ」（Collection起動プロンプト）を含める

### Phase 5.5: 外部実行タスク判定

各タスクを判定する: ✅PJ内実行→そのまま / 📤外部委譲（別の実行者がやるべき）→ Self-Describing Task構造（RUL_plc_system §9）でチケット化し「外部DBに書き出しますか？」と確認→承認後push / ⏳先送り→`deferred`ステータスで残す。

### Phase 6: Mob Checkpoint — 次ステージ提案（停止）

ここで必ず停止し、RUL_plc_session §7 の4パートを出力する。Next Action: SubLayerあり→各SubLayerの /01-collection 起動案内 / Tasksのみ→ `construction.required` が true なら /03-construction、false なら /04-operation を案内（表記は §7.4「実行形式は環境の正」。RUL_plc_adaptive §6）。Tasksのみのときは、完了報告の最後に「自動で進めるなら:」として RUL_plc_session §10 の短い版 /goal（Layer パスと開始列を埋めたもの）を1行出す（止まる挙動は変えない。workflow_depth が complex か mode が platform_builder の Layer では出さず「自動完走の対象外（理由）」を1行出す）。

## Re-Inception（Backtrack対応）

BT-A（ブロッカー）/ BT-B（節目再評価）から呼び出される差分再分解モード（RUL_plc_adaptive §5）:

1. 既存backlog.yamlを読み込む（completedタスクは保持）
2. トリガー原因を分析し、差分のみ実施: タスク追加（新ID採番）/ 修正（description・priority・dependencies更新）/ 削除（statusを`cancelled`に。物理削除しない）
3. refactoring_log に date / trigger / reason / changes を記録。タスクを足した・変えたときは `construction` を判定し直す（足したタスクが条件に当たれば tasks に加え、Next Action は /03-construction）
4. 差分テーブル（操作/タスクID/内容/理由）を提示して承認を待ち、承認後にbacklog.yamlを更新

## 出力

backlog.yaml（常に） / sublayers/（SubLayer生成時） → Stage 3（要るときだけ）または Stage 4 へ。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-01 ｜ **バージョン:** 2.1（冒頭に自動完走モードの1行・Phase 6 に自動で進める /goal を1行出す〔RUL_plc_session §10〕／Construction を既定で省く対応: 分解テーブルに AC の要点と Agent 定義の要否・acceptance_criteria・guardrails・delegable・decisions・トップレベルの construction・Phase 6 は construction.required で次を決める〔RUL_plc_adaptive §6〕）｜ 2.0（Fable観点軽量化: 指示形1本化、Re-Inceptionを差分実行に圧縮）
