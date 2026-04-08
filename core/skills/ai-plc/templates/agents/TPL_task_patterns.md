> 🏷️ **Type:** template (meta)

  **CC対応:** `.claude/skills/templates/task_patterns.md`

  **旧AIPO:** `_task_templates`

  **役割:** Stage 3 Constructionがタスク種類を判定し、適切なPhase構造を選択するためのメタパターン

---

## タスク種類判定

| 種類 | 説明 | 必須出力 | Agentテンプレート |
| --- | --- | --- | --- |
| research | 調査・分析・リサーチ | 分析レポート + 知見 | TPL_research_agent |
| implementation | DB作成・システム構築・実装 | Databaseまたは動くシステム | TPL_implementation_agent |
| content | 記事執筆・プレゼン・ドキュメント | 完成コンテンツ | TPL_content_agent |
| operation | 量産実行・パターン適用 | 量産成果物 + Evalデータ | TPL_operation_agent |
| validation | 検証・評価・レビュー | 検証結果 + 改善計画 | （専用なし—researchまたはimplementationのPhaseとして組み込み） |
| planning | 計画・ロードマップ・合意形成 | 確定計画 + コミット | （専用なし—researchのPhaseとして組み込み） |

---

## 共通原則（全Agent生成時に適用）

> ⚙️ **原則1: HITL情報の拘束力**


  Mob Checkpointまたはcontext.yamlで人間が明示的に指定した情報は「要件」として扱う。ワークスペース検索で見つかった類似情報より常に優先。

> ⚙️ **原則2: 出力の検証**


  Agent完了前に以下を確認：指定されたインプットを実際に使用したか、出力がインプットの規模・範囲と整合しているか。

> ⚙️ **原則3: 出力エンティティの明確化**


  Notionで成果物を作成する際、以下を区別：


  「Kanbanビュー」→ **Database** + Boardビュー（× ページに説明文）


  「進捗管理」→ **Database** + 適切なプロパティ（× ページ内テーブル）


  「テンプレート」→ **Page**（テンプレート形式）


  「ガイド」→ **Page**（本文あり）

> ⚙️ **原則4: 「動くシステム」ルール（implementationタスク必須）**


  implementationタイプのタスクは、実際に動くDatabase/システムを生み出さなければ完了としない。


  設計書やスキーマ定義を書いただけでは「完了」にならない。

---

## 汎用検証ステップ（全Agent共通 — RUL_plc_system §18連動）

> ✅ **全てのAgent生成時、Execution Flowの最終フェーズに検証ステップを必ず含める。**


  Adaptive Skipと連動: Simple→L1のみ / Standard→L1+L2 / Complex→L1+L2+L3

| Level | 名称 | 確認内容 | Simple | Standard | Complex |
| --- | --- | --- | --- | --- | --- |
| L1 | セクションチェック | 各パーツが単体で正しいか（論理・根拠・欠落） | ✅ | ✅ | ✅ |
| L2 | 統合チェック | 全体の整合性（矛盾・流れ・トーン一貫性） | — | ✅ | ✅ |
| L3 | 受け手チェック | 受け手が見て価値があるか（理解・アクション可能性） | — | — | ✅ |

### タスクパターン別の検証組み込み

| タスク種類 | 検証タイミング | 検証担当 |
| --- | --- | --- |
| research | 分析レポート完成後 | AIセルフチェック + Mob Checkpoint |
| implementation | DB/システム構築後 | AIテスト実行 + Mob確認 |
| content | 執筆完了後 | AIセルフレビュー + Mobレビュー |
| operation | 各量産サイクル後 | Evalデータで自動判定 |
| validation | 検証自体が成果物 | —（検証タスクには不要） |

---

## Phase構造の標準パターン

### パターンA: Autonomous + Mob交互型（標準）

```javascript
Autonomous → Mob → Autonomous → Mob → ...
```

ほとんどのAgentはこのパターン。AIが自動処理し、要所で人間確認。

### パターンB: エスカレーション型（実装系）

```javascript
設計 → Mob → DB作成 → ビュー追加 → データ投入 → Mob → ドキュメント
```

implementationタスク向け。段階的に成果物を構築。

### パターンC: 量産実行型（オペレーション）

```javascript
変数バインド → Mob → Runtime Execution → Eval → 繰り返し
```

Production Run向け。確立された型を変数で量産。

---

**作成日:** 2026-04-08

**旧テンプレート:** _task_templates

**ステータス:** Active