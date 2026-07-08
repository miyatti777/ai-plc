> 🏷️ **Type:** template (agent generation) — 記事執筆・プレゼン・ドキュメント等コンテンツ制作タスクのAgent定義生成用

## Agent定義の標準構造

- Goal: 「[Content Type]を作成し、[Audience]向けに[Purpose]を達成する」
- Input: コンテンツ種類（記事/プレゼン/ドキュメント）、ターゲットオーディエンス、テーマ・キーメッセージ、参考資料（Context Store）、トーン・スタイル指定
- Output: 完成コンテンツ。プレゼンの場合はスライド分割済み（`---`区切り）
- frontmatter（必須）: name（kebab-case）/ description / tools（最小権限）/ delegable（FlowにMob CPを含むならfalse）を先頭に付与（03-construction v2.1）

## Execution Flow

| Phase | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. リサーチ | Autonomous | テーマの調査・参考資料収集 | リサーチメモ |
| 2. 構成設計 | Autonomous | 目次・主要セクション・キーメッセージ設計 | 構成案 |
| 3. 構成承認 | Mob | 構成案の確認・調整 | 承認済み構成 |
| 4. 執筆 | Autonomous | 各セクションのドラフト作成 | ドラフト版 |
| 5. レビュー | Mob | 具体例追加・トーン調整・フィードバック | フィードバック |
| 6. 最終化 | Autonomous | フィードバック反映・フォーマット調整 | 確定版 |

## Guardrails

- Phase 2で骨格を確認してから執筆に入る（一気に全文生成しない）
- 具体例・チーム固有の情報はMob Checkpointで人間が追加
- プレゼンの場合は `---` でスライド分割する

## 生成時の調整ポイント

| コンテンツ種類 | 調整 |
| --- | --- |
| リサーチ重視の記事 | Phase 1を拡張（競合コンテンツ分析を追加） |
| プレゼンスライド | Phase 4で `---` 区切りのスライド構造を適用 |
| LT資料 | Phase 2で発表時間枠の制約とスライド数上限を設定 |
