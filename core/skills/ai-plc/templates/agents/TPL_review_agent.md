> 🏷️ **Type:** template (agent generation) — コードレビュー・品質チェック・テスト戦略タスクのAgent定義生成用。コーディング以外の成果物レビューにも対応（system §18-19連動）

原則: レビュー結果は「指摘リスト」ではなく「実行可能なテスト指示書」として出力する（コーディング時）。

## Agent定義の標準構造

- Goal（コーディング）: 「[Component/Feature]のコードを検証し、品質基準を満たすテスト指示書を生成する」
- Goal（汎用）: 「[成果物名]を system §18の3層検証 + §19のNFRチェックで検証し、改善指示を生成する」
- Input（コーディング）: 生成コード、コード生成計画、NFR要件（opt-in）、既存テストスイート（Brownfield時）
- Input（汎用）: 成果物、タスク複雑度（→検証Level決定）、ロール固有NFRチェックリスト（TPL_role_*から）、有効なExtension（intent.yamlから）
- Output（コーディング）: ビルド指示書、unit/integration/（opt-inで）performance等の各テスト指示書、テストサマリー
- Output（汎用）: 検証レポート（L1/L2/L3結果+改善指示）、NFR適合判定（Pass/Warning/Fail）
- frontmatter（必須）: name（kebab-case）/ description / tools（最小権限・reviewer系はWrite/Edit除外）/ delegable（FlowにMob CPを含むならfalse）を先頭に付与（03-construction v2.1）

## Execution Flow

| Step | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. テスト要件分析 | Autonomous | 必要なテスト種別を判定 — Unit（必須）/ Integration（複数Unit時）/ Performance（NFR要件時）/ Contract（マイクロサービス時）/ Security（opt-in）/ E2E（ユーザーワークフロー時） | テスト戦略 |
| 2. ビルド指示書生成 | Autonomous | ビルドツール・依存関係・環境変数・コマンドを文書化 | build-instructions.md |
| 3. ユニットテスト指示書 | Autonomous | 実行コマンド・期待結果・カバレッジ目標・失敗時対処 | unit-test-instructions.md |
| 4. 統合テスト指示書 | Autonomous | シナリオ・環境セットアップ・サービス間テスト・クリーンアップ | integration-test-instructions.md |
| 5. 追加テスト指示書 | Autonomous | 必要に応じ performance / security / contract / e2e | 追加指示書群 |
| 6. テストサマリー生成 | Autonomous | テスト種別ごとの総数・Pass/Fail・カバレッジ・ステータスの表と Overall判定（Ready / Not Ready for Operations） | build-and-test-summary.md |
| 7. レビュー承認 | Mob | テスト指示書のレビュー → Operations（デプロイ）への遷移承認 | 承認 / フィードバック |

汎用レビュー時は Step 2-6 を「L1/L2/L3検証の実施 → 検証レポート生成 → NFR適合判定」に読み替える。

## 生成時の調整ポイント（type別検証レンズ）

非コーディング成果物のreviewer Agent生成時は、04-operation Phase 5.5のtype別レンズ表を正とし、対象typeのレンズをGoalとStep 1（テスト要件分析→検証観点分析に読み替え）へ転記する: content=事実確認・裏取り・読者視点・可読性 / design・planning=論理・実現可能性・意思決定者の判断可能性 / research=ソース信頼性・反証可能性・対立見解。management / coordinationはreviewer生成対象外（セルフチェックで可）。reviewerには成果物と検証に必要な定義（Goal/Output・検証Level・NFR要件・Extension）のみ渡し、作成文脈・会話履歴は渡さない。

## Guardrails（権限モデル）

| 権限 | 値 | 理由 |
| --- | --- | --- |
| bash | 読み取り系のみ可 | テスト実行・ビルド確認に必要 |
| edit / write | 不可 | レビュアーは修正しない。テスト指示書のみ出力し、修正はcoding_agentが行う |
