> 🏷️ **Type:** template (agent generation) — 調査・分析・リサーチ系タスク（市場調査・競合調査・ペルソナ・リスク分析・技術調査等）のAgent定義生成用

## Agent定義の標準構造

- Goal: 「[Subject]について調査・分析し、[Deliverable]を作成する」
- Input: 調査対象（Subject）、調査の目的・角度（Focus）、参照コンテキスト（Context Store）、出力形式の指定（レポート/テーブル/図）
- Output: 分析レポート、知見サマリ（Context Storeに追加）、次アクション提案
- frontmatter（必須）: name（kebab-case）/ description / tools（最小権限）/ delegable（FlowにMob CPを含むならfalse）を先頭に付与（03-construction v2.1）

## Execution Flow

| Phase | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. スコープ定義 | Mob | 調査範囲・角度・深さを確認 | 調査計画 |
| 2. 情報収集 | Autonomous | WS検索・Web検索・Context Store参照 | 収集結果 |
| 3. 分析・構造化 | Autonomous | 収集情報を分析・フレームワーク適用 | 分析ドラフト |
| 4. レビュー | Mob | 分析結果の確認・追加調査の指示 | フィードバック |
| 5. 最終化 | Autonomous | フィードバック反映・最終レポート作成 | 確定版レポート |

## Guardrails

- 調査範囲が明確でない場合はPhase 1で確認必須
- Web検索結果は必ず出典を明記
- 定量データはソースと時期を明記

## 生成時の調整ポイント（Phase 3のフレームワーク選択）

| タスク種類 | 適用フレームワーク |
| --- | --- |
| 市場規模推定 | TAM/SAM/SOM |
| 競合調査 | 競合比較マトリクス |
| ペルソナ作成 | ペルソナテンプレート構造 |
| 課題定義 | 問題ツリー / 因果関係図 |
| 仮説マップ | 仮説検証マトリクス |
| リスク分析 | リスクマトリクス（影響×確率） |
