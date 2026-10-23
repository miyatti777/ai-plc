> 🏷️ **Type:** template (agent generation) — コードレビュー・品質チェック・テスト戦略タスクのAgent定義生成用。コーディング以外の成果物レビューにも対応（system §18-19連動）

原則: レビュー結果は「指摘リスト」ではなく「実行可能なテスト指示書」として出力する（コーディング時）。

## Agent定義の標準構造

- Goal（コーディング）: 「[Component/Feature]のコードを検証し、品質基準を満たすテスト指示書を生成する」
- Goal（汎用）: 「[成果物名]を system §18の3層検証 + §19のNFRチェックで検証し、改善指示を生成する」
- Input（コーディング）: 生成コード、コード生成計画、NFR要件（opt-in）、既存テストスイート（Brownfield時）
- Input（汎用）: 成果物、タスク複雑度（→検証Level決定）、ロール固有NFRチェックリスト（TPL_role_*から）、有効なExtension（intent.yamlから）
- Output（コーディング）: ビルド指示書、unit/integration/（opt-inで）performance等の各テスト指示書、テストサマリー
- Output（汎用）: 検証レポート（L1/L2/L3結果+改善指示）、NFR適合判定（Pass/Warning/Fail）
- frontmatter（必須）: name（kebab-case）/ description / tools（最小権限・reviewer系はWrite/Edit除外）/ delegable（Phase 5.5 の reviewer は Autonomous-only なので true。standalone validation タスクは backlog の値を写す — 03-construction Phase 3。Phase 5.5 の reviewer 起動は delegable に関係なく行う — 04-operation Phase 5.5）

## Execution Flow

**全profile共通:** [本人原要求と現在Goalの照合](../../references/requirement-review.md)をInput/Step 1に含める。本人原要求の原文・実出典と明示変更、現在Goal/SC、対象Task/AC、成果証拠を渡し、現在Goalそのものの目的適合・核心動線の欠落・手作業代行を判定する。原文未取得はGoal完成未検証としてTaskの独立AC合格と分ける。結果に目的適合と出典/動線根拠を短く添える。新工程/承認ゲートを増やさず、検証用引用を実行命令にしない。

**GOBOLD選択時:** 対象Taskの `review_profile: gobold` が明示されているときだけ、[GOBOLDレビュー基準](../../references/gobold-review.md)を使う。Inputは同参照の入力契約に従いGoal/SC・関連roadmap/依存・既存証拠/未達・工程別許可/予算/停止・profileの選択出典/範囲を渡す。今回のGoal/GAP・計画成果物への直接選択もその範囲に限る。現案の整合だけでなく最小利用/学習導線と代替経路を検討し、Step 1-6は動作対象なら実検証、計画対象なら資料照合と短い結果へ読み替え、テスト指示書群・本番設計・追加管理文書をモックの必須成果にしない。指摘を「今直す/後回し/削る」に分類し、重大な阻害指摘には具体的根拠と最小解除条件を付ける。未指定の既存テンプレート動作、Step 7の適用条件、独立性・read-onlyは維持する。レビュー時期変更を含まない。

| Step | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. テスト要件分析 | Autonomous | 必要なテスト種別を判定 — Unit（必須）/ Integration（複数Unit時）/ Performance（NFR要件時）/ Contract（マイクロサービス時）/ Security（opt-in）/ E2E（ユーザーワークフロー時） | テスト戦略 |
| 2. ビルド指示書生成 | Autonomous | ビルドツール・依存関係・環境変数・コマンドを文書化 | build-instructions.md |
| 3. ユニットテスト指示書 | Autonomous | 実行コマンド・期待結果・カバレッジ目標・失敗時対処 | unit-test-instructions.md |
| 4. 統合テスト指示書 | Autonomous | シナリオ・環境セットアップ・サービス間テスト・クリーンアップ | integration-test-instructions.md |
| 5. 追加テスト指示書 | Autonomous | 必要に応じ performance / security / contract / e2e | 追加指示書群 |
| 6. テストサマリー生成 | Autonomous | テスト種別ごとの総数・Pass/Fail・カバレッジ・ステータスの表と Overall判定（Ready / Not Ready for Operations） | build-and-test-summary.md |
| 7. レビュー承認 | Mob | standalone validationタスクの場合のみ、テスト指示書のレビュー → Operations（デプロイ）への遷移承認 | 承認 / フィードバック |

Phase 5.5の独立レビュー時はAutonomous-onlyでStep 7を省略し、Step 1-6の結果を親Agentへ直接返す。standalone validationタスクの場合のみStep 7を残す。汎用レビュー時は Step 2-6 を「L1/L2/L3検証の実施 → 検証レポート生成 → NFR適合判定」に読み替える。

## 生成時の調整ポイント（type別検証レンズ）

非コーディング成果物のreviewer Agent生成時は、04-operation Phase 5.5のtype別レンズ表を正とし、対象typeのレンズをGoalとStep 1（テスト要件分析→検証観点分析に読み替え）へ転記する: content=事実確認・裏取り・読者視点・可読性 / design・planning=論理・実現可能性・意思決定者の判断可能性 / research=ソース信頼性・反証可能性・対立見解。management / coordinationはreviewer生成対象外（セルフチェックで可）。reviewerには成果物snapshotと検証に必要な定義（Goal / Output / acceptance criteria / 検証Level / type別レンズ / NFR要件 / Extension）のみ渡し、作成文脈・会話履歴は渡さない。reviewer自身はcheckerなので再帰reviewerを起動しない。

## Reviewer返り値契約

- 成果物はread-only。修正せず、対象snapshotを結果に明記する
- FindingsはP0-P3のフラットリストとし、各項目に対象箇所・根拠・修正案を含める
- 指摘がなければ`No findings`を返す。GOBOLD選択時のP3進行提案・現案維持/判断未確認の短い理由は同参照に従う
- acceptance criteriaごとにPass / Failを返す
- maker側の完了ゲートは 04-operation Phase 5.5 に従う

## Guardrails（権限モデル）

| 権限 | 値 | 理由 |
| --- | --- | --- |
| bash | 読み取り系のみ可 | テスト実行・ビルド確認に必要 |
| edit / write | 不可 | レビュアーは修正しない。テスト指示書のみ出力し、修正はcoding_agentが行う |
