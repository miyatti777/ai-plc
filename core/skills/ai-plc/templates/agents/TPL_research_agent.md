> 🏷️ **Type:** template (agent generation)

  **CC対応:** `.claude/skills/templates/research_agent.md`

  **旧AIPO:** `Research_templates` + `Discovery_templates` + `project_management_templates`の調査系

  **役割:** 調査・分析・リサーチ系タスクのAgent定義を生成する際のテンプレート

---

## 対象タスク例

- 市場規模推定・競合調査・顧客調査
- ペルソナ作成・課題定義・仮説マップ
- プロダクトポジションステートメント
- リスク分析・ステークホルダー分析
- 技術調査・ベンチマーク

---

## Agent定義の標準構造

### Goal

「[Subject]について調査・分析し、[Deliverable]を作成する」

### Input

- 調査対象（Subject）
- 調査の目的・角度（Focus）
- 参照すべきコンテキスト（Context Storeから）
- 出力形式の指定（レポート / テーブル / Mermaid図 等）

### Output

- 分析レポート（Notionページ）
- 知見サマリ（Context Storeに追加）
- 次アクション提案

### Execution Flow（標準Phase構造）

| Phase | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. スコープ定義 | Mob | 調査範囲・角度・深さを確認 | 調査計画 |
| 2. 情報収集 | Autonomous | WS検索・Web検索・Context Store参照 | 収集結果 |
| 3. 分析・構造化 | Autonomous | 収集情報を分析・フレームワーク適用 | 分析ドラフト |
| 4. レビュー | Mob | 分析結果の確認・追加調査の指示 | フィードバック |
| 5. 最終化 | Autonomous | フィードバック反映・最終レポート作成 | 確定版レポート |

### Guardrails

- 調査範囲が明確でない場合はPhase 1で確認必須
- Web検索結果は必ず出典を明記
- 定量データはソースと時期を明記

---

## バリエーション（旧テンプレート対応）

| 旧テンプレート | Agent生成時の調整ポイント |
| --- | --- |
| CMD_prj_02_市場規模推定 | Phase 3でTAM/SAM/SOMフレームワークを適用 |
| CMD_prj_02_競合調査 | Phase 3で競合比較マトリクスを生成 |
| CMD_prj_02_ペルソナ作成 | Phase 3でペルソナテンプレート構造を適用 |
| CMD_prj_02_課題定義 | Phase 3で問題ツリー / 因果関係図を生成 |
| CMD_prj_02_仮説マップ | Phase 3で仮説検証マトリクスを生成 |
| CMD_prj_03_リスク分析 | Phase 3でリスクマトリクス（影響×確率）を生成 |

---

**作成日:** 2026-04-08

**旧テンプレート:** Research_templates + Discovery_templates

**ステータス:** Active