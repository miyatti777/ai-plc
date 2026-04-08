> 🏷️ **Type:** template (agent generation)

  **CC対応:** `.claude/skills/templates/content_agent.md`

  **旧AIPO:** `content_creation_templates` + `presentation_templates` + `lt_presentation_templates`

  **役割:** コンテンツ制作・執筆・プレゼン系タスクのAgent定義を生成する際のテンプレート

---

## 対象タスク例

- 記事執筆（ブログ・技術記事・マーケティング）
- プレゼンテーション・スライド作成
- LT資料作成
- ドキュメント作成（ガイド・マニュアル・仕様書）
- コミュニケーション文書（報告書・提案書）

---

## Agent定義の標準構造

### Goal

「[Content Type]を作成し、[Audience]向けに[Purpose]を達成する」

### Input

- コンテンツ種類（記事 / プレゼン / ドキュメント）
- ターゲットオーディエンス
- テーマ・キーメッセージ
- 参考資料（Context Storeから）
- トーン・スタイル指定

### Output

- 完成コンテンツ（Notionページ）
- プレゼンの場合: スライド分割済みページ（`---`区切り）

### Execution Flow

| Phase | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. リサーチ | Autonomous | テーマの調査・参考資料収集 | リサーチメモ |
| 2. 構成設計 | Autonomous | 目次・主要セクション・キーメッセージ設計 | 構成案 |
| 3. 構成承認 | Mob | 構成案の確認・調整 | 承認済み構成 |
| 4. 執筆 | Autonomous | 各セクションのドラフト作成 | ドラフト版 |
| 5. レビュー | Mob | 具体例追加・トーン調整・フィードバック | フィードバック |
| 6. 最終化 | Autonomous | フィードバック反映・フォーマット調整・完成版作成 | 確定版 |

### Guardrails

- Phase 2で骨格を確認してから執筆に入る（一気に全文生成しない）
- 具体例・チーム固有の情報はMob Checkpointで人間が追加
- プレゼンの場合はPresentation Mode対応（`---`でスライド分割）

---

## バリエーション（旧テンプレート対応）

| 旧テンプレート | Agent生成時の調整ポイント |
| --- | --- |
| CMD_cnt_01_コンテンツリサーチ | Phase 1を拡張（競合コンテンツ分析を追加） |
| CMD_cnt_02_記事企画・構成設計 | Phase 2-3そのまま適用 |
| CMD_cnt_03_執筆管理 | Phase 4そのまま適用 |
| CMD_cnt_04_レビュー・フィードバック | Phase 5そのまま適用 |
| CMD_cnt_06_プレゼンスライド作成 | Phase 4で---区切りスライド構造を適用 |
| LTプレゼン | Phase 2で5分枠制約を追加、スライド数上限を設定 |

---

**作成日:** 2026-04-08

**旧テンプレート:** content_creation_templates + presentation_templates

**ステータス:** Active