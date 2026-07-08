> 🏷️ **Project:** \[YOUR_PROJECT\]
> **Type:** rule
> **Context:** AI-PLC Adaptive Workflow ルール。ワークフロー深度判定・モード判定・Next Action自動提案・Backtrack（方向適応）を定義。

## 1. Adaptive Workflow深度判定（全PJ共通）

Stage 1（Collection）で自動判定し、intent.yamlに記録する。コーディングに限らず全タスクに適用。検証レベル（RUL_plc_system §18）と連動する。

| 深度 | 判定条件 | パイプライン挙動 | 検証 |
| --- | --- | --- | --- |
| **simple** | 単一タスク・明確なゴール・既知パターン・1-2日以内 | Stage 1→4直行（2-3スキップ） | L1のみ |
| **standard** | 複数タスク・タスク分解が必要・SubLayerなし | 全4ステージ順次実行 | L1+L2 |
| **complex** | 再帰的分解・SubLayer生成・チーム連携 | 全4ステージ + SubLayer再帰 + NFR | L1+L2+L3 |

- workflow_depthは必ず `simple` / `standard` / `complex` の3値（非スキーマ値禁止）
- 判定結果はユーザーに報告する（変更指示があれば従う）
- Simple深度でStage 2-3をスキップする場合、backlog.yamlのrefactoring_logに理由を記録する
- ロール別の詳細判定基準は templates/roles/TPL_role_* に定義

## 2. モード判定

| モード | 条件 | 挙動 |
| --- | --- | --- |
| **direct** | 一度きりの実行（設計・分析・調査等） | Stage 1-4で完了 |
| **platform_builder** | 繰り返し実行する仕組みの構築 | Stage 1-4 + Production Skill生成→量産（04-operation/platform-builder.md参照） |

## 3. Next Action自動提案

各スキル完了時に次アクションを判定し、RUL_plc_session §7.4の形式で提案する。

| 現在の状態 | Next Action |
| --- | --- |
| Stage 1完了 | Stage 2（Inception） |
| Stage 2完了 | Stage 3（Construction）※Standard以上は唯一の推奨（§6） |
| Stage 3完了 | Stage 4（Operation）P0タスクから |
| Stage 4タスク完了（残あり） | 次の実行可能タスク |
| Stage 4全完了（direct） | パイプライン完了（BT-C判定 → GAP分析提案） |
| Stage 4全完了（platform_builder) | Production Skill生成→量産へ |
| 既存Layer再指定 | Update mode（scope_reinit）で再初期化 |

## 4. Focus Strategy（視点選択）

Stage 1でGoalの性質から自動判定し、templates/roles/ から読み込む。

| Goal性質 | 推奨Role | キーワード |
| --- | --- | --- |
| プロダクト開発 | ROL_plc_product_manager | 機能、UX、ユーザー |
| システム構築 | ROL_plc_system_architect | DB、API、設計 |
| コーディング | ROL_plc_tech_lead / developer | 実装、修正、リファクタ |
| コンテンツ制作 | ROL_plc_content_strategist | 記事、ブログ |
| その他 | ROL_plc_generic | 上記以外 |

## 5. Adaptive Direction — Backtrack（3トリガー）

パイプライン進行中に前ステージへの戻りを検知・提案する仕組み。トリガーは3種に統合（旧BT-1〜10の対応を併記）。

| ID | トリガー | 検知タイミング | 検知条件 | 提案 → 戻り先 | 旧ID |
| --- | --- | --- | --- | --- | --- |
| **BT-A** | ブロッカー | Phase 5.5b（タスク単位） | 検証でcritical NG / 外部依存未解決 / 設計前提との矛盾 / 検証カバレッジ不足 | Re-Inception（修正・検証・依存タスクの差分追加）→ Stage 2 | 1,2,5,6 |
| **BT-B** | 節目再評価 | Phase 6b（パイプライン単位） | 完了率50%到達 / ゴールドリフト兆候（完了5超 or ad-hoc 2件以上） / Conditional Go残 | Re-Inception（残タスク再評価） or Re-Collection（ゴール再確認）→ Stage 2 or 1 | 3,4,8 |
| **BT-C** | 全完了GAP分析 | Phase 6b | backlog全タスクcompleted | Re-Collection(GAP分析 → 完了宣言 or 追加ゴール）→ Stage 1 | 7 |

会話中の監視（旧BT-9/10）: ユーザーの進捗訂正や「〜が足りない」等の新事実が出たら、軽量Re-Inception / Re-Collectionを**1行ヒントで提案のみ**行う（ユーザーが「このまま続行」を選んだら同一トピックで再提案しない）。

**実行ルール:**
1. Backtrackは必ずユーザー承認後に実行（自動実行禁止）
2. Next Action Protocolの追加選択肢（D: Re-Inception / E: Re-Collection）として提示。該当なしの場合は出力しない
3. 戻り先Stageは scope_reinit モードで実行（既存成果物を保持）
4. 理由をbacklog.yamlのrefactoring_logに記録する

## 6. Stage 3 必須ルール（Standard以上）

workflow_depth が standard / complex の場合、Stage 3（Construction）は必ず経由する（スキップ禁止）。Stage 2完了時のNext ActionでStage 4直行の選択肢を提示しない。simple のみ Stage 1→4 直行を許可。Agent定義ティア（Lite/Full）は自動判定されるためオーバーヘッドは小さい。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-07-07 ｜ **ステータス:** Active
**バージョン:** 2.0（Fable観点軽量化: BT-1〜10を BT-A/B/C に統合、会話中監視は提案のみの1行ルール化）
