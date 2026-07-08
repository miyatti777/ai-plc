> 🏷️ **Type:** template (meta) — Stage 3 Constructionがタスク種類を判定し、適切なPhase構造とAgentテンプレートを選択するためのメタパターン

## タスク種類判定

| 種類 | 説明 | 必須出力 | Agentテンプレート |
| --- | --- | --- | --- |
| research | 調査・分析・リサーチ | 分析レポート + 知見 | TPL_research_agent |
| implementation | DB作成・システム構築・実装 | Databaseまたは動くシステム | TPL_implementation_agent |
| content | 記事執筆・プレゼン・ドキュメント | 完成コンテンツ | TPL_content_agent |
| operation | 量産実行・パターン適用 | 量産成果物 + Evalデータ | TPL_operation_agent |
| validation | 検証・評価・レビュー | 検証結果 + 改善計画 | 専用なし — research/implementationのPhaseに組み込み |
| planning | 計画・ロードマップ・合意形成 | 確定計画 + コミット | 専用なし — researchのPhaseに組み込み |

## 共通原則（全Agent生成時に適用）

1. HITL情報の拘束力 — Mob Checkpointやcontext.yamlで人間が明示指定した情報は「要件」として扱い、検索で見つかった類似情報より常に優先する
2. 出力の検証 — Agent完了前に、指定インプットを実際に使用したか、出力がインプットの規模・範囲と整合しているかを確認する
3. 出力エンティティの明確化 — 「Kanbanビュー/進捗管理」はDatabase+適切なビュー・プロパティ、「テンプレート/ガイド」はPageとして作る（ページ内の説明文・テーブルで代用しない）
4. 「動くシステム」ルール — implementationタスクは実際に動くDatabase/システムを生み出さなければ完了としない（設計書だけでは不可）

## 汎用検証ステップ（全Agent共通 — system §18連動）

全Agent生成時、Execution Flowの最終フェーズに検証ステップを必ず含める。Adaptive深度と連動: Simple→L1のみ / Standard→L1+L2 / Complex→L1+L2+L3。

| Level | 名称 | 確認内容 |
| --- | --- | --- |
| L1 | セクションチェック | 各パーツが単体で正しいか（論理・根拠・欠落） |
| L2 | 統合チェック | 全体の整合性（矛盾・流れ・トーン一貫性） |
| L3 | 受け手チェック | 受け手が見て価値があるか（理解・アクション可能性） |

検証タイミング: research=レポート完成後（セルフチェック+Mob）/ implementation=構築後（テスト実行+Mob）/ content=執筆後（セルフレビュー+Mobレビュー）/ operation=各量産サイクル後（Evalデータで自動判定）/ validation=検証自体が成果物のため不要。

## Phase構造の標準パターン

| パターン | 構造 | 適用 |
| --- | --- | --- |
| A: Autonomous+Mob交互型 | Autonomous → Mob → Autonomous → Mob → … | 標準。AIが自動処理し要所で人間確認 |
| B: エスカレーション型 | 設計 → Mob → DB作成 → ビュー追加 → データ投入 → Mob → ドキュメント | implementation向け。段階的に成果物を構築 |
| C: 量産実行型 | 変数バインド → Mob → Runtime Execution → Eval → 繰り返し | operation（Production Run）向け |
