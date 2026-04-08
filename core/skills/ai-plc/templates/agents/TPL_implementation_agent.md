> 🏷️ **Type:** template (agent generation)

  **CC対応:** `.claude/skills/templates/implementation_agent.md`

  **旧AIPO:** `system_building_templates`

  **役割:** DB作成・システム構築・実装系タスクのAgent定義を生成する際のテンプレート

---

## 対象タスク例

- Database設計・構築（プロパティ・ビュー・テンプレート）
- 業務プロセス設計・ワークフロー構築
- 運用ルール定義
- Wiki構築・ドキュメント管理システム
- Form・UI実装
- AI処理ロジック実装

---

> 🚨 **最重要原則: 「動くシステム」を生み出す**


  設計書やスキーマ定義だけでは「完了」にならない。


  実際にDatabaseが存在して動作していることが完了条件。

---

## Agent定義の標準構造

### Goal

「[System Name]を設計・実装し、実際に動作する状態にする」

### Input

- 要件定義（何を管理するか）
- スコープ（プロパティ数・ビュー数の目安）
- 既存システムとの接続点（Relation先等）
- 初期データ（あれば）

### Output

- **Database**（プロパティ + ビュー + テンプレート）
- 初期データ投入済み
- 使い方ガイド（付属ドキュメント）

### Execution Flow（エスカレーション型）

| Phase | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. 設計 | Autonomous | DBスキーマ設計・プロパティ定義・ビュー設計 | 設計案 |
| 2. 設計承認 | Mob | プロパティ・ビュー・データ構造の確認 | 承認済み設計 |
| 3. DB作成 | Autonomous | 実際にDatabaseを作成（createDatabase） | Database |
| 4. ビュー追加 | Autonomous | 必要なビューを追加（Table/Board/Timeline等） | Views |
| 5. データ投入 | Autonomous | 初期データ・テンプレートを投入 | Data |
| 6. 検証 | Mob | 実際に動作確認・調整指示 | フィードバック |
| 7. ドキュメント | Autonomous | 使い方ガイド作成（DBの付属） | ガイドページ |

### Guardrails

- Phase 3で実際にDatabaseを作成すること（設計書だけで止めない）
- Relation先のDBが存在することを確認してからRelationプロパティを設定
- ビューは最低1つ（Table）を必ず作成
- テンプレートが必要な場合はDBテンプレートとして作成

---

## バリエーション（旧テンプレート対応）

| 旧テンプレート | Agent生成時の調整ポイント |
| --- | --- |
| CMD_sys_01_汎用DB作成 | 標準フローそのまま適用 |
| CMD_sys_02_業務プロセス設計 | Phase 1にAs-Is/To-Be分析を追加 |
| CMD_sys_03_運用ルール定義 | Phase 7でルールドキュメントを重点化 |
| CMD_sys_04_Wiki構築 | Phase 3でページ階層設計を追加 |
| CMD_sys_05_Database実装 | 標準フローそのまま適用 |
| CMD_sys_06_Form・UI実装 | Phase 4でFormビュー作成を追加 |

---

**作成日:** 2026-04-08

**旧テンプレート:** system_building_templates

**ステータス:** Active